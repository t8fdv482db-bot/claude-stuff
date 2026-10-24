"""ElevenLabs voice provider: Voice Design for synthetic voices, v3 TTS with timestamps."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from ..config import require_key
from ..ffmpeg import duration
from ..models import AdScript, AvatarSpec, VoiceTrack
from .base import VoiceProvider, build_tts_text, words_from_alignment

PREVIEW_TEXT = (
    "Hey! Okay, so I have to tell you about something that genuinely made my mornings easier. "
    "It's simple, it's quick, and honestly, it just works. Let me show you how it fits into your day."
)


class ElevenLabsVoice(VoiceProvider):
    name = "elevenlabs"

    def __init__(self, tts_model: str = "eleven_v3"):
        from elevenlabs.client import ElevenLabs

        self.client = ElevenLabs(api_key=require_key("ELEVENLABS_API_KEY"))
        self.tts_model = tts_model
        self.design_model = os.environ.get("ADGEN_VOICE_DESIGN_MODEL", "eleven_ttv_v3")

    def design_voice(self, spec: AvatarSpec, name: str, preview_dir: Path) -> str:
        # Voice Design generates a brand-new synthetic voice from a text description.
        # Voice cloning is deliberately not supported: presenters must never sound like real people.
        description = spec.default_voice_description()
        design = self.client.text_to_voice.design(
            voice_description=description,
            model_id=self.design_model,
            text=PREVIEW_TEXT,
        )
        preview = design.previews[0]
        preview_dir.mkdir(parents=True, exist_ok=True)
        (preview_dir / "voice_preview.mp3").write_bytes(base64.b64decode(preview.audio_base_64))
        voice = self.client.text_to_voice.create(
            voice_name=f"adgen-{name}",
            voice_description=description,
            generated_voice_id=preview.generated_voice_id,
            labels={"source": "adgen", "synthetic": "true"},
        )
        return voice.voice_id

    def synthesize(self, script: AdScript, voice_id: str, language: str, out_dir: Path) -> VoiceTrack:
        with_tags = self.tts_model.startswith("eleven_v3")
        text, ranges = build_tts_text(script, with_tags=with_tags)
        kwargs = {}
        if language and language != "en":
            kwargs["language_code"] = language
        resp = self.client.text_to_speech.convert_with_timestamps(
            voice_id=voice_id,
            text=text,
            model_id=self.tts_model,
            output_format="mp3_44100_192",
            **kwargs,
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        audio_path = out_dir / "voice_raw.mp3"
        audio_path.write_bytes(base64.b64decode(resp.audio_base_64))
        al = resp.alignment
        words = words_from_alignment(
            al.characters, al.character_start_times_seconds, al.character_end_times_seconds, ranges
        )
        return VoiceTrack(audio_path=str(audio_path), duration=duration(audio_path), words=words, characters=len(text))
