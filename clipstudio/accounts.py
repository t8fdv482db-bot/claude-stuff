"""Multi-account posting: accounts, clip→account assignments, anti-demonetization safeguards,
the Raw → Edited → Scheduled → Posted pipeline, calendar and simple analytics.

Every rule lives here (not in the browser), so it holds no matter which page you use.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import db

PLATFORMS = {
    "youtube": "YouTube Shorts",
    "tiktok": "TikTok",
    "instagram": "Instagram Reels",
}
STATUSES = ["raw", "edited", "scheduled", "posted"]
STATUS_LABELS = {"raw": "Raw", "edited": "Edited", "scheduled": "Scheduled", "posted": "Posted"}
CHECKLIST = {
    "captions": "Captions / on-screen text added",
    "commentary": "Commentary, hook or edits added (not a straight re-upload)",
    "credit": "Source streamer credited in the caption/description",
}
PALETTE = ["#ff3d6e", "#7c5cff", "#2fd27a", "#ffb020", "#29b6f6", "#ff7a45", "#e05cff", "#00c2a8"]
# TikTok's Creator Rewards program only pays for videos of 1 minute or more.
TIKTOK_REWARDS_MIN = 60.0
NICHE_STOPWORDS = {"the", "and", "clips", "clip", "shorts", "short", "best", "of", "moments", "highlights",
                   "funny", "daily", "live", "stream", "streams", "gaming", "fan", "fans", "page", "official"}


class RuleError(ValueError):
    """A safeguard blocked the action. The message is shown to the user as-is."""


# ---------------------------------------------------------------- helpers
def tz() -> ZoneInfo:
    try:
        return ZoneInfo(db.setting("timezone") or "UTC")
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def today_local() -> date:
    return datetime.now(tz()).date()


def platform_max_len(platform: str) -> float:
    return float(db.setting(f"max_len_{platform}") or {"youtube": 180, "tiktok": 600, "instagram": 180}[platform])


def clip_length(clip: dict) -> float:
    return float(clip.get("end") or 0) - float(clip.get("start") or 0)


def parse_sched(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip().replace("T", " ")[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        try:
            return datetime.strptime(s.strip()[:10], "%Y-%m-%d")
        except ValueError:
            return None


def posted_day(a: dict) -> date | None:
    if not a.get("posted_at"):
        return None
    return datetime.fromtimestamp(float(a["posted_at"]), timezone.utc).astimezone(tz()).date()


def activity_day(a: dict) -> date | None:
    """The day an assignment uses up one of the account's daily posts."""
    if a["status"] == "posted":
        return posted_day(a)
    if a["status"] == "scheduled":
        d = parse_sched(a.get("scheduled_at"))
        return d.date() if d else None
    return None


# ---------------------------------------------------------------- accounts
def validate_account(data: dict, existing: dict | None = None) -> dict:
    vals: dict = {}
    if "platform" in data or existing is None:
        p = str(data.get("platform", "")).lower().strip()
        if p not in PLATFORMS:
            raise RuleError("Pick a platform: YouTube Shorts, TikTok or Instagram Reels.")
        vals["platform"] = p
    if "handle" in data or existing is None:
        h = str(data.get("handle", "")).strip()
        if not h:
            raise RuleError("Give the account a handle, e.g. @kaiclips.")
        vals["handle"] = ("@" + h.lstrip("@"))[:60]
    if "niche" in data:
        vals["niche"] = str(data.get("niche") or "").strip()[:80]
    if "followers" in data:
        try:
            vals["followers"] = max(0, int(float(str(data.get("followers") or 0).replace(",", ""))))
        except ValueError as e:
            raise RuleError("Followers must be a number.") from e
    if "daily_limit" in data:
        try:
            vals["daily_limit"] = max(1, min(50, int(data.get("daily_limit") or 3)))
        except (TypeError, ValueError) as e:
            raise RuleError("Daily post limit must be a number.") from e
    if "color" in data:
        c = str(data.get("color") or "")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", c):
            raise RuleError("Color must look like #ff3d6e.")
        vals["color"] = c
    if "archived" in data:
        vals["archived"] = 1 if data.get("archived") else 0
    return vals


def create_account(data: dict) -> dict:
    vals = validate_account(data)
    platform, handle = vals["platform"], vals["handle"]
    if db.q1("SELECT id FROM accounts WHERE platform=? AND lower(handle)=lower(?)", (platform, handle)):
        raise RuleError(f"{handle} is already added on {PLATFORMS[platform]}.")
    n = db.q1("SELECT COUNT(*) n FROM accounts")["n"]
    vals.setdefault("color", PALETTE[n % len(PALETTE)])
    vals.setdefault("daily_limit", int(db.setting("default_daily_limit") or 3))
    aid = db.insert("accounts", created=db.now(), **vals)
    return account_out(db.get("accounts", aid))


