from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import Avatar


class LipSyncProvider(ABC):
    name: str

    @abstractmethod
    def animate(self, avatar: Avatar, portrait: Path, audio: Path, out_path: Path) -> float:
        """Render a talking-head video of the avatar speaking `audio`. Returns billed seconds."""
