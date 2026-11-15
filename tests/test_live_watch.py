"""Watch mode on pre-recorded segments that 'arrive' one minute at a time."""
import json
import shutil
import subprocess

import pytest

from synth import SPIKES, fake_words, make_chat, make_video

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def test_watch_mode_cuts_moments_as_they_happen(home, tmp_path, monkeypatch):
    from clipstudio import db, live, media, transcribe
    from clipstudio.sources import Detected
    from clipstudio.worker import JobContext

    monkeypatch.setattr(transcribe, "transcribe_wav",
                        lambda wav, off, log=None, cancel=None: fake_words(off, off + media.duration(wav)))
    src = make_video(tmp_path / "live.mp4")
    chat = [json.loads(x) for x in make_chat(tmp_path / "chat.jsonl").read_text().splitlines()]
    seg_dir = tmp_path / "segs"
    seg_dir.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-c", "copy", "-f", "segment", "-segment_time", "60",
                    "-reset_timestamps", "1", "-segment_list", "all.csv", "-segment_list_type", "csv",
                    "seg_%05d.ts"], cwd=seg_dir, check=True)
    rows = (seg_dir / "all.csv").read_text().splitlines()

    jid = db.insert("jobs", url="https://www.twitch.tv/test", platform="twitch", is_live=1, streamer_id=1,
                    options=json.dumps({"min_len": 20, "max_len": 60}), created=db.now())
    ctx = JobContext(jid)
    w = live.Watcher(ctx, Detected("https://www.twitch.tv/test", "twitch", "live", "test"),
                     {"webpage_url": "https://www.twitch.tv/test"})
    run_dir = w.dir / "run_0"
    run_dir.mkdir()
    w.rec.runs.append({"dir": run_dir, "wall0": w.wall0, "started": w.wall0, "tool": "test", "offset": 0.0})
    w.chat = []
    notified = []
    monkeypatch.setattr(live.notify, "clip_ready", lambda cid, log=None: notified.append(cid))

    for k, row in enumerate(rows):                      # one new minute per tick
        name = row.split(",")[0]
        shutil.copy(seg_dir / name, run_dir / name)
        with open(run_dir / "list.csv", "a") as fh:
            fh.write(row + "\n")
        t_end = float(row.split(",")[2])
        w.chat = [m for m in chat if m["t"] <= t_end]
        w.tick(final=(k == len(rows) - 1))

    clips = db.q("SELECT * FROM clips WHERE job_id=? ORDER BY peak", (jid,))
    assert len(clips) == len(SPIKES), ctx.log_path.read_text()
    for c, spike in zip(clips, SPIKES):
        assert abs(c["peak"] - spike) <= 5
        assert 20 <= c["end"] - c["start"] <= 60
        assert c["render_state"] == "ready", c["render_error"]
    assert notified == [c["id"] for c in db.q("SELECT id FROM clips WHERE job_id=? ORDER BY id", (jid,))]
    scores = live.scores_for(jid)
    assert len(scores["t"]) > 300 and scores["clips"]
