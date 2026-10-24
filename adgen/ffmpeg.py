"""Thin helpers around the ffmpeg / ffprobe CLIs."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise FFmpegError(f"{tool} not found on PATH. Install ffmpeg (https://ffmpeg.org/download.html).")


def run(args: list[str], *, input_bytes: bytes | None = None) -> str:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
    proc = subprocess.run(cmd, input=input_bytes, capture_output=True)
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg failed: {' '.join(cmd)}\n{proc.stderr.decode(errors='replace')[-3000:]}")
    return proc.stderr.decode(errors="replace")


def run_capture_stderr(args: list[str]) -> str:
    """Run ffmpeg with info-level logging (for filters like loudnorm that report on stderr)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-y", *map(str, args)]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg failed: {' '.join(cmd)}\n{proc.stderr.decode(errors='replace')[-3000:]}")
    return proc.stderr.decode(errors="replace")


def probe(path: str | Path) -> dict:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe failed on {path}: {proc.stderr}")
    return json.loads(proc.stdout)


def duration(path: str | Path) -> float:
    return float(probe(path)["format"]["duration"])


def video_size(path: str | Path) -> tuple[int, int]:
    for s in probe(path)["streams"]:
        if s["codec_type"] == "video":
            return int(s["width"]), int(s["height"])
    raise FFmpegError(f"No video stream in {path}")


def escape_filter_path(path: str | Path) -> str:
    """Escape a path for use inside an ffmpeg filtergraph option value."""
    p = str(Path(path).resolve())
    return p.replace("\\", "/").replace(":", r"\:").replace("'", r"\'").replace(",", r"\,")
