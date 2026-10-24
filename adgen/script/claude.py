"""Script writer backed by the Claude API (structured JSON output + a compliance audit pass)."""

from __future__ import annotations

import json
import logging

import anthropic

from ..config import require_key
from ..cost import claude_cost
from ..models import AdScript, ProductBrief, ScriptSegment, ScriptSet
from ..safety import check_timing, lint_script
from . import prompts
from .base import ScriptWriter

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_REVISION_ROUNDS = 2
END_CARD_SECONDS = 2.5


class ScriptRejected(RuntimeError):
    def __init__(self, problems: dict[str, list[str]]):
        self.problems = problems
        lines = [f"{v}: {p}" for v, ps in problems.items() for p in ps]
        super().__init__("Scripts failed compliance checks after revisions:\n" + "\n".join(lines))


def word_budget(length: int) -> int:
    return round((length - END_CARD_SECONDS * 0.6) * 2.5)


class ClaudeScriptWriter(ScriptWriter):
    name = "claude"

    def __init__(self, model: str = "claude-opus-5-5", client: anthropic.Anthropic | None = None):
        self.model = model
        if client is None:
            require_key("ANTHROPIC_API_KEY")
            client = anthropic.Anthropic()
        self.client = client
        self.cost = 0.0

    # -- API ---------------------------------------------------------------
    def _call(self, system: str, user: str, schema: dict, effort: str) -> dict:
        resp = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        usage = resp.usage
        self.cost += claude_cost(resp.model or self.model, usage.input_tokens, usage.output_tokens)
        if resp.stop_reason == "refusal":
            raise RuntimeError("Claude declined to write this ad. Review the brief for policy issues.")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("Script response was truncated (max_tokens); try again.")
        texts = [b.text for b in resp.content if b.type == "text"]
        if not texts:
            raise RuntimeError("Claude returned no text content.")
        return json.loads(texts[-1])

    def _draft(self, brief: ProductBrief, n: int, feedback: str = "") -> list[AdScript]:
        data = self._call(
            prompts.SYSTEM_PROMPT,
            prompts.write_prompt(brief, n, word_budget(brief.length), feedback),
            prompts.SCRIPTS_SCHEMA,
            effort="high",
        )
        out = []
        for v in data["variants"][:n]:
            out.append(
                AdScript(
                    variant="?",
                    angle=v["angle"],
                    segments=[ScriptSegment(**s) for s in v["segments"]],
                    on_screen_cta=v["on_screen_cta"],
                    claims_used=v["claims_used"],
                )
            )
        return out

    def _audit(self, brief: ProductBrief, scripts: list[AdScript]) -> dict[str, list[str]]:
        payload = {
            "scripts": [
                {
                    "variant": s.variant,
                    "segments": [seg.text for seg in s.segments],
                    "on_screen_cta": s.on_screen_cta,
                }
                for s in scripts
            ]
        }
        user = f"<brief>\n{prompts.brief_block(brief)}\n</brief>\n\n<scripts>\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n</scripts>"
        data = self._call(prompts.AUDIT_SYSTEM_PROMPT, user, prompts.AUDIT_SCHEMA, effort="medium")
        return {r["variant"]: r["problems"] for r in data["reviews"]}

    def _problems(self, brief: ProductBrief, scripts: list[AdScript]) -> dict[str, list[str]]:
        problems = {s.variant: lint_script(s, brief) + check_timing(s, brief, END_CARD_SECONDS) for s in scripts}
        for variant, items in self._audit(brief, scripts).items():
            if variant in problems:
                problems[variant].extend(items)
        return {v: p for v, p in problems.items() if p}

    # -- public --------------------------------------------------------------
    def write(self, brief: ProductBrief, n_variants: int = 3) -> ScriptSet:
        self.cost = 0.0
        letters = [chr(ord("A") + i) for i in range(n_variants)]
        scripts = self._draft(brief, n_variants)
        if len(scripts) < n_variants:
            raise RuntimeError(f"Expected {n_variants} variants, got {len(scripts)}")
        for letter, s in zip(letters, scripts):
            s.variant = letter

        problems = self._problems(brief, scripts)
        for round_no in range(MAX_REVISION_ROUNDS):
            if not problems:
                break
            log.info("Revision round %d for variants %s", round_no + 1, list(problems))
            for variant, items in problems.items():
                old = next(s for s in scripts if s.variant == variant)
                feedback = f"Rejected draft (angle: {old.angle}):\n{old.full_text}\nProblems:\n- " + "\n- ".join(items)
                (new,) = self._draft(brief, 1, feedback)
                new.variant = variant
                scripts[scripts.index(old)] = new
            problems = self._problems(brief, [s for s in scripts if s.variant in problems])
        if problems:
            raise ScriptRejected(problems)
        return ScriptSet(product=brief.name, provider=f"claude:{self.model}", variants=scripts, cost_usd=round(self.cost, 4))
