"""Twitch: in-progress VOD lookup for live channels and viewer clips for VODs."""
from __future__ import annotations

import json
import math
import re
import urllib.request
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
