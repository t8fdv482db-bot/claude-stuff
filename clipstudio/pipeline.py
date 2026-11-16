"""The finished-video pipeline and everything that turns a chosen moment into a rendered clip.

download audio (+ chat in parallel) → transcribe → score → [AI review] → download only the
needed sections → render. Every step caches to disk, so a crash or restart resumes cheaply.
"""
from __future__ import annotations

import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np

from . import db, media, render, scoring, transcribe
from .media import Cancelled, UserError, fmt_time
from .sources import chat as chatmod
from .sources import common, detect, twitch
from .worker import JobContext, Relaunch, bus, manager

SECTION_PAD = 10.0     # seconds of footage kept around each clip so trims don't need a re-download
PLATFORM_NAMES = {"youtube": "YouTube", "twitch": "Twitch", "kick": "Kick", "file": "stream"}


# ---------------------------------------------------------------- small helpers
def cache_dir(platform: str, vid: str) -> Path:
    safe = "".join(ch for ch in f"{platform}_{vid}" if ch.isalnum() or ch in "_-")[:80]
    p = db.storage_dir() / "cache" / safe
    p.mkdir(parents=True, exist_ok=True)
    return p


def clip_dir(clip_id: int) -> Path:
    p = db.storage_dir() / "clips" / str(clip_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def public_clip(c: dict) -> dict:
    c = dict(c)
    for k in ("signals", "source_extra"):
        try:
            c[k] = json.loads(c.get(k) or "{}")
        except ValueError:
            c[k] = {}
    c["length"] = round((c.get("end") or 0) - (c.get("start") or 0), 1)
    v = int(c.get("created") or 0) + int(Path(c["video_path"]).stat().st_mtime if c.get("video_path") and Path(c["video_path"]).exists() else 0)
    c["video_url"] = f"/media/clip/{c['id']}/video?v={v}" if c.get("video_path") else None
    c["thumb_url"] = f"/media/clip/{c['id']}/thumb?v={v}" if c.get("thumb_path") else None
    c["gif_url"] = f"/media/clip/{c['id']}/gif?v={v}" if c.get("gif_path") else None
    for k in ("src_path", "video_path", "thumb_path", "gif_path"):
        c.pop(k, None)
    return c


def publish_clip(clip_id: int, new: bool = False) -> None:
    c = db.get("clips", clip_id)
    if c:
        d = public_clip(c)
        d["_new"] = new
        bus.publish("clip", d)


def resolve_options(job: dict) -> dict:
    """Job options merged with settings defaults and campaign limits."""
    s = db.all_settings()
    try:
        o = json.loads(job.get("options") or "{}")
    except ValueError:
        o = {}
    out = {
        "clip_count": int(o.get("clip_count") or s["clip_count"]),
        "min_len": float(o.get("min_len") or s["min_len"]),
        "max_len": float(o.get("max_len") or s["max_len"]),
        "layout": o.get("layout") or None,
        "ai": bool(o.get("ai", s["ai_enabled"])),
        "keep_source": bool(o.get("keep_source", s["keep_source"])),
    }
    camp = db.get("campaigns", job["campaign_id"]) if job.get("campaign_id") else None
    if camp:
        if camp.get("min_len"):
            out["min_len"] = max(out["min_len"], float(camp["min_len"]))
        if camp.get("max_len"):
            out["max_len"] = min(out["max_len"], float(camp["max_len"]))
        if out["min_len"] > out["max_len"]:
            out["min_len"] = out["max_len"]
    return out


def weights() -> dict[str, float]:
    s = db.all_settings()
    return {"chat": float(s["w_chat"]), "audio": float(s["w_audio"]),
            "transcript": float(s["w_transcript"]), "clips": float(s["w_clips"])}


def phrases_for(streamer: dict | None) -> list[str]:
    extra = scoring.parse_list(streamer.get("hype_words")) if streamer else []
    return scoring.DEFAULT_TRANSCRIPT_PHRASES + extra


def compose_description(title: str, streamer: dict | None, campaign: dict | None, platform: str,
                        channel: str = "") -> str:
    lines = []
    if campaign and (campaign.get("disclosure") or "").strip():
        lines.append(campaign["disclosure"].strip())
    lines.append(title)
    who = (streamer or {}).get("name") or channel
    if who:
        lines.append("")
        lines.append(f"🎥 {who} live on {PLATFORM_NAMES.get(platform, platform)}")
    tags = []
    if campaign:
        tags += scoring.parse_list(campaign.get("hashtags"))
    if streamer:
        tags += scoring.parse_list(streamer.get("default_tags"))
    tags = list(dict.fromkeys(t if t.startswith(("#", "@")) else "#" + t.replace(" ", "") for t in tags))
    if tags:
        lines.append("")
        lines.append(" ".join(tags))
    return "\n".join(lines)


def fallback_title(name: str, words: list[dict], segments: list[dict], peak: float) -> str:
    """No-AI title: the most excited sentence said right around the peak, quoted."""
    best, best_score = "", -1.0
    for s in segments:
        if s["e"] < peak - 12 or s["s"] > peak + 6:
            continue
        text = s["text"].strip()
        score = text.count("!") * 2 + text.count("?") + (3 if 8 <= len(text) <= 60 else 0) - abs(s["s"] - peak) / 10
        if text and score > best_score:
            best, best_score = text, score
    who = name or "Streamer"
    if best:
        best = best.strip(" .")
        room = 66 - len(who) - 5
        if len(best) > room:
            best = best[: room - 1].rsplit(" ", 1)[0] + "…"
        return f'{who}: "{best}"'
    return f"{who} at {fmt_time(peak)}"


# ---------------------------------------------------------------- analysis
def load_rms(audio: Path, cache: Path, cancel=None) -> np.ndarray:
    f = cache / "rms.npy"
    if f.exists():
        return np.load(f)
    rms = media.audio_rms(audio, cancel=cancel)
    np.save(f, rms)
    return rms


def build_signals(n: int, *, rms: np.ndarray | None, chat: list[dict] | None, words: list[dict] | None,
                  streamer: dict | None, clip_times: list[tuple[float, float]] | None,
                  chat_shift: float = 5.0) -> scoring.Signals:
    s = db.all_settings()
    return scoring.Signals(
        n=n,
        chat=scoring.chat_signal(chat, n, scoring.parse_list(s["hype_tokens"]), chat_shift) if chat else None,
        audio=scoring.audio_signals(rms, n) if rms is not None and len(rms) else None,
        transcript=scoring.transcript_signal(words, n, phrases_for(streamer)) if words else None,
        clips=scoring.clips_signal(clip_times, n) if clip_times else None,
    )


def choose(ctx: JobContext, cands: list[dict], *, count: int, opts: dict, words: list[dict],
           segments: list[dict], chat: list[dict], streamer: dict | None, n: int) -> list[dict]:
    """Rank candidates, or let the AI filter and tighten them."""
    for c in cands:
        c["title"] = fallback_title((streamer or {}).get("name", ""), words, segments, c["peak"])
        c["hook"] = ""
        c["reason"] = "Top detector score: " + ", ".join(f"{k} {v:+.1f}" for k, v in c["signals"].items())
    if opts["ai"]:
        from . import ai
        if not ai.api_key():
            ctx.log("AI review is on but no Anthropic API key is set (Settings → AI). Using detector ranking.")
        else:
            ctx.log(f"AI review of {len(cands)} candidates…")
            cands = ai.review_candidates(ctx, cands, words=words, chat=chat, streamer=streamer,
                                         min_len=opts["min_len"], max_len=opts["max_len"], duration=n)
            cands.sort(key=lambda c: (c.get("ai_score") or 0, c["score"]), reverse=True)
            return cands[:count]
    cands.sort(key=lambda c: c["score"], reverse=True)
    return cands[:count]


def create_clips(ctx: JobContext, chosen: list[dict], *, job: dict, opts: dict, source_url: str,
                 source_extra: dict | None, words: list[dict], src_path: Path | None = None,
                 src_offset: float = 0.0, src_end: float | None = None) -> list[int]:
    streamer = db.get("streamers", job["streamer_id"]) if job.get("streamer_id") else None
    campaign = db.get("campaigns", job["campaign_id"]) if job.get("campaign_id") else None
    ids = []
    for c in chosen:
        cid = db.insert(
            "clips", job_id=job["id"], streamer_id=job.get("streamer_id"), campaign_id=job.get("campaign_id"),
            start=c["start"], end=c["end"], peak=c["peak"], score=c["score"], ai_score=c.get("ai_score"),
            reason=c.get("reason", ""), title=c.get("title", ""), hook=c.get("hook", ""),
            description=compose_description(c.get("title", ""), streamer, campaign, job["platform"],
                                            job.get("channel", "")),
            status="pending", render_state="queued", layout=opts.get("layout"),
            signals=json.dumps(c.get("signals", {})), source_url=source_url,
            source_extra=json.dumps(source_extra or {}), created=db.now(),
            src_path=str(src_path) if src_path else None, src_offset=src_offset, src_end=src_end)
        d = clip_dir(cid)
        lo, hi = c["start"] - SECTION_PAD - 30, c["end"] + SECTION_PAD + 30
        (d / "words.json").write_text(json.dumps({"from": lo, "to": hi,
                                                  "words": transcribe.window(words, lo, hi)}), "utf-8")
        ids.append(cid)
        publish_clip(cid, new=True)
    return ids


# ---------------------------------------------------------------- sources for clips
def ensure_source(clip: dict, log=None, cancel=None) -> tuple[Path, float]:
    """Make sure footage covering the clip exists locally; returns (path, offset of its t=0)."""
    start, end = float(clip["start"]), float(clip["end"])
    if clip.get("src_path") and Path(clip["src_path"]).exists():
        off = float(clip.get("src_offset") or 0)
        s_end = float(clip.get("src_end") or 1e12)
        if off <= start + 0.01 and end <= s_end + 0.01:
            return Path(clip["src_path"]), off
    url = clip.get("source_url")
    if not url:
        raise UserError("The footage for this clip is no longer on disk (live segments older than the "
                        "keep window are deleted), so it can't be re-cut beyond its current range.")
    try:
        extra = json.loads(clip.get("source_extra") or "{}")
    except ValueError:
        extra = {}
    platform = detect(url).platform
    a, b = max(0.0, start - SECTION_PAD), end + SECTION_PAD
    job_dir = db.storage_dir() / "jobs" / str(clip["job_id"]) / "sections"
    out = job_dir / f"c{clip['id']}_{int(a)}_{int(b)}"
    if platform == "file":
        job_dir.mkdir(parents=True, exist_ok=True)
        path = common.cut_local(Path(url), a, b, out.with_suffix(".mp4"), cancel=cancel)
        db.update("clips", clip["id"], src_path=str(path), src_offset=a, src_end=a + media.duration(path))
        return path, a
    try:
        path = common.download_section(url, a, b, out, platform, log=log, cancel=cancel, extra=extra)
        got = media.duration(path)
        off = a
        if got and abs(got - (b - a)) > 1.5:   # cut snapped to an earlier keyframe: trust the end
            off = max(0.0, b - got)
    except Cancelled:
        raise
    except Exception as e:  # noqa: BLE001 - fall back to the full video
        if log:
            log(f"Section download failed ({str(e)[:160]}); downloading the full video instead.")
        meta_dir = job_dir.parent
        full = common.download_full(url, meta_dir, platform, log=log, cancel=cancel, extra=extra)
        path = common.cut_local(full, a, b, out.with_suffix(".mp4"), cancel=cancel)
        off = a
    db.update("clips", clip["id"], src_path=str(path), src_offset=off, src_end=off + media.duration(path))
    return path, off


def clip_words(clip: dict, src: Path, src_offset: float, log=None, cancel=None) -> list[dict]:
    d = clip_dir(clip["id"])
    f = d / "words.json"
    if f.exists():
        data = json.loads(f.read_text("utf-8"))
        if data["from"] <= clip["start"] and clip["end"] <= data["to"]:
            return data["words"]
    # the cut moved outside what we transcribed: transcribe the local footage
    wav = d / "words.wav"
    media.extract_wav(src, wav, 0, None, cancel)
    data = transcribe.transcribe_wav(wav, src_offset, log, cancel)
    wav.unlink(missing_ok=True)
    end = src_offset + media.duration(src)
    f.write_text(json.dumps({"from": src_offset, "to": end, "words": data["words"]}), "utf-8")
    return data["words"]


def render_clip(clip_id: int, log=None, cancel=None) -> None:
    """(Re-)render one clip from its source footage and current settings."""
    clip = db.get("clips", clip_id)
    if not clip:
        return
    db.update("clips", clip_id, render_state="rendering", render_error=None)
    publish_clip(clip_id)
    try:
        src, off = ensure_source(clip, log, cancel)
        clip = db.get("clips", clip_id)
        streamer = db.get("streamers", clip["streamer_id"]) if clip.get("streamer_id") else None
        campaign = db.get("campaigns", clip["campaign_id"]) if clip.get("campaign_id") else None
        settings = db.all_settings()
        layout = clip.get("layout") or (streamer or {}).get("layout") or settings["default_layout"]
        facecam = None
        if streamer and streamer.get("facecam"):
            try:
                facecam = json.loads(streamer["facecam"])
            except ValueError:
                facecam = None
        if layout == "split" and not facecam and log:
            log(f"Clip {clip_id}: no facecam box set for this streamer — using the blur layout.")
        words = clip_words(clip, src, off, log, cancel)
        disclosure = (campaign or {}).get("disclosure") or ""
        ass = render.build_ass(words, clip["start"], clip["end"], style=settings,
                               caption_y=render.caption_y(layout if facecam or layout != "split" else "blur"),
                               hook=clip.get("hook") or "", disclosure=disclosure,
                               disclosure_seconds=float((campaign or {}).get("disclosure_seconds") or 3))
        with manager.render_slots:
            paths = render.render_video(src, off, clip["start"], clip["end"], clip_dir(clip_id), layout=layout,
                                        facecam=facecam, ass_text=ass, cancel=cancel, peak=clip.get("peak"))
        db.update("clips", clip_id, render_state="ready", video_path=str(paths["video"]),
                  thumb_path=str(paths["thumb"]), gif_path=str(paths["gif"]),
                  disclosure_burned=1 if disclosure.strip() else 0)
    except Cancelled:
        db.update("clips", clip_id, render_state="error", render_error="Cancelled")
        raise
    except Exception as e:  # noqa: BLE001
        db.update("clips", clip_id, render_state="error", render_error=str(e)[:500])
        if log:
            log(f"Clip {clip_id} failed to render: {str(e)[:300]}")
    finally:
        publish_clip(clip_id)


def render_all(ctx: JobContext, ids: list[int]) -> None:
    todo = [i for i in ids if (db.get("clips", i) or {}).get("render_state") != "ready"]
    if not todo:
        return
    ctx.log(f"Downloading and rendering {len(todo)} clips…")
    done = [0]
    lock = threading.Lock()

    def one(cid: int) -> None:
        if ctx.cancel.is_set():
            return
        render_clip(cid, ctx.log, ctx.cancel)
        with lock:
            done[0] += 1
            ctx.progress(done[0] / len(todo))

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(one, todo))
    ctx.check()


