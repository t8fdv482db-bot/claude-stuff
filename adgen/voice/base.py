from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

from ..models import AdScript, AvatarSpec, VoiceTrack, Word


class VoiceProvider(ABC):
    name: str

    @abstractmethod
    def design_voice(self, spec: AvatarSpec, name: str, preview_dir: Path) -> str:
        """Create a fully synthetic voice matching the avatar; return its voice id."""

    @abstractmethod
    def synthesize(self, script: AdScript, voice_id: str, language: str, out_dir: Path) -> VoiceTrack:
        """Speak the whole script in one take and return audio + word timings."""


def build_tts_text(script: AdScript, with_tags: bool) -> tuple[str, list[tuple[int, int]]]:
    """Join segments into one TTS string. Returns text and each segment's (start, end) char range.

    With tags, each segment is prefixed with an ElevenLabs v3 audio tag such as [excited]
    so the read carries emotion; tags are stripped from word timings later.
    """
    parts: list[str] = []
    ranges: list[tuple[int, int]] = []
    pos = 0
    for seg in script.segments:
        prefix = f"[{seg.delivery}] " if with_tags else ""
        chunk = prefix + seg.text.strip()
        if parts:
            pos += 1  # joining space
        ranges.append((pos, pos + len(chunk)))
        parts.append(chunk)
        pos += len(chunk)
    return " ".join(parts), ranges


_TAG_RE = re.compile(r"^\[[^\]]*\]$")


def words_from_alignment(
    chars: list[str],
    starts: list[float],
    ends: list[float],
    seg_ranges: list[tuple[int, int]],
) -> list[Word]:
    """Group per-character timestamps into words, dropping [audio tags]."""
    words: list[Word] = []
    buf: list[int] = []
    in_tag = False

    def segment_of(idx: int) -> int:
        for i, (a, b) in enumerate(seg_ranges):
            if a <= idx < b:
                return i
        return len(seg_ranges) - 1

    def flush():
        if not buf:
            return
        text = "".join(chars[i] for i in buf).strip()
        if text and not _TAG_RE.match(text) and re.search(r"\w", text):
            words.append(Word(text=text, start=starts[buf[0]], end=ends[buf[-1]], segment=segment_of(buf[0])))
        buf.clear()

    for i, ch in enumerate(chars):
        if ch == "[":
            flush()
            in_tag = True
            continue
        if in_tag:
            if ch == "]":
                in_tag = False
            continue
        if ch.isspace():
            flush()
        else:
            buf.append(i)
    flush()
    return words
