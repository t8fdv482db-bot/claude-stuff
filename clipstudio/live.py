"""Live streams: a "highlights so far" catch-up pass plus watch mode.

Watch mode records the stream into rolling 5-minute .ts segments (yt-dlp, falling back to
streamlink), reads live chat, and every minute transcribes the newest audio and re-scores the
last 15 minutes. When a moment beats the threshold (and is 90 s away from the last clip) it waits
for the reaction "tail", cuts the moment out of the segments and renders it right away.
"""
from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

from . import db, media, notify, pipeline, scoring, transcribe
from .media import Cancelled, UserError, fmt_time
from .sources import chat as chatmod
from .sources import common, detect, kick, twitch, youtube
from .worker import JobContext, bus

SEGMENT_SECONDS = 300
TICK = 60
WINDOW = 900          # seconds re-scored each tick
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------- catch-up
def run_catchup(ctx: JobContext, det, meta: dict) -> None:
    hours = float(db.setting("live_catchup_hours") or 3)
    try:
        if det.platform == "twitch":
            vod = twitch.live_vod_url(det.channel or meta.get("channel_id") or "", ctx.log)
            if not vod:
                ctx.log("Catch-up skipped: this channel has no VOD for the current stream (VODs disabled?).")
                return
            vmeta = common.metadata(vod, "twitch", ctx.log)
            dur = vmeta["duration"] or 0
            start = max(0.0, dur - hours * 3600)
            ctx.log(f"Catch-up: analysing the in-progress VOD from {fmt_time(start)} to {fmt_time(dur)}.")
            chat_path = pipeline.cache_dir("twitch", vmeta["id"] + "_live") / "chat.jsonl"
            chat_thread = threading.Thread(target=chatmod.replay, args=(vmeta["webpage_url"], chat_path),
                                           kwargs={"cancel": ctx.cancel, "log": ctx.log}, daemon=True)
            chat_thread.start()
            clip_times = twitch.viewer_clips(vmeta["webpage_url"], vmeta.get("channel_id"), ctx.log)
            pipeline.analyze(ctx, url=vmeta["webpage_url"], platform="twitch",
                             cache=pipeline.cache_dir("twitch", f"{vmeta['id']}_live_{int(start)}"),
                             duration=0, label="_catchup", chat_thread=chat_thread, chat_path=chat_path,
                             clip_times=clip_times, audio_extra=_range(start, dur), t_offset=start,
                             chat_wait_max=120)
        elif det.platform == "youtube":
            rng = youtube.catchup_range(meta, hours)
            if not rng:
                ctx.log("Catch-up skipped: the stream only just started (or its start time is unknown).")
                return
            ctx.log(f"Catch-up: downloading the stream from {fmt_time(rng[0])} to {fmt_time(rng[1])} (live from start).")
            pipeline.analyze(ctx, url=meta["webpage_url"], platform="youtube",
                             cache=pipeline.cache_dir("youtube", f"{meta['id']}_live_{int(rng[0])}"),
                             duration=0, label="_catchup", extra=youtube.catchup_extra(),
                             audio_extra=_range(*rng), t_offset=rng[0])
        elif det.platform == "kick":
            try:
                info = common.extract_info(f"https://kick.com/{det.channel}/videos", ctx.log, flat=True, playlistend=1)
                entries = info.get("entries") or []
            except Exception:  # noqa: BLE001
                entries = []
            if not entries:
                ctx.log("Catch-up skipped: Kick doesn't expose the in-progress stream as a VOD yet. Watch mode still runs.")
                return
            url = entries[0].get("url") or entries[0].get("webpage_url")
            vmeta = common.metadata(url, "kick", ctx.log)
            start = max(0.0, (vmeta["duration"] or 0) - hours * 3600)
            pipeline.analyze(ctx, url=vmeta["webpage_url"], platform="kick",
                             cache=pipeline.cache_dir("kick", f"{vmeta['id']}_live_{int(start)}"), duration=0,
                             label="_catchup", audio_extra=_range(start, vmeta["duration"] or start + 1),
                             t_offset=start)
        ctx.log("Catch-up done.")
    except Cancelled:
        return
    except Exception as e:  # noqa: BLE001 - catch-up must never kill watch mode
        ctx.log(f"Catch-up failed: {str(e)[:300]}. Watch mode keeps running.")


def _range(a: float, b: float) -> dict:
    from yt_dlp.utils import download_range_func
    return {"download_ranges": download_range_func(None, [(a, b)])}


