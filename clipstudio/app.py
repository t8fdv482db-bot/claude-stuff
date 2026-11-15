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
            raise HTTPException(400, f"Not a YouTube, Twitch or Kick link: {url}")
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