def account_out(a: dict) -> dict:
    a = dict(a)
    a["platform_label"] = PLATFORMS.get(a["platform"], a["platform"])
    return a


def list_accounts(include_archived: bool = False) -> list[dict]:
    sql = "SELECT * FROM accounts" + ("" if include_archived else " WHERE archived=0")
    order = {p: i for i, p in enumerate(PLATFORMS)}
    rows = [account_out(a) for a in db.q(sql)]
    rows.sort(key=lambda a: (order.get(a["platform"], 9), a["handle"].lower()))
    return rows


# ---------------------------------------------------------------- niche matching
def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower())}


def clip_context(clip: dict) -> str:
    """Everything that says what a clip is about: streamer, channel, titles, description."""
    parts = [clip.get("title") or "", clip.get("description") or "", clip.get("hook") or ""]
    if clip.get("streamer_id"):
        s = db.get("streamers", clip["streamer_id"])
        if s:
            parts += [s["name"], s.get("channels") or "", s.get("default_tags") or ""]
    job = db.get("jobs", clip["job_id"]) if clip.get("job_id") else None
    if job:
        parts += [job.get("channel") or "", job.get("title") or "", job.get("url") or ""]
    return " ".join(parts)


def niche_match(niche: str, clip: dict) -> tuple[bool, str]:
    """(matches, explanation). A niche like "Kai Cenat GTA 6" needs the streamer and the topic."""
    words = [w for w in re.findall(r"[a-z0-9]+", (niche or "").lower()) if w not in NICHE_STOPWORDS]
    if not words:
        return True, ""
    have = _tokens(clip_context(clip))
    # Group the niche into known streamer names (multi-word) and other topic words.
    names = []
    for s in db.q("SELECT name FROM streamers"):
        nw = [w for w in re.findall(r"[a-z0-9]+", s["name"].lower())]
        if nw and all(w in words for w in nw):
            names.append(nw)
    name_words = {w for nw in names for w in nw}
    topic = [w for w in words if w not in name_words]
    missing = []
    for nw in names:
        if not all(w in have for w in nw):
            missing.append(" ".join(nw).title())
    # topic words: "gta 6" style pairs — a bare number only counts together with its neighbour
    if topic:
        strong = [w for w in topic if not w.isdigit() and len(w) >= 3]
        weak = [w for w in topic if w not in strong]
        if names:
            # streamer already matched above: any one topic word is enough ("gta")
            topic_ok = any(w in have for w in (strong or weak))
        elif strong:
            # no known streamer in the niche: at least half of its real words must appear
            topic_ok = sum(w in have for w in strong) >= (len(strong) + 1) // 2
        else:
            topic_ok = any(w in have for w in weak)
        if not topic_ok:
            orig = {w.lower(): w for w in re.findall(r"[A-Za-z0-9]+", niche)}   # keep the user's casing
            missing.append(" ".join(orig.get(w, w) for w in topic if w not in have) or " ".join(topic))
    if missing:
        return False, f"Doesn't look like “{niche}” content (no sign of: {', '.join(missing)})."
    return True, ""


# ---------------------------------------------------------------- originality checklist
def checklist(clip: dict) -> dict:
    try:
        saved = json.loads(clip.get("originality") or "{}")
    except ValueError:
        saved = {}
    return {k: bool(saved.get(k)) for k in CHECKLIST}


def checklist_hints(clip: dict) -> dict[str, str]:
    """What Clip Studio can see for itself, to help the user tick the boxes honestly."""
    hints = {}
    if clip.get("render_state") == "ready":
        hints["captions"] = "Word-by-word captions are burned into this clip."
    if (clip.get("hook") or "").strip():
        hints["commentary"] = f"Hook text: “{clip['hook']}”."
    name = ""
    if clip.get("streamer_id"):
        s = db.get("streamers", clip["streamer_id"])
        name = (s or {}).get("name", "")
    if name and name.lower() in (clip.get("description") or "").lower():
        hints["credit"] = f"Description mentions {name}."
    elif name:
        hints["credit"] = f"Add “{name}” (and their channel) to the description."
    return hints


def checklist_complete(clip: dict) -> bool:
    return all(checklist(clip).values())


