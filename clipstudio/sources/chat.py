"""Chat via chat-downloader (Twitch + YouTube, replay and live). Stored as JSON lines: {"t": sec, "m": text}."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable, Iterator


def load(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # half-written last line after a crash
    return out


def replay(url: str, out: Path, *, cancel: threading.Event | None = None,
           log: Callable[[str], None] | None = None, duration: float = 0,
           progress: Callable[[float], None] | None = None) -> Path:
    """Download replay chat, resumable: restarts from the last saved timestamp."""
    done = out.with_suffix(".done")
    if done.exists():
        return out
    from chat_downloader import ChatDownloader
    start = 0.0
    existing = load(out)
    if existing:
        start = max(0.0, existing[-1]["t"] - 1)
        if log:
            log(f"Resuming chat download at {int(start)} s ({len(existing)} messages saved).")
    n = len(existing)
    last_pub = 0.0
    try:
        chat = ChatDownloader().get_chat(url, start_time=start or None, message_types=["text_message"],
                                         chat_type="live", inactivity_timeout=120)
        with open(out, "a", encoding="utf-8") as fh:
            for msg in chat:
                if cancel is not None and cancel.is_set():
                    return out
                t = msg.get("time_in_seconds")
                text = msg.get("message") or ""
                if t is None or t < start:
                    continue
                fh.write(json.dumps({"t": round(float(t), 2), "m": text[:200]}, ensure_ascii=False) + "\n")
                n += 1
                if progress and duration and time.time() - last_pub > 1:
                    last_pub = time.time()
                    progress(min(1.0, t / duration))
    except Exception as e:  # noqa: BLE001 - chat is optional, never fail the job on it
        if log:
            log(f"Chat replay unavailable ({type(e).__name__}: {str(e)[:150]}). Continuing without chat.")
        return out
    done.write_text(str(n))
    if log:
        log(f"Chat replay saved: {n} messages.")
    return out


def live_messages(url: str, stop: threading.Event) -> Iterator[tuple[float, str]]:
    """Yield (wall_clock_time, text) for live chat until `stop` is set."""
    from chat_downloader import ChatDownloader
    chat = ChatDownloader().get_chat(url, message_types=["text_message"], chat_type="live",
                                     message_receive_timeout=0.5, inactivity_timeout=None)
    for msg in chat:
        if stop.is_set():
            break
        if not msg:
            continue
        ts = msg.get("timestamp")
        wall = ts / 1e6 if ts and ts > 1e12 else time.time()
        yield wall, (msg.get("message") or "")[:200]
