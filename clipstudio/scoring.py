"""Find the most hype 20–60 s moments from chat, audio, transcript and viewer-clip signals.

Everything is a per-second series. Each signal is turned into a z-score against a trailing
~5-minute baseline, combined with user weights, smoothed, then peaks are picked with
non-max suppression and turned into clip windows snapped to sentence boundaries.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np

DEFAULT_TRANSCRIPT_PHRASES = [
    "oh my god", "no way", "let's go", "lets go", "what the", "holy", "bro", "dude", "yo", "nah",
    "are you serious", "are you kidding", "i can't believe", "what is happening", "oh no", "run",
    "chat", "clip", "insane", "crazy", "wtf", "shut up", "get out", "help",
]


# ---------------------------------------------------------------- helpers
def _moving_avg(x: np.ndarray, win: int) -> np.ndarray:
    if win <= 1 or len(x) == 0:
        return x.astype(np.float64)
    k = np.ones(win) / win
    return np.convolve(x, k, mode="same")


def rolling_z(x: np.ndarray, win: int = 300, clip: tuple[float, float] = (-3.0, 8.0)) -> np.ndarray:
    """z-score of each second against the trailing `win` seconds (early part uses the first window)."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    if n == 0:
        return x
    if not np.any(x):
        return np.zeros(n)
    c1 = np.concatenate([[0.0], np.cumsum(x)])
    c2 = np.concatenate([[0.0], np.cumsum(x * x)])
    t = np.arange(n)
    lo = np.maximum(0, t - win)
    hi = np.maximum(t, min(win, n))          # early seconds: baseline = the first window
    cnt = np.maximum(1, hi - lo)
    mean = (c1[hi] - c1[lo]) / cnt
    var = np.maximum(0.0, (c2[hi] - c2[lo]) / cnt - mean * mean)
    floor = max(float(np.std(x)) * 0.25, 1e-3)
    std = np.maximum(np.sqrt(var), floor)
    return np.clip((x - mean) / std, *clip)


def _token_regexes(tokens: list[str]) -> list[re.Pattern]:
    out = []
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        if re.fullmatch(r"[\w' ]+", tok):
            out.append(re.compile(r"(?<!\w)" + re.escape(tok) + r"(?!\w)", re.I))
        else:
            out.append(re.compile(re.escape(tok)))
    return out


def parse_list(text: str | list | None) -> list[str]:
    if not text:
        return []
    if isinstance(text, list):
        return [t.strip() for t in text if t and t.strip()]
    return [t.strip() for t in re.split(r"[,\n]", text) if t.strip()]


# ---------------------------------------------------------------- signals
def chat_signal(messages: list[dict], n: int, tokens: list[str], shift: float = 5.0) -> np.ndarray:
    """Messages per second (+1 per message containing a hype token), shifted back because chat reacts late."""
    out = np.zeros(n)
    pats = _token_regexes(tokens)
    for m in messages:
        t = int(math.floor(float(m["t"]) - shift))
        if 0 <= t < n:
            text = m.get("m") or ""
            out[t] += 1.0 + (1.0 if any(p.search(text) for p in pats) else 0.0)
    return _moving_avg(out, 3)


