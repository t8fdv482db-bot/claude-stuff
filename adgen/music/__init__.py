"""Background music providers. Every provider returns a file at least `seconds` long."""

from __future__ import annotations

import array
import math
import random
import wave
from abc import ABC, abstractmethod
from pathlib import Path

from .. import ffmpeg
from ..config import Settings, require_key


class MusicProvider(ABC):
    name: str

    @abstractmethod
    def generate(self, prompt: str, seconds: float, out_path: Path) -> Path:
        """Write an instrumental bed of >= `seconds` to out_path (any audio format)."""


def default_music_prompt(tone: str) -> str:
    t = tone.lower()
    if "fun" in t or "playful" in t or "comed" in t:
        style = "playful, bouncy, quirky pizzicato and ukulele, light percussion"
    elif "polish" in t or "premium" in t or "luxury" in t or "corporate" in t:
        style = "sleek, confident modern electronic with soft synth pads and tight drums"
    elif "calm" in t or "wellness" in t:
        style = "calm, airy ambient pads with soft piano"
    else:
        style = "upbeat, warm lo-fi pop with mellow keys and a light groove"
    return (
        f"Instrumental background music for a short social media ad: {style}. "
        "No vocals. Steady energy, sits quietly under a voice-over, clean ending."
    )


class ElevenLabsMusic(MusicProvider):
    name = "elevenlabs"

    def generate(self, prompt: str, seconds: float, out_path: Path) -> Path:
        from elevenlabs.client import ElevenLabs

        client = ElevenLabs(api_key=require_key("ELEVENLABS_API_KEY"))
        audio = client.music.compose(
            prompt=prompt,
            music_length_ms=int(max(10.0, seconds) * 1000),
            force_instrumental=True,
        )
        out_path = out_path.with_suffix(".mp3")
        with out_path.open("wb") as f:
            for chunk in audio:
                f.write(chunk)
        return out_path


class LibraryMusic(MusicProvider):
    """Pick a track you own/licensed from a local folder and loop it to length."""

    name = "library"

    def __init__(self, folder: Path, tone: str = ""):
        self.folder = Path(folder)
        self.tone = tone

    def generate(self, prompt: str, seconds: float, out_path: Path) -> Path:
        tracks = sorted(p for p in self.folder.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".flac", ".ogg"))
        if not tracks:
            raise FileNotFoundError(f"No music files in {self.folder}. Add licensed tracks or use another provider.")
        words = {w for w in self.tone.lower().split() if len(w) > 2}
        matching = [t for t in tracks if words & set(t.stem.lower().replace("_", " ").replace("-", " ").split())]
        track = random.Random(prompt).choice(matching or tracks)
        out_path = out_path.with_suffix(".wav")
        ffmpeg.run(["-stream_loop", "-1", "-i", track, "-t", f"{seconds:.3f}", "-ar", "48000", "-ac", "2", out_path])
        return out_path


class MockMusic(MusicProvider):
    """Offline synth pad + pluck loop (I–V–vi–IV) so ducking and mixing can be tested."""

    name = "mock"
    RATE = 22050

    def generate(self, prompt: str, seconds: float, out_path: Path) -> Path:
        chords = [(261.6, 329.6, 392.0), (196.0, 246.9, 293.7), (220.0, 261.6, 329.6), (174.6, 220.0, 261.6)]
        bar = 2.0
        n = int(seconds * self.RATE)
        buf = array.array("h")
        for i in range(n):
            t = i / self.RATE
            chord = chords[int(t / bar) % 4]
            tb = t % bar
            pad = sum(math.sin(2 * math.pi * f * t) for f in chord) / 3
            beat = t % 0.5
            pluck_f = chord[int(t / 0.5) % 3] * 2
            pluck = math.sin(2 * math.pi * pluck_f * t) * math.exp(-beat * 9)
            kick = math.sin(2 * math.pi * (55 + 90 * math.exp(-beat * 30)) * beat) * math.exp(-beat * 12) if int(t / 0.5) % 2 == 0 else 0.0
            swell = min(1.0, tb * 4) * 0.8 + 0.2
            buf.append(int(7000 * (0.5 * pad * swell + 0.35 * pluck + 0.6 * kick)))
        out_path = out_path.with_suffix(".wav")
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.RATE)
            w.writeframes(buf.tobytes())
        return out_path


def get_music_provider(settings: Settings, tone: str = "") -> MusicProvider | None:
    p = settings.music_provider
    if p == "none":
        return None
    if p == "elevenlabs":
        return ElevenLabsMusic()
    if p == "library":
        return LibraryMusic(settings.music_library, tone)
    if p == "mock":
        return MockMusic()
    raise ValueError(f"Unknown music provider {p!r}")
