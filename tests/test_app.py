"""HTTP API smoke tests (no media work)."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(home, monkeypatch):
    from clipstudio import app as appmod
    from clipstudio.worker import manager
    monkeypatch.setattr(manager, "submit", lambda job_id: None)       # don't actually run jobs
    monkeypatch.setattr(manager, "resume_unfinished", lambda: None)
    with TestClient(appmod.app) as c:
        yield c


def test_pages_render(client):
    for path in ("/", "/review", "/streamers", "/streamers/1", "/campaigns", "/submissions", "/settings",
                 "/accounts", "/board", "/pipeline", "/calendar", "/calendar?week=1", "/analytics"):
        r = client.get(path)
        assert r.status_code == 200, path


def test_create_jobs_detects_platforms(client):
    r = client.post("/api/jobs", json={"urls": "https://www.twitch.tv/videos/123\nkick.com/somebody\nhttps://youtu.be/abc", "clip_count": 5})
    jobs = r.json()["jobs"]
    assert [(j["platform"], j["is_live"]) for j in jobs] == [("twitch", 0), ("kick", 1), ("youtube", 0)]
    assert jobs[0]["options"]["clip_count"] == 5
    assert client.post("/api/jobs", json={"urls": "https://example.com/x"}).status_code == 400


def test_api_key_is_never_returned(client):
    client.post("/api/settings", json={"anthropic_api_key": "sk-ant-TOPSECRET", "clip_count": 4})
    assert "TOPSECRET" not in client.get("/settings").text
    client.post("/api/settings", json={"anthropic_api_key": ""})          # empty = keep
    from clipstudio import db
    assert db.setting("anthropic_api_key") == "sk-ant-TOPSECRET" and db.setting("clip_count") == 4


def test_facecam_validation(client):
    assert client.put("/api/streamers/1", json={"facecam": {"x": 0.7, "y": 0, "w": 0.3, "h": 0.3}}).status_code == 200
    assert client.put("/api/streamers/1", json={"facecam": {"x": 0.9, "y": 0, "w": 0.3, "h": 0.3}}).status_code == 400


def test_time_parsing():
    from clipstudio.app import _parse_time
    assert _parse_time("1:23:45") == 5025 and _parse_time("83:10") == 4990 and _parse_time("2h3m4s") == 7384


def test_detect_local_and_urls(tmp_path):
    from clipstudio.sources import detect
    f = tmp_path / "vod.mp4"
    f.write_bytes(b"x")
    assert detect(str(f)).platform == "file"
    assert detect("https://www.twitch.tv/lacy").kind == "live"
    assert detect("https://www.twitch.tv/videos/2233445566").kind == "vod"
    assert detect("https://kick.com/video/abc-123").kind == "vod"
    assert detect("https://www.youtube.com/@lacy/live").kind == "live"


def test_find_ignores_marker_files(tmp_path):
    from clipstudio.sources.common import _find
    for n in ("audio.done", "audio.m4a.part", "audio.info.json", "audio.m4a"):
        (tmp_path / n).write_text("x")
    assert _find(tmp_path, "audio").name == "audio.m4a"


def test_account_api_flow(client):
    r = client.post("/api/accounts", json={"platform": "tiktok", "handle": "kai.tt", "niche": "Kai Cenat"})
    assert r.status_code == 200 and r.json()["handle"] == "@kai.tt"
    assert client.post("/api/accounts", json={"platform": "tiktok", "handle": "@KAI.TT"}).status_code == 409
    from clipstudio import db
    cid = db.insert("clips", job_id=1, start=0, end=70, status="approved", render_state="ready", title="t")
    r = client.post("/api/assignments", json={"clip_id": cid, "account_id": 1})
    aid = r.json()["assignment"]["id"]
    r = client.post(f"/api/assignments/{aid}/status", json={"status": "edited"})
    assert r.status_code == 409 and "checklist" in r.json()["error"]
    client.put(f"/api/clips/{cid}/checklist", json={"captions": True, "commentary": True, "credit": True})
    assert client.post(f"/api/assignments/{aid}/status", json={"status": "edited"}).status_code == 200
    assert client.get("/api/board").json()["pool"][0]["platforms"] == ["tiktok"]
