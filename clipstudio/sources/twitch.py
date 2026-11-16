"""Twitch: in-progress VOD lookup for live channels and viewer clips for VODs."""
from __future__ import annotations

import json
import math
import re
import urllib.request
from pathlib import Path
from typing import Callable

from .common import extract_info

GQL = "https://gql.twitch.tv/gql"
PUBLIC_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"  # the public web client id


def vod_id(url: str) -> str | None:
    m = re.search(r"/videos?/(\d+)", url) or re.search(r"/v/(\d+)", url)
    return m.group(1) if m else None


def _gql(query: str, variables: dict) -> dict:
    req = urllib.request.Request(GQL, data=json.dumps({"query": query, "variables": variables}).encode(),
                                 headers={"Client-ID": PUBLIC_CLIENT_ID, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def live_vod_url(channel: str, log: Callable[[str], None] | None = None) -> str | None:
    """The archive VOD of the broadcast that is live right now (None if VODs are disabled)."""
    try:
        info = extract_info(f"https://www.twitch.tv/{channel}/videos?filter=archives&sort=time", log,
                            flat=True, playlistend=3)
    except Exception as e:  # noqa: BLE001
        if log:
            log(f"Couldn't list {channel}'s VODs: {str(e)[:150]}")
        return None
    for entry in info.get("entries") or []:
        url = entry.get("url") or entry.get("webpage_url")
        if not url:
            continue
        if not url.startswith("http"):
            url = f"https://www.twitch.tv/videos/{str(url).lstrip('v')}"
        # The newest archive while live is the in-progress one; yt-dlp marks it live or with a fresh timestamp.
        return url
    return None


def viewer_clips(vod_url: str, channel_login: str | None,
                 log: Callable[[str], None] | None = None) -> list[tuple[float, float]]:
    """[(vod_seconds_of_moment, weight)] from Twitch clips made on this VOD. Best effort."""
    vid = vod_id(vod_url)
    if not vid or not channel_login:
        return []
    query = """query($login:String!){ user(login:$login){ clips(first:100, criteria:{period:LAST_MONTH, sort:VIEWS_DESC}){
      edges{ node{ id viewCount durationSeconds videoOffsetSeconds video{ id } } } } } }"""
    try:
        data = _gql(query, {"login": channel_login.lower()})
        edges = (((data.get("data") or {}).get("user") or {}).get("clips") or {}).get("edges") or []
    except Exception as e:  # noqa: BLE001
        if log:
            log(f"Twitch viewer clips unavailable ({str(e)[:120]}).")
        return []
    out = []
    for e in edges:
        n = e.get("node") or {}
        if (n.get("video") or {}).get("id") != vid or n.get("videoOffsetSeconds") is None:
            continue
        # A clip captures the ~30 s *before* someone pressed the button; the moment sits near its end.
        t = float(n["videoOffsetSeconds"]) + 0.7 * float(n.get("durationSeconds") or 30)
        out.append((t, 1.0 + math.log10(1 + (n.get("viewCount") or 0))))
    if log:
        log(f"Found {len(out)} viewer clips on this VOD.")
    return out


# ---------------------------------------------------------------- chat replay
_COMMENTS_Q = """query($id:ID!,$off:Int){video(id:$id){comments(contentOffsetSeconds:$off){
  edges{node{id contentOffsetSeconds message{fragments{text}}}}}}}"""


def _comments_at(vid: str, off: int) -> list[dict]:
    for attempt in range(4):
        try:
            data = _gql(_COMMENTS_Q, {"id": vid, "off": int(off)})
            edges = ((((data.get("data") or {}).get("video") or {}).get("comments") or {}).get("edges")) or []
            return [e["node"] for e in edges if e.get("node")]
        except Exception:  # noqa: BLE001
            if attempt == 3:
                raise
            import time
            time.sleep(1 + attempt * 2)
    return []


def _fetch_range(vid: str, a: int, b: int, out: Path, cancel=None, tick=None) -> None:
    """All comments with a <= t < b, paging by time offset (cursor paging needs a browser token)."""
    done = out.with_suffix(".done")
    if done.exists():
        return
    seen: set[str] = set()
    rows: list[dict] = []
    off = a
    while off < b:
        if cancel is not None and cancel.is_set():
            return
        nodes = _comments_at(vid, off)
        if not nodes:
            break
        last = off
        for n in nodes:
            t = n.get("contentOffsetSeconds")
            if t is None or n.get("id") in seen:
                continue
            seen.add(n["id"])
            last = max(last, int(t))
            if a <= t < b:
                text = "".join(f.get("text") or "" for f in ((n.get("message") or {}).get("fragments") or []))
                rows.append({"t": float(t), "m": text[:200]})
        off = last if last > off else off + 1     # same second again (de-duplicated), or move on
        if tick:
            tick(off - a)
    with open(out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    done.write_text(str(len(rows)))


def chat_replay(vod_url: str, duration: float, out: Path, *, cancel=None, log=None, workers: int = 8) -> Path:
    """Download a Twitch VOD's chat replay in parallel time ranges. Resumable; writes chat.jsonl."""
    from concurrent.futures import ThreadPoolExecutor
    done = out.with_suffix(".done")
    if done.exists():
        return out
    vid = vod_id(vod_url)
    if not vid or not duration:
        if log:
            log("Chat replay skipped (unknown VOD id or length).")
        return out
    parts_dir = out.parent / "chat_parts"
    parts_dir.mkdir(exist_ok=True)
    step = max(60, int(math.ceil(duration / (workers * 4))))
    ranges = [(a, min(int(duration) + 1, a + step)) for a in range(0, int(duration) + 1, step)]
    progress = [0] * len(ranges)
    import threading
    import time
    lock = threading.Lock()
    last_log = [time.time()]

    def work(i: int) -> None:
        a, b = ranges[i]

        def tick(n: int) -> None:
            with lock:
                progress[i] = n
                if log and time.time() - last_log[0] > 20:
                    last_log[0] = time.time()
                    log(f"Chat replay: {100 * sum(progress) / max(1, duration):.0f}%")
        _fetch_range(vid, a, b, parts_dir / f"p{a:07d}.jsonl", cancel, tick)

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(work, range(len(ranges))))
    except Exception as e:  # noqa: BLE001
        if log:
            log(f"Chat replay unavailable ({type(e).__name__}: {str(e)[:120]}). Continuing without chat.")
        return out
    if cancel is not None and cancel.is_set():
        return out
    n = 0
    with open(out, "w", encoding="utf-8") as fh:
        for p in sorted(parts_dir.glob("p*.jsonl")):
            for line in p.read_text("utf-8").splitlines():
                fh.write(line + "\n")
                n += 1
    done.write_text(str(n))
    if log:
        log(f"Chat replay saved: {n} messages.")
    return out
