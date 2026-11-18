"""Multi-account posting: assignments, anti-demonetization safeguards, pipeline, calendar, analytics."""
import json
from datetime import datetime, timedelta

import pytest


@pytest.fixture()
def setup(home):
    from clipstudio import accounts as acc
    from clipstudio import db
    db.set_setting("timezone", "America/New_York")
    kai = db.insert("streamers", name="Kai Cenat", layout="blur")
    jid = db.insert("jobs", url="https://www.twitch.tv/videos/1", platform="twitch", channel="kaicenat",
                    title="GTA 6 LAUNCH DAY", created=db.now())

    def clip(streamer=kai, length=45, **kw):
        vals = dict(job_id=jid, streamer_id=streamer, start=100, end=100 + length, status="approved",
                    render_state="ready", title="Kai crashes the plane", description="Kai Cenat live on Twitch",
                    hook="NO WAY", created=db.now())
        vals.update(kw)
        return db.insert("clips", **vals)

    yt1 = acc.create_account({"platform": "youtube", "handle": "kaiclips", "niche": "Kai Cenat GTA 6"})
    yt2 = acc.create_account({"platform": "youtube", "handle": "@gtamoments", "niche": "GTA 6"})
    tt = acc.create_account({"platform": "tiktok", "handle": "kai.tt", "niche": "Kai Cenat GTA 6", "daily_limit": 2})
    return {"acc": acc, "db": db, "clip": clip, "kai": kai, "yt1": yt1, "yt2": yt2, "tt": tt}


def tick_all(acc, cid):
    acc.set_checklist(cid, {"captions": True, "commentary": True, "credit": True})


def test_account_basics(setup):
    acc, yt1 = setup["acc"], setup["yt1"]
    assert yt1["handle"] == "@kaiclips" and yt1["daily_limit"] == 3 and yt1["color"].startswith("#")
    assert setup["tt"]["daily_limit"] == 2
    with pytest.raises(acc.RuleError):
        acc.create_account({"platform": "youtube", "handle": "KaiClips"})       # duplicate handle
    with pytest.raises(acc.RuleError):
        acc.create_account({"platform": "myspace", "handle": "x"})
    assert [a["platform"] for a in acc.list_accounts()] == ["youtube", "youtube", "tiktok"]


def test_same_platform_twice_is_blocked(setup):
    acc, cid = setup["acc"], setup["clip"]()
    acc.assign(cid, setup["yt1"]["id"])
    with pytest.raises(acc.RuleError, match="already assigned to @kaiclips on YouTube Shorts"):
        acc.assign(cid, setup["yt2"]["id"])
    a, _ = acc.assign(cid, setup["tt"]["id"])                                    # other platform is fine
    assert a["account_id"] == setup["tt"]["id"]


def test_niche_mismatch_warns(setup):
    acc, db = setup["acc"], setup["db"]
    lacy = db.insert("streamers", name="Lacy", layout="blur")
    ok_clip = setup["clip"]()
    other = setup["clip"](streamer=lacy, title="Lacy wins", description="Lacy live")
    _, w_ok = acc.assign(ok_clip, setup["yt1"]["id"])
    assert not any("Doesn't look like" in w for w in w_ok)
    _, w_bad = acc.assign(other, setup["yt1"]["id"])
    assert any("Kai Cenat" in w for w in w_bad)
    # a plain topic niche matches by topic words
    assert acc.niche_match("GTA 6", db.get("clips", ok_clip))[0]
    assert acc.niche_match("", db.get("clips", other))[0]


def test_checklist_required_before_ready(setup):
    acc, cid = setup["acc"], setup["clip"]()
    a, _ = acc.assign(cid, setup["yt1"]["id"])
    with pytest.raises(acc.RuleError, match="originality checklist"):
        acc.move(a["id"], "edited")
    acc.set_checklist(cid, {"captions": True, "commentary": True})
    with pytest.raises(acc.RuleError, match="credited"):
        acc.move(a["id"], "edited")
    acc.set_checklist(cid, {"credit": True})
    a, _ = acc.move(a["id"], "edited")
    assert a["status"] == "edited"
    acc.set_checklist(cid, {"credit": False})                                    # un-tick → back to raw
    assert setup["db"].get("assignments", a["id"])["status"] == "raw"


def test_hints(setup):
    acc, db = setup["acc"], setup["db"]
    h = acc.checklist_hints(db.get("clips", setup["clip"]()))
    assert "captions" in h and "commentary" in h and "Kai Cenat" in h["credit"]