# ---------------------------------------------------------------- recorder
class Recorder:
    """yt-dlp (or streamlink) → ffmpeg segment muxer. Each (re)start is a 'run' in its own folder."""

    def __init__(self, url: str, base: Path, log, session_wall0: float) -> None:
        self.url, self.base, self.log, self.wall0 = url, base, log, session_wall0
        self.runs: list[dict] = []
        self.procs: list[subprocess.Popen] = []
        self.use_streamlink = False

    def start(self) -> None:
        k = len(self.runs)
        d = self.base / f"run_{k}"
        d.mkdir(parents=True, exist_ok=True)
        if self.use_streamlink:
            src = [sys.executable, "-m", "streamlink", "--stdout", "--loglevel", "error",
                   self.url, "1080p60,1080p,936p60,720p60,720p,best"]
        else:
            src = [sys.executable, "-m", "yt_dlp", "-q", "--no-warnings", "--no-part",
                   "-f", "best[height<=1080]/best", "-o", "-", self.url]
        mux = ["ffmpeg", "-nostdin", "-v", "error", "-fflags", "+genpts", "-i", "pipe:0", "-map", "0:v:0?",
               "-map", "0:a:0?", "-c", "copy", "-f", "segment", "-segment_time", str(SEGMENT_SECONDS),
               "-reset_timestamps", "1", "-segment_format", "mpegts", "-segment_list", "list.csv",
               "-segment_list_type", "csv", "seg_%05d.ts"]
        p1 = subprocess.Popen(src, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                              creationflags=_NO_WINDOW)
        p2 = subprocess.Popen(mux, stdin=p1.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              cwd=str(d), creationflags=_NO_WINDOW)
        p1.stdout.close()
        self.procs = [p1, p2]
        self.runs.append({"dir": d, "wall0": time.time(), "started": time.time(), "tool":
                          "streamlink" if self.use_streamlink else "yt-dlp"})
        self.log(f"Recording live stream with {self.runs[-1]['tool']} (5-minute segments).")

    def alive(self) -> bool:
        return bool(self.procs) and self.procs[-1].poll() is None

    def stop(self) -> None:
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
        for p in self.procs:
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()

    def error_text(self) -> str:
        out = []
        for p in self.procs:
            try:
                out.append((p.stderr.read() or b"").decode("utf-8", "replace")[-300:])
            except Exception:  # noqa: BLE001
                pass
        return " ".join(o.strip() for o in out if o.strip())

    def segments(self) -> list[dict]:
        """All segments on disk with session times: {path, t0, t1 (None = still being written)}."""
        segs: list[dict] = []
        for run in self.runs:
            d = run["dir"]
            files = sorted(d.glob("seg_*.ts"))
            if not files:
                continue
            done: dict[str, tuple[float, float]] = {}
            lst = d / "list.csv"
            if lst.exists():
                with open(lst, newline="") as fh:
                    for row in csv.reader(fh):
                        if len(row) >= 3:
                            done[row[0]] = (float(row[1]), float(row[2]))
            floor = (segs[-1]["t1"] or segs[-1]["t0"]) if segs else 0.0
            offset = run.get("offset")
            if offset is None:
                # Session time of this run's first frame. A live stream arrives in real time, so a
                # file's last-write time minus the media it holds is when its first frame arrived.
                first = files[0]
                if first.name in done:
                    offset = run["offset"] = max(floor, first.stat().st_mtime - self.wall0 - done[first.name][1])
                else:
                    try:
                        held = media.duration(first)
                    except Exception:  # noqa: BLE001
                        held = 0.0
                    offset = max(floor, first.stat().st_mtime - self.wall0 - held)
            prev_end = 0.0
            for f in files:
                if f.name in done:
                    a, b = done[f.name]
                    segs.append({"path": f, "t0": offset + a, "t1": offset + b})
                    prev_end = b
                else:
                    segs.append({"path": f, "t0": offset + prev_end, "t1": None})
        return segs