# ---------------------------------------------------------------- VOD pipeline
def analyze(ctx: JobContext, *, url: str, platform: str, cache: Path, duration: float,
            extra: dict | None = None, label: str = "", chat_thread: threading.Thread | None = None,
            chat_path: Path | None = None, clip_times: list[tuple[float, float]] | None = None,
            count: int | None = None, audio_extra: dict | None = None, t_offset: float = 0.0,
            chat_wait_max: float | None = None) -> list[int]:
    """Analyse one source and make clips.

    `audio_extra` are yt-dlp options for the audio download only (e.g. a time range); when the
    downloaded audio starts at `t_offset` seconds into the source, every time is shifted back to
    source time before clips are created.
    """
    job = ctx.job
    opts = resolve_options(job)
    count = count or opts["clip_count"]
    streamer = db.get("streamers", job["streamer_id"]) if job.get("streamer_id") else None
    marker = ctx.dir / f"selected{label}.json"
    if marker.exists():
        ids = [i for i in json.loads(marker.read_text()) if db.get("clips", i)]
        ctx.log(f"Resuming: {len(ids)} clips were already chosen.")
        ctx.stage("rendering")
        render_all(ctx, ids)
        return ids

    ctx.stage("downloading", "Downloading audio only (fast path) so analysis can start right away…")
    if platform == "file":
        audio = Path(url)
    else:
        audio = common.download_audio(url, cache, platform, log=ctx.log, cancel=ctx.cancel,
                                      progress=ctx.progress, extra={**(extra or {}), **(audio_extra or {})})
    if not duration or t_offset:
        duration = media.duration(audio)
    n = int(math.ceil(duration))
    ctx.log(f"Audio ready ({fmt_time(duration)}). Measuring loudness…")
    rms = load_rms(audio, cache, ctx.cancel)

    ctx.stage("chat")
    chat: list[dict] = []
    if chat_thread is not None:
        if chat_thread.is_alive():
            ctx.log("Waiting for the chat replay download to finish…")
        waited = 0.0
        while chat_thread.is_alive() and (chat_wait_max is None or waited < chat_wait_max):
            ctx.check()
            chat_thread.join(1)
            waited += 1
        if chat_thread.is_alive():
            ctx.log("Chat replay is still downloading — scoring with the chat saved so far.")
    if chat_path is not None:
        chat = chatmod.load(chat_path)
        if t_offset:
            chat = [{"t": m["t"] - t_offset, "m": m["m"]} for m in chat if m["t"] >= t_offset]
        ctx.log(f"Chat: {len(chat)} messages.")
    if clip_times and t_offset:
        clip_times = [(t - t_offset, w) for t, w in clip_times if t >= t_offset]

    ctx.stage("transcribing")
    s = db.all_settings()
    long_video = duration > 90 * 60
    if s["transcribe_mode"] == "smart" and long_video:
        pre = build_signals(n, rms=rms, chat=chat, words=None, streamer=streamer, clip_times=clip_times)
        pre_c = scoring.find_moments(pre, weights(), count * 4, min_len=opts["min_len"], max_len=opts["max_len"])
        ranges = transcribe.merge_ranges([(c["start"] - 50, c["end"] + 50) for c in pre_c], duration)
        ctx.log(f"Long video: transcribing only the {len(ranges)} most promising areas "
                f"({sum(b - a for a, b in ranges) / 60:.0f} min). Set 'Transcribe' to 'full' in Settings to do everything.")
    else:
        ranges = [(0.0, duration)]
    tr = transcribe.transcribe(audio, cache / "transcript", ranges, log=ctx.log, cancel=ctx.cancel,
                               progress=ctx.progress)
    words, segments = tr["words"], tr["segments"]

    ctx.stage("scoring", "Scoring moments…")
    sig = build_signals(n, rms=rms, chat=chat, words=words, streamer=streamer, clip_times=clip_times)
    cands = scoring.find_moments(sig, weights(), count * 2, min_len=opts["min_len"], max_len=opts["max_len"],
                                 words=words, segments=segments)
    common.info_json(ctx.dir / f"candidates{label}.json", cands)
    ctx.log(f"Found {len(cands)} candidate moments.")
    if not cands:
        raise UserError("No hype moments found — the video may be silent or too short.")
    chosen = choose(ctx, cands, count=count, opts=opts, words=words, segments=segments, chat=chat,
                    streamer=streamer, n=n)
    if t_offset:
        for c in chosen:
            c["start"] += t_offset
            c["end"] += t_offset
            c["peak"] += t_offset
        words = [{**w, "s": w["s"] + t_offset, "e": w["e"] + t_offset} for w in words]
    ctx.log("Chosen: " + ", ".join(f"{fmt_time(c['start'])}–{fmt_time(c['end'])}" for c in chosen))
    ids = create_clips(ctx, chosen, job=ctx.job, opts=opts, source_url=url, source_extra=extra, words=words)
    marker.write_text(json.dumps(ids))
    ctx.stage("rendering")
    render_all(ctx, ids)
    if not opts["keep_source"] and platform != "file":
        for p in list(cache.glob("audio.*")) + list(cache.glob("full.*")):
            if p.suffix != ".done":
                p.unlink(missing_ok=True)
        (cache / "audio.done").unlink(missing_ok=True)
        (cache / "full.done").unlink(missing_ok=True)
    return ids


