"""Campaign rules (Whop / Content Rewards style) and the checker that warns about rule breaks."""
from __future__ import annotations

import json

from . import db
from .scoring import parse_list

PLATFORMS = ["youtube", "tiktok", "instagram", "x"]


def platforms(c: dict) -> list[str]:
    try:
        v = json.loads(c.get("platforms") or "[]")
        return [p for p in v if p in PLATFORMS]
    except ValueError:
        return list(PLATFORMS)


def check(clip: dict, camp: dict, *, channel: str = "", platform: str | None = None) -> list[str]:
    """Human-readable warnings for every campaign rule this clip breaks."""
    out: list[str] = []
    length = float(clip["end"]) - float(clip["start"])
    if camp.get("min_len") and length < float(camp["min_len"]) - 0.05:
        out.append(f"Too short for {camp['name']}: {length:.0f}s (min {float(camp['min_len']):.0f}s).")
    if camp.get("max_len") and length > float(camp["max_len"]) + 0.05:
        out.append(f"Too long for {camp['name']}: {length:.0f}s (max {float(camp['max_len']):.0f}s).")
    disc = (camp.get("disclosure") or "").strip()
    if disc:
        if not clip.get("disclosure_burned"):
            out.append("Disclosure isn't burned into the video yet — re-render the clip.")
        first = (clip.get("description") or "").strip().splitlines()[:1]
        if not first or first[0].strip() != disc:
            out.append(f"Description must start with the disclosure: “{disc}”.")
    desc = (clip.get("description") or "") + " " + (clip.get("title") or "")
    low = desc.lower()
    missing = []
    for tag in parse_list(camp.get("hashtags")):
        t = tag if tag.startswith(("#", "@")) else "#" + tag
        if t.lower() not in low:
            missing.append(t)
    if missing:
        out.append("Missing required tags: " + " ".join(missing))
    src = (camp.get("required_source") or "").strip()
    if src and src.lower() not in (channel or "").lower():
        out.append(f"Footage must come from “{src}” (this clip is from “{channel or 'unknown'}”).")
    if platform and platform not in platforms(camp):
        out.append(f"{camp['name']} doesn't allow posting on {platform}.")
    return out


def clip_warnings(clip: dict, platform: str | None = None) -> list[str]:
    if not clip.get("campaign_id"):
        return []
    camp = db.get("campaigns", clip["campaign_id"])
    if not camp:
        return []
    job = db.get("jobs", clip["job_id"]) or {}
    return check(clip, camp, channel=(job.get("channel") or "") + " " + (job.get("url") or ""), platform=platform)
