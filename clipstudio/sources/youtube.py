"""YouTube specifics: live catch-up from the start of a running stream."""
from __future__ import annotations

import time


def catchup_extra() -> dict:
    """yt-dlp options that make a live stream downloadable from its beginning."""
    return {"live_from_start": True}


def catchup_range(meta: dict, hours: float) -> tuple[float, float] | None:
    """(start, end) in stream seconds for the 'highlights so far' pass, or None if unknown."""
    started = meta.get("release_timestamp")
    if not started:
        return None
    elapsed = time.time() - float(started)
    if elapsed < 120:
        return None
    return max(0.0, elapsed - hours * 3600), elapsed - 30
