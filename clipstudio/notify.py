"""New-clip notifications: in-page toast + sound (SSE) and an optional Discord webhook."""
from __future__ import annotations

import json
import threading
import urllib.request

from . import db
from .worker import bus


def review_link(clip_id: int) -> str:
    port = __import__("os").environ.get("CLIPSTUDIO_PORT", "8765")
    return f"http://127.0.0.1:{port}/review?clip={clip_id}"


def clip_ready(clip_id: int, log=None) -> None:
    clip = db.get("clips", clip_id)
    if not clip:
        return
    bus.publish("clip_ready", {"id": clip_id, "title": clip.get("title"), "job_id": clip.get("job_id")})
    hook = (db.setting("discord_webhook") or "").strip()
    if hook.startswith("https://"):
        threading.Thread(target=_discord, args=(hook, clip, log), daemon=True).start()


def _discord(url: str, clip: dict, log=None) -> None:
    streamer = db.get("streamers", clip["streamer_id"]) if clip.get("streamer_id") else None
    length = (clip.get("end") or 0) - (clip.get("start") or 0)
    payload = {
        "username": "Clip Studio",
        "embeds": [{
            "title": (clip.get("title") or "New clip")[:250],
            "url": review_link(clip["id"]),
            "description": f"{(streamer or {}).get('name', '')} · {length:.0f}s · score {clip.get('score') or 0:.2f}"
                           + (f"\n{clip['reason']}" if clip.get("reason") else ""),
            "color": 0xFF3D6E,
        }],
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "ClipStudio"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:  # noqa: BLE001
        if log:
            log(f"Discord notification failed: {str(e)[:120]}")
