"""Synthetic test media: a 6-minute testsrc2 video with loud spikes, a fake chat file and a fake transcript."""
from __future__ import annotations

import json
import random
import subprocess
from pathlib import Path

DURATION = 360
SPIKES = [75, 180, 290]   # seconds where the "hype" happens


def make_video(path: Path, duration: int = DURATION, spikes: list[int] = SPIKES) -> Path:
    burst = "+".join(f"between(t,{t},{t + 3})" for t in spikes)
    expr = (f"(0.04+0.015*sin(2*PI*0.07*t))*sin(2*PI*440*t)*(1+18*({burst}))"
            f"+0.01*sin(2*PI*3*t)*sin(2*PI*220*t)")
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error",
                    "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={duration}",
                    "-f", "lavfi", "-i", f"aevalsrc=exprs='{expr}':s=44100:d={duration}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-g", "60",
                    "-c:a", "aac", "-b:a", "96k", "-shortest", str(path)], check=True)
    return path


def make_chat(path: Path, duration: int = DURATION, spikes: list[int] = SPIKES, seed: int = 1) -> Path:
    rnd = random.Random(seed)
    msgs = []
    t = 0.0
    while t < duration:
        t += rnd.expovariate(0.6)
        msgs.append({"t": round(t, 2), "m": rnd.choice(["hi", "lol", "gg", "what game is this", "nice"])})
    for s in spikes:
        for _ in range(70):   # chat reacts 3–12 s after the moment
            msgs.append({"t": round(s + rnd.uniform(3, 12), 2), "m": rnd.choice(["KEKW", "LMAO 💀", "no way", "clip it", "W"])})
    msgs.sort(key=lambda m: m["t"])
    path.write_text("\n".join(json.dumps(m) for m in msgs) + "\n", encoding="utf-8")
    return path


def fake_words(start: float, end: float, spikes: list[int] = SPIKES) -> dict:
    """Plausible word timestamps: calm talk with sentence ends, excited phrases at the spikes."""
    words, segs = [], []
    t = start
    sent_start, n_in_sent = t, 0
    while t < end - 0.5:
        hot = any(s <= t < s + 4 for s in spikes)
        w = {"s": round(t, 2), "e": round(t + 0.35, 2), "w": "NO" if hot else "word"}
        n_in_sent += 1
        if hot:
            w["w"] = ["no", "way!", "oh", "my", "god!"][n_in_sent % 5]
        if n_in_sent >= 10:
            w["w"] += "."
        words.append(w)
        if w["w"].endswith((".", "!")) and n_in_sent >= 5:
            segs.append({"s": round(sent_start, 2), "e": w["e"], "text": " ".join(x["w"] for x in words[-n_in_sent:])})
            t += 0.9
            sent_start, n_in_sent = t, 0
        else:
            t += 0.45
    return {"words": words, "segments": segs}
