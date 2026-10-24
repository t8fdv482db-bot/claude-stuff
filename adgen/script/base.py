from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import ProductBrief, ScriptSet


class ScriptWriter(ABC):
    name: str

    @abstractmethod
    def write(self, brief: ProductBrief, n_variants: int = 3) -> ScriptSet:
        """Return n script variants that pass the safety lint."""
