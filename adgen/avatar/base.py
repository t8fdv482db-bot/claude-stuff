from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import AvatarSpec


class PortraitProvider(ABC):
    name: str

    @abstractmethod
    def generate(self, spec: AvatarSpec, out_path: Path) -> dict:
        """Write a 9:16 portrait of a synthetic presenter to out_path; return provider metadata."""


def portrait_prompt(spec: AvatarSpec) -> str:
    eth = "" if spec.ethnicity in ("", "unspecified") else f"{spec.ethnicity} "
    extra = f" {spec.extra.strip().rstrip('.')}." if spec.extra.strip() else ""
    return (
        f"Photorealistic vertical smartphone video still of a fictional, non-famous {spec.age} "
        f"{eth}{spec.gender}, an original person who does not exist, sitting and facing the camera "
        f"at eye level, framed from mid-chest up with the head in the upper third. Wearing "
        f"{spec.outfit}. Setting: {spec.setting}, softly out of focus.{extra} Relaxed friendly "
        "expression, lips gently closed, eyes looking into the lens, natural skin texture with pores "
        "and subtle imperfections, soft natural window light, authentic UGC creator look, shot on a "
        "modern phone front camera, 9:16, no text, no logos, no watermark, no hands near face."
    )
