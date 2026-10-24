from ..config import Settings
from .base import LipSyncProvider


def get_lipsync_provider(settings: Settings) -> LipSyncProvider:
    if settings.lipsync_provider == "mock":
        from .mock import MockLipSync

        return MockLipSync()
    from .fal import FalLipSync

    return FalLipSync(settings.lipsync_provider)
