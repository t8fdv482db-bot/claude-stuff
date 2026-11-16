"""End-to-end on synthetic media: the scorer must find the planted moments and render proper Shorts."""
import json
import shutil

import pytest

from synth import SPIKES, fake_words, make_chat, make_video

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


@pytest.fixture(scope="module")
def media_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("synth")
    video = make_video(d / "stream.mp4")
    make_chat(d / "stream.chat.jsonl")
    return video


def test_finds_planted_moments_and_renders(home, media_dir, monkeypatch):
    from clipstudio import db, media, pipeline, transcribe
    from clipstudio.worker import JobContext

    def fake_transcribe_wav(wav, offset, log=None, cancel=None):
        return fake_words(offset, offset + media.duration(wav))

    monkeypatch.setattr(transcribe, "transcribe_wav", fake_transcribe_wav)

    jid = db.insert("jobs", url=str(media_dir), platform="file", streamer_id=1,
                    options=json.dumps({"clip_count": 3, "min_len": 20, "max_len": 60, "layout": "blur"}),
                    status="running", stage="queued", created=db.now())
    ctx = JobContext(jid)
    pipeline.run_vod(ctx)

    clips = db.q("SELECT * FROM clips WHERE job_id=? ORDER BY peak", (jid,))
    assert len(clips) == 3, (ctx.log_path.read_text())
    for clip, spike in zip(clips, SPIKES):
        assert abs(clip["peak"] - spike) <= 5, f"peak {clip['peak']} not near {spike}"
        assert clip["start"] <= spike <= clip["end"]
        length = clip["end"] - clip["start"]
        assert 20 <= length <= 60, length
        assert clip["render_state"] == "ready", clip["render_error"]
        info = media.probe(clip["video_path"])
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        assert (v["width"], v["height"]) == (1080, 1920)
        assert any(s["codec_type"] == "audio" for s in info["streams"])
        assert abs(float(info["format"]["duration"]) - length) < 0.6
        assert media.duration(clip["gif_path"]) > 0
        assert clip["title"]