def run_vod(ctx: JobContext) -> None:
    job = ctx.job
    det = detect(job["url"])
    ctx.stage("downloading", f"Fetching info for {job['url']}")
    meta = common.info_json(ctx.dir / "meta.json")
    if meta is None and det.platform == "file":
        meta = local_metadata(Path(det.url))
    if meta is None:
        meta = common.metadata(det.url, det.platform, ctx.log)
        common.info_json(ctx.dir / "meta.json", meta)
    if meta["is_live"]:
        ctx.log("This link is live right now — switching to live mode (catch-up + watch).")
        ctx.set(is_live=1, status="queued", title=meta["title"], channel=meta["channel"])
        raise Relaunch()
    max_h = float(db.setting("max_video_hours") or 12)
    if meta["duration"] and meta["duration"] > max_h * 3600:
        raise UserError(f"This video is {meta['duration'] / 3600:.1f} h long, over the {max_h:g} h limit "
                        f"(change it in Settings → Storage).")
    ctx.set(title=meta["title"], channel=meta["channel"], duration=meta["duration"], platform=det.platform)
    ctx.log(f"“{meta['title']}” by {meta['channel']} — {fmt_time(meta['duration'])}")
    cache = cache_dir(det.platform, meta["id"] or str(job["id"]))

    # chat replay runs in parallel with the audio download
    chat_thread, chat_path = None, None
    if det.platform == "file":
        side = Path(det.url).with_suffix(".chat.jsonl")
        if side.exists():
            chat_path = side
            ctx.log(f"Using chat file {side.name}.")
        else:
            ctx.log("Local file: no chat (put a <name>.chat.jsonl next to it to add one).")
    elif det.platform == "kick":
        ctx.log("Kick has no chat replay — scoring uses audio + transcript only.")
    else:
        chat_path = cache / "chat.jsonl"
        if det.platform == "twitch":
            chat_thread = threading.Thread(target=twitch.chat_replay,
                                           args=(meta["webpage_url"], meta["duration"], chat_path),
                                           kwargs={"cancel": ctx.cancel, "log": ctx.log}, daemon=True)
        else:
            chat_thread = threading.Thread(target=chatmod.replay, args=(meta["webpage_url"], chat_path),
                                           kwargs={"cancel": ctx.cancel, "log": ctx.log, "duration": meta["duration"]},
                                           daemon=True)
        chat_thread.start()
    clip_times = None
    if det.platform == "twitch":
        clip_times = twitch.viewer_clips(meta["webpage_url"], meta.get("channel_id"), ctx.log)
    analyze(ctx, url=meta["webpage_url"], platform=det.platform, cache=cache, duration=meta["duration"],
            chat_thread=chat_thread, chat_path=chat_path, clip_times=clip_times)


