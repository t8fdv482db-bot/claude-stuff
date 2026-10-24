"""Image + audio -> talking video, using avatar models hosted on fal.ai."""

from __future__ import annotations

from pathlib import Path

from .. import falai, ffmpeg
from ..models import Avatar
from .base import LipSyncProvider

# provider name -> (fal endpoint, extra arguments)
MODELS: dict[str, tuple[str, dict]] = {
    "kling_avatar_v2_pro": ("fal-ai/kling-video/ai-avatar/v2/pro", {}),
    "kling_avatar_v2_standard": ("fal-ai/kling-video/ai-avatar/v2/standard", {}),
    # 1080p is limited to 30s of audio; ads are <= 30s so that's fine.
    "omnihuman_v15": ("fal-ai/bytedance/omnihuman/v1.5", {"resolution": "1080p"}),
}

PROMPT = (
    "The person talks naturally and warmly to the camera like a social media creator, with subtle "
    "natural head movement, blinking and small hand-free gestures. Camera is static."
)


class FalLipSync(LipSyncProvider):
    def __init__(self, name: str):
        if name not in MODELS:
            raise ValueError(f"Unknown fal lip-sync model {name!r}; choose from {list(MODELS)}")
        self.name = name
        self.endpoint, self.extra = MODELS[name]

    def animate(self, avatar: Avatar, portrait: Path, audio: Path, out_path: Path) -> float:
        # Upload as mp3 to keep the request small; fal accepts mp3/wav/m4a.
        mp3 = out_path.with_suffix(".upload.mp3")
        ffmpeg.run(["-i", audio, "-c:a", "libmp3lame", "-b:a", "192k", mp3])
        args = {
            "image_url": falai.upload(portrait),
            "audio_url": falai.upload(mp3),
            "prompt": PROMPT,
            **self.extra,
        }
        result = falai.run(self.endpoint, args)
        falai.download(result["video"]["url"], out_path)
        mp3.unlink(missing_ok=True)
        return float(result.get("duration") or ffmpeg.duration(out_path))