# ---------------------------------------------------------------- watcher
class Watcher:
    def __init__(self, ctx: JobContext, det, meta: dict) -> None:
        self.ctx, self.det, self.meta = ctx, det, meta
        live_root = ctx.dir / "live"
        live_root.mkdir(parents=True, exist_ok=True)
        n = len([p for p in live_root.glob("sess_*") if p.is_dir()])
        self.dir = live_root / f"sess_{n}"
        self.dir.mkdir()
        self.wall0 = time.time()
        self.rec = Recorder(meta["webpage_url"] if det.platform != "twitch" else det.url, self.dir,
                            ctx.log, self.wall0)
        self.rms = np.zeros(0, dtype=np.float32)       # 10 Hz, session time
        self.words: list[dict] = []
        self.segs_tr: list[dict] = []
        self.chat: list[dict] = []
        self.chat_lock = threading.Lock()
        self.t_done = 0.0
        self.scores: dict[int, float] = {}
        self.clip_peaks: list[float] = []
        self.skipped: list[float] = []
        self.job = ctx.job
        self.streamer = db.get("streamers", self.job["streamer_id"]) if self.job.get("streamer_id") else None
        self.opts = pipeline.resolve_options(self.job)
        self.threshold = float(db.setting("live_threshold") or 2.2)
        self.tail = float(db.setting("live_tail") or 10)
        self.keep = float(db.setting("live_keep_minutes") or 120) * 60
        self.scores_path = ctx.dir / "live" / "scores.json"
        self.wall_offsets: list[float] = []

    # ---- chat
    def chat_loop(self) -> None:
        ctx = self.ctx
        while not ctx.stop.is_set():
            try:
                if self.det.platform == "kick":
                    it = kick.live_messages(self.det.channel, ctx.stop, ctx.log)
                else:
                    it = chatmod.live_messages(self.meta["webpage_url"] if self.det.platform == "youtube"
                                               else self.det.url, ctx.stop)
                    ctx.log("Connected to live chat.")
                got = False
                for wall, text in it:
                    got = True
                    with self.chat_lock:
                        self.chat.append({"t": wall - self.wall0, "m": text})
                if self.det.platform == "kick" and not got:
                    return   # kick reader logged why; rely on audio + transcript
            except Exception as e:  # noqa: BLE001
                ctx.log(f"Live chat dropped ({type(e).__name__}: {str(e)[:100]}); reconnecting in 15 s.")
            ctx.stop.wait(15)

    # ---- main loop
    def run(self) -> None:
        ctx = self.ctx
        threading.Thread(target=self.chat_loop, daemon=True, name=f"chat-{ctx.job_id}").start()
        self.rec.start()
        next_tick = time.time() + TICK
        try:
            while not ctx.stop.is_set():
                if not self.rec.alive():
                    if not self._handle_recorder_exit():
                        break
                if time.time() >= next_tick:
                    next_tick = time.time() + TICK
                    self.tick()
                ctx.stop.wait(1)
            ctx.check()
            self.tick(final=True)
        finally:
            self.rec.stop()

    def _handle_recorder_exit(self) -> bool:
        run = self.rec.runs[-1]
        err = self.rec.error_text()
        quick = time.time() - run["started"] < 45 and not list(run["dir"].glob("seg_*.ts"))
        self.fails = getattr(self, "fails", 0) + 1 if quick else 0
        if self.fails >= 8:
            raise UserError(f"Couldn't record this live stream (yt-dlp and streamlink both failed): {err[:200]}")
        if self.fails >= 2:
            self.ctx.stop.wait(20)
        if quick and not self.rec.use_streamlink:
            self.ctx.log(f"yt-dlp couldn't record ({err[:160] or 'no data'}); trying streamlink.")
            self.rec.use_streamlink = True
            self.rec.start()
            return True
        try:
            still = common.metadata(self.det.url, self.det.platform)["is_live"]
        except Exception:  # noqa: BLE001
            still = False
        if still:
            self.ctx.log("Recorder stopped but the stream is still live — restarting it.")
            self.rec.start()
            return True
        self.ctx.log("The stream has ended.")
        return False

    # ---- analysis
    def available_end(self, segs: list[dict]) -> float:
        if not segs:
            return 0.0
        last = segs[-1]
        if last["t1"] is not None:
            return last["t1"]
        try:
            return last["t0"] + media.duration(last["path"])
        except Exception:  # noqa: BLE001
            return last["t0"]

    def tick(self, final: bool = False) -> None:
        ctx = self.ctx
        segs = self.rec.segments()
        avail = self.available_end(segs) - (0 if final else 1.0)
        if avail - self.t_done < 5:
            return
        try:
            self._ingest(segs, self.t_done, avail)
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            ctx.log(f"Live analysis step failed: {str(e)[:200]}")
            return
        self.t_done = avail
        self._score_and_clip(avail, final)
        self._cleanup(segs, avail)

    def _ingest(self, segs: list[dict], a: float, b: float) -> None:
        """Audio loudness + transcript for [a, b] (session time)."""
        for s in segs:
            s_end = s["t1"] if s["t1"] is not None else b
            lo, hi = max(a, s["t0"]), min(b, s_end)
            if hi - lo < 0.5:
                continue
            wav = self.dir / "tick.wav"
            media.extract_wav(s["path"], wav, lo - s["t0"], hi - lo, self.ctx.cancel)
            rms = media.audio_rms(wav, cancel=self.ctx.cancel)
            i0 = int(round(lo * 10))
            need = i0 + len(rms)
            if len(self.rms) < need:
                self.rms = np.concatenate([self.rms, np.zeros(need - len(self.rms), dtype=np.float32)])
            self.rms[i0:i0 + len(rms)] = rms
            data = transcribe.transcribe_wav(wav, lo, None, self.ctx.cancel)
            self.words += data["words"]
            self.segs_tr += data["segments"]
            wav.unlink(missing_ok=True)

    def _score_and_clip(self, avail: float, final: bool) -> None:
        ctx = self.ctx
        lo = max(0, int(avail) - WINDOW)
        n = int(avail) - lo
        if n < 30:
            return
        with self.chat_lock:
            chat = [{"t": m["t"] - lo, "m": m["m"]} for m in self.chat if lo <= m["t"] < avail + 10]
        words = [{**w, "s": w["s"] - lo, "e": w["e"] - lo} for w in self.words if w["e"] > lo]
        segments = [{**s, "s": s["s"] - lo, "e": s["e"] - lo} for s in self.segs_tr if s["e"] > lo]
        rms = self.rms[lo * 10:int(avail * 10)]
        sig = pipeline.build_signals(n, rms=rms, chat=chat, words=words, streamer=self.streamer, clip_times=None)
        score = scoring.combine(sig, pipeline.weights())
        for i, v in enumerate(score):
            self.scores[lo + i] = round(float(v), 3)
        self._save_scores()
        # only look where the reaction "tail" has already been recorded
        last_ok = n - int(self.tail) if not final else n - 3
        if last_ok <= 30:
            return
        masked = score.copy()
        masked[last_ok:] = -np.inf
        masked[:30] = -np.inf        # need some setup before the moment
        for p in self.clip_peaks + self.skipped:
            a, b = int(p - lo - 90), int(p - lo + 90)
            masked[max(0, a):max(0, min(n, b))] = -np.inf
        peak = int(np.argmax(masked))
        if not np.isfinite(masked[peak]) or masked[peak] < self.threshold:
            return
        start, end = scoring.make_window(peak, n, min_len=self.opts["min_len"], max_len=self.opts["max_len"],
                                         words=words, bounds=scoring.sentence_bounds(words, segments))
        if end > n - 1 and not final:
            return   # the end of the window isn't recorded yet: try next tick
        cand = {"peak": float(peak), "start": start, "end": min(end, n - 0.5), "score": round(float(score[peak]), 3),
                "signals": {k: round(float(v[peak]), 2) for k, v in sig.z.items()}}
        chosen = pipeline.choose(ctx, [cand], count=1, opts={**self.opts, "min_len": self.opts["min_len"]},
                                 words=words, segments=segments, chat=chat, streamer=self.streamer, n=n)
        if not chosen:
            ctx.log(f"Moment at {fmt_time(lo + peak)} scored {cand['score']:.2f} but the AI rejected it.")
            self.skipped.append(lo + peak)
            return
        c = chosen[0]
        for k in ("start", "end", "peak"):
            c[k] = round(c[k] + lo, 2)
        self.clip_peaks.append(c["peak"])
        ctx.log(f"🔥 Hype moment at {fmt_time(c['peak'])} (score {c['score']:.2f}) — cutting {fmt_time(c['start'])}–{fmt_time(c['end'])}.")
        self._make_clip(c)

    def _make_clip(self, c: dict) -> None:
        ctx = self.ctx
        a = max(0.0, c["start"] - pipeline.SECTION_PAD)
        b = c["end"] + min(pipeline.SECTION_PAD, max(0.0, self.t_done - c["end"]))
        segs = [s for s in self.rec.segments() if (s["t1"] or 1e12) > a and s["t0"] < b]
        if not segs:
            ctx.log("Couldn't find the recorded segments for that moment.")
            return
        cut_dir = ctx.dir / "sections"
        cut_dir.mkdir(exist_ok=True)
        lst = self.dir / "cut.txt"
        lst.write_text("".join(f"file '{s['path'].relative_to(self.dir).as_posix()}'\n" for s in segs), "utf-8")
        out = cut_dir / f"live_{int(c['start'])}_{int(c['end'])}.mp4"
        media.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{a - segs[0]['t0']:.3f}",
                   "-f", "concat", "-safe", "0", "-i", lst.name, "-t", f"{b - a:.3f}", "-map", "0:v:0", "-map", "0:a:0?",
                   "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-c:a", "aac", "-b:a", "192k",
                   str(out.resolve())], cwd=self.dir, cancel=ctx.cancel)
        words = [w for w in self.words if a - 5 <= w["s"] <= b + 5]
        ids = pipeline.create_clips(ctx, [c], job=self.job, opts=self.opts, source_url="", source_extra=None,
                                    words=words, src_path=out, src_offset=a, src_end=a + media.duration(out))
        db.update("clips", ids[0], source_url=None)
        pipeline.render_clip(ids[0], ctx.log, ctx.cancel)
        self._save_scores()
        if (db.get("clips", ids[0]) or {}).get("render_state") == "ready":
            notify.clip_ready(ids[0], ctx.log)

    def _save_scores(self) -> None:
        keys = sorted(self.scores)
        keys = [k for k in keys if k >= (keys[-1] - 7200 if keys else 0)]
        data = {"t": keys, "s": [self.scores[k] for k in keys], "clips": self.clip_peaks, "threshold": self.threshold}
        self.scores_path.write_text(json.dumps(data), "utf-8")
        step = max(1, math.ceil(len(keys) / 1200))
        bus.publish("live_score", {"job_id": self.ctx.job_id, **downsample(data, step)})

    def _cleanup(self, segs: list[dict], avail: float) -> None:
        for s in segs:
            if s["t1"] is not None and s["t1"] < avail - self.keep:
                s["path"].unlink(missing_ok=True)
        cutoff = avail - self.keep - 600
        if cutoff > 0:
            self.words = [w for w in self.words if w["e"] > cutoff]
            self.segs_tr = [s for s in self.segs_tr if s["e"] > cutoff]
            with self.chat_lock:
                self.chat = [m for m in self.chat if m["t"] > cutoff]


