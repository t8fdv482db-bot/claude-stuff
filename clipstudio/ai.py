"""Optional AI review with the Claude API: score each candidate, tighten the cut, write a title + hook.

The API key comes from the ANTHROPIC_API_KEY env var or the Settings page. It is never logged.
"""
from __future__ import annotations

import json
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from . import db
from .media import fmt_time

# $ per million tokens (input, output). Unknown models fall back to Sonnet pricing.
PRICES = {
    "claude-sonnet-5-5": (2.0, 10.0), "claude-sonnet-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0), "claude-haiku-5-5": (0.10, 0.50), "claude-fable-5-2": (8.0, 40.0),
    "claude-opus-4-8": (5.0, 25.0), "claude-sonnet-4-6": (3.0, 15.0), "claude-haiku-4-5": (1.0, 5.0),
}
# Models that accept server-side refusal fallbacks.
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-2", "claude-fable-5-1"}

SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "start": {"type": "number"},
        "end": {"type": "number"},
        "title": {"type": "string"},
        "hook": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["score", "start", "end", "title", "hook", "reason"],
    "additionalProperties": False,
}

SYSTEM = """You are a senior Shorts editor who clips gaming/IRL livestreams (YouTube Shorts, TikTok, Reels).
You judge whether a candidate moment works as a standalone vertical Short and package it.

Scoring (1-10): a 10 stands alone with zero backstory, has a clear setup and a payoff (a reaction,
a punchline, a fail, a clutch, a reveal) inside the cut. Score low if it needs context from earlier
in the stream, if nothing actually happens, if the payoff is cut off, or if it's just loud noise.

Cut: you may tighten or shift start/end (in the same absolute seconds as the transcript), but the clip
must stay between the given min and max length, start at the beginning of a sentence and end after
the payoff/reaction finishes. If the detector's cut is already right, return it unchanged.

Title: under 70 characters, a curiosity hook that makes people want to watch, includes the streamer's
name, never claims anything that doesn't happen in the clip, no hashtags, no emojis spam (one is ok).
Hook: 2-6 words of on-screen text for the first seconds (e.g. "HE DIDN'T SEE IT COMING").
Reason: one short line explaining your score."""

_usage_lock = threading.Lock()


def api_key() -> str:
    import os
    return (os.environ.get("ANTHROPIC_API_KEY") or db.setting("anthropic_api_key") or "").strip()


def client():
    import anthropic
    return anthropic.Anthropic(api_key=api_key(), max_retries=3, timeout=90)


def model_name() -> str:
    return (db.setting("ai_model") or "claude-sonnet-5-5").strip()


def cost(model: str, inp: int, out: int) -> float:
    pin, pout = PRICES.get(model, PRICES["claude-sonnet-5-5"])
    return inp / 1e6 * pin + out / 1e6 * pout


def add_usage(job_id: int | None, inp: int, out: int, model: str) -> None:
    if not job_id:
        return
    with _usage_lock:
        j = db.get("jobs", job_id)
        if not j:
            return
        db.update("jobs", job_id, ai_input_tokens=(j["ai_input_tokens"] or 0) + inp,
                  ai_output_tokens=(j["ai_output_tokens"] or 0) + out,
                  ai_cost=round((j["ai_cost"] or 0) + cost(model, inp, out), 5))
    from .worker import bus, public_job
    bus.publish("job", public_job(db.get("jobs", job_id)))


def ask_json(prompt: str, max_tokens: int = 2000) -> tuple[dict | None, int, int, str]:
    """One structured-output call. Returns (parsed JSON or None, input tokens, output tokens, model)."""
    model = model_name()
    kwargs = dict(model=model, max_tokens=max_tokens, system=SYSTEM,
                  messages=[{"role": "user", "content": prompt}],
                  output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}})
    c = client()
    if model in FALLBACK_MODELS:
        resp = c.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    else:
        resp = c.messages.create(**kwargs)
    inp = getattr(resp.usage, "input_tokens", 0) or 0
    out = getattr(resp.usage, "output_tokens", 0) or 0
    if resp.stop_reason in ("refusal", "max_tokens"):
        return None, inp, out, model
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
    try:
        return json.loads(text), inp, out, model
    except ValueError:
        return None, inp, out, model


# ---------------------------------------------------------------- prompt pieces
def transcript_block(words: list[dict], a: float, b: float) -> str:
    lines, cur, t0 = [], [], None
    for w in words:
        if w["e"] < a or w["s"] > b:
            continue
        if t0 is None:
            t0 = w["s"]
        cur.append(w["w"])
        if w["w"].endswith((".", "?", "!")) or len(cur) >= 14:
            lines.append(f"[{t0:.1f}] {' '.join(cur)}")
            cur, t0 = [], None
    if cur:
        lines.append(f"[{t0:.1f}] {' '.join(cur)}")
    return "\n".join(lines) or "(no speech detected)"


def chat_summary(chat: list[dict], peak: float) -> str:
    burst = [m["m"] for m in chat if peak - 10 <= m["t"] <= peak + 25]
    before = [m for m in chat if peak - 70 <= m["t"] < peak - 10]
    if not burst:
        return "(no chat for this moment)"
    top = Counter(m.strip()[:60] for m in burst if m.strip()).most_common(12)
    rate_burst = len(burst) / 35
    rate_before = len(before) / 60
    return (f"{len(burst)} messages in the 35 s around the peak ({rate_burst:.1f}/s vs {rate_before:.1f}/s before).\n"
            "Top messages: " + " | ".join(f"{m} ×{n}" if n > 1 else m for m, n in top))


