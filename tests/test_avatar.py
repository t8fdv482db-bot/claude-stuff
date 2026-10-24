from pathlib import Path

import pytest

from adgen import ffmpeg
from adgen.avatar.library import AvatarLibrary
from adgen.config import Settings
from adgen.lipsync import fal as fal_lipsync
from adgen.lipsync.mock import MockLipSync
from adgen.models import AdScript, AvatarSpec, ScriptSegment
from adgen.safety import SafetyError
from adgen.voice.mock import MockVoice


@pytest.fixture
def library(tmp_path):
    return AvatarLibrary(tmp_path / "avatars")


def test_create_list_get_delete(library):
    s = Settings().offline()
    a, cost = library.create("Brand Face", AvatarSpec(gender="man", age="40s"), s)
    assert a.id == "brand-face" and a.voice_id == "mock-120"
    assert library.portrait_path(a).exists()
    b, _ = library.create("Brand Face", AvatarSpec(), s)
    assert b.id == "brand-face-2"
    assert [x.id for x in library.list()] == ["brand-face", "brand-face-2"]
    assert library.get("brand-face").spec.gender == "man"
    library.delete("brand-face")
    assert [x.id for x in library.list()] == ["brand-face-2"]
    assert cost.total == 0.0


def test_create_rejects_real_person(library):
    with pytest.raises(SafetyError):
        library.create("x", AvatarSpec(extra="a lookalike of a famous singer"), Settings().offline())
    assert library.list() == []


def test_mock_lipsync_matches_audio(library, tmp_path):
    a, _ = library.create("Maya", AvatarSpec(), Settings().offline())
    script = AdScript(
        variant="A", angle="x", on_screen_cta="x",
        segments=[ScriptSegment(role="hook", text="Hello there, this is short."), ScriptSegment(role="cta", text="Bye now.")],
    )
    track = MockVoice().synthesize(script, a.voice_id, "en", tmp_path)
    out = tmp_path / "talk.mp4"
    secs = MockLipSync().animate(a, library.portrait_path(a), Path(track.audio_path), out)
    assert abs(secs - track.duration) < 0.15
    assert ffmpeg.video_size(out) == (1080, 1920)


def test_fal_lipsync_request_shape(monkeypatch, tmp_path, library):
    a, _ = library.create("Maya", AvatarSpec(), Settings().offline())
    calls = {}
    monkeypatch.setattr(fal_lipsync.falai, "upload", lambda p: f"https://fal.test/{Path(p).name}")

    def fake_run(endpoint, args):
        calls["endpoint"], calls["args"] = endpoint, args
        return {"video": {"url": "https://fal.test/out.mp4"}, "duration": 4.2}

    monkeypatch.setattr(fal_lipsync.falai, "run", fake_run)
    monkeypatch.setattr(fal_lipsync.falai, "download", lambda url, dest: Path(dest).write_bytes(b"x"))
    wav = tmp_path / "a.wav"
    ffmpeg.run(["-f", "lavfi", "-i", "sine=frequency=200:duration=1", wav])
    secs = fal_lipsync.FalLipSync("kling_avatar_v2_pro").animate(a, library.portrait_path(a), wav, tmp_path / "o.mp4")
    assert secs == 4.2
    assert calls["endpoint"] == "fal-ai/kling-video/ai-avatar/v2/pro"
    assert calls["args"]["image_url"].endswith("portrait.png")
    assert calls["args"]["audio_url"].endswith(".mp3")
    with pytest.raises(ValueError):
        fal_lipsync.FalLipSync("nope")
