"""Guardrails: synthetic-only presenters, and scripts limited to user-supplied claims."""

from __future__ import annotations

import re

from .models import AdScript, AvatarSpec, ProductBrief


class SafetyError(ValueError):
    pass


# Phrases that ask for a specific real person's likeness or voice.
_LIKENESS_PATTERNS = [
    r"\blook(s|ing)?[\s-]*like\b",
    r"\blook[\s-]*alike\b",
    r"\bresembl",
    r"\bsound(s|ing)?[\s-]*like\b",
    r"\bimpersonat",
    r"\bclone\b",
    r"\bcelebrit",
    r"\bfamous\b",
    r"\b(actor|actress|singer|rapper|influencer|politician|athlete|youtuber|tiktoker)\b",
    r"\bin the style of\b",
    r"\bvoice of\b",
    r"\bdouble of\b",
]


def check_avatar_spec(spec: AvatarSpec) -> None:
    """Reject presenter specs that reference real people. Every presenter must be synthetic."""
    fields = {
        "age": spec.age,
        "gender": spec.gender,
        "ethnicity": spec.ethnicity,
        "setting": spec.setting,
        "outfit": spec.outfit,
        "extra": spec.extra,
        "voice_description": spec.voice_description,
    }
    for name, value in fields.items():
        low = value.lower()
        for pat in _LIKENESS_PATTERNS:
            if re.search(pat, low):
                raise SafetyError(
                    f"Avatar field '{name}' looks like it references a real person ({value!r}). "
                    "Presenters must be fully synthetic: describe attributes, not people."
                )
        # A run of 2+ capitalised words in a description field is usually a person's name.
        if name in ("extra", "voice_description", "outfit") and re.search(
            r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", value
        ):
            raise SafetyError(
                f"Avatar field '{name}' contains what looks like a proper name ({value!r}). "
                "Remove names; describe the look or voice generically."
            )


# Wording that frames the presenter as a real customer or invents social proof.
_TESTIMONIAL_PATTERNS = [
    r"\bi(?:'ve| have) been using\b",
    r"\bi(?:'ve| have) (?:tried|used)\b",
    r"\bi (?:used|tried|bought|ordered)\b",
    r"\bsince i (?:started|switched|began)\b",
    r"\bmy (?:results|skin|transformation)\b",
    r"\bchanged my life\b",
    r"\bas a (?:real |verified )?customer\b",
    r"\b(?:customers|users|people|everyone) (?:say|says|love|are saying|rave)\b",
    r"\b(?:reviews?|rated|stars?)\b",
    r"\b(?:best[- ]selling|#1|number one|clinically|proven|doctor[- ]recommended|dermatologist)\b",
    r"\b(?:viral|sold out)\b",
]

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?\s*%?|\b(?:percent|half|double|twice|triple)\b", re.I)


def _norm_numbers(text: str) -> set[str]:
    return {re.sub(r"\s+", "", m.group(0).lower()).replace(",", ".") for m in _NUMBER_RE.finditer(text)}


def brief_corpus(brief: ProductBrief) -> str:
    return "\n".join(
        [brief.name, brief.description, brief.target_audience, brief.cta, brief.product_url or ""]
        + brief.selling_points
        + brief.approved_claims
    )


def lint_script(script: AdScript, brief: ProductBrief) -> list[str]:
    """Deterministic checks. Returns a list of problems (empty == pass)."""
    problems: list[str] = []
    corpus = brief_corpus(brief)
    corpus_low = corpus.lower()
    allowed_numbers = _norm_numbers(corpus)
    for seg in script.segments:
        low = seg.text.lower()
        for pat in _TESTIMONIAL_PATTERNS:
            m = re.search(pat, low)
            if m and m.group(0) not in corpus_low:
                problems.append(
                    f"[{seg.role}] '{m.group(0)}' implies personal use, testimonials or unsupported "
                    "social proof - present the product, don't claim to be a customer."
                )
        for num in _norm_numbers(seg.text) - allowed_numbers:
            problems.append(f"[{seg.role}] number/stat '{num}' does not appear in the brief.")
    on_screen = _norm_numbers(script.on_screen_cta) - allowed_numbers
    for num in on_screen:
        problems.append(f"[end card] number '{num}' does not appear in the brief.")
    roles = [s.role for s in script.segments]
    if not roles or roles[0] != "hook":
        problems.append("Script must open with a hook segment.")
    if "cta" not in roles:
        problems.append("Script must end with a call to action.")
    return problems


def check_timing(script: AdScript, brief: ProductBrief, end_card_seconds: float) -> list[str]:
    """Word budget: voice must fit in length minus the end card, at ~2.5 words/sec."""
    budget = int((brief.length - end_card_seconds * 0.6) * 2.5)
    problems = []
    if script.word_count > budget * 1.12:
        problems.append(f"Script is {script.word_count} words; budget for {brief.length}s is ~{budget}.")
    if script.word_count < budget * 0.6:
        problems.append(f"Script is only {script.word_count} words; aim for ~{budget}.")
    hook = script.segments[0] if script.segments else None
    if hook and hook.word_count > 9:
        problems.append(f"Hook is {hook.word_count} words; keep it under ~3 seconds (<= 8 words).")
    return problems
