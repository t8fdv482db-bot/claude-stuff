"""FastAPI routes + Server-Sent Events."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db
from .media import have_ffmpeg, ffmpeg_missing_message
from .sources import detect
from .worker import bus, manager, public_job

HERE = Path(__file__).parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bus.loop = asyncio.get_running_loop()
    db.conn()
    from . import pipeline  # noqa: F401 - registers the job runners
    manager.resume_unfinished()
    task = asyncio.create_task(_housekeeping())
    yield
    task.cancel()


app = FastAPI(title="Clip Studio", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


async def _housekeeping() -> None:
    from . import pipeline
    while True:
        await asyncio.sleep(60)
        try:
            await asyncio.to_thread(pipeline.housekeeping)
        except Exception:  # noqa: BLE001
            pass


def page(request: Request, name: str, **ctx) -> HTMLResponse:
    base = {"request": request, "ffmpeg_ok": have_ffmpeg(), "ffmpeg_msg": ffmpeg_missing_message(),
            "nav": name.split(".")[0]}
    base.update(ctx)
    return templates.TemplateResponse(request, name, base)


def body_json(raw: bytes) -> dict:
    try:
        return json.loads(raw or b"{}")
    except ValueError as e:
        raise HTTPException(400, "Invalid JSON") from e


# ---------------------------------------------------------------- pages
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return page(request, "home.html", settings=db.all_settings(),
                streamers=db.q("SELECT id, name, layout FROM streamers ORDER BY name"),
                campaigns=db.q("SELECT id, name FROM campaigns ORDER BY name"))


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: int):
    job = db.get("jobs", job_id)
    if not job:
        raise HTTPException(404, "No such job")
    return page(request, "job.html", job=public_job(job))


# ---------------------------------------------------------------- jobs API
@app.get("/api/detect")
def api_detect(url: str):
    d = detect(url)
    return {"url": d.url, "platform": d.platform, "kind": d.kind, "badge": d.badge}


@app.get("/api/probe")
async def api_probe(url: str):
    """Slower, accurate live/VOD check through yt-dlp (used to update the badge)."""
    from .sources.common import metadata
    d = detect(url)
    if d.platform == "file":
        return {"ok": True, "platform": "file", "kind": "vod", "title": Path(d.url).name, "channel": "",
                "duration": 0, "badge": "Local file · VOD"}
    try:
        meta = await asyncio.to_thread(metadata, d.url, d.platform)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:300], "platform": d.platform, "kind": d.kind, "badge": d.badge}
    kind = "live" if meta["is_live"] else "vod"
    names = {"youtube": "YouTube", "twitch": "Twitch", "kick": "Kick"}
    return {"ok": True, "platform": d.platform, "kind": kind, "title": meta["title"],
            "channel": meta["channel"], "duration": meta["duration"],
            "badge": f"{names.get(d.platform, 'Unknown')} · {'LIVE' if kind == 'live' else 'VOD'}"}


JOB_OPTION_KEYS = ("streamer_id", "clip_count", "min_len", "max_len", "layout", "campaign_id", "ai",
                   "keep_source")


@app.post("/api/jobs")
async def create_jobs(request: Request):
    data = body_json(await request.body())
    lines = [ln.strip() for ln in str(data.get("urls", "")).splitlines() if ln.strip()]
    if not lines:
        raise HTTPException(400, "Paste at least one link.")
    opts = {k: data.get(k) for k in JOB_OPTION_KEYS if data.get(k) not in (None, "")}
    created = []
    for url in lines:
        d = detect(url)
        if d.platform == "unknown":
            raise HTTPException(400, f"Not a YouTube, Twitch or Kick link (or a video file on this PC): {url}")
        jid = db.insert("jobs", url=d.url, platform=d.platform, is_live=1 if d.kind == "live" else 0,
                        streamer_id=opts.get("streamer_id"), campaign_id=opts.get("campaign_id"),
                        options=json.dumps(opts), status="queued", stage="queued", created=db.now())
        job = public_job(db.get("jobs", jid))
        bus.publish("job", job)
        manager.submit(jid)
        created.append(job)
    return {"jobs": created}


@app.get("/api/jobs")
def list_jobs(limit: int = 50):
    rows = db.q("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))
    counts = {r["job_id"]: r["n"] for r in db.q("SELECT job_id, COUNT(*) n FROM clips GROUP BY job_id")}
    out = []
    for r in rows:
        j = public_job(r)
        j["clip_count"] = counts.get(r["id"], 0)
        out.append(j)
    return {"jobs": out}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    job = db.get("jobs", job_id)
    if not job:
        raise HTTPException(404, "No such job")
    return public_job(job)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    manager.cancel(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: int):
    """Live jobs: stop watching gracefully (clips already made are kept)."""
    return {"ok": manager.stop_live(job_id)}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: int):
    job = db.get("jobs", job_id)
    if not job:
        raise HTTPException(404, "No such job")
    if job_id in manager.contexts:
        raise HTTPException(409, "This job is still running — cancel it first, or wait for it to finish.")
    if job["status"] in ("done", "cancelled"):
        # Re-run = choose clips again with the current settings (downloads/transcripts stay cached).
        # After an error we keep the markers so the job resumes where it stopped.
        d = db.storage_dir() / "jobs" / str(job_id)
        for marker in list(d.glob("selected*.json")) + [d / "meta.json"]:
            marker.unlink(missing_ok=True)
    db.update("jobs", job_id, status="queued", stage="queued", progress=0, error=None, finished=None)
    bus.publish("job", public_job(db.get("jobs", job_id)))
    manager.submit(job_id)
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int):
    manager.cancel(job_id)
    db.ex("DELETE FROM jobs WHERE id=?", (job_id,))
    bus.publish("job_deleted", {"id": job_id})
    return {"ok": True}


@app.get("/api/jobs/{job_id}/log", response_class=PlainTextResponse)
def job_log(job_id: int, tail: int = 400):
    p = db.storage_dir() / "jobs" / str(job_id) / "job.log"
    if not p.exists():
        return ""
    lines = p.read_text("utf-8", errors="replace").splitlines()
    return "\n".join(lines[-tail:])


@app.get("/api/events")
async def events(request: Request):
    qu = bus.subscribe()

    async def gen():
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(qu.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'], default=str)}\n\n"
        finally:
            bus.unsubscribe(qu)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    return HTMLResponse(f"<h1>{exc.status_code}</h1><p>{exc.detail}</p><p><a href='/'>Home</a></p>",
                        status_code=exc.status_code)


@app.get("/api/clips/counts")
def clip_counts():
    rows = db.q("SELECT status, COUNT(*) n FROM clips GROUP BY status")
    return {r["status"]: r["n"] for r in rows}


# ---------------------------------------------------------------- review
def _clip_out(c: dict) -> dict:
    from .campaigns import clip_warnings
    from .pipeline import public_clip
    d = public_clip(c)
    d["warnings"] = clip_warnings(c)
    if c.get("campaign_id"):
        camp = db.get("campaigns", c["campaign_id"])
        if camp:
            d["campaign"] = {"id": camp["id"], "name": camp["name"], "submit_url": camp["submit_url"],
                             "submit_window_min": camp["submit_window_min"]}
    d["posts"] = db.q("SELECT * FROM posts WHERE clip_id=? ORDER BY id", (c["id"],))
    return d


@app.get("/review", response_class=HTMLResponse)
def review_page(request: Request):
    return page(request, "review.html",
                streamers=db.q("SELECT id, name FROM streamers ORDER BY name"),
                jobs=db.q("SELECT id, title, url FROM jobs WHERE id IN (SELECT DISTINCT job_id FROM clips) ORDER BY id DESC LIMIT 100"))


@app.get("/api/clips")
def list_clips(status: str | None = None, streamer_id: int | None = None, job_id: int | None = None,
               clip_id: int | None = None):
    where, args = [], []
    if status:
        where.append("status=?"); args.append(status)
    if streamer_id:
        where.append("streamer_id=?"); args.append(streamer_id)
    if job_id:
        where.append("job_id=?"); args.append(job_id)
    if clip_id:
        where.append("id=?"); args.append(clip_id)
    sql = "SELECT * FROM clips" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT 500"
    return {"clips": [_clip_out(c) for c in db.q(sql, args)]}


@app.get("/api/clips/{clip_id}")
def get_clip(clip_id: int):
    c = db.get("clips", clip_id)
    if not c:
        raise HTTPException(404, "No such clip")
    return _clip_out(c)


def _rerender(clip_id: int) -> None:
    from .pipeline import publish_clip, render_clip
    db.update("clips", clip_id, render_state="queued")
    publish_clip(clip_id)
    manager.render(lambda: render_clip(clip_id))


@app.patch("/api/clips/{clip_id}")
async def patch_clip(clip_id: int, request: Request):
    c = db.get("clips", clip_id)
    if not c:
        raise HTTPException(404, "No such clip")
    data = body_json(await request.body())
    vals = {}
    for k in ("title", "description", "hook", "layout"):
        if k in data and data[k] is not None:
            vals[k] = str(data[k])[:5000]
    if "title" in vals:
        vals["title"] = vals["title"][:100]
    if "status" in data:
        if data["status"] not in ("pending", "approved", "rejected", "posted"):
            raise HTTPException(400, "Bad status")
        vals["status"] = data["status"]
    db.update("clips", clip_id, **vals)
    if ("hook" in vals and vals["hook"] != (c.get("hook") or "")) or ("layout" in vals and vals["layout"] != c.get("layout")):
        _rerender(clip_id)
    from .pipeline import publish_clip
    publish_clip(clip_id)
    return _clip_out(db.get("clips", clip_id))


@app.post("/api/clips/{clip_id}/trim")
async def trim_clip(clip_id: int, request: Request):
    c = db.get("clips", clip_id)
    if not c:
        raise HTTPException(404, "No such clip")
    data = body_json(await request.body())
    start = float(c["start"]) + float(data.get("start_delta", 0))
    end = float(c["end"]) + float(data.get("end_delta", 0))
    job = db.get("jobs", c["job_id"]) or {}
    dur = job.get("duration") or 0
    start = max(0.0, start)
    if dur and not job.get("is_live"):
        end = min(float(dur), end)
    if end - start < 5:
        raise HTTPException(400, "A clip can't be shorter than 5 seconds.")
    if end - start > 180:
        raise HTTPException(400, "A clip can't be longer than 3 minutes.")
    if not c.get("source_url") and c.get("src_path"):
        # live clips: only the footage recorded around the moment is kept
        lo, hi = float(c.get("src_offset") or 0), float(c.get("src_end") or end)
        if start < lo - 0.05 or end > hi + 0.05:
            raise HTTPException(400, f"Can't extend this live clip further — only {hi - lo:.0f}s of footage was "
                                     f"recorded around it ({max(0, float(c['start']) - lo):.0f}s before, "
                                     f"{max(0, hi - float(c['end'])):.0f}s after).")
    db.update("clips", clip_id, start=round(start, 2), end=round(end, 2))
    _rerender(clip_id)
    return _clip_out(db.get("clips", clip_id))


@app.post("/api/clips/{clip_id}/rerender")
def rerender_clip(clip_id: int):
    if not db.get("clips", clip_id):
        raise HTTPException(404, "No such clip")
    _rerender(clip_id)
    return {"ok": True}


@app.delete("/api/clips/{clip_id}")
def delete_clip(clip_id: int):
    import shutil
    from .pipeline import clip_dir
    db.ex("DELETE FROM clips WHERE id=?", (clip_id,))
    db.ex("DELETE FROM posts WHERE clip_id=?", (clip_id,))
    shutil.rmtree(clip_dir(clip_id), ignore_errors=True)
    return {"ok": True}


@app.get("/media/clip/{clip_id}/{kind}")
def clip_media(clip_id: int, kind: str):
    from fastapi.responses import FileResponse
    c = db.get("clips", clip_id)
    col = {"video": "video_path", "thumb": "thumb_path", "gif": "gif_path"}.get(kind)
    if not c or not col or not c.get(col) or not Path(c[col]).exists():
        raise HTTPException(404, "Not rendered yet")
    return FileResponse(c[col], headers={"Cache-Control": "max-age=3600"})


# ---------------------------------------------------------------- streamers
def _streamer_out(s: dict) -> dict:
    s = dict(s)
    try:
        s["facecam"] = json.loads(s["facecam"]) if s.get("facecam") else None
    except ValueError:
        s["facecam"] = None
    f = db.storage_dir() / "streamers" / str(s["id"]) / "frame.jpg"
    s["frame_url"] = f"/media/streamer/{s['id']}/frame?v={int(f.stat().st_mtime)}" if f.exists() else None
    return s


@app.get("/streamers", response_class=HTMLResponse)
def streamers_page(request: Request):
    rows = db.q("SELECT * FROM streamers ORDER BY name")
    counts = {r["streamer_id"]: r["n"] for r in db.q("SELECT streamer_id, COUNT(*) n FROM clips GROUP BY streamer_id")}
    return page(request, "streamers.html", streamers=[dict(_streamer_out(s), clips=counts.get(s["id"], 0)) for s in rows])


@app.get("/streamers/{sid}", response_class=HTMLResponse)
def streamer_page(request: Request, sid: int):
    s = db.get("streamers", sid)
    if not s:
        raise HTTPException(404, "No such streamer")
    return page(request, "streamer.html", s=_streamer_out(s), s_json=json.dumps(_streamer_out(s)))


@app.get("/api/streamers")
def api_streamers():
    return {"streamers": [_streamer_out(s) for s in db.q("SELECT * FROM streamers ORDER BY name")]}


@app.post("/api/streamers")
async def create_streamer(request: Request):
    data = body_json(await request.body())
    name = str(data.get("name", "")).strip()[:60]
    if not name:
        raise HTTPException(400, "Give the streamer a name.")
    sid = db.insert("streamers", name=name, layout=db.setting("default_layout") or "split")
    return _streamer_out(db.get("streamers", sid))


@app.put("/api/streamers/{sid}")
async def update_streamer(sid: int, request: Request):
    if not db.get("streamers", sid):
        raise HTTPException(404, "No such streamer")
    data = body_json(await request.body())
    vals = {}
    for k in ("name", "hype_words", "default_tags", "channels"):
        if k in data:
            vals[k] = str(data[k] or "")[:5000]
    if "layout" in data:
        if data["layout"] not in ("split", "blur", "center"):
            raise HTTPException(400, "Unknown layout")
        vals["layout"] = data["layout"]
    if "facecam" in data:
        fc = data["facecam"]
        if fc is None:
            vals["facecam"] = None
        else:
            try:
                box = {k: round(min(1.0, max(0.0, float(fc[k]))), 4) for k in ("x", "y", "w", "h")}
            except (KeyError, TypeError, ValueError) as e:
                raise HTTPException(400, "Facecam box needs x, y, w, h fractions") from e
            if box["w"] < 0.03 or box["h"] < 0.03 or box["x"] + box["w"] > 1.001 or box["y"] + box["h"] > 1.001:
                raise HTTPException(400, "That facecam box is too small or outside the frame.")
            vals["facecam"] = json.dumps(box)
    db.update("streamers", sid, **vals)
    return _streamer_out(db.get("streamers", sid))


@app.delete("/api/streamers/{sid}")
def delete_streamer(sid: int):
    db.ex("DELETE FROM streamers WHERE id=?", (sid,))
    return {"ok": True}


@app.post("/api/streamers/{sid}/frame")
async def streamer_frame(sid: int, request: Request):
    from .frames import grab
    from .media import UserError
    if not db.get("streamers", sid):
        raise HTTPException(404, "No such streamer")
    data = body_json(await request.body())
    url = str(data.get("url", "")).strip()
    t = _parse_time(str(data.get("t", "0")))
    out = db.storage_dir() / "streamers" / str(sid) / "frame.jpg"
    try:
        await asyncio.to_thread(grab, url, t, out)
    except UserError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Couldn't grab a frame: {str(e)[:300]}") from e
    return _streamer_out(db.get("streamers", sid))


@app.post("/api/streamers/{sid}/frame-upload")
async def streamer_frame_upload(sid: int, request: Request):
    if not db.get("streamers", sid):
        raise HTTPException(404, "No such streamer")
    form = await request.form()
    f = form.get("file")
    if f is None or not hasattr(f, "read"):
        raise HTTPException(400, "Choose an image file.")
    raw = await f.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(400, "Image is too large (max 20 MB).")
    d = db.storage_dir() / "streamers" / str(sid)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / ("upload" + Path(getattr(f, "filename", "x.png") or "x.png").suffix.lower()[:6])
    tmp.write_bytes(raw)
    from .media import run as _run
    try:
        await asyncio.to_thread(_run, ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(tmp),
                                       "-frames:v", "1", "-q:v", "3", str(d / "frame.jpg")])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, "That file isn't an image ffmpeg can read.") from e
    finally:
        tmp.unlink(missing_ok=True)
    return _streamer_out(db.get("streamers", sid))


@app.get("/media/streamer/{sid}/frame")
def streamer_frame_img(sid: int):
    from fastapi.responses import FileResponse
    p = db.storage_dir() / "streamers" / str(sid) / "frame.jpg"
    if not p.exists():
        raise HTTPException(404, "No frame yet")
    return FileResponse(p)


def _parse_time(s: str) -> float:
    """'1:23:45', '83:10', '125' or '2h3m4s' → seconds."""
    import re
    s = s.strip().lower()
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", s)
    if m and any(m.groups()):
        h, mi, se = (float(x) if x else 0.0 for x in m.groups())
        return h * 3600 + mi * 60 + se
    total = 0.0
    try:
        for part in s.split(":"):
            total = total * 60 + float(part or 0)
    except ValueError as e:
        raise HTTPException(400, "Timestamp should look like 1:23:45 or 125") from e
    return total


@app.get("/api/jobs/{job_id}/live-scores")
def live_scores(job_id: int):
    from .live import scores_for
    return scores_for(job_id)


@app.post("/api/clips/{clip_id}/regen-title")
async def regen_title(clip_id: int):
    from . import ai
    from .pipeline import clip_dir, publish_clip
    c = db.get("clips", clip_id)
    if not c:
        raise HTTPException(404, "No such clip")
    if not ai.api_key():
        raise HTTPException(400, "Add your Anthropic API key in Settings → AI first.")
    f = clip_dir(clip_id) / "words.json"
    words = json.loads(f.read_text("utf-8"))["words"] if f.exists() else []
    s = db.get("streamers", c["streamer_id"]) if c.get("streamer_id") else None
    try:
        res = await asyncio.to_thread(ai.regenerate_title, c, words, (s or {}).get("name", ""))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"AI request failed: {type(e).__name__}: {str(e)[:200]}") from e
    old_title = c.get("title") or ""
    vals = {"title": res["title"]}
    if old_title and old_title in (c.get("description") or ""):
        vals["description"] = c["description"].replace(old_title, res["title"], 1)
    db.update("clips", clip_id, **vals)
    publish_clip(clip_id)
    return _clip_out(db.get("clips", clip_id))


# ---------------------------------------------------------------- campaigns
CAMPAIGN_FIELDS = {"name": str, "payout_notes": str, "disclosure": str, "hashtags": str, "required_source": str,
                   "submit_url": str, "min_len": float, "max_len": float, "disclosure_seconds": float,
                   "submit_window_min": int}


def _campaign_out(c: dict) -> dict:
    from .campaigns import platforms
    c = dict(c)
    c["platforms"] = platforms(c)
    return c


@app.get("/campaigns", response_class=HTMLResponse)
def campaigns_page(request: Request):
    rows = [_campaign_out(c) for c in db.q("SELECT * FROM campaigns ORDER BY name")]
    return page(request, "campaigns.html", campaigns=rows, campaigns_json=json.dumps(rows))


@app.post("/api/campaigns")
async def create_campaign(request: Request):
    data = body_json(await request.body())
    if not str(data.get("name", "")).strip():
        raise HTTPException(400, "Give the campaign a name.")
    cid = db.insert("campaigns", name=str(data["name"]).strip()[:80])
    return await _save_campaign(cid, data)


@app.put("/api/campaigns/{cid}")
async def update_campaign(cid: int, request: Request):
    if not db.get("campaigns", cid):
        raise HTTPException(404, "No such campaign")
    return await _save_campaign(cid, body_json(await request.body()))


async def _save_campaign(cid: int, data: dict) -> dict:
    from .campaigns import PLATFORMS
    vals = {}
    for k, typ in CAMPAIGN_FIELDS.items():
        if k in data and data[k] is not None and data[k] != "":
            try:
                vals[k] = typ(data[k]) if typ is not str else str(data[k])[:2000]
            except (TypeError, ValueError) as e:
                raise HTTPException(400, f"Bad value for {k}") from e
        elif k in data and typ is not str:
            vals[k] = 0
        elif k in data:
            vals[k] = ""
    if vals.get("submit_url") and not vals["submit_url"].startswith(("http://", "https://")):
        raise HTTPException(400, "Submission page must be a http(s) link.")
    if "platforms" in data:
        vals["platforms"] = json.dumps([p for p in data["platforms"] if p in PLATFORMS])
    if vals.get("min_len") and vals.get("max_len") and vals["min_len"] > vals["max_len"]:
        raise HTTPException(400, "Min length is longer than max length.")
    db.update("campaigns", cid, **vals)
    return _campaign_out(db.get("campaigns", cid))


@app.delete("/api/campaigns/{cid}")
def delete_campaign(cid: int):
    db.ex("DELETE FROM campaigns WHERE id=?", (cid,))
    return {"ok": True}


# ---------------------------------------------------------------- posting + submissions
@app.post("/api/clips/{clip_id}/posted")
async def mark_posted(clip_id: int, request: Request):
    from .campaigns import clip_warnings
    from .pipeline import publish_clip
    c = db.get("clips", clip_id)
    if not c:
        raise HTTPException(404, "No such clip")
    data = body_json(await request.body())
    platform = str(data.get("platform", "")).lower()
    url = str(data.get("url", "")).strip()
    if platform not in ("youtube", "tiktok", "instagram", "x"):
        raise HTTPException(400, "Pick a platform.")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Paste the link to your post (starting with https://).")
    now = db.now()
    db.insert("posts", clip_id=clip_id, platform=platform, url=url, posted_at=now, submitted=0)
    db.update("clips", clip_id, status="posted", posted_url=url, posted_at=now, submitted=0)
    publish_clip(clip_id)
    out = _clip_out(db.get("clips", clip_id))
    out["warnings"] = clip_warnings(db.get("clips", clip_id), platform=platform)
    return out


@app.patch("/api/posts/{post_id}")
async def patch_post(post_id: int, request: Request):
    p = db.get("posts", post_id)
    if not p:
        raise HTTPException(404, "No such post")
    data = body_json(await request.body())
    sub = 1 if data.get("submitted") else 0
    db.update("posts", post_id, submitted=sub, submitted_at=db.now() if sub else None)
    pending = db.q1("SELECT COUNT(*) n FROM posts WHERE clip_id=? AND submitted=0", (p["clip_id"],))["n"]
    db.update("clips", p["clip_id"], submitted=1 if pending == 0 else 0)
    return db.get("posts", post_id)


@app.delete("/api/posts/{post_id}")
def delete_post(post_id: int):
    db.ex("DELETE FROM posts WHERE id=?", (post_id,))
    return {"ok": True}


@app.get("/submissions", response_class=HTMLResponse)
def submissions_page(request: Request):
    rows = db.q("""SELECT p.*, c.title, c.campaign_id, c.thumb_path, cp.name AS campaign, cp.submit_window_min,
                   cp.submit_url FROM posts p JOIN clips c ON c.id = p.clip_id
                   LEFT JOIN campaigns cp ON cp.id = c.campaign_id ORDER BY p.posted_at DESC LIMIT 500""")
    return page(request, "submissions.html", rows=rows, rows_json=json.dumps(rows, default=str))


# ---------------------------------------------------------------- export + YouTube
@app.get("/api/clips/{clip_id}/download")
def download_clip(clip_id: int, name: str | None = None):
    """The rendered MP4 as a download. `name` (from the Share window) sets a friendly filename."""
    import re
    from fastapi.responses import FileResponse
    from .export import slug
    c = db.get("clips", clip_id)
    if not c or not c.get("video_path") or not Path(c["video_path"]).exists():
        raise HTTPException(404, "This clip isn't rendered yet.")
    filename = f"{clip_id:04d}_{slug(c.get('title'))}.mp4"
    if name and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,90}\.mp4", name):
        filename = name
    return FileResponse(c["video_path"], media_type="video/mp4", filename=filename,
                        headers={"Cache-Control": "no-store"})


@app.get("/api/clips/{clip_id}/share-info")
def share_info(clip_id: int):
    """What the Share window needs: thumbnail, caption, hashtags and the file's real format/size."""
    from .export import caption_text
    from .media import probe
    from .pipeline import public_clip
    c = db.get("clips", clip_id)
    if not c or not c.get("video_path") or not Path(c["video_path"]).exists():
        raise HTTPException(404, "This clip isn't rendered yet.")
    info = probe(Path(c["video_path"]))
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {})
    text = caption_text(c)
    lines = text.splitlines()
    tag_lines = [ln for ln in lines if ln.strip() and all(w.startswith(("#", "@")) for w in ln.split())]
    caption = "\n".join(ln for ln in lines if ln not in tag_lines).strip()
    pc = public_clip(c)
    return {"id": clip_id, "title": c.get("title") or "", "thumb_url": pc.get("thumb_url"),
            "download_url": f"/api/clips/{clip_id}/download", "caption": caption,
            "hashtags": " ".join(tag_lines), "width": v.get("width"), "height": v.get("height"),
            "duration": float(info.get("format", {}).get("duration") or 0),
            "size": Path(c["video_path"]).stat().st_size,
            "mp4": "mp4" in (info.get("format", {}).get("format_name") or "") and v.get("codec_name") == "h264"
                   and a.get("codec_name") in ("aac", None)}


