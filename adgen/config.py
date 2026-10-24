"""Settings loaded from the environment / .env. API keys are never hardcoded."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    pass


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


@dataclass(frozen=True)
class Settings:
    script_provider: str = field(default_factory=lambda: _env("ADGEN_SCRIPT_PROVIDER", "claude"))
    portrait_provider: str = field(default_factory=lambda: _env("ADGEN_PORTRAIT_PROVIDER", "flux2pro"))
    voice_provider: str = field(default_factory=lambda: _env("ADGEN_VOICE_PROVIDER", "elevenlabs"))
    lipsync_provider: str = field(
        default_factory=lambda: _env("ADGEN_LIPSYNC_PROVIDER", "kling_avatar_v2_pro")
    )
    music_provider: str = field(default_factory=lambda: _env("ADGEN_MUSIC_PROVIDER", "elevenlabs"))
    claude_model: str = field(default_factory=lambda: _env("ADGEN_CLAUDE_MODEL", "claude-opus-5-5"))
    tts_model: str = field(default_factory=lambda: _env("ADGEN_TTS_MODEL", "eleven_v3"))
    output_dir: Path = field(default_factory=lambda: Path(_env("ADGEN_OUTPUT_DIR", "output")))
    avatar_dir: Path = field(default_factory=lambda: Path(_env("ADGEN_AVATAR_DIR", "avatars")))
    music_library: Path = field(
        default_factory=lambda: Path(_env("ADGEN_MUSIC_LIBRARY", "assets/music"))
    )
    cache_dir: Path = field(default_factory=lambda: Path(_env("ADGEN_CACHE_DIR", ".cache")))

    def offline(self) -> "Settings":
        """All providers swapped for free local mocks (no keys, no network)."""
        return replace(
            self,
            script_provider="mock",
            portrait_provider="mock",
            voice_provider="mock",
            lipsync_provider="mock",
            music_provider="mock",
        )

    def with_overrides(self, **kw) -> "Settings":
        return replace(self, **{k: v for k, v in kw.items() if v})

    def providers(self) -> dict[str, str]:
        return {
            "script": self.script_provider,
            "portrait": self.portrait_provider,
            "voice": self.voice_provider,
            "lipsync": self.lipsync_provider,
            "music": self.music_provider,
        }


def require_key(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            f"{name} is not set. Add it to your .env file (see .env.example), "
            "or run with --offline to use the free mock providers."
        )
    return value


_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def font_file(bold: bool = True) -> str:
    """Resolve a TTF/OTF for captions, labels and end cards."""
    explicit = os.environ.get("ADGEN_FONT_FILE")
    if explicit and Path(explicit).exists():
        return explicit
    if shutil.which("fc-match"):
        pattern = "Inter:style=ExtraBold" if bold else "Inter"
        try:
            out = subprocess.run(
                ["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True, timeout=5
            ).stdout.strip()
            if out and Path(out).exists():
                return out
        except (OSError, subprocess.SubprocessError):
            pass
    for c in _FONT_CANDIDATES:
        if Path(c).exists():
            return c
    raise ConfigError("No usable font found; set ADGEN_FONT_FILE to a .ttf/.otf file.")
