from __future__ import annotations

from pathlib import Path

from .. import ffmpeg
from ..config import Settings
from ..models import VoiceTrack, Word
from .base import VoiceProvider

MAX_SPEEDUP = 1.15


def get_voice_provider(settings: Settings) -> VoiceProvider:
    if settings.voice_provider == "elevenlabs":
        from .elevenlabs import ElevenLabsVoice

        return ElevenLabsVoice(tts_model=settings.tts_model)
    if settings.voice_provider == "mock":
        from .mock import MockVoice

        return MockVoice()
    raise ValueError(f"Unknown voice provider {settings.voice_provider!r}")


def fit_to_length(track: VoiceTrack, max_seconds: float, out_dir: Path) -> VoiceTrack:
    """Normalise the voice to 48 kHz WAV, speeding it up slightly (<= 15%) if it runs long.

    Word timings are rescaled to match, so captions and cuts stay in sync.
    """
    tempo = 1.0
    if track.duration > max_seconds:
        tempo = min(track.duration / max_seconds, MAX_SPEEDUP)
    out = out_dir / "voice.wav"
    filters = [f"atempo={tempo:.4f}"] if tempo > 1.0 else []
    args = ["-i", track.audio_path]
    if filters:
        args += ["-af", ",".join(filters)]
    args += ["-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", out]
    ffmpeg.run(args)
    words = [
        Word(text=w.text, start=round(w.start / tempo, 3), end=round(w.end / tempo, 3), segment=w.segment)
        for w in track.words
    ]
    return VoiceTrack(
        audio_path=str(out),
        duration=ffmpeg.duration(out),
        words=words,
        characters=track.characters,
        tempo=round(tempo, 4),
    )
