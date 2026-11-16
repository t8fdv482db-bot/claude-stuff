"""Publishing: YouTube upload + slot scheduling, and exports for TikTok / Reels / X.

Nothing is ever uploaded unless its status is 'approved' at the moment of upload.
"""
from __future__ import annotations

import json
import re
import tempfile
import threading
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import db
from .worker import bus

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
QUOTA_REASONS = {"quotaExceeded", "uploadLimitExceeded", "dailyLimitExceeded", "rateLimitExceeded"}
_lock = threading.Lock()
_connect_state = {"running": False, "error": None}


# ---------------------------------------------------------------- slots
def parse_slots(text: str) -> list[time]:
    out = []
    for part in re.split(r"[,\s]+", text or ""):
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", part.strip())
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
            out.append(time(int(m.group(1)), int(m.group(2))))
    return sorted(set(out))


def resolve_local(d: date, t: time, tz: ZoneInfo) -> datetime:
    """Local wall time → aware UTC datetime.

    DST gap (e.g. 02:30 on spring-forward day doesn't exist): moves forward to the real time (03:30).
    DST overlap (01:30 happens twice on fall-back day): uses the first occurrence.
    """
    naive = datetime.combine(d, t)
    aware = naive.replace(tzinfo=tz, fold=0)
    utc = aware.astimezone(timezone.utc)
    back = utc.astimezone(tz)
    if back.replace(tzinfo=None) != naive:            # nonexistent local time
        later = naive.replace(tzinfo=tz, fold=1).astimezone(timezone.utc)
        utc = max(utc, later)
    return utc


def next_free_slots(slots: list[time], tz_name: str, taken: set[datetime] | list[datetime], count: int,
                    now: datetime | None = None, lead: timedelta = timedelta(minutes=20),
                    max_days: int = 120) -> list[datetime]:
    """The next `count` free publish times (UTC), skipping taken slots and anything too soon."""
    if not slots or count <= 0:
        return []
    tz = ZoneInfo(tz_name)
    now = now or datetime.now(timezone.utc)
    taken_min = {_minute(t) for t in taken}
    out: list[datetime] = []
    day = now.astimezone(tz).date()
    for _ in range(max_days):
        for s in slots:
            utc = resolve_local(day, s, tz)
            key = _minute(utc)
            if utc < now + lead or key in taken_min:
                continue
            taken_min.add(key)
            out.append(utc)
            if len(out) == count:
                return out
        day += timedelta(days=1)
    return out


