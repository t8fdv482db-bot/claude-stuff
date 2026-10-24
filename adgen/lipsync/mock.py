"""Offline lip-sync: opens the mock presenter's mouth in time with the audio envelope."""

from __future__ import annotations

import array
import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from .. import ffmpeg
from ..models import Avatar
from .base import LipSyncProvider

FPS = 30
RW, RH = 540, 960  # render size; upscaled to 1080x1920 by ffmpeg


def _envelope(audio: Path) -> list[float]:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(audio), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
        capture_output=True,
        check=True,
    ).stdout
    pcm = array.array("h")
    pcm.frombytes(raw[: len(raw) // 2 * 2])
    hop = 16000 // FPS
    env = []
    for i in range(0, len(pcm), hop):
        chunk = pcm[i : i + hop]
        env.append(math.sqrt(sum(s * s for s in chunk) / max(1, len(chunk))) / 32768)
    peak = max(env) if env else 1.0
    return [min(1.0, e / (peak * 0.7 + 1e-9)) for e in env]


class MockLipSync(LipSyncProvider):
    name = "mock"

    def animate(self, avatar: Avatar, portrait: Path, audio: Path, out_path: Path) -> float:
        env = _envelope(audio)
        base = Image.open(portrait).convert("RGB").resize((RW, RH), Image.LANCZOS)
        mouth = avatar.meta.get("mouth")
        proc = subprocess.Popen(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{RW}x{RH}", "-r", str(FPS), "-i", "-",
                "-i", str(audio),
                "-vf", "scale=1080:1920:flags=lanczos", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_path),
            ],
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        smooth = 0.0
        for i, e in enumerate(env):
            smooth = 0.55 * smooth + 0.45 * e
            frame = base.copy()
            if mouth:
                d = ImageDraw.Draw(frame)
                cx, cy = mouth["cx"] * RW, mouth["cy"] * RH
                w = mouth["w"] * RW * (0.85 + 0.15 * smooth)
                h = max(2.0, mouth["h"] * RH * 1.4 * smooth)
                d.ellipse([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], fill=(90, 30, 35), outline=(150, 70, 70), width=3)
            # gentle 'breathing' push-in so the shot isn't frozen
            z = 1.012 + 0.012 * math.sin(i / FPS * 0.9)
            if z > 1.0:
                zw, zh = int(RW / z), int(RH / z)
                frame = frame.crop(((RW - zw) // 2, (RH - zh) // 2, (RW - zw) // 2 + zw, (RH - zh) // 2 + zh)).resize((RW, RH))
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        if proc.wait() != 0:
            raise ffmpeg.FFmpegError(proc.stderr.read().decode(errors="replace"))
        return ffmpeg.duration(out_path)
