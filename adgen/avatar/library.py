"""Saved, reusable presenters ('brand faces'): portrait + matched synthetic voice."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..config import Settings
from ..cost import CostReport, portrait_cost, voice_design_cost
from ..models import Avatar, AvatarSpec, slugify
from ..safety import check_avatar_spec


class AvatarLibrary:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, avatar_id: str) -> Path:
        return self.root / avatar_id

    def portrait_path(self, avatar: Avatar) -> Path:
        return self.path(avatar.id) / avatar.portrait_file

    def list(self) -> list[Avatar]:
        if not self.root.exists():
            return []
        out = []
        for f in sorted(self.root.glob("*/avatar.json")):
            out.append(Avatar.model_validate_json(f.read_text()))
        return out

    def get(self, avatar_id: str) -> Avatar:
        f = self.path(avatar_id) / "avatar.json"
        if not f.exists():
            known = ", ".join(a.id for a in self.list()) or "none"
            raise KeyError(f"No avatar {avatar_id!r} in {self.root} (have: {known})")
        return Avatar.model_validate_json(f.read_text())

    def save(self, avatar: Avatar) -> None:
        d = self.path(avatar.id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "avatar.json").write_text(avatar.model_dump_json(indent=2))

    def delete(self, avatar_id: str) -> None:
        self.get(avatar_id)
        shutil.rmtree(self.path(avatar_id))

    def _unique_id(self, name: str) -> str:
        base = slugify(name)[:40] or "avatar"
        candidate, i = base, 2
        while self.path(candidate).exists():
            candidate, i = f"{base}-{i}", i + 1
        return candidate

    def create(self, name: str, spec: AvatarSpec, settings: Settings) -> tuple[Avatar, CostReport]:
        """Generate a new synthetic presenter and its voice, and save it to the library."""
        from . import get_portrait_provider
        from ..voice import get_voice_provider

        check_avatar_spec(spec)
        portraits = get_portrait_provider(settings)
        voices = get_voice_provider(settings)
        avatar_id = self._unique_id(name)
        d = self.path(avatar_id)
        d.mkdir(parents=True, exist_ok=True)
        cost = CostReport()
        try:
            meta = portraits.generate(spec, d / "portrait.png")
            cost.add("avatar", portraits.name, "portrait image", portrait_cost(portraits.name))
            voice_id = voices.design_voice(spec, avatar_id, d)
            cost.add("voice", voices.name, "voice design", voice_design_cost(voices.name))
        except Exception:
            shutil.rmtree(d, ignore_errors=True)
            raise
        avatar = Avatar(
            id=avatar_id,
            name=name,
            spec=spec,
            portrait_provider=portraits.name,
            voice_provider=voices.name,
            voice_id=voice_id,
            meta=meta,
        )
        self.save(avatar)
        (d / "cost.json").write_text(json.dumps(cost.to_dict(), indent=2))
        return avatar, cost
