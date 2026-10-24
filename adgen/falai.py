"""Shared helpers for models hosted on fal.ai (portraits, lip-sync)."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from .config import require_key

log = logging.getLogger(__name__)


def _client():
    import fal_client

    require_key("FAL_KEY")  # fal_client reads FAL_KEY from the environment
    return fal_client


def upload(path: str | Path) -> str:
    return _client().upload_file(Path(path))


def run(endpoint: str, arguments: dict) -> dict:
    fal = _client()

    def on_update(status):
        if isinstance(status, fal.InProgress) and status.logs:
            for entry in status.logs:
                log.info("[%s] %s", endpoint, entry.get("message"))

    return fal.subscribe(endpoint, arguments=arguments, with_logs=True, on_queue_update=on_update)


def download(url: str, dest: str | Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    return dest
