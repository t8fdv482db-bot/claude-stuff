"""Synthetic presenter portraits with FLUX.2 [pro] on fal.ai."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from .. import falai
from ..models import AvatarSpec
from .base import PortraitProvider, portrait_prompt

ENDPOINT = "fal-ai/flux-2-pro"


class Flux2ProPortrait(PortraitProvider):
    name = "flux2pro"

    def generate(self, spec: AvatarSpec, out_path: Path) -> dict:
        prompt = portrait_prompt(spec)
        result = falai.run(
            ENDPOINT,
            {
                "prompt": prompt,
                "image_size": {"width": 1152, "height": 2048},
                "output_format": "png",
                "safety_tolerance": "2",
            },
        )
        raw = out_path.with_name("portrait_raw.png")
        falai.download(result["images"][0]["url"], raw)
        with Image.open(raw) as im:
            ImageOps.fit(im.convert("RGB"), (1080, 1920), Image.LANCZOS, centering=(0.5, 0.4)).save(out_path)
        raw.unlink(missing_ok=True)
        return {"prompt": prompt, "endpoint": ENDPOINT, "seed": result.get("seed")}
