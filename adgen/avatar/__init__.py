from ..config import Settings
from .base import PortraitProvider


def get_portrait_provider(settings: Settings) -> PortraitProvider:
    if settings.portrait_provider == "flux2pro":
        from .flux import Flux2ProPortrait

        return Flux2ProPortrait()
    if settings.portrait_provider == "mock":
        from .mock import MockPortrait

        return MockPortrait()
    raise ValueError(f"Unknown portrait provider {settings.portrait_provider!r}")
