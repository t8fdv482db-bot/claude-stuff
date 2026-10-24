"""Cost estimation before a render and cost logging after it."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .models import WORDS_PER_SECOND, AdScript, ProductBrief, utcnow

# Rough token usage for one script-writing round (3 variants) and one claims audit,
# including adaptive thinking. Used only for estimates; actuals come from API usage.
SCRIPT_TOKENS_IN, SCRIPT_TOKENS_OUT = 3_000, 6_000
AUDIT_TOKENS_IN, AUDIT_TOKENS_OUT = 2_500, 2_500
CHARS_PER_WORD = 6.0


@lru_cache(maxsize=1)
def pricing() -> dict:
    path = os.environ.get("ADGEN_PRICING_FILE") or Path(__file__).with_name("pricing.yaml")
    return yaml.safe_load(Path(path).read_text())


def claude_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = pricing()["anthropic"].get(model)
    if p is None:
        return 0.0
    return input_tokens / 1e6 * p["input"] + output_tokens / 1e6 * p["output"]


def tts_cost(provider: str, model: str, characters: int) -> float:
    if provider != "elevenlabs":
        return 0.0
    rate = pricing()["elevenlabs"]["tts_per_1k_chars"].get(model, 0.08)
    return characters / 1000 * rate


def voice_design_cost(provider: str) -> float:
    return pricing()["elevenlabs"]["voice_design_per_call"] if provider == "elevenlabs" else 0.0


def portrait_cost(provider: str) -> float:
    return pricing()["fal"]["flux2pro_per_image"] if provider == "flux2pro" else 0.0


def lipsync_cost(provider: str, seconds: float) -> float:
    return pricing()["fal"]["lipsync_per_second"].get(provider, 0.0) * seconds


def music_cost(provider: str, seconds: float) -> float:
    if provider != "elevenlabs":
        return 0.0
    return pricing()["elevenlabs"]["music_per_minute"] * seconds / 60


@dataclass
class CostLine:
    stage: str
    provider: str
    detail: str
    usd: float


@dataclass
class CostReport:
    lines: list[CostLine] = field(default_factory=list)

    def add(self, stage: str, provider: str, detail: str, usd: float) -> None:
        self.lines.append(CostLine(stage, provider, detail, round(usd, 4)))

    @property
    def total(self) -> float:
        return round(sum(l.usd for l in self.lines), 4)

    def to_dict(self) -> dict:
        return {"total_usd": self.total, "lines": [asdict(l) for l in self.lines]}


def estimate_scripts(model: str, provider: str) -> CostReport:
    r = CostReport()
    if provider == "claude":
        r.add("script", provider, f"{model}: write 3 variants", claude_cost(model, SCRIPT_TOKENS_IN, SCRIPT_TOKENS_OUT))
        r.add("script", provider, f"{model}: claims audit", claude_cost(model, AUDIT_TOKENS_IN, AUDIT_TOKENS_OUT))
    else:
        r.add("script", provider, "offline template", 0.0)
    return r


def estimate_render(
    brief: ProductBrief,
    scripts: list[AdScript],
    providers: dict[str, str],
    tts_model: str,
    *,
    new_avatar: bool = False,
    music: bool = True,
) -> CostReport:
    """Estimate the paid API spend for rendering the given script variants."""
    r = CostReport()
    if new_avatar:
        r.add("avatar", providers["portrait"], "portrait image", portrait_cost(providers["portrait"]))
        r.add("voice", providers["voice"], "voice design", voice_design_cost(providers["voice"]))
    for s in scripts:
        chars = int(len(s.full_text) + 15 * len(s.segments))  # + delivery tags
        r.add("voice", providers["voice"], f"variant {s.variant}: {chars} chars", tts_cost(providers["voice"], tts_model, chars))
        # Lip-sync is billed per output second, and only on-camera spans are animated.
        cam_seconds = min(brief.length, s.avatar_words / WORDS_PER_SECOND + 0.4 * len(s.segments))
        r.add(
            "lipsync",
            providers["lipsync"],
            f"variant {s.variant}: ~{cam_seconds:.0f}s on camera",
            lipsync_cost(providers["lipsync"], cam_seconds),
        )
    if music and providers["music"] not in ("none",):
        r.add("music", providers["music"], f"{brief.length}s bed", music_cost(providers["music"], brief.length))
    r.add("assembly", "ffmpeg", f"{len(scripts)} x {len(brief.aspect_ratios)} exports", 0.0)
    return r


def append_ledger(ledger_path: Path, entry: dict) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a") as f:
        f.write(json.dumps({"logged_at": utcnow(), **entry}) + "\n")


def read_ledger(ledger_path: Path) -> list[dict]:
    if not ledger_path.exists():
        return []
    return [json.loads(line) for line in ledger_path.read_text().splitlines() if line.strip()]
