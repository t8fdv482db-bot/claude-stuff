"""Word-by-word 'TikTok style' captions as an ASS subtitle file (burned in by libass)."""

from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

from ..models import Word

HIGHLIGHT = "&H0000E1FF&"  # ASS colours are &HAABBGGRR -> warm yellow
BASE = "&H00FFFFFF&"

# Per aspect ratio: font size and bottom margin (keeps clear of platform UI at the bottom).
LAYOUT = {
    (1080, 1920): (84, 560),
    (1080, 1080): (66, 150),
    (1920, 1080): (70, 110),
}


def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _clean(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").upper()


def group_words(words: list[Word], max_words: int = 3, max_span: float = 1.3) -> list[list[Word]]:
    """Short caption 'pages': break on sentence ends, segment changes, size and duration."""
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur and (
            len(cur) >= max_words
            or w.segment != cur[-1].segment
            or cur[-1].text[-1] in ".!?"
            or w.end - cur[0].start > max_span
        ):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def build_ass(words: list[Word], size: tuple[int, int], font_path: str, end_time: float) -> str:
    w, h = size
    font_size, margin_v = LAYOUT.get(size, (int(h * 0.045), int(h * 0.12)))
    family = ImageFont.truetype(font_path, 10).getname()[0]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,{family},{font_size},{BASE},{BASE},&H00000000&,&H64000000&,-1,0,0,0,100,100,0,0,1,{max(4, font_size // 12)},3,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    groups = group_words(words)
    for gi, group in enumerate(groups):
        next_start = groups[gi + 1][0].start if gi + 1 < len(groups) else end_time
        group_end = min(group[-1].end + 0.3, next_start)
        for wi, word in enumerate(group):
            start = word.start
            end = group[wi + 1].start if wi + 1 < len(group) else group_end
            if end <= start:
                continue
            parts = []
            for j, other in enumerate(group):
                txt = _clean(other.text)
                if j == wi:
                    parts.append(f"{{\\c{HIGHLIGHT}\\fscx112\\fscy112}}{txt}{{\\r}}")
                else:
                    parts.append(txt)
            # Pop-in on the first word of each page.
            anim = "{\\fad(60,0)}" if wi == 0 else ""
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Word,,0,0,0,,{anim}{' '.join(parts)}")
    return header + "\n".join(lines) + "\n"


def write_ass(words: list[Word], size: tuple[int, int], font_path: str, end_time: float, out: Path) -> Path:
    out.write_text(build_ass(words, size, font_path, end_time), encoding="utf-8")
    return out
