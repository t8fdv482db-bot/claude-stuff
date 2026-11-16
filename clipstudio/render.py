"""Vertical 1080×1920 rendering: layouts, word-by-word ASS captions, hook/disclosure text, thumbnail + GIF.

ffmpeg always runs with cwd = the clip folder and a *relative* `captions.ass`, which avoids the
Windows drive-letter escaping problems of the subtitles/ass filters.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

from .media import has_audio, run

W, H = 1080, 1920
TOP_FRAC = 0.38
TOP_H = int(round(H * TOP_FRAC / 2) * 2)   # 730
LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"


# ---------------------------------------------------------------- ASS captions
def ass_color(hex_color: str, alpha: int = 0) -> str:
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _clean(word: str) -> str:
    w = word.strip().upper()
    w = re.sub(r"^[\"'“”‘’(\[]+|[\"'“”‘’)\],.;:]+$", "", w)
    return w.replace("\\", "").replace("{", "(").replace("}", ")")


def group_words(words: list[dict], per_line: int = 3) -> list[list[dict]]:
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        if cur and (len(cur) >= per_line or w["s"] - cur[-1]["e"] > 0.7
                    or cur[-1]["w"].strip().endswith((".", "?", "!"))):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def caption_events(words: list[dict], clip_start: float, clip_end: float, per_line: int = 3) -> list[dict]:
    """One event per spoken word: the whole 2–3 word line, with the current word highlighted.

    Events never overlap: each ends where the next begins (or shortly after the last word).
    """
    dur = clip_end - clip_start
    rel = []
    for w in words:
        s, e = w["s"] - clip_start, w["e"] - clip_start
        if e <= 0 or s >= dur or not _clean(w["w"]):
            continue
        rel.append({"s": max(0.0, s), "e": min(dur, max(e, s + 0.05)), "w": w["w"]})
    rel.sort(key=lambda w: w["s"])
    events: list[dict] = []
    groups = group_words(rel, per_line)
    for gi, g in enumerate(groups):
        nxt = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else dur
        for i, w in enumerate(g):
            start = w["s"]
            end = g[i + 1]["s"] if i + 1 < len(g) else min(w["e"] + 0.4, nxt)
            if events and start < events[-1]["end"]:
                start = events[-1]["end"]
            end = min(end, dur)
            if end - start < 0.02:
                continue
            events.append({"start": start, "end": end, "words": [_clean(x["w"]) for x in g], "hi": i})
    return events


def _wrap(text: str, width: int = 22) -> str:
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    return r"\N".join(lines)


def build_ass(words: list[dict], clip_start: float, clip_end: float, *, style: dict, caption_y: int,
              hook: str = "", hook_seconds: float = 3.0, disclosure: str = "",
              disclosure_seconds: float = 3.0) -> str:
    font = style.get("caption_font") or "Arial"
    size = int(style.get("caption_size") or 84)
    base = ass_color(style.get("caption_color") or "#FFFFFF")
    hi = ass_color(style.get("caption_highlight") or "#FFE600")
    per = int(style.get("caption_words") or 3)
    per = max(1, min(4, per))
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{size},{base},{base},&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,{max(4, size // 12)},2,5,40,40,0,1
Style: Hook,{font},64,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,16,0,8,80,80,150,1
Style: Disclosure,{font},34,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,3,1,7,36,36,36,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for ev in caption_events(words, clip_start, clip_end, per):
        parts = []
        for i, w in enumerate(ev["words"]):
            parts.append(f"{{\\1c{hi}&}}{w}{{\\1c{base}&}}" if i == ev["hi"] else w)
        text = f"{{\\an5\\pos({W // 2},{caption_y})}}" + " ".join(parts)
        lines.append(f"Dialogue: 0,{ass_time(ev['start'])},{ass_time(ev['end'])},Caption,,0,0,0,,{text}")
    dur = clip_end - clip_start
    if hook.strip():
        h = _clean_text(hook)
        lines.append(f"Dialogue: 1,{ass_time(0)},{ass_time(min(hook_seconds, dur))},Hook,,0,0,0,,{_wrap(h)}")
    if disclosure.strip():
        d = _clean_text(disclosure)
        lines.append(f"Dialogue: 2,{ass_time(0)},{ass_time(min(disclosure_seconds, dur))},Disclosure,,0,0,0,,"
                     f"{_wrap(d, 40)}")
    return head + "\n".join(lines) + "\n"


def _clean_text(s: str) -> str:
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


# ---------------------------------------------------------------- layouts
def caption_y(layout: str) -> int:
    return TOP_H if layout == "split" else int(H * 0.70)


def filter_graph(layout: str, facecam: dict | None, subs: str | None = "captions.ass") -> str:
    tail = f",fps=30,ass={subs}" if subs else ",fps=30"
    if layout == "split" and facecam:
        x, y, w, h = (float(facecam[k]) for k in ("x", "y", "w", "h"))
        bot_h = H - TOP_H
        return (
            "[0:v]split=2[a][b];"
            f"[a]crop=iw*{w:.4f}:ih*{h:.4f}:iw*{x:.4f}:ih*{y:.4f},"
            f"scale={W}:{TOP_H}:force_original_aspect_ratio=increase,crop={W}:{TOP_H},setsar=1[top];"
            f"[b]crop=w='min(iw,ih*{W}/{bot_h})':h='min(ih,iw*{bot_h}/{W})',"
            f"scale={W}:{bot_h},setsar=1[bot];"
            f"[top][bot]vstack=inputs=2{tail}[v]"
        )
    if layout == "center":
        return (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1{tail}[v]")
    # blur (default / fallback)
    return (
        "[0:v]split=2[a][b];"
        f"[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=10:2,"
        f"eq=brightness=-0.18,scale={W}:{H},setsar=1[bg];"
        f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease,setsar=1[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2{tail}[v]"
    )


def render_video(src: Path, src_offset: float, start: float, end: float, out_dir: Path, *, layout: str,
                 facecam: dict | None, ass_text: str, cancel: threading.Event | None = None,
                 peak: float | None = None) -> dict[str, Path]:
    """Render clip.mp4 + thumb.jpg + preview.gif into out_dir. Returns their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "captions.ass").write_text(ass_text, encoding="utf-8")
    if layout == "split" and not facecam:
        layout = "blur"
    dur = end - start
    tmp = out_dir / "clip.tmp.mp4"
    args = ["ffmpeg", "-nostdin", "-y", "-v", "error",
            "-ss", f"{max(0.0, start - src_offset):.3f}", "-i", str(Path(src).resolve()),
            "-t", f"{dur:.3f}", "-filter_complex", filter_graph(layout, facecam), "-map", "[v]"]
    if has_audio(src):
        args += ["-map", "0:a:0", "-af", LOUDNORM, "-ar", "48000", "-c:a", "aac", "-b:a", "160k"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", "-f", "mp4", tmp.name]
    run(args, cwd=out_dir, cancel=cancel)
    video = out_dir / "clip.mp4"
    tmp.replace(video)
    t_peak = (peak - start) if peak is not None else dur / 2
    t_peak = min(max(0.5, t_peak), max(0.5, dur - 0.5))
    thumb = out_dir / "thumb.jpg"
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{t_peak:.2f}", "-i", video.name,
         "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "3", thumb.name], cwd=out_dir, cancel=cancel)
    gif = out_dir / "preview.gif"
    g0 = max(0.0, min(t_peak - 1.5, dur - 3))
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{g0:.2f}", "-t", "3", "-i", video.name,
         "-filter_complex", "fps=10,scale=240:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];"
         "[b][p]paletteuse=dither=bayer", "-loop", "0", gif.name], cwd=out_dir, cancel=cancel)
    return {"video": video, "thumb": thumb, "gif": gif}
