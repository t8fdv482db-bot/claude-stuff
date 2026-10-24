from ..config import Settings
from .base import ScriptWriter


def get_script_writer(settings: Settings) -> ScriptWriter:
    if settings.script_provider == "claude":
        from .claude import ClaudeScriptWriter

        return ClaudeScriptWriter(model=settings.claude_model)
    if settings.script_provider == "mock":
        from .mock import MockScriptWriter

        return MockScriptWriter()
    raise ValueError(f"Unknown script provider {settings.script_provider!r}")
