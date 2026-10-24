"""Static end card (logo + product + CTA) and the 16:9 'stage' behind the presenter."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from ..config import font_file

ACCENT = (255, 205, 60)


def _backdrop(size: tuple[int, int], image: Path | None, darken: float) -> Image.Image:
    w, h = size
    if image is None:
        bg = Image.new("RGB", size, (24, 26, 32))
        d = ImageDraw.Draw(bg)
        for y in range(h):
            t = y / h
            d.line([(0, y), (w, y)], fill=(int(24 + 20 * t), int(26 + 10 * t), int(32 + 30 * t)))
        return bg
    with Image.open(image) as src:
        bg = ImageOps.fit(ImageOps.exif_transpose(src).convert("RGB"), (w // 4, h // 4), Image.BILINEAR)
    bg = bg.filter(ImageFilter.GaussianBlur(10)).resize(size, Image.BILINEAR)
    return Image.blend(bg, Image.new("RGB", size, (0, 0, 0)), darken)


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_w: int, start_size: int) -> ImageFont.FreeTypeFont:
    size = start_size
    while size > 18:
        f = ImageFont.truetype(font_file(), size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 4
    return ImageFont.truetype(font_file(), size)


def render_end_card(
    size: tuple[int, int],
    product_name: str,
    cta: str,
    url: str | None,
    logo: Path | None,
    bg_image: Path | None,
    out: Path,
) -> Path:
    w, h = size
    card = _backdrop(size, bg_image, 0.62)
    d = ImageDraw.Draw(card)
    unit = min(w, h)
    y = h * (0.30 if h > w else 0.24)
    if logo and Path(logo).exists():
        with Image.open(logo) as lg:
            lg = ImageOps.contain(lg.convert("RGBA"), (int(w * 0.6), int(unit * 0.22)), Image.LANCZOS)
        card.paste(lg, (int((w - lg.width) / 2), int(y - lg.height / 2)), lg)
        y += lg.height / 2 + unit * 0.08
    else:
        f = _fit_text(d, product_name, int(w * 0.85), int(unit * 0.11))
        d.text((w / 2, y), product_name, font=f, fill=(255, 255, 255), anchor="mm")
        y += unit * 0.13
    # CTA "button"
    f = _fit_text(d, cta, int(w * 0.72), int(unit * 0.065))
    tw = d.textlength(cta, font=f)
    pad_x, pad_y = unit * 0.05, unit * 0.035
    box = [w / 2 - tw / 2 - pad_x, y, w / 2 + tw / 2 + pad_x, y + f.size + 2 * pad_y]
    d.rounded_rectangle(box, radius=int((box[3] - box[1]) / 2), fill=ACCENT)
    d.text((w / 2, (box[1] + box[3]) / 2), cta, font=f, fill=(20, 20, 20), anchor="mm")
    y = box[3] + unit * 0.06
    if url and url.lower() not in cta.lower():
        f2 = _fit_text(d, url, int(w * 0.8), int(unit * 0.042))
        d.text((w / 2, y), url, font=f2, fill=(235, 235, 235), anchor="mm")
    card.save(out)
    return out


def render_stage(size: tuple[int, int], product_name: str, image: Path | None, out: Path) -> Path:
    """16:9 background: blurred product fill with the product framed on the right.

    The 9:16 presenter is overlaid on the left third during assembly.
    """
    w, h = size
    stage = _backdrop(size, image, 0.45)
    d = ImageDraw.Draw(stage)
    right_x0 = int(w * 0.44)
    if image is not None:
        with Image.open(image) as src:
            fg = ImageOps.contain(ImageOps.exif_transpose(src).convert("RGB"), (int(w * 0.5), int(h * 0.6)), Image.LANCZOS)
        x = right_x0 + (w - right_x0 - fg.width) // 2
        y = int(h * 0.08)
        mask = Image.new("L", fg.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, fg.width - 1, fg.height - 1], radius=24, fill=255)
        stage.paste(fg, (x, y), mask)
        ty = y + fg.height + int(h * 0.07)
    else:
        ty = h // 2
    f = _fit_text(d, product_name, int(w * 0.5), int(h * 0.07))
    d.text((right_x0 + (w - right_x0) / 2, ty), product_name, font=f, fill=(255, 255, 255), anchor="mm")
    stage.save(out)
    return out
