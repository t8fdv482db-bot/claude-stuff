"""Platform detection + per-platform helpers (YouTube, Twitch, Kick)."""
from __future__ import annotations

import re
from dataclasses import dataclass

YT = re.compile(r"(?:^|//)(?:www\.|m\.)?(?:youtube\.com|youtu\.be|youtube-nocookie\.com)/", re.I)
TW = re.compile(r"(?:^|//)(?:www\.|m\.)?twitch\.tv/", re.I)
KICK = re.compile(r"(?:^|//)(?:www\.)?kick\.com/", re.I)


@dataclass
class Detected:
    url: str
    platform: str        # youtube | twitch | kick | unknown
    kind: str            # vod | live | maybe-live
    channel: str = ""

    @property
    def badge(self) -> str:
        names = {"youtube": "YouTube", "twitch": "Twitch", "kick": "Kick"}
        k = {"vod": "VOD", "live": "LIVE", "maybe-live": "LIVE?"}[self.kind]
        return f"{names.get(self.platform, 'Unknown')} · {k}"


def detect(url: str) -> Detected:
    """Fast, offline guess from the URL alone (the worker confirms live status with yt-dlp)."""
    u = url.strip()
    if u and not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    if TW.search(u):
        m = re.search(r"twitch\.tv/(?:videos/(\d+)|([A-Za-z0-9_]+)/(?:video|v)/(\d+))", u, re.I)
        if m:
            return Detected(u, "twitch", "vod")
        if re.search(r"twitch\.tv/[^/]+/clip/|clips\.twitch\.tv/", u, re.I):
            return Detected(u, "twitch", "vod")
        m = re.search(r"twitch\.tv/([A-Za-z0-9_]+)/?(?:[?#].*)?$", u, re.I)
        if m:
            return Detected(f"https://www.twitch.tv/{m.group(1)}", "twitch", "live", m.group(1).lower())
        return Detected(u, "twitch", "vod")
    if KICK.search(u):
        if re.search(r"kick\.com/(?:video/|[^/]+/videos/|[^/]+/clips?/)", u, re.I):
            return Detected(u, "kick", "vod")
        m = re.search(r"kick\.com/([A-Za-z0-9_\-]+)/?(?:[?#].*)?$", u, re.I)
        if m:
            return Detected(f"https://kick.com/{m.group(1)}", "kick", "live", m.group(1).lower())
        return Detected(u, "kick", "vod")
    if YT.search(u):
        if re.search(r"youtube\.com/(?:@[^/]+|c/[^/]+|channel/[^/]+|user/[^/]+)/live/?$", u, re.I):
            return Detected(u, "youtube", "live")
        if re.search(r"youtube\.com/live/", u, re.I):
            return Detected(u, "youtube", "maybe-live")
        return Detected(u, "youtube", "maybe-live" if "live" in u.lower() else "vod")
    return Detected(u, "unknown", "vod")
