"""Offline template script writer: free, deterministic, used for tests and dry runs."""

from __future__ import annotations

from ..models import AdScript, ProductBrief, ScriptSegment, ScriptSet
from .base import ScriptWriter
from .claude import word_budget

_ANGLES = [
    ("question hook", "Okay, real question for {aud_short}.", "curious"),
    ("problem agitation", "Stop scrolling if this sounds familiar.", "serious"),
    ("direct reveal", "This is {name}, and here's why it matters.", "excited"),
]

_PROBLEMS = [
    "You want something that just works, but nothing you've tried fits into your day.",
    "Most options out there make you choose between easy and good.",
    "It's frustrating when the thing you need just doesn't keep up with you.",
]


def _sentence(s: str) -> str:
    s = s.strip().rstrip(".")
    return s[:1].upper() + s[1:] + "."


class MockScriptWriter(ScriptWriter):
    name = "mock"

    def write(self, brief: ProductBrief, n_variants: int = 3) -> ScriptSet:
        budget = word_budget(brief.length)
        aud_short = brief.target_audience.split(",")[0].split(" who ")[0].strip().lower()
        variants = []
        for i in range(n_variants):
            angle, hook, delivery = _ANGLES[i % len(_ANGLES)]
            hook = hook.format(aud_short=aud_short or "you", name=brief.name)
            problem = _PROBLEMS[i % len(_PROBLEMS)]
            points = brief.selling_points[i % len(brief.selling_points):] + brief.selling_points[: i % len(brief.selling_points)]
            cta = f"{_sentence(brief.cta)[:-1]} and see for yourself."
            solution_sentences = [f"Meet {brief.name}."]
            used = []
            fixed = len(hook.split()) + len(problem.split()) + len(cta.split())
            for p in points:
                candidate = solution_sentences + [_sentence(p)]
                if fixed + sum(len(x.split()) for x in candidate) > budget:
                    break
                solution_sentences = candidate
                used.append(p)
            if not used:
                solution_sentences.append(_sentence(points[0]))
                used.append(points[0])
            # B-roll carries most of the solution; the presenter returns for the final beat.
            mid = len(solution_sentences) if len(solution_sentences) <= 2 else len(solution_sentences) - 1
            segments = [
                ScriptSegment(role="hook", text=hook, delivery=delivery, visual="avatar"),
                ScriptSegment(role="problem", text=problem, delivery="warm", visual="avatar"),
                ScriptSegment(
                    role="solution",
                    text=" ".join(solution_sentences[:mid]),
                    delivery="confident",
                    visual="broll",
                    broll_focus=used[0],
                ),
            ]
            if solution_sentences[mid:]:
                segments.append(
                    ScriptSegment(
                        role="solution",
                        text=" ".join(solution_sentences[mid:]),
                        delivery="excited",
                        visual="avatar",
                    )
                )
            segments.append(ScriptSegment(role="cta", text=cta, delivery="excited", visual="avatar"))
            variants.append(
                AdScript(
                    variant=chr(ord("A") + i),
                    angle=angle,
                    segments=segments,
                    on_screen_cta=brief.cta,
                    claims_used=used,
                )
            )
        return ScriptSet(product=brief.name, provider="mock", variants=variants)
