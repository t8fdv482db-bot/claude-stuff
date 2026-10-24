"""Orchestrates the stages: voice -> lip-sync -> B-roll -> music -> assembly -> outputs."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import ffmpeg
from .assembly import compose
from .assembly.captions import write_ass
from .assembly.endcard import render_end_card, render_stage
from .avatar.library import AvatarLibrary
from .broll.kenburns import compose_still, make_clip, pick_image
from .config import Settings, font_file
from .cost import CostReport, append_ledger, lipsync_cost, music_cost, tts_cost
from .lipsync import get_lipsync_provider
from .models import RESOLUTIONS, AdScript, Avatar, ProductBrief, RenderOptions, ScriptSet, VoiceTrack
from .music import default_music_prompt, get_music_provider
from .safety import check_avatar_spec, lint_script
from .voice import fit_to_length, get_voice_provider

log = logging.getLogger(__name__)

FPS = 30
TAIL = 0.3  # seconds of picture after the last word, before the end card
MIN_END_CARD = 1.5
MAX_END_CARD = 3.5
MIN_LIPSYNC = 2.0  # lip-sync windows shorter than this are widened with neighbouring audio

Progress = Callable[[str], None]


@dataclass
class AdResult:
    variant: str
    folder: Path
    videos: dict[str, Path]
    thumbnail: Path
    duration: float
    cost: CostReport
    warnings: list[str] = field(default_factory=list)


@dataclass
class Span:
    """A run of consecutive on-camera segments, lip-synced in one provider call."""

    segments: list[int]
    start: float  # first frame shown (voice timeline)
    end: float
    win_start: float = 0.0  # audio window sent to lip-sync (may be wider)
    win_end: float = 0.0
    video: Path | None = None


def plan_spans(script: AdScript, bounds: list[tuple[float, float]], voice_duration: float) -> list[Span]:
    spans: list[Span] = []
    for i, seg in enumerate(script.segments):
        if seg.visual != "avatar":
            continue
        s, e = bounds[i]
        if spans and spans[-1].segments[-1] == i - 1:
            spans[-1].segments.append(i)
            spans[-1].end = e
        else:
            spans.append(Span(segments=[i], start=s, end=e))
    for sp in spans:
        a, b = sp.start, min(sp.end, voice_duration)
        while b - a < MIN_LIPSYNC and (a > 0 or b < voice_duration):
            a, b = max(0.0, a - 0.25), min(voice_duration, b + 0.25)
        sp.win_start, sp.win_end = round(a, 3), round(b, 3)
    return spans


def frame_bounds(bounds: list[tuple[float, float]]) -> list[tuple[int, int]]:
    """Convert second-based segment bounds to contiguous frame ranges (no drift)."""
    out = []
    for s, e in bounds:
        out.append((round(s * FPS), round(e * FPS)))
    return out


def _file_hash(*paths: Path, extra: str = "") -> str:
    h = hashlib.sha256(extra.encode())
    for p in paths:
        h.update(Path(p).read_bytes())
    return h.hexdigest()[:24]


class Renderer:
    def __init__(self, settings: Settings, options: RenderOptions | None = None, progress: Progress | None = None):
        self.s = settings
        self.opt = options or RenderOptions()
        self.progress = progress or (lambda msg: log.info(msg))
        ffmpeg.require_ffmpeg()
        self.font = font_file()

    # -- stages -------------------------------------------------------------
    def _voice(self, script: AdScript, avatar: Avatar, brief: ProductBrief, work: Path, cost: CostReport) -> VoiceTrack:
        voices = get_voice_provider(self.s)
        if voices.name != avatar.voice_provider:
            raise ValueError(
                f"Avatar '{avatar.id}' has a {avatar.voice_provider} voice but the voice provider is {voices.name}."
            )
        self.progress(f"[{script.variant}] voice: synthesising with {voices.name}")
        raw = voices.synthesize(script, avatar.voice_id, brief.language, work)
        cost.add("voice", voices.name, f"{raw.characters} chars", tts_cost(voices.name, self.s.tts_model, raw.characters))
        max_voice = brief.length - MIN_END_CARD - TAIL
        track = fit_to_length(raw, max_voice, work)
        (work / "words.json").write_text(json.dumps([w.model_dump() for w in track.words], indent=1))
        return track

    def _lipsync(self, spans: list[Span], avatar: Avatar, portrait: Path, track: VoiceTrack, work: Path, cost: CostReport) -> None:
        provider = get_lipsync_provider(self.s)
        cache = self.s.cache_dir / "lipsync"
        cache.mkdir(parents=True, exist_ok=True)
        for n, sp in enumerate(spans):
            clip_audio = work / f"span{n}.wav"
            ffmpeg.run(["-i", track.audio_path, "-ss", f"{sp.win_start:.3f}", "-to", f"{sp.win_end:.3f}", "-c:a", "pcm_s16le", clip_audio])
            key = _file_hash(portrait, clip_audio, extra=provider.name)
            cached = cache / f"{key}.mp4"
            if cached.exists():
                self.progress(f"lip-sync span {n + 1}/{len(spans)}: cache hit (no charge)")
            else:
                self.progress(f"lip-sync span {n + 1}/{len(spans)}: {provider.name}, {sp.win_end - sp.win_start:.1f}s")
                tmp = work / f"span{n}_raw.mp4"
                billed = provider.animate(avatar, portrait, clip_audio, tmp)
                cost.add("lipsync", provider.name, f"span {n + 1}: {billed:.1f}s", lipsync_cost(provider.name, billed))
                shutil.copyfile(tmp, cached)
            sp.video = cached

    def _music(self, brief: ProductBrief, seconds: float, job_dir: Path, cost: CostReport) -> Path | None:
        if not self.opt.music:
            return None
        provider = get_music_provider(self.s, brief.tone)
        if provider is None:
            return None
        prompt = self.opt.music_prompt or default_music_prompt(brief.tone)
        existing = sorted(job_dir.glob("music.*"))
        if existing:
            return existing[0]
        self.progress(f"music: {provider.name}")
        path = provider.generate(prompt, seconds, job_dir / "music")
        cost.add("music", provider.name, f"{seconds:.0f}s bed", music_cost(provider.name, seconds))
        return path

    # -- one variant --------------------------------------------------------
    def render_variant(
        self,
        brief: ProductBrief,
        script: AdScript,
        avatar: Avatar,
        portrait: Path,
        job_dir: Path,
        shared_cost: CostReport,
    ) -> AdResult:
        folder = job_dir / f"variant_{script.variant}"
        work = folder / "work"
        work.mkdir(parents=True, exist_ok=True)
        cost = CostReport()
        warnings: list[str] = []

        problems = lint_script(script, brief)
        if problems:
            raise ValueError(f"Variant {script.variant} fails compliance checks: {problems}")

        track = self._voice(script, avatar, brief, work, cost)
        if track.tempo > 1.0:
            warnings.append(f"Voice sped up {track.tempo:.2f}x to fit {brief.length}s.")
        bounds = track.segment_bounds(len(script.segments))
        body_end = round(track.duration + TAIL, 3)
        bounds[-1] = (bounds[-1][0], body_end)
        end_card = min(MAX_END_CARD, max(MIN_END_CARD, brief.length - body_end))
        total = round(body_end + end_card, 3)
        if total > brief.length + 0.5:
            warnings.append(f"Ad runs {total:.1f}s, over the {brief.length}s target; shorten the script.")

        spans = plan_spans(script, bounds, track.duration)
        self._lipsync(spans, avatar, portrait, track, work, cost)
        music = self._music(brief, max(total, brief.length) + 1.0, job_dir, shared_cost)
        self.progress(f"[{script.variant}] audio mix + loudness normalisation")
        audio = compose.mix_audio(
            Path(track.audio_path), music, total, body_end, work,
            music_db=self.opt.music_volume_db, target_lufs=self.opt.target_lufs,
        )

        images = [Path(p) for p in brief.image_paths if Path(p).exists()]
        logo = Path(brief.logo_path) if brief.logo_path else None
        frames = frame_bounds(bounds)
        end_frames = round(total * FPS) - frames[-1][1]
        videos: dict[str, Path] = {}
        for ratio in brief.aspect_ratios:
            size = RESOLUTIONS[ratio]
            tag = ratio.replace(":", "x")
            rdir = work / tag
            rdir.mkdir(exist_ok=True)
            self.progress(f"[{script.variant}] assembling {ratio}")
            stage = render_stage(size, brief.name, images[0] if images else None, rdir / "stage.png") if size[0] > size[1] else None
            clips: list[Path] = []
            broll_n = 0
            for i, seg in enumerate(script.segments):
                f0, f1 = frames[i]
                if f1 <= f0:
                    continue
                out = rdir / f"shot{i:02d}.mp4"
                if seg.visual == "avatar":
                    sp = next(s for s in spans if i in s.segments)
                    offset = max(0.0, f0 / FPS - sp.win_start)
                    compose.avatar_clip(sp.video, offset, f1 - f0, size, out, stage)
                else:
                    img = pick_image(images, seg.broll_focus, broll_n)
                    still = compose_still(img, size, brief.name, rdir / f"still{i:02d}.png")
                    make_clip(still, f1 - f0, size, out, motion=broll_n + i)
                    broll_n += 1
                clips.append(out)
            card = render_end_card(size, brief.name, script.on_screen_cta or brief.cta, brief.product_url, logo, images[0] if images else None, rdir / "endcard.png")
            clips.append(compose.still_clip(card, end_frames, rdir / "endcard.mp4"))
            ass = write_ass(track.words, size, self.font, body_end, rdir / "captions.ass") if self.opt.captions else None
            label = self.opt.ai_label_text if self.opt.ai_label else None
            videos[ratio] = compose.finalize_video(clips, size, audio, folder / f"ad_{tag}.mp4", ass=ass, font_path=self.font, label=label)

        first = videos[brief.aspect_ratios[0]]
        thumb = compose.thumbnail(first, min(1.0, body_end / 3), folder / "thumbnail.jpg")
        for ratio, v in videos.items():
            if v != first:
                compose.thumbnail(v, min(1.0, body_end / 3), folder / f"thumbnail_{ratio.replace(':', 'x')}.jpg")

        self._write_metadata(folder, brief, script, avatar, track, total, cost, warnings, spans)
        return AdResult(script.variant, folder, videos, thumb, total, cost, warnings)

    def _write_metadata(self, folder, brief, script, avatar, track, total, cost, warnings, spans) -> None:
        (folder / "script.json").write_text(script.model_dump_json(indent=2))
        lines = [f"Variant {script.variant} - {script.angle}", ""]
        for seg in script.segments:
            lines.append(f"[{seg.role.upper()} | {seg.visual} | {seg.delivery}] {seg.text}")
        lines += ["", f"End card: {script.on_screen_cta}"]
        (folder / "script.txt").write_text("\n".join(lines) + "\n")
        settings = {
            "brief": brief.model_dump(),
            "avatar": {"id": avatar.id, "name": avatar.name, "spec": avatar.spec.model_dump(), "voice_id": avatar.voice_id},
            "providers": self.s.providers() | {"tts_model": self.s.tts_model, "claude_model": self.s.claude_model},
            "options": self.opt.model_dump(),
            "duration_seconds": total,
            "voice_tempo": track.tempo,
            "lipsync_windows": [[sp.win_start, sp.win_end] for sp in spans],
            "warnings": warnings,
        }
        (folder / "settings.json").write_text(json.dumps(settings, indent=2, default=str))
        (folder / "cost.json").write_text(json.dumps(cost.to_dict(), indent=2))

    # -- whole job ----------------------------------------------------------
    def render(self, brief: ProductBrief, scripts: list[AdScript], avatar: Avatar, library: AvatarLibrary, script_set: ScriptSet | None = None) -> list[AdResult]:
        check_avatar_spec(avatar.spec)
        portrait = library.portrait_path(avatar)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        job_dir = self.s.output_dir / brief.slug / stamp
        job_dir.mkdir(parents=True, exist_ok=True)
        if script_set is not None:
            (job_dir / "scripts.json").write_text(script_set.model_dump_json(indent=2))
        shared = CostReport()
        results = []
        for script in scripts:
            results.append(self.render_variant(brief, script, avatar, portrait, job_dir, shared))
        # Shared costs (music) are attributed to the job, not to a single variant.
        total = shared.total + sum(r.cost.total for r in results)
        summary = {
            "product": brief.name,
            "job": str(job_dir),
            "avatar": avatar.id,
            "variants": {r.variant: {"folder": str(r.folder), "cost": r.cost.to_dict(), "duration": r.duration} for r in results},
            "shared_cost": shared.to_dict(),
            "total_usd": round(total, 4),
            "providers": self.s.providers(),
        }
        (job_dir / "job.json").write_text(json.dumps(summary, indent=2))
        append_ledger(self.s.output_dir / "cost_log.jsonl", {"kind": "render", **summary})
        return results