def test_length_flags(setup):
    acc, db = setup["acc"], setup["db"]
    long_clip = db.get("clips", setup["clip"](length=200))
    assert any("Too long for YouTube Shorts" in w for w in acc.length_flags(long_clip, "youtube"))
    assert not any("Too long" in w for w in acc.length_flags(long_clip, "tiktok"))
    short = db.get("clips", setup["clip"](length=30))
    assert any("Creator Rewards" in w for w in acc.length_flags(short, "tiktok"))
    db.set_setting("max_len_youtube", 60.0)
    assert acc.length_flags(db.get("clips", setup["clip"](length=61)), "youtube")


def test_daily_limit_warning(setup):
    acc, tt = setup["acc"], setup["tt"]
    day = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    warns = []
    for i in range(3):
        cid = setup["clip"](length=70)
        tick_all(acc, cid)
        a, _ = acc.assign(cid, tt["id"])
        _, w = acc.move(a["id"], "scheduled", scheduled_at=f"{day} 1{i}:00")
        warns.append(w)
    assert not any("limit" in x for x in warns[0] + warns[1])
    assert any("limit 2/day" in x for x in warns[2])


def test_schedule_needs_time_and_post_syncs_submissions(setup):
    acc, db = setup["acc"], setup["db"]
    cid = setup["clip"]()
    tick_all(acc, cid)
    a, _ = acc.assign(cid, setup["yt1"]["id"])
    with pytest.raises(acc.RuleError, match="date"):
        acc.move(a["id"], "scheduled")
    a, _ = acc.move(a["id"], "scheduled", scheduled_at="2030-01-02T15:30")
    assert a["scheduled_at"] == "2030-01-02 15:30"
    with pytest.raises(acc.RuleError, match="https"):
        acc.move(a["id"], "posted", post_url="youtube.com/x")
    a, _ = acc.move(a["id"], "posted", post_url="https://youtube.com/shorts/abc")
    assert a["status"] == "posted" and a["posted_at"]
    post = db.q1("SELECT * FROM posts WHERE clip_id=?", (cid,))
    assert post["platform"] == "youtube" and post["url"].endswith("abc")


def test_rejected_and_unrendered_clips(setup):
    acc = setup["acc"]
    with pytest.raises(acc.RuleError, match="rejected"):
        acc.assign(setup["clip"](status="rejected"), setup["yt1"]["id"])
    cid = setup["clip"](render_state="rendering")
    tick_all(acc, cid)
    a, _ = acc.assign(cid, setup["yt1"]["id"])
    with pytest.raises(acc.RuleError, match="rendered"):
        acc.move(a["id"], "edited")


def test_calendar_and_filters(setup):
    acc = setup["acc"]
    cid = setup["clip"](length=70)
    tick_all(acc, cid)
    a, _ = acc.assign(cid, setup["tt"]["id"])
    today = acc.today_local().isoformat()
    acc.move(a["id"], "scheduled", scheduled_at=f"{today} 23:59")
    wk = acc.week(0)
    day = next(d for d in wk["days"] if d["date"] == today)
    assert [it["id"] for it in day["items"]] == [a["id"]] and day["items"][0]["time"] == "23:59"
    assert len(acc.list_assignments(platform="tiktok")) == 1
    assert acc.list_assignments(platform="youtube") == []
    assert len(acc.list_assignments(streamer_id=setup["kai"], status="scheduled")) == 1


def test_analytics(setup):
    acc = setup["acc"]
    for acct, views, money in ((setup["yt1"], 12000, 3.5), (setup["tt"], 50000, 20)):
        cid = setup["clip"](length=70)
        tick_all(acc, cid)
        a, _ = acc.assign(cid, acct["id"])
        acc.move(a["id"], "posted")
        acc.log_stats(a["id"], views=f"{views:,}", earnings=f"${money}")
    data = acc.analytics()
    assert data["totals"] == {"views": 62000, "earnings": 23.5, "posts": 2}
    tt = data["platforms"]["tiktok"]
    assert tt["views"] == 50000 and tt["streamers"][0]["name"] == "Kai Cenat"
    assert tt["topics"][0]["name"] == "Kai Cenat GTA 6" and tt["rpm"] == 0.4
    with pytest.raises(acc.RuleError):
        acc.log_stats(1, views="lots")
    _ = json


def test_campaign_platform_rule_warns_on_board(setup):
    acc, db = setup["acc"], setup["db"]
    camp = db.insert("campaigns", name="Marlon Reach", platforms=json.dumps(["tiktok", "instagram"]))
    cid = setup["clip"](campaign_id=camp)
    _, w = acc.assign(cid, setup["yt1"]["id"])
    assert any("doesn't allow posting on youtube" in x for x in w)
    _, w = acc.assign(cid, setup["tt"]["id"])
    assert not any("doesn't allow" in x for x in w)
