"""Shared data models passed between pipeline stages."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

AspectRatio = Literal["9:16", "1:1", "16:9"]
AdLength = Literal[15, 20, 30]
SegmentRole = Literal["hook", "problem", "solution", "cta"]
Visual = Literal["avatar", "broll"]
Delivery = Literal["excited", "warm", "curious", "confident", "playful", "calm", "serious"]

WORDS_PER_SECOND = 2.5

RESOLUTIONS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "product"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProductBrief(BaseModel):
    """Everything the user tells us about the product and the ad they want."""

    name: str
    description: str
    target_audience: str
    selling_points: list[str] = Field(min_length=1)
    image_paths: list[str] = Field(default_factory=list)
    product_url: str | None = None
    logo_path: str | None = None
    cta: str = "Shop now"
    tone: str = "casual UGC"
    length: AdLength = 30
    aspect_ratios: list[AspectRatio] = Field(default_factory=lambda: ["9:16"])
    language: str = "en"
    # Free-form extra facts the script may use verbatim (prices, offers...).
    approved_claims: list[str] = Field(default_factory=list)

    @property
    def slug(self) -> str:
        return slugify(self.name)

    @property
    def word_budget(self) -> int:
        return int(self.length * WORDS_PER_SECOND)


class ScriptSegment(BaseModel):
    role: SegmentRole
    text: str
    delivery: Delivery = "warm"
    visual: Visual = "avatar"
    broll_focus: str = ""

    @property
    def word_count(self) -> int:
        return len(self.text.split())


class AdScript(BaseModel):
    variant: str  # "A", "B", "C"
    angle: str
    segments: list[ScriptSegment]
    on_screen_cta: str
    claims_used: list[str] = Field(default_factory=list)

    @property
    def full_text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments)

    @property
    def word_count(self) -> int:
        return sum(s.word_count for s in self.segments)

    @property
    def est_seconds(self) -> float:
        return round(self.word_count / WORDS_PER_SECOND, 1)

    @property
    def avatar_words(self) -> int:
        return sum(s.word_count for s in self.segments if s.visual == "avatar")


class ScriptSet(BaseModel):
    product: str
    created_at: str = Field(default_factory=utcnow)
    provider: str
    variants: list[AdScript]
    cost_usd: float = 0.0

    def get(self, variant: str) -> AdScript:
        for v in self.variants:
            if v.variant.upper() == variant.upper():
                return v
        raise KeyError(f"No variant {variant!r}; have {[v.variant for v in self.variants]}")


class AvatarSpec(BaseModel):
    """Attributes of a fully synthetic presenter."""

    age: str = "late 20s"
    gender: str = "woman"
    ethnicity: str = "unspecified"
    setting: str = "bright modern apartment living room"
    outfit: str = "casual knit sweater"
    extra: str = ""
    voice_description: str = ""
    accent: str = "American"
    language: str = "en"

    def describe(self) -> str:
        eth = "" if self.ethnicity in ("", "unspecified") else f"{self.ethnicity} "
        return f"{self.age} {eth}{self.gender}".strip()

    def default_voice_description(self) -> str:
        return (
            self.voice_description
            or f"A friendly, natural-sounding {self.age} {self.gender} with a {self.accent} accent, "
            "conversational and warm, like talking to a friend, clear studio-quality recording."
        )


class Avatar(BaseModel):
    """A reusable 'brand face': synthetic portrait + matched synthetic voice."""

    id: str
    name: str
    spec: AvatarSpec
    portrait_file: str = "portrait.png"
    portrait_provider: str
    voice_provider: str
    voice_id: str
    created_at: str = Field(default_factory=utcnow)
    # Provider-specific metadata (e.g. mock mouth position).
    meta: dict = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", v):
            raise ValueError("avatar id must be lowercase letters, digits and dashes")
        return v


class Word(BaseModel):
    text: str
    start: float
    end: float
    segment: int


class VoiceTrack(BaseModel):
    audio_path: str
    duration: float
    words: list[Word]
    characters: int
    tempo: float = 1.0

    def segment_bounds(self, n_segments: int) -> list[tuple[float, float]]:
        """(start, end) of each script segment, contiguous and covering 0..duration."""
        starts: list[float | None] = [None] * n_segments
        for w in self.words:
            if starts[w.segment] is None:
                starts[w.segment] = w.start
        starts[0] = 0.0
        # Segments without words (shouldn't happen) inherit the previous start.
        for i in range(1, n_segments):
            if starts[i] is None:
                starts[i] = starts[i - 1]
        bounds = []
        for i in range(n_segments):
            s = starts[i]
            e = starts[i + 1] if i + 1 < n_segments else self.duration
            # Cut slightly before the next word starts so the breath lands in the previous shot.
            if i + 1 < n_segments:
                e = max(s, e - 0.05)
                starts[i + 1] = e
            bounds.append((round(s, 3), round(e, 3)))
        return bounds


class RenderOptions(BaseModel):
    captions: bool = True
    ai_label: bool = True
    ai_label_text: str = "AI-generated"
    music: bool = True
    music_prompt: str = ""
    music_volume_db: float = -20.0
    end_card_seconds: float = 2.5
    target_lufs: float = -14.0