def set_checklist(clip_id: int, values: dict) -> dict:
    clip = db.get("clips", clip_id)
    if not clip:
        raise RuleError("No such clip.")
    cur = checklist(clip)
    for k in CHECKLIST:
        if k in values:
            cur[k] = bool(values[k])
    db.update("clips", clip_id, originality=json.dumps(cur))
    if not all(cur.values()):
        # un-ticking a box takes edited (not yet scheduled) assignments back to Raw
        db.ex("UPDATE assignments SET status='raw', updated=? WHERE clip_id=? AND status='edited'",
              (db.now(), clip_id))
    return cur


# ---------------------------------------------------------------- warnings
def length_flags(clip: dict, platform: str) -> list[str]:
    out = []
    length = clip_length(clip)
    mx = platform_max_len(platform)
    if length > mx + 0.05:
        out.append(f"Too long for {PLATFORMS[platform]}: {length:.0f}s (max {mx:.0f}s).")
    if platform == "tiktok" and length < TIKTOK_REWARDS_MIN:
        out.append(f"Under 1 minute ({length:.0f}s) — not eligible for TikTok Creator Rewards payouts.")
    return out


def day_count(account_id: int, day: date, exclude_id: int | None = None) -> int:
    n = 0
    for a in db.q("SELECT * FROM assignments WHERE account_id=? AND status IN ('scheduled','posted')", (account_id,)):
        if a["id"] != exclude_id and activity_day(a) == day:
            n += 1
    return n


def limit_warning(account: dict, day: date | None, exclude_id: int | None = None, adding: int = 1) -> str | None:
    if day is None:
        return None
    n = day_count(account["id"], day, exclude_id) + adding
    lim = int(account.get("daily_limit") or 3)
    if n > lim:
        return (f"{account['handle']} would post {n} times on {day:%a %d %b} (limit {lim}/day). "
                "Posting too often can get an account flagged as spam.")
    return None


def warnings_for(a: dict, clip: dict | None = None, account: dict | None = None) -> list[str]:
    clip = clip or db.get("clips", a["clip_id"]) or {}
    account = account or db.get("accounts", a["account_id"]) or {}
    out = []
    ok, why = niche_match(account.get("niche") or "", clip)
    if not ok:
        out.append(why)
    out += length_flags(clip, account.get("platform", "youtube"))
    if a.get("status") in ("scheduled", "posted"):
        w = limit_warning(account, activity_day(a), exclude_id=a["id"], adding=1)
        if w:
            out.append(w)
    if a.get("status") in ("edited", "scheduled", "posted") and not checklist_complete(clip):
        out.append("Originality checklist isn't complete.")
    s = db.get("streamers", clip["streamer_id"]) if clip.get("streamer_id") else None
    if s and checklist(clip).get("credit") and s["name"].lower() not in (clip.get("description") or "").lower():
        out.append(f"Credit is ticked but the description doesn't mention {s['name']}.")
    return out


# ---------------------------------------------------------------- assignments
def assignment_out(a: dict, clip: dict | None = None, account: dict | None = None) -> dict:
    from .pipeline import public_clip
    clip = clip or db.get("clips", a["clip_id"]) or {}
    account = account or db.get("accounts", a["account_id"]) or {}
    out = dict(a)
    out["warnings"] = warnings_for(a, clip, account)
    out["account"] = account_out(account) if account else None
    if clip:
        pc = public_clip(clip)
        s = db.get("streamers", clip["streamer_id"]) if clip.get("streamer_id") else None
        out["clip"] = {k: pc.get(k) for k in ("id", "title", "length", "thumb_url", "video_url", "status",
                                              "render_state", "streamer_id", "job_id", "description", "hook")}
        out["clip"]["streamer"] = (s or {}).get("name")
        out["clip"]["checklist"] = checklist(clip)
    return out


def assign(clip_id: int, account_id: int) -> tuple[dict, list[str]]:
    """Put a clip on an account. Blocks a second account on the same platform."""
    clip = db.get("clips", clip_id)
    account = db.get("accounts", account_id)
    if not clip:
        raise RuleError("No such clip.")
    if not account or account.get("archived"):
        raise RuleError("No such account.")
    if clip["status"] == "rejected":
        raise RuleError("This clip was rejected — approve it on the Review page first.")
    if db.q1("SELECT id FROM assignments WHERE clip_id=? AND account_id=?", (clip_id, account_id)):
        raise RuleError(f"This clip is already on {account['handle']}.")
    other = db.q1("""SELECT a.id, ac.handle FROM assignments a JOIN accounts ac ON ac.id=a.account_id
                     WHERE a.clip_id=? AND ac.platform=?""", (clip_id, account["platform"]))
    if other:
        raise RuleError(f"Blocked: this clip is already assigned to {other['handle']} on "
                        f"{PLATFORMS[account['platform']]}. Posting the same clip on two accounts of one "
                        "platform gets flagged as reused content and can demonetize both.")
    aid = db.insert("assignments", clip_id=clip_id, account_id=account_id, status="raw",
                    created=db.now(), updated=db.now())
    a = db.get("assignments", aid)
    return assignment_out(a, clip, account), warnings_for(a, clip, account)


