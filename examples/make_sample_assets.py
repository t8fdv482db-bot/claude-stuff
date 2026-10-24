"""Draw placeholder product shots + logo for the fictional sample product 'Pocket Brew'.

Run: python examples/make_sample_assets.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).parent / "sample_product"
FONT = "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf"


def font(size: int):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default(size)


def bottle(draw: ImageDraw.ImageDraw, cx: int, top: int, h: int, body=(32, 44, 52), band=(230, 160, 80)):
    w = int(h * 0.36)
    # body
    draw.rounded_rectangle([cx - w // 2, top + int(h * 0.16), cx + w // 2, top + h], radius=w // 3, fill=body)
    # lid
    draw.rounded_rectangle(
        [cx - int(w * 0.38), top, cx + int(w * 0.38), top + int(h * 0.2)], radius=w // 8, fill=(18, 22, 26)
    )
    # band + label
    draw.rectangle([cx - w // 2, top + int(h * 0.5), cx + w // 2, top + int(h * 0.62)], fill=band)
    f = font(int(w * 0.16))
    draw.text((cx, top + int(h * 0.56)), "POCKET BREW", fill=(25, 25, 25), font=f, anchor="mm")
    # highlight
    draw.rounded_rectangle(
        [cx - w // 2 + int(w * 0.1), top + int(h * 0.22), cx - w // 2 + int(w * 0.18), top + int(h * 0.9)],
        radius=8,
        fill=(70, 86, 98),
    )


def scene(name: str, bg_top, bg_bottom, caption: str, extra=None, size=(1600, 1600)):
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(size[1]):
        t = y / size[1]
        d.line([(0, y), (size[0], y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(bg_top, bg_bottom)))
    shadow = Image.new("L", size, 0)
    ImageDraw.Draw(shadow).ellipse([size[0] // 2 - 260, 1330, size[0] // 2 + 260, 1420], fill=140)
    img.paste((0, 0, 0), mask=shadow.filter(ImageFilter.GaussianBlur(30)))
    d = ImageDraw.Draw(img)
    bottle(d, size[0] // 2, 260, 1120)
    if extra:
        extra(d, size)
    d.text((size[0] // 2, 120), caption, fill=(255, 255, 255), font=font(64), anchor="mm")
    img.save(OUT / name, quality=92)


def beans(d, size):
    for i, (x, y) in enumerate([(260, 1250), (330, 1300), (1250, 1280), (1330, 1230), (1200, 1340)]):
        d.ellipse([x - 34, y - 24, x + 34, y + 24], fill=(92, 56, 30))
        d.line([x - 20, y - 10, x + 20, y + 10], fill=(60, 34, 18), width=5)


def ice(d, size):
    for x, y in [(300, 1180), (1280, 1220), (1210, 1100)]:
        d.rounded_rectangle([x - 60, y - 60, x + 60, y + 60], radius=18, fill=(205, 232, 245), outline=(255, 255, 255), width=4)


def logo():
    img = Image.new("RGBA", (800, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([20, 50, 220, 250], fill=(230, 160, 80, 255))
    d.ellipse([75, 105, 165, 195], fill=(32, 44, 52, 255))
    d.text((250, 150), "Pocket Brew", fill=(255, 255, 255, 255), font=font(96), anchor="lm")
    img.save(OUT / "logo.png")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    scene("product_hero.jpg", (40, 70, 90), (210, 190, 160), "Cold brew, anywhere", beans)
    scene("product_ice.jpg", (120, 170, 200), (235, 240, 245), "Leak-proof lid", ice)
    scene("product_desk.jpg", (60, 50, 45), (180, 140, 110), "Brews overnight", beans)
    logo()
    print("wrote", sorted(p.name for p in OUT.iterdir()))
