"""Small ffmpeg/ffprobe helpers. Every command is an argument list (never a shell string)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np


class Cancelled(Exception):
    pass


class UserError(Exception):
    """An error with a message that is safe and useful to show in the UI."""


FFMPEG_HELP = {
    "win32": "ffmpeg not found — install it with `winget install Gyan.FFmpeg`, then restart Clip Studio.",
    "darwin": "ffmpeg not found — install it with `brew install ffmpeg`, then restart Clip Studio.",
}


def ffmpeg_missing_message() -> str:
    return FFMPEG_HELP.get(sys.platform, "ffmpeg not found — install it with your package manager (e.g. `sudo apt install ffmpeg`).")


def have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(args: list, *, cwd: Path | None = None, cancel: threading.Event | None = None,
        timeout: float | None = None, on_line: Callable[[str], None] | None = None) -> str:
    """Run a command, killing it if `cancel` is set. Returns stderr text (tail) on success."""
    args = [str(a) for a in args]
    if args[0] in ("ffmpeg", "ffprobe") and not shutil.which(args[0]):
        raise UserError(ffmpeg_missing_message())
    proc = subprocess.Popen(args, cwd=str(cwd) if cwd else None, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
    tail: list[str] = []
    out_chunks: list[bytes] = []

    def pump_err():
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            tail.append(line)
            if len(tail) > 60:
                del tail[:20]
            if on_line:
                on_line(line)

    def pump_out():
        out_chunks.append(proc.stdout.read())

    t1 = threading.Thread(target=pump_err, daemon=True)
    t2 = threading.Thread(target=pump_out, daemon=True)
    t1.start(); t2.start()
    start = time.time()
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            proc.kill(); proc.wait()
            raise Cancelled()
        if timeout and time.time() - start > timeout:
            proc.kill(); proc.wait()
            raise RuntimeError(f"{Path(args[0]).name} timed out")
        time.sleep(0.1)
    t1.join(2); t2.join(2)
    if proc.returncode != 0:
        msg = "\n".join(tail[-8:])
        raise RuntimeError(f"{Path(args[0]).name} failed: {msg}")
    run.last_stdout = b"".join(out_chunks)  # type: ignore[attr-defined]
    return "\n".join(tail)


def probe(path: Path) -> dict:
    run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    return json.loads(run.last_stdout or b"{}")  # type: ignore[attr-defined]


def duration(path: Path) -> float:
    info = probe(path)
    try:
        return float(info["format"]["duration"])
    except (KeyError, ValueError):
        return 0.0


def has_audio(path: Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(path).get("streams", []))


def audio_rms(path: Path, *, rate: int = 8000, hop: float = 0.1, start: float | None = None,
              cancel: threading.Event | None = None) -> np.ndarray:
    """Loudness envelope: RMS (linear, 0..1) every `hop` seconds, streamed so 12-hour files are fine."""
    args = ["ffmpeg", "-nostdin", "-v", "error"]
    if start:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(path), "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"]
    if not shutil.which("ffmpeg"):
        raise UserError(ffmpeg_missing_message())
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    hop_n = int(rate * hop)
    out: list[float] = []
    leftover = np.zeros(0, dtype=np.float32)
    try:
        while True:
            if cancel is not None and cancel.is_set():
                proc.kill()
                raise Cancelled()
            buf = proc.stdout.read(hop_n * 2 * 600)  # 60 s at a time
            if not buf:
                break
            x = np.frombuffer(buf[: len(buf) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
            x = np.concatenate([leftover, x])
            n = len(x) // hop_n
            if n:
                blocks = x[: n * hop_n].reshape(n, hop_n)
                out.extend(np.sqrt(np.mean(blocks * blocks, axis=1)).tolist())
            leftover = x[n * hop_n:]
    finally:
        proc.stdout.close()
        proc.wait()
    return np.asarray(out, dtype=np.float32)


def extract_wav(src: Path, dst: Path, start: float, length: float | None,
                cancel: threading.Event | None = None) -> Path:
    args = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-i", src]
    if length:
        args += ["-t", f"{length:.3f}"]
    args += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", dst]
    run(args, cancel=cancel)
    return dst


def fmt_time(t: float) -> str:
    t = max(0, int(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
