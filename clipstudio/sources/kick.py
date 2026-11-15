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
