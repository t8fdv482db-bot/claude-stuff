"""Exports for posting by hand: mp4 + caption text, single clips or a zip of approved clips.

Clip Studio never posts anything itself and never logs in to social accounts.
"""
from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path

from . import db


def slug(text: str, n: int = 50) -> str:
    s = re.sub(r"[^\w\- ]+", "", text or "").strip().replace(" ", "_")
    return (s[:n] or "clip").strip("_") or "clip"


def caption_text(clip: dict) -> str:
    desc = (clip.get("description") or "").strip()
    title = (clip.get("title") or "").strip()
    if not desc:
        return title
    return desc if title in desc else f"{title}\n\n{desc}"


def export_zip(clip_ids: list[int]) -> Path:
    tmp = Path(tempfile.mkstemp(prefix="clipstudio_", suffix=".zip")[1])
    with zipfile.ZipFile(tmp, "w") as z:
        for cid in clip_ids:
            c = db.get("clips", cid)
            if not c or not c.get("video_path") or not Path(c["video_path"]).exists():
                continue
            base = f"{cid:04d}_{slug(c.get('title'))}"
            z.write(c["video_path"], f"{base}.mp4", compress_type=zipfile.ZIP_STORED)
            z.writestr(f"{base}.txt", caption_text(c), compress_type=zipfile.ZIP_DEFLATED)
    return tmp