def unassign(assignment_id: int) -> None:
    db.ex("DELETE FROM assignments WHERE id=?", (assignment_id,))


def move(assignment_id: int, status: str, *, scheduled_at: str | None = None, post_url: str | None = None,
         posted_at: float | None = None) -> tuple[dict, list[str]]:
    """Change pipeline status. Returns (assignment, warnings). Hard rules raise RuleError."""
    a = db.get("assignments", assignment_id)
    if not a:
        raise RuleError("No such assignment.")
    if status not in STATUSES:
        raise RuleError("Unknown status.")
    clip = db.get("clips", a["clip_id"]) or {}
    account = db.get("accounts", a["account_id"]) or {}
    vals: dict = {"status": status, "updated": db.now()}
    if status in ("edited", "scheduled", "posted") and not checklist_complete(clip):
        missing = [CHECKLIST[k] for k, v in checklist(clip).items() if not v]
        raise RuleError("Finish the originality checklist before marking this clip ready: " + "; ".join(missing))
    if status in ("edited", "scheduled", "posted") and clip.get("render_state") != "ready":
        raise RuleError("This clip isn't rendered yet.")
    if status == "scheduled":
        when = parse_sched(scheduled_at or a.get("scheduled_at"))
        if not when:
            raise RuleError("Pick a date and time to schedule it.")
        vals["scheduled_at"] = when.strftime("%Y-%m-%d %H:%M")
    if status == "posted":
        vals["posted_at"] = float(posted_at) if posted_at else (a.get("posted_at") or db.now())
        if post_url is not None:
            url = post_url.strip()
            if url and not url.startswith(("http://", "https://")):
                raise RuleError("The post link should start with https://")
            vals["post_url"] = url or None
    if status in ("raw", "edited"):
        vals["posted_at"] = None
    db.update("assignments", assignment_id, **vals)
    a = db.get("assignments", assignment_id)
    if status == "posted" and a.get("post_url"):
        _sync_campaign_post(a, account)
    warns = warnings_for(a, clip, account)
    return assignment_out(a, clip, account), warns


def _sync_campaign_post(a: dict, account: dict) -> None:
    """A posted clip also lands in Submissions so campaign countdowns keep working."""
    if not db.q1("SELECT id FROM posts WHERE clip_id=? AND url=?", (a["clip_id"], a["post_url"])):
        db.insert("posts", clip_id=a["clip_id"], platform=account["platform"], url=a["post_url"],
                  posted_at=a["posted_at"], submitted=0)
        db.update("clips", a["clip_id"], status="posted", posted_url=a["post_url"], posted_at=a["posted_at"])


def log_stats(assignment_id: int, views=None, earnings=None) -> dict:
    vals = {}
    try:
        if views is not None and str(views).strip() != "":
            vals["views"] = max(0, int(float(str(views).replace(",", ""))))
        if earnings is not None and str(earnings).strip() != "":
            vals["earnings"] = max(0.0, round(float(str(earnings).replace("$", "").replace(",", "")), 2))
    except ValueError as e:
        raise RuleError("Views and earnings must be numbers.") from e
    if not db.get("assignments", assignment_id):
        raise RuleError("No such assignment.")
    vals["updated"] = db.now()
    db.update("assignments", assignment_id, **vals)
    return assignment_out(db.get("assignments", assignment_id))


def list_assignments(*, platform: str | None = None, account_id: int | None = None, streamer_id: int | None = None,
                     status: str | None = None) -> list[dict]:
    where, args = ["ac.archived=0"], []
    if platform:
        where.append("ac.platform=?"); args.append(platform)
    if account_id:
        where.append("a.account_id=?"); args.append(account_id)
    if streamer_id:
        where.append("c.streamer_id=?"); args.append(streamer_id)
    if status:
        where.append("a.status=?"); args.append(status)
    rows = db.q(f"""SELECT a.* FROM assignments a JOIN accounts ac ON ac.id=a.account_id
                    JOIN clips c ON c.id=a.clip_id WHERE {' AND '.join(where)}
                    ORDER BY COALESCE(a.scheduled_at, ''), a.id DESC""", args)
    return [assignment_out(a) for a in rows]


