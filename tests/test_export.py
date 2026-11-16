"""Exports: caption text and the approved-clips zip."""
import zipfile

from clipstudio import db, publish


def test_caption_and_zip(home, tmp_path):
    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"fake mp4")
    a = db.insert("clips", job_id=1, start=0, end=30, status="approved", render_state="ready", video_path=str(vid),
                  title="Lacy's car flies", description="#ad Paid by Whop\nLacy's car flies\n\n#gta6")
    db.insert("clips", job_id=1, start=0, end=30, status="pending", render_state="ready", video_path=str(vid), title="nope")
    assert publish.caption_text(db.get("clips", a)).startswith("#ad Paid by Whop")
    z = publish.export_zip([a])
    names = zipfile.ZipFile(z).namelist()
    assert names == [f"{a:04d}_Lacys_car_flies.mp4", f"{a:04d}_Lacys_car_flies.txt"]
    assert publish.youtube_description(db.get("clips", a)).endswith("#shorts")


def test_upload_refuses_unapproved(home):
    import pytest
    from datetime import datetime, timezone
    cid = db.insert("clips", job_id=1, start=0, end=30, status="pending", render_state="ready")
    with pytest.raises(PermissionError):
        publish.upload(cid, datetime.now(timezone.utc))


def test_schedule_quota_marks_rest_for_retry(home, monkeypatch):
    db.set_setting("yt_slots", "11:00, 15:00, 19:00, 22:00")
    db.set_setting("timezone", "America/New_York")
    ids = [db.insert("clips", job_id=1, start=0, end=30, status="approved", render_state="ready", title=f"c{i}")
           for i in range(3)]
    calls = []

    def fake_upload(cid, when):
        calls.append((cid, when))
        if len(calls) == 2:
            raise publish.QuotaError("quotaExceeded")
        return f"yt{cid}"

    monkeypatch.setattr(publish, "credentials", lambda: object())
    monkeypatch.setattr(publish, "upload", fake_upload)
    started = []
    monkeypatch.setattr(publish.threading, "Thread",
                        lambda target, args=(), daemon=None: type("T", (), {"start": lambda self: started.append(target(*args))})())
    r = publish.schedule_approved()
    assert r["ok"]
    c = [db.get("clips", i) for i in ids]
    assert c[0]["youtube_id"] == f"yt{ids[0]}" and c[0]["yt_state"] == "scheduled"
    assert [x["yt_state"] for x in c[1:]] == ["retry", "retry"]
    assert "quota" in c[1]["yt_error"] and c[1]["yt_retry_after"] > 0
    times = [w for _, w in calls]
    assert times[0] < times[1]