def local_metadata(path: Path) -> dict:
    if not path.exists():
        raise UserError(f"File not found: {path}")
    return {"id": f"{path.stem}_{int(path.stat().st_mtime)}", "title": path.stem, "channel": "",
            "channel_id": "", "duration": media.duration(path), "is_live": False, "live_status": None,
            "release_timestamp": None, "webpage_url": str(path), "width": None, "height": None}


def run_live(ctx: JobContext) -> None:
    from . import live
    live.run_live(ctx)


# ---------------------------------------------------------------- housekeeping
def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def housekeeping() -> None:
    """Keep disk use under the limit by deleting the oldest *source* files (never rendered clips)."""
    limit = float(db.setting("max_disk_gb") or 0) * 1024 ** 3
    root = db.storage_dir()
    if limit > 0:
        active = {str(j) for j in manager.contexts}
        files = []
        for sub in ("cache", "jobs"):
            base = root / sub
            if not base.exists():
                continue
            for p in base.rglob("*"):
                if p.is_file() and p.suffix in (".mp4", ".m4a", ".webm", ".ts", ".mkv", ".opus", ".mp3", ".aac", ".wav"):
                    files.append(p)
        total = sum(_size(p) for p in root.rglob("*") if p.is_file())
        if total > limit:
            files.sort(key=lambda p: p.stat().st_mtime)
            for p in files:
                if total <= limit * 0.9:
                    break
                if sub_job_active(p, root, active):
                    continue
                total -= _size(p)
                p.unlink(missing_ok=True)
                done = p.with_suffix(".done")
                done.unlink(missing_ok=True)
    try:
        from . import publish
        publish.retry_due_uploads()
    except Exception:  # noqa: BLE001
        pass


def sub_job_active(p: Path, root: Path, active: set[str]) -> bool:
    try:
        rel = p.relative_to(root / "jobs")
        return rel.parts[0] in active
    except ValueError:
        return False


manager.configure(run_vod, run_live)
