import json

from adgen import ffmpeg
from adgen.assembly.captions import build_ass, group_words
from adgen.assembly.compose import measure_lufs
from adgen.avatar.library import AvatarLibrary
from adgen.config import Settings, font_file
from adgen.cost import estimate_render, read_ledger
from adgen.models import AvatarSpec, Word
from adgen.pipeline import Renderer, plan_spans
from adgen.script.mock import MockScriptWriter


def test_caption_grouping_and_ass():
    words = [
        Word(text="Okay,", start=0.1, end=0.4, segment=0),
        Word(text="real", start=0.45, end=0.7, segment=0),
        Word(text="question.", start=0.75, end=1.2, segment=0),
        Word(text="Meet", start=1.5, end=1.8, segment=1),
        Word(text="{Brew}", start=1.85, end=2.2, segment=1),
    ]
    groups = group_words(words)
    assert [[w.text for w in g] for g in groups] == [["Okay,", "real", "question."], ["Meet", "{Brew}"]]
    ass = build_ass(words, (1080, 1920), font_file(), 3.0)
    events = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    assert len(events) == 5
    assert "PlayResY: 1920" in ass
    assert "{Brew}" not in ass and "(BREW)" in ass  # override braces escaped


def test_plan_spans_widens_short_windows(brief):
    script = MockScriptWriter().write(brief).get("A")
    n = len(script.segments)
    bounds = [(i * 1.0, (i + 1) * 1.0) for i in range(n)]
    spans = plan_spans(script, bounds, float(n))
    visuals = [s.visual for s in script.segments]
    assert sum(len(sp.segments) for sp in spans) == visuals.count("avatar")
    for sp in spans:
        assert sp.win_end - sp.win_start >= 2.0 - 1e-9
        assert sp.win_start <= sp.start and sp.win_end >= min(sp.end, n)


def test_estimate_render_uses_pricing(brief):
    scripts = MockScriptWriter().write(brief).variants
    providers = {"script": "claude", "portrait": "flux2pro", "voice": "elevenlabs", "lipsync": "kling_avatar_v2_pro", "music": "elevenlabs"}
    est = estimate_render(brief, scripts, providers, "eleven_v3", new_avatar=True)
    by_stage = {}
    for line in est.lines:
        by_stage[line.stage] = by_stage.get(line.stage, 0) + line.usd
    assert 0.5 < by_stage["lipsync"] < 3 * brief.length * 0.115
    assert by_stage["avatar"] == 0.05
    assert est.total > 0
    mock = estimate_render(brief, scripts, {k: "mock" for k in providers}, "eleven_v3")
    assert mock.total == 0


def test_offline_render_end_to_end(tmp_path, brief):
    brief = brief.model_copy(update={"length": 15, "aspect_ratios": ["9:16", "16:9"]})
    settings = Settings().offline().with_overrides(output_dir=tmp_path / "out", cache_dir=tmp_path / "cache")
    library = AvatarLibrary(tmp_path / "avatars")
    avatar, _ = library.create("Test Host", AvatarSpec(), settings)
    script_set = MockScriptWriter().write(brief)
    results = Renderer(settings).render(brief, [script_set.get("B")], avatar, library, script_set)

    (res,) = results
    assert set(res.videos) == {"9:16", "16:9"}
    assert ffmpeg.video_size(res.videos["9:16"]) == (1080, 1920)
    assert ffmpeg.video_size(res.videos["16:9"]) == (1920, 1080)
    for v in res.videos.values():
        assert abs(ffmpeg.duration(v) - res.duration) < 0.15
        assert 14.0 <= res.duration <= 15.6
        assert abs(measure_lufs(v) - (-14.0)) < 1.0
    for name in ("script.json", "script.txt", "settings.json", "cost.json", "thumbnail.jpg", "thumbnail_16x9.jpg"):
        assert (res.folder / name).exists(), name
    settings_json = json.loads((res.folder / "settings.json").read_text())
    assert settings_json["options"]["ai_label"] is True
    ledger = read_ledger(tmp_path / "out" / "cost_log.jsonl")
    assert ledger[-1]["kind"] == "render" and ledger[-1]["total_usd"] == 0.0
