"""Kick: best-effort live chat over Kick's public Pusher websocket. Kick has no replay chat."""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from typing import Callable, Iterator

PUSHER = "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679?protocol=7&client=js&version=8.4.0&flash=false"


def chatroom_id(channel: str) -> int | None:
    req = urllib.request.Request(f"https://kick.com/api/v2/channels/{channel}",
                                 headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    return (data.get("chatroom") or {}).get("id")


def live_messages(channel: str, stop: threading.Event,
                  log: Callable[[str], None] | None = None) -> Iterator[tuple[float, str]]:
    from websockets.sync.client import connect
    try:
        room = chatroom_id(channel)
    except Exception as e:  # noqa: BLE001
        if log:
            log(f"Kick chat unavailable (channel lookup blocked: {str(e)[:100]}). Using audio + transcript only.")
        return
    if not room:
        if log:
            log("Kick chat unavailable (no chatroom id). Using audio + transcript only.")
        return
    with connect(PUSHER, open_timeout=15) as ws:
        ws.send(json.dumps({"event": "pusher:subscribe", "data": {"auth": "", "channel": f"chatrooms.{room}.v2"}}))
        if log:
            log("Connected to Kick live chat.")
        while not stop.is_set():
            try:
                raw = ws.recv(timeout=2)
            except TimeoutError:
                continue
            try:
                msg = json.loads(raw)
                if msg.get("event") == "App\\Events\\ChatMessageEvent":
                    data = json.loads(msg.get("data") or "{}")
                    yield time.time(), (data.get("content") or "")[:200]
                elif msg.get("event") == "pusher:ping":
                    ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
            except ValueError:
                continue


def normalize_vod_url(url: str) -> str:
    """kick.com/video/<uuid> (old link style) → kick.com/<channel>/videos/<uuid>, which yt-dlp understands."""
    import re
    m = re.search(r"kick\.com/video/([0-9a-f-]{36})", url, re.I)
    if not m:
        return url
    req = urllib.request.Request(f"https://kick.com/api/v1/video/{m.group(1)}",
                                 headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            slug = json.loads(resp.read().decode())["livestream"]["channel"]["slug"]
    except Exception:  # noqa: BLE001
        return url
    return f"https://kick.com/{slug}/videos/{m.group(1)}"


def vod_meta(url: str) -> dict | None:
    """Metadata + direct HLS playlist for a Kick VOD from Kick's public API (fallback when yt-dlp can't)."""
    import re
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", url, re.I)
    if not m:
        return None
    req = urllib.request.Request(f"https://kick.com/api/v1/video/{m.group(1)}",
                                 headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read().decode())
    except Exception:  # noqa: BLE001
        return None
    ls = d.get("livestream") or {}
    if not d.get("source"):
        return None
    return {"id": m.group(1), "title": ls.get("session_title") or "Kick VOD",
            "channel": (ls.get("channel") or {}).get("slug", ""), "channel_id": (ls.get("channel") or {}).get("slug", ""),
            "duration": float(ls.get("duration") or 0) / 1000.0, "is_live": False, "live_status": "was_live",
            "release_timestamp": None, "webpage_url": d["source"], "width": None, "height": None}