def audio_signals(rms: np.ndarray, n: int, hop: float = 0.1) -> dict[str, np.ndarray]:
    """Loudness, sudden jumps and a laughter/scream proxy (short, spiky, high-energy bursts)."""
    per = int(round(1 / hop))
    db = 20 * np.log10(np.asarray(rms, dtype=np.float64) + 1e-4)
    m = min(n, len(db) // per)
    loud = np.full(n, float(np.median(db)) if len(db) else -80.0)
    burst = np.zeros(n)
    if m == 0:
        return {"loud": loud, "jump": np.zeros(n), "burst": burst}
    frames = db[: m * per].reshape(m, per)
    # energy-domain mean so a short scream inside a second counts
    loud[:m] = 10 * np.log10(np.mean(10 ** (frames / 10), axis=1))
    base = _moving_avg(loud, 61)
    jump = np.maximum(0.0, loud - np.concatenate([[loud[0]] * 3, loud[:-3]]))
    # burst: frames well above the local baseline, inside a spiky (high-variance) 3-second window
    hi = (frames > (base[:m, None] + 8)).sum(axis=1).astype(np.float64)
    spread = frames.std(axis=1)
    burst[:m] = _moving_avg(hi, 3) * _moving_avg(spread, 3) / 10.0
    return {"loud": loud, "jump": jump, "burst": burst}


def transcript_signal(words: list[dict], n: int, phrases: list[str]) -> np.ndarray:
    """Hype phrases, exclamations and fast talking from the word-timestamped transcript."""
    out = np.zeros(n)
    if not words:
        return out
    pats = _token_regexes(phrases)
    for w in words:
        t = int(w["s"])
        if 0 <= t < n:
            out[t] += 0.3                                   # speech rate
            if w["w"].strip().endswith(("!", "?!")):
                out[t] += 1.0
    # phrases can span words: scan a sliding text of ~6 words
    for i in range(len(words)):
        t = int(words[i]["s"])
        if not 0 <= t < n:
            continue
        text = " ".join(x["w"].strip() for x in words[i:i + 6]).lower()
        first = words[i]["w"].strip().lower()
        for p in pats:
            mt = p.search(text)
            if mt and mt.start() <= len(first):           # match starts at this word
                out[t] += 2.0
    return _moving_avg(out, 3)


def clips_signal(clip_times: list[tuple[float, float]], n: int) -> np.ndarray:
    out = np.zeros(n)
    t = np.arange(n)
    for ct, wgt in clip_times:
        out += wgt * np.exp(-0.5 * ((t - ct) / 6.0) ** 2)
    return out


# ---------------------------------------------------------------- combine
@dataclass
class Signals:
    n: int
    chat: np.ndarray | None = None
    audio: dict[str, np.ndarray] | None = None
    transcript: np.ndarray | None = None
    clips: np.ndarray | None = None
    z: dict[str, np.ndarray] = field(default_factory=dict)


def combine(sig: Signals, weights: dict[str, float], baseline: int = 300) -> np.ndarray:
    parts: dict[str, np.ndarray] = {}
    if sig.chat is not None and np.any(sig.chat):
        parts["chat"] = rolling_z(sig.chat, baseline)
    if sig.audio is not None:
        a = sig.audio
        parts["audio"] = (0.55 * rolling_z(a["loud"], baseline) + 0.2 * rolling_z(a["jump"], baseline)
                          + 0.25 * rolling_z(a["burst"], baseline))
    if sig.transcript is not None and np.any(sig.transcript):
        parts["transcript"] = rolling_z(sig.transcript, baseline)
    if sig.clips is not None and np.any(sig.clips):
        parts["clips"] = np.clip(sig.clips, 0, 4)          # already a strong, sparse signal
    sig.z = parts
    total = np.zeros(sig.n)
    wsum = 0.0
    for k, v in parts.items():
        w = float(weights.get(k, 1.0))
        total += w * v
        wsum += w
    if wsum <= 0:
        return total
    return _moving_avg(total / wsum, 5)


# ---------------------------------------------------------------- moments
def sentence_bounds(words: list[dict], segments: list[dict] | None = None) -> tuple[list[float], list[float]]:
    """Possible clip starts (sentence starts) and ends (sentence ends) from Whisper output."""
    starts, ends = [], []
    for s in segments or []:
        starts.append(float(s["s"]))
        ends.append(float(s["e"]))
    for i, w in enumerate(words):
        if w["w"].strip().endswith((".", "?", "!")):
            ends.append(float(w["e"]))
            if i + 1 < len(words):
                starts.append(float(words[i + 1]["s"]))
        if i > 0 and float(w["s"]) - float(words[i - 1]["e"]) > 0.8:   # pause = boundary
            starts.append(float(w["s"]))
            ends.append(float(words[i - 1]["e"]))
    return sorted(set(starts)), sorted(set(ends))


def _snap(t: float, cands: list[float], tol: float, lo: float, hi: float) -> float:
    best = None
    for c in cands:
        if lo <= c <= hi and abs(c - t) <= tol and (best is None or abs(c - t) < abs(best - t)):
            best = c
    return best if best is not None else t


def _not_mid_word(t: float, words: list[dict], side: str) -> float:
    for w in words:
        if w["s"] < t < w["e"]:
            return float(w["s"]) - 0.15 if side == "start" else float(w["e"]) + 0.15
    return t


def make_window(peak: float, n: float, *, pre: float = 18, post: float = 8, min_len: float = 20,
                max_len: float = 60, words: list[dict] | None = None,
                bounds: tuple[list[float], list[float]] | None = None) -> tuple[float, float]:
    words = words or []
    starts, ends = bounds if bounds else sentence_bounds(words)
    start, end = peak - pre, peak + post
    start = _snap(start, starts, 4, 0, peak - 3)
    end = _snap(end, ends, 4, peak + 2, n)
    start = _not_mid_word(max(0.0, start), words, "start")
    end = _not_mid_word(min(n, end), words, "end")
    # clamp to [min_len, max_len]
    if end - start < min_len:
        need = min_len - (end - start)
        back = min(need * 0.7, start)
        start -= back
        end = min(n, end + (need - back))
        if end - start < min_len:
            start = max(0.0, end - min_len)
        s2 = _snap(start, starts, 4, max(0.0, end - max_len), start)   # only move earlier
        start = _not_mid_word(s2, words, "start")
    if end - start > max_len:
        start = end - max_len
        s2 = _snap(start, starts, 4, start, peak - 3)                   # only move later
        start = _not_mid_word(s2, words, "start")
        if end - start > max_len:
            start = end - max_len
    start = max(0.0, start)
    end = min(float(n), end)
    if end - start < min_len:          # very short source
        end = min(float(n), start + min_len)
        start = max(0.0, end - min_len)
    return round(start, 2), round(end, 2)


def pick_peaks(score: np.ndarray, count: int, min_gap: float = 90, floor: float = 0.0,
               exclude: list[float] | None = None) -> list[int]:
    order = np.argsort(-score, kind="stable")
    picked: list[int] = []
    blocked = list(exclude or [])
    for idx in order:
        if score[idx] <= floor or len(picked) >= count:
            break
        if all(abs(idx - p) >= min_gap for p in picked) and all(abs(idx - b) >= min_gap for b in blocked):
            picked.append(int(idx))
    return picked


def find_moments(sig: Signals, weights: dict[str, float], count: int, *, min_len: float = 20,
                 max_len: float = 60, min_gap: float = 90, words: list[dict] | None = None,
                 segments: list[dict] | None = None, pre: float = 18, post: float = 8,
                 score: np.ndarray | None = None) -> list[dict]:
    if score is None:
        score = combine(sig, weights)
    bounds = sentence_bounds(words or [], segments)
    out = []
    for p in pick_peaks(score, count, min_gap):
        s, e = make_window(p, sig.n, pre=pre, post=post, min_len=min_len, max_len=max_len,
                           words=words, bounds=bounds)
        out.append({"peak": float(p), "start": s, "end": e, "score": round(float(score[p]), 3),
                    "signals": {k: round(float(v[p]), 2) for k, v in sig.z.items()}})
    return out