def _minute(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(second=0, microsecond=0)


def rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def parse_rfc3339(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def taken_slots() -> list[datetime]:
    rows = db.q("SELECT publish_at FROM clips WHERE publish_at IS NOT NULL AND (youtube_id IS NOT NULL OR yt_state='uploading')")
    return [parse_rfc3339(r["publish_at"]) for r in rows if r["publish_at"]]


# ---------------------------------------------------------------- export
def slug(text: str, n: int = 50) -> str:
    s = re.sub(r"[^\w\- ]+", "", text or "").strip().replace(" ", "_")
    return (s[:n] or "clip").strip("_") or "clip"


def caption_text(clip: dict) -> str:
    desc = (clip.get("description") or "").strip()
    title = (clip.get("title") or "").strip()
    if not desc:
        return title
    return desc if title in desc else f"{title}\n\n{desc}"


def export_zip(clip_ids: list[int]) -> Path:
    tmp = Path(tempfile.mkstemp(prefix="clipstudio_", suffix=".zip")[1])
    with zipfile.ZipFile(tmp, "w") as z:
        for cid in clip_ids:
            c = db.get("clips", cid)
            if not c or not c.get("video_path") or not Path(c["video_path"]).exists():
                continue
            base = f"{cid:04d}_{slug(c.get('title'))}"
            z.write(c["video_path"], f"{base}.mp4", compress_type=zipfile.ZIP_STORED)
            z.writestr(f"{base}.txt", caption_text(c), compress_type=zipfile.ZIP_DEFLATED)
    return tmp


# ---------------------------------------------------------------- YouTube auth
def yt_dir() -> Path:
    p = db.home() / "youtube"
    p.mkdir(parents=True, exist_ok=True)
    return p


def secret_path() -> Path:
    return yt_dir() / "client_secret.json"


def token_path() -> Path:
    return yt_dir() / "token.json"


def save_client_secret(raw: bytes) -> None:
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ValueError("That isn't a JSON file.") from e
    if "installed" not in data:
        if "web" in data:
            raise ValueError("This is a 'Web application' client. Create an OAuth client of type 'Desktop app' instead.")
        raise ValueError("This doesn't look like a Google OAuth client_secret.json.")
    secret_path().write_bytes(raw)


def credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    if not token_path().exists():
        return None
    creds = Credentials.from_authorized_user_file(str(token_path()), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path().write_text(creds.to_json(), "utf-8")
    return creds if creds and creds.valid else None


def status() -> dict:
    out = {"has_secret": secret_path().exists(), "connected": False, "channel": None,
           "connecting": _connect_state["running"], "error": _connect_state["error"]}
    try:
        creds = credentials()
    except Exception as e:  # noqa: BLE001
        out["error"] = f"Saved login stopped working ({type(e).__name__}); connect again."
        return out
    if creds:
        out["connected"] = True
        info = yt_dir() / "channel.json"
        if info.exists():
            out["channel"] = json.loads(info.read_text("utf-8")).get("title")
    return out


def connect_async() -> None:
    """Desktop OAuth flow: opens the browser at Google's consent page; token is saved locally."""
    if _connect_state["running"]:
        return
    if not secret_path().exists():
        raise ValueError("Upload your client_secret.json first.")

    def run():
        _connect_state.update(running=True, error=None)
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(str(secret_path()), SCOPES)
            creds = flow.run_local_server(host="localhost", port=0, open_browser=True, prompt="consent",
                                          success_message="Clip Studio is connected to YouTube. You can close this tab.",
                                          timeout_seconds=300)
            token_path().write_text(creds.to_json(), "utf-8")
            try:
                from googleapiclient.discovery import build
                yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
                items = yt.channels().list(part="snippet", mine=True).execute().get("items") or []
                if items:
                    (yt_dir() / "channel.json").write_text(json.dumps({"title": items[0]["snippet"]["title"]}), "utf-8")
            except Exception:  # noqa: BLE001
                pass
            bus.publish("notice", {"message": "YouTube connected ✔", "kind": "ok"})
        except Exception as e:  # noqa: BLE001
            _connect_state["error"] = f"YouTube login didn't finish: {type(e).__name__}"
        finally:
            _connect_state["running"] = False

    threading.Thread(target=run, daemon=True).start()


def disconnect() -> None:
    token_path().unlink(missing_ok=True)
    (yt_dir() / "channel.json").unlink(missing_ok=True)


# ---------------------------------------------------------------- upload
class QuotaError(Exception):
    pass


def _http_reason(err) -> str:
    try:
        data = json.loads(err.content.decode())
        errs = data.get("error", {}).get("errors") or []
        return (errs[0].get("reason") if errs else "") or data.get("error", {}).get("status", "")
    except Exception:  # noqa: BLE001
        return ""


def youtube_title(clip: dict) -> str:
    t = (clip.get("title") or "Clip").strip()
    return t[:100]


def youtube_description(clip: dict) -> str:
    d = caption_text(clip)
    if "#shorts" not in d.lower() and "#shorts" not in (clip.get("title") or "").lower():
        d = (d + "\n\n#shorts").strip()
    return d[:4900]


def upload(clip_id: int, publish_at: datetime) -> str:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    clip = db.get("clips", clip_id)
    if not clip or clip["status"] != "approved":   # hard rule: never post anything not approved
        raise PermissionError("Clip is not approved.")
    creds = credentials()
    if not creds:
        raise RuntimeError("YouTube isn't connected (Settings → YouTube).")
    streamer = db.get("streamers", clip["streamer_id"]) if clip.get("streamer_id") else None
    from .scoring import parse_list
    tags = [t.lstrip("#") for t in parse_list((streamer or {}).get("default_tags"))][:15]
    body = {
        "snippet": {"title": youtube_title(clip), "description": youtube_description(clip),
                    "tags": tags + ["shorts"], "categoryId": "20"},
        "status": {"privacyStatus": "private", "publishAt": rfc3339(publish_at),
                   "selfDeclaredMadeForKids": False},
    }
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    media = MediaFileUpload(clip["video_path"], mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    try:
        resp = None
        while resp is None:
            _status, resp = req.next_chunk()
        return resp["id"]
    except HttpError as e:
        reason = _http_reason(e)
        if e.resp.status in (403, 429) and (reason in QUOTA_REASONS or "quota" in str(e).lower()):
            raise QuotaError(reason) from e
        raise RuntimeError(f"YouTube rejected the upload ({e.resp.status} {reason or ''})".strip()) from e


def next_quota_reset() -> float:
    """YouTube quotas reset at midnight Pacific time."""
    pt = ZoneInfo("America/Los_Angeles")
    now = datetime.now(pt)
    reset = datetime.combine(now.date() + timedelta(days=1), time(0, 5), tzinfo=pt)
    return reset.timestamp()


def schedule_approved(clip_ids: list[int] | None = None) -> dict:
    """Upload approved clips as private with publishAt in the next free slots (runs in a thread)."""
    from .campaigns import clip_warnings
    if not credentials():
        return {"ok": False, "message": "Connect YouTube first (Settings → YouTube)."}
    if clip_ids is None:
        rows = db.q("SELECT * FROM clips WHERE status='approved' AND youtube_id IS NULL AND render_state='ready' "
                    "AND (yt_state IS NULL OR yt_state IN ('error','retry')) ORDER BY id")
    else:
        rows = [c for c in (db.get("clips", i) for i in clip_ids) if c]
    todo = []
    for c in rows:
        if any("doesn't allow posting" in w for w in clip_warnings(c, platform="youtube")):
            db.update("clips", c["id"], yt_state="error", yt_error="Its campaign doesn't allow YouTube.")
            continue
        todo.append(c)
    if not todo:
        return {"ok": True, "message": "Nothing to schedule — approve some rendered clips first."}
    slots = parse_slots(db.setting("yt_slots"))
    if not slots:
        return {"ok": False, "message": "Add YouTube time slots in Settings first."}
    times = next_free_slots(slots, db.setting("timezone") or "UTC", taken_slots(), len(todo))
    for c, when in zip(todo, times):
        db.update("clips", c["id"], yt_state="queued", publish_at=rfc3339(when), yt_error=None)
    threading.Thread(target=_upload_all, args=([c["id"] for c in todo[:len(times)]],), daemon=True).start()
    return {"ok": True, "message": f"Uploading {len(times)} clip(s) as private, scheduled from "
                                   f"{times[0].astimezone(ZoneInfo(db.setting('timezone') or 'UTC')):%a %d %b %H:%M}."}


def _upload_all(ids: list[int]) -> None:
    from .pipeline import publish_clip
    with _lock:
        for i, cid in enumerate(ids):
            c = db.get("clips", cid)
            if not c or c.get("youtube_id"):
                continue
            db.update("clips", cid, yt_state="uploading")
            publish_clip(cid)
            try:
                vid = upload(cid, parse_rfc3339(c["publish_at"]))
                db.update("clips", cid, youtube_id=vid, yt_state="scheduled", yt_error=None)
            except QuotaError:
                msg = "YouTube daily quota reached, the rest will retry tomorrow."
                retry = next_quota_reset()
                for rest in ids[i:]:
                    db.update("clips", rest, yt_state="retry", yt_error=msg, yt_retry_after=retry, publish_at=None)
                    publish_clip(rest)
                bus.publish("notice", {"message": msg, "kind": "error"})
                return
            except PermissionError:
                db.update("clips", cid, yt_state=None, publish_at=None)
            except Exception as e:  # noqa: BLE001
                db.update("clips", cid, yt_state="error", yt_error=str(e)[:300], publish_at=None)
            publish_clip(cid)
    bus.publish("notice", {"message": "YouTube uploads finished.", "kind": "ok"})


def retry_due_uploads() -> None:
    import time as _t
    due = db.q("SELECT id FROM clips WHERE yt_state='retry' AND status='approved' AND yt_retry_after <= ?", (_t.time(),))
    if due and not _lock.locked():
        schedule_approved([r["id"] for r in due])


# ---------------------------------------------------------------- calendar
def week(offset: int = 0) -> dict:
    tz_name = db.setting("timezone") or "UTC"
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    slots = parse_slots(db.setting("yt_slots"))
    rows = db.q("SELECT id, title, publish_at, youtube_id, yt_state, thumb_path FROM clips WHERE publish_at IS NOT NULL")
    by_day: dict[str, list] = {}
    for r in rows:
        local = parse_rfc3339(r["publish_at"]).astimezone(tz)
        by_day.setdefault(local.date().isoformat(), []).append({**r, "local": local.strftime("%H:%M")})
    days = []
    for i in range(7):
        d = monday + timedelta(days=i)
        items = sorted(by_day.get(d.isoformat(), []), key=lambda x: x["local"])
        used = {x["local"] for x in items}
        free = [s.strftime("%H:%M") for s in slots
                if resolve_local(d, s, tz).astimezone(tz).strftime("%H:%M") not in used]
        days.append({"date": d.isoformat(), "label": d.strftime("%a %d %b"), "today": d == today,
                     "items": items, "free": free})
    retry = db.q("SELECT id, title, yt_error FROM clips WHERE yt_state='retry'")
    return {"days": days, "tz": tz_name, "offset": offset, "retry": retry}
