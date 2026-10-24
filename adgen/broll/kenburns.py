"""Product B-roll from still images: framed product over a blurred fill, with slow camera motion."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .. import ffmpeg
from ..config import font_file

FPS = 30


def compose_still(image: Path | None, size: tuple[int, int], fallback_text: str, out: Path) -> Path:
    """Product image 'contained' in the frame over a blurred, darkened 'cover' of itself."""
    w, h = size
    if image is None:
        canvas = Image.new("RGB", size, (28, 30, 36))
        d = ImageDraw.Draw(canvas)
        f = ImageFont.truetype(font_file(), int(min(w, h) * 0.09))
        d.text((w / 2, h / 2), fallback_text, fill=(255, 255, 255), font=f, anchor="mm")
        canvas.save(out)
        return out
    with Image.open(image) as src:
        src = ImageOps.exif_transpose(src).convert("RGB")
        bg = ImageOps.fit(src, (w // 4, h // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(12))
        bg = bg.resize(size, Image.BILINEAR)
        bg = Image.blend(bg, Image.new("RGB", size, (0, 0, 0)), 0.35)
        fg = ImageOps.contain(src, (int(w * 0.92), int(h * 0.80)), Image.LANCZOS)
        shadow = Image.new("L", size, 0)
        x, y = (w - fg.width) // 2, (h - fg.height) // 2
        ImageDraw.Draw(shadow).rounded_rectangle([x + 10, y + 24, x + fg.width + 10, y + fg.height + 24], radius=28, fill=150)
        bg.paste((0, 0, 0), mask=shadow.filter(ImageFilter.GaussianBlur(28)))
        mask = Image.new("L", fg.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, fg.width - 1, fg.height - 1], radius=28, fill=255)
        bg.paste(fg, (x, y), mask)
    bg.save(out)
    return out


_MOTIONS = [
    # (zoom expression, x expression, y expression) — push in, pull out, drift right, drift left
    ("1+0.10*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    ("1.10-0.10*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    ("1.08", "(iw-iw/zoom)*on/{n}", "ih/2-(ih/zoom/2)"),
    ("1.08", "(iw-iw/zoom)*(1-on/{n})", "ih/2-(ih/zoom/2)"),
]


def make_clip(still: Path, frames: int, size: tuple[int, int], out: Path, motion: int = 0) -> Path:
    w, h = size
    z, x, y = (expr.format(n=max(frames - 1, 1)) for expr in _MOTIONS[motion % len(_MOTIONS)])
    # Upscale before zoompan so sub-pixel motion doesn't jitter.
    vf = (
        f"scale={w * 2}:{h * 2}:flags=bicubic,"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={FPS},"
        "format=yuv420p"
    )
    ffmpeg.run(
        ["-i", still, "-vf", vf, "-frames:v", frames, "-r", FPS, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an", out]
    )
    return out


def pick_image(images: list[Path], focus: str, index: int) -> Path | None:
    """Prefer an image whose filename shares a word with the shot's focus; else rotate."""
    if not images:
        return None
    words = {w for w in focus.lower().replace("-", " ").split() if len(w) > 3}
    for img in images:
        stem = set(img.stem.lower().replace("_", " ").replace("-", " ").split())
        if words & stem:
            return img
    return images[index % len(images)]
