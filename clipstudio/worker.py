"""In-process job runner: a thread pool for pipelines, a render limiter, cancellation and progress events.

No Redis/Celery: jobs live in SQLite, so a restart simply re-queues unfinished jobs and every
pipeline step reuses its on-disk cache.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from . import db
from .media import Cancelled, UserError

STAGES = ["queued", "downloading", "chat", "transcribing", "scoring", "rendering", "done"]
STAGE_SPAN = {  # overall-progress range per stage
    "queued": (0, 0), "downloading": (0, 25), "chat": (25, 30), "transcribing": (30, 60),
    "scoring": (60, 65), "rendering": (65, 100), "done": (100, 100),
}


class Relaunch(Exception):
    """Raised by the VOD pipeline when a link turns out to be live: re-run it as a live job."""


# ---------------------------------------------------------------- events (SSE)
class EventBus:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.subs: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        qu: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.subs.add(qu)
        return qu

    def unsubscribe(self, qu: asyncio.Queue) -> None:
        self.subs.discard(qu)

    def _deliver(self, msg: dict) -> None:
        for qu in list(self.subs):
            try:
                qu.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def publish(self, kind: str, data: Any) -> None:
        msg = {"event": kind, "data": data}
        if self.loop is None or self.loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self._deliver(msg)
        else:
            self.loop.call_soon_threadsafe(self._deliver, msg)


bus = EventBus()


def public_job(job: dict) -> dict:
    j = dict(job)
    try:
        j["options"] = json.loads(j.get("options") or "{}")
    except ValueError:
        j["options"] = {}
    return j


def job_dir(job_id: int) -> Path:
    p = db.storage_dir() / "jobs" / str(job_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------- per-job context
class JobContext:
    """Handed to pipeline code: progress, logging and cancellation for one job."""

    def __init__(self, job_id: int) -> None:
        self.job_id = job_id
        self.cancel = threading.Event()
        self.stop = threading.Event()       # live: "stop watching" (graceful)
        self.dir = job_dir(job_id)
        self.log_path = self.dir / "job.log"
        self.stage_name = "queued"
        self._last_pub = 0.0

    @property
    def job(self) -> dict:
        return db.get("jobs", self.job_id) or {}

    @property
    def options(self) -> dict:
        try:
            return json.loads(self.job.get("options") or "{}")
        except ValueError:
            return {}

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        bus.publish("log", {"job_id": self.job_id, "line": line})

    def set(self, **vals: Any) -> None:
        db.update("jobs", self.job_id, **vals)
        bus.publish("job", public_job(db.get("jobs", self.job_id)))

    def stage(self, name: str, note: str | None = None) -> None:
        self.check()
        self.stage_name = name
        lo, _ = STAGE_SPAN.get(name, (0, 0))
        self.set(stage=name, progress=lo)
        if note:
            self.log(note)

    def progress(self, frac: float) -> None:
        """Fraction (0..1) through the current stage."""
        lo, hi = STAGE_SPAN.get(self.stage_name, (0, 100))
        pct = lo + (hi - lo) * max(0.0, min(1.0, frac))
        nowt = time.time()
        if nowt - self._last_pub > 0.5 or frac >= 1:
            self._last_pub = nowt
            self.set(progress=round(pct, 1))

    def check(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()


# ---------------------------------------------------------------- manager
class Manager:
    def __init__(self) -> None:
        n = max(1, int(db.setting("max_parallel_jobs") or 2))
        self.pool = ThreadPoolExecutor(max_workers=n, thread_name_prefix="job")
        self.render_slots = threading.BoundedSemaphore(max(1, (os.cpu_count() or 2) // 2))
        self.render_pool = ThreadPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) // 2),
                                              thread_name_prefix="render")
        self.contexts: dict[int, JobContext] = {}
        self.lock = threading.Lock()
        self._runner: Callable[[JobContext], None] | None = None
        self._live_runner: Callable[[JobContext], None] | None = None

    def configure(self, vod_runner: Callable[[JobContext], None],
                  live_runner: Callable[[JobContext], None]) -> None:
        self._runner = vod_runner
        self._live_runner = live_runner

    def submit(self, job_id: int) -> None:
        with self.lock:
            if job_id in self.contexts:
                return
            ctx = JobContext(job_id)
            self.contexts[job_id] = ctx
        job = db.get("jobs", job_id)
        if job and job.get("is_live"):
            # live jobs run for hours: give them their own thread instead of a pool slot
            threading.Thread(target=self._run, args=(ctx, True), daemon=True,
                             name=f"live-{job_id}").start()
        else:
            self.pool.submit(self._run, ctx, False)

    def _run(self, ctx: JobContext, live: bool) -> None:
        relaunch = False
        try:
            if ctx.cancel.is_set():
                raise Cancelled()
            ctx.set(status="running", started=db.now(), error=None)
            runner = self._live_runner if live else self._runner
            assert runner is not None
            runner(ctx)
            ctx.set(status="done", stage="done", progress=100, finished=db.now())
            ctx.log("Finished.")
        except Relaunch:
            relaunch = True
        except Cancelled:
            ctx.set(status="cancelled", finished=db.now())
            ctx.log("Cancelled.")
        except UserError as e:
            ctx.set(status="error", error=str(e), finished=db.now())
            ctx.log(f"ERROR: {e}")
        except Exception as e:  # noqa: BLE001
            ctx.log("ERROR: " + traceback.format_exc(limit=6))
            ctx.set(status="error", error=f"Something went wrong: {e}", finished=db.now())
        finally:
            with self.lock:
                self.contexts.pop(ctx.job_id, None)
        if relaunch:
            self.submit(ctx.job_id)

    def cancel(self, job_id: int) -> bool:
        with self.lock:
            ctx = self.contexts.get(job_id)
        if ctx:
            ctx.cancel.set()
            ctx.stop.set()
            return True
        job = db.get("jobs", job_id)
        if job and job["status"] == "queued":
            db.update("jobs", job_id, status="cancelled")
            bus.publish("job", public_job(db.get("jobs", job_id)))
        return False

    def stop_live(self, job_id: int) -> bool:
        with self.lock:
            ctx = self.contexts.get(job_id)
        if ctx:
            ctx.stop.set()
            return True
        return False

    def resume_unfinished(self) -> None:
        """After a restart: re-queue anything that was running. Caches make this cheap."""
        for j in db.q("SELECT id FROM jobs WHERE status IN ('queued','running','watching') ORDER BY id"):
            db.update("jobs", j["id"], status="queued")
            self.submit(j["id"])

    def render(self, fn: Callable[[], None]) -> None:
        """Run a (re-)render in the background, limited to CPU cores / 2 at a time."""
        def wrapped():
            with self.render_slots:
                fn()
        self.render_pool.submit(wrapped)


manager = Manager()
