"""Offline voice: synthesises a speech-like 'babble' with real word timings.

It is not intelligible speech; it exists so captions, lip-sync timing, ducking and
loudness normalisation can be tested end to end without API keys.
"""

from __future__ import annotations

import array
import hashlib
import math
import random
import wave
from pathlib import Path

from ..models import AdScript, AvatarSpec, VoiceTrack, Word
from .base import VoiceProvider

RATE = 24_000


def _word_seconds(word: str) -> float:
    letters = sum(c.isalnum() for c in word)
    return max(0.16, 0.052 * letters + 0.07)


class MockVoice(VoiceProvider):
    name = "mock"

    def design_voice(self, spec: AvatarSpec, name: str, preview_dir: Path) -> str:
        pitch = 120 if spec.gender.lower() in ("man", "male") else 205
        return f"mock-{pitch}"

    def synthesize(self, script: AdScript, voice_id: str, language: str, out_dir: Path) -> VoiceTrack:
        try:
            f0_base = float(voice_id.split("-")[-1])
        except ValueError:
            f0_base = 180.0
        rng = random.Random(int(hashlib.md5(script.full_text.encode()).hexdigest()[:8], 16))
        samples = array.array("h")
        words: list[Word] = []
        t = 0.0
        samples.extend([0] * int(0.15 * RATE))
        t = len(samples) / RATE
        for seg_idx, seg in enumerate(script.segments):
            tokens = seg.text.split()
            for wi, tok in enumerate(tokens):
                dur = _word_seconds(tok)
                n = int(dur * RATE)
                vowel = rng.random()
                f0 = f0_base * (1.0 + 0.08 * math.sin(wi * 1.3))
                phase = 0.0
                for i in range(n):
                    x = i / n
                    env = min(1.0, x * 12) * min(1.0, (1 - x) * 8) * (0.55 + 0.45 * math.sin(math.pi * x * 2.0) ** 2)
                    f = f0 * (1 + 0.05 * (0.5 - x))
                    phase += 2 * math.pi * f / RATE
                    v = (
                        math.sin(phase)
                        + 0.6 * math.sin(2 * phase)
                        + (0.5 + 0.4 * vowel) * math.sin(3 * phase)
                        + 0.25 * math.sin(5 * phase)
                    )
                    samples.append(int(5200 * env * v))
                words.append(Word(text=tok, start=round(t, 3), end=round(t + dur, 3), segment=seg_idx))
                gap = 0.24 if tok[-1] in ".!?" else (0.12 if tok[-1] in ",;:" else 0.055)
                samples.extend([0] * int(gap * RATE))
                t = len(samples) / RATE
            samples.extend([0] * int(0.18 * RATE))  # breath between segments
            t = len(samples) / RATE
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "voice_raw.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(samples.tobytes())
        return VoiceTrack(audio_path=str(path), duration=len(samples) / RATE, words=words, characters=len(script.full_text))
