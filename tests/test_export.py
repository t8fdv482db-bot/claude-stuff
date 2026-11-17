"""Exports: caption text and the approved-clips zip."""
import zipfile

from clipstudio import db, export


def test_caption_and_zip(home, tmp_path):
    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"fake mp4")
    a = db.insert("clips", job_id=1, start=0, end=30, status="approved", render_state="ready", video_path=str(vid),
                  title="Lacy's car flies", description="#ad Paid by Whop\nLacy's car flies\n\n#gta6")
    db.insert("clips", job_id=1, start=0, end=30, status="pending", render_state="ready", video_path=str(vid), title="nope")
    assert export.caption_text(db.get("clips", a)).startswith("#ad Paid by Whop")
    z = export.export_zip([a])
    names = zipfile.ZipFile(z).namelist()
    assert names == [f"{a:04d}_Lacys_car_flies.mp4", f"{a:04d}_Lacys_car_flies.txt"]


def test_old_youtube_login_data_is_removed(tmp_path, monkeypatch):
    """Upgrading from a version with the YouTube login drops its columns, setting and saved token."""
    import sqlite3
    home = tmp_path / "old"
    (home / "youtube").mkdir(parents=True)
    (home / "youtube" / "token.json").write_text("{}")
    c = sqlite3.connect(home / "clipstudio.db")
    c.executescript(db.SCHEMA)                       # today's tables + the old YouTube columns
    for col in ("youtube_id", "yt_state", "publish_at", "yt_error", "yt_retry_after"):
        c.execute(f"ALTER TABLE clips ADD COLUMN {col} TEXT")
    c.execute("INSERT INTO settings VALUES ('yt_slots', '\"11:00\"')")
    c.execute("INSERT INTO clips (job_id, youtube_id) VALUES (1, 'abc')")
    c.commit(); c.close()
    monkeypatch.setenv("CLIPSTUDIO_HOME", str(home))
    db.set_home(home)
    db.conn()
    cols = {r["name"] for r in db.q("PRAGMA table_info(clips)")}
    assert not cols & {"youtube_id", "yt_state", "publish_at"} and "originality" in cols
    assert db.q1("SELECT * FROM settings WHERE key='yt_slots'") is None
    assert not (home / "youtube").exists()
    assert db.q1("SELECT COUNT(*) n FROM clips")["n"] == 1          # clips themselves are kept
    db.set_home(tmp_path / "unused")