def build_prompt(cand: dict, *, words: list[dict], chat: list[dict], streamer: str, min_len: float,
                 max_len: float) -> str:
    a, b = cand["start"] - 45, cand["end"] + 45
    return f"""Streamer: {streamer or "unknown"}
Detector cut: start {cand['start']:.1f}, end {cand['end']:.1f} (peak at {cand['peak']:.1f}, i.e. {fmt_time(cand['peak'])} into the stream).
Allowed length: {min_len:.0f}-{max_len:.0f} seconds. Times are absolute seconds.

Transcript from {a:.0f} s to {b:.0f} s (each line starts with its time):
{transcript_block(words, a, b)}

Chat reaction:
{chat_summary(chat, cand['peak'])}

Return JSON only."""


# ---------------------------------------------------------------- validation
def clean_title(title: str, streamer: str) -> str:
    t = re.sub(r"#\w+", "", title or "").strip().strip('"').strip()
    t = re.sub(r"\s{2,}", " ", t)
    if len(t) >= 70:
        t = t[:69].rsplit(" ", 1)[0].rstrip(",.;:-") + "…"
    return t


def clean_hook(hook: str) -> str:
    words = re.sub(r"#\w+", "", hook or "").split()
    return " ".join(words[:6])


def validate(res: dict | None, cand: dict, *, min_len: float, max_len: float, duration: float,
             streamer: str) -> dict | None:
    """Apply a model answer to a candidate. Bad cuts are ignored (the detector's cut is kept)."""
    if not isinstance(res, dict):
        return None
    try:
        score = int(round(float(res.get("score"))))
    except (TypeError, ValueError):
        return None
    if not 1 <= score <= 10:
        return None
    out = dict(cand)
    out["ai_score"] = score
    try:
        s, e = float(res.get("start")), float(res.get("end"))
        ok = (0 <= s < e <= (duration or 1e12) and min_len - 0.5 <= e - s <= max_len + 0.5
              and s >= cand["start"] - 45 and e <= cand["end"] + 45 and s < cand["peak"] + 2 and e > cand["peak"] - 2)
        if ok:
            out["start"], out["end"] = round(s, 2), round(e, 2)
    except (TypeError, ValueError):
        pass
    title = clean_title(str(res.get("title") or ""), streamer)
    if title:
        out["title"] = title
    hook = clean_hook(str(res.get("hook") or ""))
    if len(hook.split()) >= 2:
        out["hook"] = hook
    out["reason"] = str(res.get("reason") or "").strip()[:200] or out.get("reason", "")
    return out


# ---------------------------------------------------------------- entry points
def review_candidates(ctx, cands: list[dict], *, words: list[dict], chat: list[dict], streamer: dict | None,
                      min_len: float, max_len: float, duration: float) -> list[dict]:
    name = (streamer or {}).get("name", "")
    min_score = int(db.setting("ai_min_score") or 6)

    def one(c: dict) -> dict | None:
        try:
            res, inp, out, model = ask_json(build_prompt(c, words=words, chat=chat, streamer=name,
                                                         min_len=min_len, max_len=max_len))
        except Exception as e:  # noqa: BLE001
            ctx.log(f"AI review failed for {fmt_time(c['peak'])}: {type(e).__name__}: {str(e)[:160]} — keeping detector cut.")
            return dict(c)
        add_usage(ctx.job_id, inp, out, model)
        v = validate(res, c, min_len=min_len, max_len=max_len, duration=duration, streamer=name)
        if v is None:
            ctx.log(f"AI answer for {fmt_time(c['peak'])} was unusable — keeping detector cut.")
            return dict(c)
        if v["ai_score"] < min_score:
            ctx.log(f"AI dropped {fmt_time(c['peak'])} ({v['ai_score']}/10): {v['reason']}")
            return None
        return v

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, cands))
    kept = [r for r in results if r]
    j = db.get("jobs", ctx.job_id) or {}
    ctx.log(f"AI kept {len(kept)} of {len(cands)} candidates. Tokens so far: {j.get('ai_input_tokens', 0)} in / "
            f"{j.get('ai_output_tokens', 0)} out ≈ ${j.get('ai_cost', 0):.3f}")
    return kept


def regenerate_title(clip: dict, words: list[dict], streamer: str) -> dict:
    """New title + hook for one clip (cut unchanged)."""
    cand = {"start": clip["start"], "end": clip["end"], "peak": clip.get("peak") or (clip["start"] + clip["end"]) / 2}
    prompt = build_prompt(cand, words=words, chat=[], streamer=streamer, min_len=clip["end"] - clip["start"],
                          max_len=clip["end"] - clip["start"])
    prompt += f"\n\nThe current title is: {clip.get('title') or '(none)'}\nWrite a different, better title. Keep start/end as given."
    res, inp, out, model = ask_json(prompt)
    add_usage(clip.get("job_id"), inp, out, model)
    if not isinstance(res, dict):
        raise RuntimeError("The AI didn't return a usable answer — try again.")
    return {"title": clean_title(str(res.get("title") or ""), streamer) or clip.get("title"),
            "hook": clean_hook(str(res.get("hook") or "")), "reason": str(res.get("reason") or "")[:200]}
