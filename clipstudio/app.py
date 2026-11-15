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
    db.update("jobs", job_id, status="queued", stage="queued", progress=0, error=None)
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
