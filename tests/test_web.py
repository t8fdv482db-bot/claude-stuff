import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ADGEN_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("ADGEN_AVATAR_DIR", str(tmp_path / "avatars"))
    from adgen.web.app import app

    return TestClient(app)


def _wait(client, job):
    for _ in range(100):
        j = client.get(f"/api/jobs/{job}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.1)
    raise AssertionError("job timed out")


def test_brief_scripts_and_avatar_flow(client):
    assert client.get("/").status_code == 200
    sample = client.get("/api/sample").json()
    files = [("images", (u.rsplit("/", 1)[1], client.get(u).content, "image/jpeg")) for u in sample["image_urls"]]
    form = {
        "name": sample["name"], "description": sample["description"], "target_audience": sample["target_audience"],
        "selling_points": "\n".join(sample["selling_points"]), "cta": sample["cta"], "length": "15", "aspect_ratios": "9:16,1:1",
    }
    r = client.post("/api/brief", data=form, files=files)
    assert r.status_code == 200, r.text
    brief_id = r.json()["brief_id"]
    assert len(r.json()["brief"]["image_paths"]) == 3

    job = _wait(client, client.post("/api/scripts", data={"brief_id": brief_id, "offline": "true"}).json()["job"])
    assert job["status"] == "done", job
    scripts_file = job["result"]["scripts_file"]
    est = client.post("/api/render/estimate", data={"brief_id": brief_id, "scripts_file": scripts_file, "variants": "A,B", "offline": "true"}).json()
    assert est["total_usd"] == 0 and any(l["stage"] == "lipsync" for l in est["lines"])

    bad = client.post("/api/avatars", data={"name": "x", "extra": "a celebrity lookalike", "offline": "true"})
    assert bad.status_code == 400
    job = _wait(client, client.post("/api/avatars", data={"name": "Sam", "offline": "true"}).json()["job"])
    assert job["status"] == "done", job
    avatars = client.get("/api/avatars").json()
    assert [a["id"] for a in avatars] == ["sam"]
    assert client.get(avatars[0]["portrait"]).status_code == 200


def test_files_route_blocks_traversal(client):
    assert client.get("/files/../pyproject.toml").status_code == 404
    assert client.get("/api/brief-nope").status_code == 404
