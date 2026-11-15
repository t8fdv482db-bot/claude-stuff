"""yt-dlp wrappers shared by all platforms: metadata, audio-only download, section download."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

from ..media import Cancelled, UserError, run

VIDEO_FMT = "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b"
AUDIO_FMT = "worstaudio[abr>=40]/worstaudio/bestaudio/worst"


class _Log:
    def __init__(self, log: Callable[[str], None] | None):
        self.log = log

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        if self.log and "nsig" not in msg:
            self.log("yt-dlp: " + msg[:300])

    def error(self, msg: str) -> None:
        if self.log:
            self.log("yt-dlp: " + msg[:300])


def _opts(log=None, cancel: threading.Event | None = None,
          progress: Callable[[float], None] | None = None, **extra) -> dict:
    def hook(d: dict) -> None:
        if cancel is not None and cancel.is_set():
            from yt_dlp.utils import DownloadCancelled
            raise DownloadCancelled("cancelled")
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                progress(min(1.0, d.get("downloaded_bytes", 0) / total))
            elif d.get("fragment_count"):
                progress(min(1.0, (d.get("fragment_index") or 0) / d["fragment_count"]))
    o = {"quiet": True, "no_warnings": False, "noprogress": True, "logger": _Log(log),
         "progress_hooks": [hook], "retries": 5, "fragment_retries": 10,
         "concurrent_fragment_downloads": 4, "noplaylist": True}
    o.update(extra)
    return o


def friendly(err: Exception, platform: str, what: str = "video") -> UserError:
    msg = str(err)
    low = msg.lower()
    names = {"youtube": "YouTube", "twitch": "Twitch", "kick": "Kick"}
    name = names.get(platform, "This")
    if "private" in low or "members-only" in low or "subscriber" in low:
        return UserError(f"This {name} {what} is private or subscriber-only, so it can't be downloaded.")
    if "not currently live" in low or "is offline" in low:
        return UserError(f"This {name} channel isn't live right now.")
    if "unsupported url" in low:
        return UserError(f"That link doesn't look like a {name} video, VOD or channel.")
    if "403" in low or "forbidden" in low or "unable to download" in low or "not found" in low or "404" in low:
        return UserError(f"This {name} {what} isn't reachable (it may be deleted, region-locked or blocked). "
                         f"Details: {msg[:200]}")
    return UserError(f"{name} download failed: {msg[:300]}")


def extract_info(url: str, log=None, flat: bool = False, **extra) -> dict:
    import yt_dlp
    o = _opts(log, skip_download=True, **extra)
    if flat:
        o["extract_flat"] = "in_playlist"
        o["noplaylist"] = False
        o["playlistend"] = extra.get("playlistend", 10)
    with yt_dlp.YoutubeDL(o) as ydl:
        return ydl.sanitize_info(ydl.extract_info(url, download=False))


def metadata(url: str, platform: str, log=None) -> dict:
    """Title, channel, duration and live status."""
    from yt_dlp.utils import DownloadError
    try:
        info = extract_info(url, log)
    except DownloadError as e:
        raise friendly(e, platform) from e
    if info.get("_type") == "playlist" and info.get("entries"):
        info = info["entries"][0]
    live = bool(info.get("is_live")) or info.get("live_status") in ("is_live", "post_live_processing")
    return {
        "id": str(info.get("id") or ""),
        "title": info.get("title") or info.get("fulltitle") or "",
        "channel": info.get("uploader") or info.get("channel") or info.get("uploader_id") or "",
        "channel_id": info.get("channel_id") or info.get("uploader_id") or "",
        "duration": float(info.get("duration") or 0),
        "is_live": live,
        "live_status": info.get("live_status"),
        "release_timestamp": info.get("release_timestamp") or info.get("timestamp"),
        "webpage_url": info.get("webpage_url") or url,
        "width": info.get("width"), "height": info.get("height"),
    }


def _find(out_dir: Path, stem: str) -> Path | None:
    for p in sorted(out_dir.glob(stem + ".*")):
        if p.suffix not in (".part", ".ytdl", ".json") and not p.name.endswith(".part"):
            return p
    return None


def download_audio(url: str, out_dir: Path, platform: str, *, log=None, cancel=None, progress=None,
                   extra: dict | None = None) -> Path:
    """Low-bitrate audio only — the fast path that lets analysis start before any video is fetched."""
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled, DownloadError
    done = out_dir / "audio.done"
    if done.exists():
        p = _find(out_dir, "audio")
        if p:
            return p
    o = _opts(log, cancel, progress, format=AUDIO_FMT, outtmpl=str(out_dir / "audio.%(ext)s"),
              continuedl=True, **(extra or {}))
    try:
        with yt_dlp.YoutubeDL(o) as ydl:
            ydl.download([url])
    except DownloadCancelled as e:
        raise Cancelled() from e
    except DownloadError as e:
        if cancel is not None and cancel.is_set():
            raise Cancelled() from e
        raise friendly(e, platform) from e
    p = _find(out_dir, "audio")
    if not p:
        raise UserError("Audio download finished but no file was produced.")
    done.write_text("ok")
    return p


def download_section(url: str, start: float, end: float, out_path: Path, platform: str, *,
                     log=None, cancel=None, extra: dict | None = None) -> Path:
    """Download only [start, end] of the video (max 1080p), cut on exact frames."""
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled, DownloadError, download_range_func
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stem = out_path.stem
    existing = _find(out_path.parent, stem)
    if existing and (out_path.parent / (stem + ".done")).exists():
        return existing
    o = _opts(log, cancel, None, format=VIDEO_FMT, outtmpl=str(out_path.parent / (stem + ".%(ext)s")),
              download_ranges=download_range_func(None, [(max(0.0, start), end)]),
              force_keyframes_at_cuts=True, merge_output_format="mp4", **(extra or {}))
    try:
        with yt_dlp.YoutubeDL(o) as ydl:
            ydl.download([url])
    except DownloadCancelled as e:
        raise Cancelled() from e
    except DownloadError as e:
        if cancel is not None and cancel.is_set():
            raise Cancelled() from e
        raise friendly(e, platform) from e
    p = _find(out_path.parent, stem)
    if not p:
        raise RuntimeError("section download produced no file")
    (out_path.parent / (stem + ".done")).write_text(json.dumps({"start": start, "end": end}))
    return p


def download_full(url: str, out_dir: Path, platform: str, *, log=None, cancel=None, progress=None,
                  extra: dict | None = None) -> Path:
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled, DownloadError
    done = out_dir / "full.done"
    if done.exists():
        p = _find(out_dir, "full")
        if p:
            return p
    o = _opts(log, cancel, progress, format=VIDEO_FMT, outtmpl=str(out_dir / "full.%(ext)s"),
              merge_output_format="mp4", continuedl=True, **(extra or {}))
    try:
        with yt_dlp.YoutubeDL(o) as ydl:
            ydl.download([url])
    except DownloadCancelled as e:
        raise Cancelled() from e
    except DownloadError as e:
        raise friendly(e, platform) from e
    p = _find(out_dir, "full")
    if not p:
        raise UserError("Video download finished but no file was produced.")
    done.write_text("ok")
    return p


def cut_local(src: Path, start: float, end: float, dst: Path, cancel=None) -> Path:
    """Frame-accurate cut from a local file (used when section download isn't possible)."""
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{max(0, start):.3f}", "-i", src,
         "-t", f"{end - max(0, start):.3f}", "-map", "0:v:0", "-map", "0:a:0?",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-c:a", "aac", "-b:a", "192k", dst],
        cancel=cancel)
    return dst


def info_json(path: Path, data: Any | None = None) -> Any:
    if data is None:
        return json.loads(path.read_text("utf-8")) if path.exists() else None
    path.write_text(json.dumps(data), "utf-8")
    return data
