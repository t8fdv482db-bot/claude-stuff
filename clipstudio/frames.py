"""Grab a single frame from any link (or local file) at a timestamp — used by the facecam picker."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from . import media
from .media import UserError
from .sources import common, detect


def grab(url: str, t: float, out: Path, log=None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    d = detect(url)
    if d.platform == "unknown":
        raise UserError("Paste a YouTube, Twitch or Kick link (or a video file path).")
    if d.platform == "file":
        _frame(Path(d.url), max(0.0, t), out)
        return out
    meta = common.metadata(d.url, d.platform, log)
    if meta["is_live"]:
        info = common.extract_info(d.url, log, format=common.VIDEO_FMT.replace("bv*[height<=1080]+ba/", ""))
        stream = info.get("url") or (info.get("requested_formats") or [{}])[0].get("url")
        if not stream:
            raise UserError("Couldn't get the live stream address.")
        headers = "".join(f"{k}: {v}\r\n" for k, v in (info.get("http_headers") or {}).items())
        args = ["ffmpeg", "-nostdin", "-y", "-v", "error"]
        if headers:
            args += ["-headers", headers]
        media.run(args + ["-i", stream, "-frames:v", "1", "-q:v", "3", str(out)], timeout=60)
        return out
    if meta["duration"] and t > meta["duration"]:
        t = meta["duration"] / 2
    tmp = Path(tempfile.mkdtemp(prefix="cs_frame_"))
    try:
        got = None
        if d.platform in ("twitch", "kick"):
            try:
                got = common.download_section_hls(d.url, t, t + 2, tmp / "grab", log=log)
            except Exception:  # noqa: BLE001 - fall back to yt-dlp below
                got = None
        sec = got[0] if got else common.download_section(d.url, t, t + 2, tmp / "grab", d.platform, log=log)
        _frame(sec, 0.2, out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def _frame(src: Path, t: float, out: Path) -> None:
    media.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src),
               "-frames:v", "1", "-q:v", "3", str(out)], timeout=60)
    if not out.exists():
        raise UserError("No frame at that time — try an earlier timestamp.")
