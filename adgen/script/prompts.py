"""Prompt text and JSON schemas for the Claude script writer."""

from __future__ import annotations

import json

from ..models import ProductBrief

SYSTEM_PROMPT = """\
You are a senior direct-response copywriter who writes short-form video ad scripts \
(TikTok, Reels, Shorts, YouTube, Meta) for an AI-generated presenter who speaks to camera.

Structure every script as segments in this order: hook -> problem -> solution -> cta.
- hook: a scroll-stopping opener that lands in the first 2-3 seconds (8 words or fewer). \
Use a pattern interrupt, a bold question, or a relatable callout of the audience.
- problem: the specific pain or desire of the target audience.
- solution: the product and the user's selling points, concretely.
- cta: one clear call to action that matches the CTA the user gave.
You may split problem or solution into two segments if it helps pacing, but keep the order.

Timing: the voice-over is read at about 2.5 words per second. Hit the word budget you are \
given (within about 10%). Write for the ear: short sentences, contractions, natural rhythm. \
No emojis, hashtags, stage directions, or brackets in the spoken text. Spell numbers the way \
they should be spoken only if they appear in the brief.

Visuals: each segment has visual "avatar" (presenter on camera) or "broll" (product shots \
with the voice continuing over them). The hook and the cta must be "avatar". At least one \
problem/solution segment must be "broll". For broll segments, set broll_focus to which \
product feature or image the shot should show; otherwise leave it empty.

delivery is the emotional read for the voice actor (one word from the allowed list).

NON-NEGOTIABLE RULES
1. Use only facts and claims that appear in the brief. Do not invent statistics, \
percentages, prices, discounts, awards, ingredients, results, timelines, guarantees, \
reviews, ratings, or comparisons.
2. The presenter is an AI-generated host, not a customer. Never write lines that claim or \
imply the presenter personally used, bought, or got results from the product (no "I've been \
using", "I tried", "since I started", "my skin"). Never invent testimonials or quote other \
customers or experts. Describing the product, addressing the viewer ("you"), and expressing \
opinions about the product's described features is fine.
3. Do not mention or imitate any real person, celebrity, or brand other than the product's own.
4. Write in the requested language.

Each variant must use a genuinely different creative angle (e.g. problem-agitation, \
curiosity/question, us-vs-them, "things I wish I knew", direct offer) and a different hook \
style, so the variants are useful for A/B testing. List in claims_used every product claim \
the script makes, copied from or paraphrasing the brief."""


SEGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "role": {"type": "string", "enum": ["hook", "problem", "solution", "cta"]},
        "text": {"type": "string"},
        "delivery": {
            "type": "string",
            "enum": ["excited", "warm", "curious", "confident", "playful", "calm", "serious"],
        },
        "visual": {"type": "string", "enum": ["avatar", "broll"]},
        "broll_focus": {"type": "string"},
    },
    "required": ["role", "text", "delivery", "visual", "broll_focus"],
    "additionalProperties": False,
}

SCRIPTS_SCHEMA = {
    "type": "object",
    "properties": {
        "variants": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "angle": {"type": "string"},
                    "segments": {"type": "array", "items": SEGMENT_SCHEMA},
                    "on_screen_cta": {"type": "string"},
                    "claims_used": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["angle", "segments", "on_screen_cta", "claims_used"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["variants"],
    "additionalProperties": False,
}

AUDIT_SYSTEM_PROMPT = """\
You are a strict advertising compliance reviewer. You receive a product brief (the ONLY \
source of truth) and ad scripts. For each script, list every problem of these kinds:
- a factual claim, number, statistic, result, price, offer, award, ingredient, or comparison \
that is not supported by the brief;
- any line that claims or implies the presenter is a real customer or personally used the \
product, or any invented testimonial, review, or expert endorsement;
- any reference to a real person or celebrity.
Opinions about features that ARE in the brief ("this is so easy") are fine. Be precise and \
quote the offending words. If a script has no problems, return an empty list for it."""

AUDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "variant": {"type": "string"},
                    "problems": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["variant", "problems"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["reviews"],
    "additionalProperties": False,
}


def brief_block(brief: ProductBrief) -> str:
    data = {
        "product_name": brief.name,
        "description": brief.description,
        "target_audience": brief.target_audience,
        "key_selling_points": brief.selling_points,
        "additional_approved_claims": brief.approved_claims,
        "product_url": brief.product_url,
        "call_to_action": brief.cta,
        "product_images": [p.rsplit("/", 1)[-1] for p in brief.image_paths],
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def write_prompt(brief: ProductBrief, n_variants: int, word_budget: int, feedback: str = "") -> str:
    parts = [
        f"<brief>\n{brief_block(brief)}\n</brief>",
        f"Tone: {brief.tone}",
        f"Ad length: {brief.length} seconds (the last ~2.5s is a silent end card with logo and CTA)",
        f"Word budget for the spoken script: about {word_budget} words total",
        f"Language: {brief.language}",
        f"Write {n_variants} variants.",
    ]
    if feedback:
        parts.append(
            "A previous draft was rejected for these reasons. Fix every one of them:\n" + feedback
        )
    return "\n\n".join(parts)