@app.get("/api/clips/{clip_id}/caption.txt")
def download_caption(clip_id: int):
    from .export import caption_text, slug
    c = db.get("clips", clip_id)
    if not c:
        raise HTTPException(404, "No such clip")
    return PlainTextResponse(caption_text(c), headers={
        "Content-Disposition": f'attachment; filename="{clip_id:04d}_{slug(c.get("title"))}.txt"'})


@app.get("/api/export/approved.zip")
async def export_approved():
    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask
    from .export import export_zip
    ids = [r["id"] for r in db.q("SELECT id FROM clips WHERE status='approved' AND render_state='ready' ORDER BY id")]
    if not ids:
        raise HTTPException(404, "No approved clips to export yet.")
    path = await asyncio.to_thread(export_zip, ids)
    import time as _t
    return FileResponse(path, media_type="application/zip", filename=f"clipstudio_approved_{_t.strftime('%Y%m%d_%H%M')}.zip",
                        background=BackgroundTask(lambda: path.unlink(missing_ok=True)))


# ---------------------------------------------------------------- settings
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    import os
    from zoneinfo import available_timezones
    s = db.all_settings()
    s.pop("anthropic_api_key", None)                 # never sent to the browser
    return page(request, "settings.html", s=s, s_json=json.dumps(s),
                key_set=bool(db.setting("anthropic_api_key")), env_key=bool(os.environ.get("ANTHROPIC_API_KEY")),
                timezones=sorted(available_timezones()),
                storage=str(db.storage_dir()), home=str(db.home()))


