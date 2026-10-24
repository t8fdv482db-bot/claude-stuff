"""Offline portrait: a clearly-illustrated placeholder presenter (no API calls)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import font_file
from ..models import AvatarSpec
from .base import PortraitProvider

W, H = 1080, 1920
SKIN = [(241, 205, 178), (224, 172, 135), (198, 140, 100), (160, 105, 70), (115, 75, 50), (87, 58, 40)]
OUTFIT = [(52, 88, 140), (150, 60, 70), (60, 120, 90), (200, 150, 70), (90, 70, 130), (40, 40, 45)]
HAIR = [(30, 22, 18), (70, 45, 30), (120, 80, 40), (200, 170, 110), (20, 20, 20)]

# Mouth position, normalised to the image size; used by the mock lip-sync animator.
MOUTH = {"cx": 0.5, "cy": 0.448, "w": 0.105, "h": 0.03}


def _pick(seq, key: str):
    return seq[int(hashlib.md5(key.encode()).hexdigest(), 16) % len(seq)]


class MockPortrait(PortraitProvider):
    name = "mock"

    def generate(self, spec: AvatarSpec, out_path: Path) -> dict:
        key = spec.model_dump_json()
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)
        top, bottom = _pick(OUTFIT, spec.setting + "a"), _pick(OUTFIT, spec.setting + "b")
        for y in range(H):
            t = y / H
            c = tuple(int(0.55 * (a + (b - a) * t) + 0.45 * 235) for a, b in zip(top, bottom))
            d.line([(0, y), (W, y)], fill=c)
        bg = img.filter(ImageFilter.GaussianBlur(4))
        d = ImageDraw.Draw(bg)
        skin = _pick(SKIN, spec.ethnicity + spec.age)
        hair = _pick(HAIR, key)
        outfit = _pick(OUTFIT, spec.outfit)
        cx = W // 2
        # shoulders / outfit
        d.rounded_rectangle([cx - 400, 1080, cx + 400, H + 200], radius=260, fill=outfit)
        d.rectangle([cx - 70, 920, cx + 70, 1100], fill=skin)  # neck
        # hair back, head, hair front
        long_hair = spec.gender.lower() in ("woman", "female")
        if long_hair:
            d.rounded_rectangle([cx - 250, 430, cx + 250, 1150], radius=200, fill=hair)
        d.ellipse([cx - 210, 470, cx + 210, 1010], fill=skin)
        d.chord([cx - 225, 420, cx + 225, 760], 180, 360, fill=hair)
        # eyes, brows, nose
        for ex in (cx - 85, cx + 85):
            d.ellipse([ex - 32, 655, ex + 32, 695], fill=(250, 250, 250))
            d.ellipse([ex - 16, 659, ex + 16, 691], fill=(55, 40, 30))
            d.line([ex - 45, 615, ex + 40, 608], fill=hair, width=12)
        d.line([cx, 690, cx - 14, 790, cx + 8, 795], fill=tuple(int(v * 0.85) for v in skin), width=6)
        # closed mouth (the lip-sync mock opens it)
        mx, my, mw = int(MOUTH["cx"] * W), int(MOUTH["cy"] * H), int(MOUTH["w"] * W)
        d.line([mx - mw // 2, my, mx + mw // 2, my], fill=(150, 70, 70), width=8)
        f = ImageFont.truetype(font_file(), 34)
        d.text((cx, H - 90), "OFFLINE MOCK PRESENTER", fill=(255, 255, 255), font=f, anchor="mm")
        f2 = ImageFont.truetype(font_file(), 28)
        d.text((cx, H - 50), f"{spec.describe()} · {spec.outfit}", fill=(235, 235, 235), font=f2, anchor="mm")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        bg.save(out_path)
        return {"mouth": MOUTH, "skin": skin}