def downsample(data: dict, step: int) -> dict:
    if step <= 1:
        return data
    t, s = data["t"], data["s"]
    out_t, out_s = [], []
    for i in range(0, len(t), step):
        chunk = s[i:i + step]
        out_t.append(t[i])
        out_s.append(max(chunk))
    return {**data, "t": out_t, "s": out_s}


# ---------------------------------------------------------------- entry
def run_live(ctx: JobContext) -> None:
    job = ctx.job
    det = detect(job["url"])
    ctx.stage("downloading", f"Checking {job['url']}…")
    try:
        meta = common.metadata(det.url, det.platform, ctx.log)
    except UserError as e:
        if det.kind == "live":
            raise UserError(f"{det.channel or job['url']} isn't live right now (or the channel isn't reachable). "
                            f"Paste a VOD link instead, or start this job again when they go live.") from e
        raise
    if not meta["is_live"]:
        if det.kind == "live":
            raise UserError(f"{det.channel or job['url']} isn't live right now. Paste a VOD link instead.")
        ctx.set(is_live=0)
        ctx.log("This video isn't live (any more) — processing it as a normal video.")
        pipeline.run_vod(ctx)
        return
    if not det.channel and det.platform != "youtube":
        det.channel = (meta.get("channel_id") or "").lower()
    ctx.set(title=meta["title"], channel=meta["channel"], is_live=1, status="watching", stage="watching")
    ctx.log(f"LIVE: “{meta['title']}” by {meta['channel']}. Starting catch-up and watch mode.")
    catch = threading.Thread(target=run_catchup, args=(ctx, det, meta), daemon=True, name=f"catchup-{ctx.job_id}")
    catch.start()
    watcher = Watcher(ctx, det, meta)
    watcher.run()
    while catch.is_alive():
        ctx.check()
        catch.join(1)
    ctx.log("Stopped watching.")


def scores_for(job_id: int) -> dict:
    p = db.storage_dir() / "jobs" / str(job_id) / "live" / "scores.json"
    if not p.exists():
        return {"t": [], "s": [], "clips": [], "threshold": float(db.setting("live_threshold") or 2.2)}
    data = json.loads(p.read_text("utf-8"))
    return downsample(data, max(1, math.ceil(len(data["t"]) / 1200)))