# ---------------------------------------------------------------- calendar
def week(offset: int = 0, account_id: int | None = None) -> dict:
    today = today_local()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    days = [monday + timedelta(days=i) for i in range(7)]
    accounts = [a for a in list_accounts() if not account_id or a["id"] == account_id]
    acc_ids = {a["id"] for a in accounts}
    by_day: dict[str, list] = {d.isoformat(): [] for d in days}
    for a in db.q("SELECT * FROM assignments WHERE status IN ('scheduled','posted')"):
        if a["account_id"] not in acc_ids:
            continue
        d = activity_day(a)
        if d and d.isoformat() in by_day:
            item = assignment_out(a)
            when = parse_sched(a.get("scheduled_at"))
            item["time"] = when.strftime("%H:%M") if when and a["status"] == "scheduled" else (
                datetime.fromtimestamp(a["posted_at"], timezone.utc).astimezone(tz()).strftime("%H:%M")
                if a.get("posted_at") else "")
            by_day[d.isoformat()].append(item)
    out_days = []
    for d in days:
        items = sorted(by_day[d.isoformat()], key=lambda x: x["time"])
        counts = {}
        for it in items:
            counts[it["account_id"]] = counts.get(it["account_id"], 0) + 1
        over = [a["handle"] for a in accounts if counts.get(a["id"], 0) > int(a["daily_limit"] or 3)]
        out_days.append({"date": d.isoformat(), "label": d.strftime("%a %d %b"), "today": d == today,
                         "items": items, "over": over})
    return {"days": out_days, "offset": offset, "accounts": accounts, "tz": str(tz())}


# ---------------------------------------------------------------- analytics
def analytics() -> dict:
    rows = db.q("""SELECT a.*, ac.platform, ac.handle, ac.niche, ac.color, c.streamer_id, c.title,
                          s.name AS streamer
                   FROM assignments a JOIN accounts ac ON ac.id=a.account_id
                   JOIN clips c ON c.id=a.clip_id LEFT JOIN streamers s ON s.id=c.streamer_id
                   WHERE a.status='posted'""")
    per_platform = {}
    for p, label in PLATFORMS.items():
        mine = [r for r in rows if r["platform"] == p]
        streamers: dict[str, dict] = {}
        topics: dict[str, dict] = {}
        for r in mine:
            for key, bucket in ((r["streamer"] or "Unknown streamer", streamers), (r["niche"] or "No niche", topics)):
                b = bucket.setdefault(key, {"name": key, "posts": 0, "views": 0, "earnings": 0.0})
                b["posts"] += 1
                b["views"] += r["views"] or 0
                b["earnings"] += r["earnings"] or 0
        rank = lambda d: sorted(d.values(), key=lambda b: (b["views"], b["earnings"]), reverse=True)[:5]  # noqa: E731
        per_platform[p] = {
            "label": label, "posts": len(mine), "views": sum(r["views"] or 0 for r in mine),
            "earnings": round(sum(r["earnings"] or 0 for r in mine), 2),
            "rpm": round(sum(r["earnings"] or 0 for r in mine) / max(1, sum(r["views"] or 0 for r in mine)) * 1000, 2),
            "streamers": rank(streamers), "topics": rank(topics),
        }
    per_clip: dict[int, dict] = {}
    for r in rows:
        c = per_clip.setdefault(r["clip_id"], {"clip_id": r["clip_id"], "title": r["title"], "streamer": r["streamer"],
                                               "views": 0, "earnings": 0.0, "accounts": []})
        c["views"] += r["views"] or 0
        c["earnings"] += r["earnings"] or 0
        c["accounts"].append({"handle": r["handle"], "color": r["color"], "platform": r["platform"]})
    top_clips = sorted(per_clip.values(), key=lambda c: (c["views"], c["earnings"]), reverse=True)[:10]
    posted = [assignment_out(db.get("assignments", r["id"])) for r in
              sorted(rows, key=lambda r: r["posted_at"] or 0, reverse=True)]
    return {"platforms": per_platform, "top_clips": top_clips, "posted": posted,
            "totals": {"views": sum(r["views"] or 0 for r in rows),
                       "earnings": round(sum(r["earnings"] or 0 for r in rows), 2), "posts": len(rows)}}