@app.post("/api/settings")
async def save_settings(request: Request):
    data = body_json(await request.body())
    for k, v in data.items():
        if k not in db.DEFAULTS:
            continue
        default = db.DEFAULTS[k]
        if k == "anthropic_api_key":
            v = str(v or "").strip()
            if v == "" and not data.get("clear_api_key"):
                continue                               # empty box = keep the saved key
        elif k == "timezone":
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(str(v))
            except Exception as e:  # noqa: BLE001
                raise HTTPException(400, f"Unknown timezone: {v}") from e
        elif k == "storage_dir" and v:
            p = Path(str(v)).expanduser()
            try:
                p.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise HTTPException(400, f"Can't use that folder: {e}") from e
        if isinstance(default, bool):
            v = bool(v)
        elif isinstance(default, int):
            try:
                v = int(float(v))
            except (TypeError, ValueError) as e:
                raise HTTPException(400, f"{k} must be a number") from e
        elif isinstance(default, float):
            try:
                v = float(v)
            except (TypeError, ValueError) as e:
                raise HTTPException(400, f"{k} must be a number") from e
        else:
            v = str(v)
        db.set_setting(k, v)
    if data.get("clear_api_key"):
        db.set_setting("anthropic_api_key", "")
    return {"ok": True}


@app.post("/api/settings/test-discord")
def test_discord():
    import urllib.request
    url = (db.setting("discord_webhook") or "").strip()
    if not url.startswith("https://"):
        raise HTTPException(400, "Save a Discord webhook URL first.")
    req = urllib.request.Request(url, data=json.dumps({"content": "✅ Clip Studio test — new clips will show up here."}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "ClipStudio"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Discord didn't accept it: {str(e)[:150]}") from e
    return {"ok": True}


@app.get("/api/storage")
async def storage_usage():
    def size() -> int:
        return sum(p.stat().st_size for p in db.storage_dir().rglob("*") if p.is_file())
    used = await asyncio.to_thread(size)
    return {"used_gb": round(used / 1024 ** 3, 2), "limit_gb": db.setting("max_disk_gb"), "path": str(db.storage_dir())}


# ---------------------------------------------------------------- multi-account posting
from .accounts_routes import router as _accounts_router  # noqa: E402

app.include_router(_accounts_router)
