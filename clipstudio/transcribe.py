"""faster-whisper with word timestamps, chunked and cached on disk so re-runs (and crashes) cost nothing."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable

from . import db
from .media import Cancelled, extract_wav

CHUNK = 600.0  # seconds per cached chunk

_model = None
_model_key: tuple | None = None
_model_lock = threading.Lock()
_run_lock = threading.Lock()   # one transcription at a time; whisper already uses every core


def pick_device(pref: str = "auto") -> tuple[str, str]:
    if pref == "cpu":
        return "cpu", "int8"
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:  # noqa: BLE001
        pass
    if pref == "cuda":
        return "cuda", "float16"
    return "cpu", "int8"


def model(log: Callable[[str], None] | None = None):
    global _model, _model_key
    name = db.setting("whisper_model") or "small.en"
    device, ctype = pick_device(db.setting("whisper_device") or "auto")
    key = (name, device, ctype)
    with _model_lock:
        if _model is None or _model_key != key:
            from faster_whisper import WhisperModel
            if log:
                log(f"Loading Whisper '{name}' on {device.upper()} (first time downloads the model)…")
            try:
                _model = WhisperModel(name, device=device, compute_type=ctype)
            except Exception as e:  # noqa: BLE001 - e.g. CUDA present but cuDNN missing
                if device == "cpu":
                    raise
                if log:
                    log(f"GPU Whisper failed ({str(e)[:120]}); falling back to CPU.")
                _model = WhisperModel(name, device="cpu", compute_type="int8")
                key = (name, "cpu", "int8")
            _model_key = key
        return _model


def transcribe_wav(wav: Path, offset: float, log=None, cancel: threading.Event | None = None) -> dict:
    m = model(log)
    words, segs = [], []
    with _run_lock:
        segments, _info = m.transcribe(str(wav), word_timestamps=True, vad_filter=True, beam_size=1,
                                       condition_on_previous_text=False)
        for seg in segments:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            segs.append({"s": round(seg.start + offset, 2), "e": round(seg.end + offset, 2),
                         "text": seg.text.strip()})
            for w in seg.words or []:
                words.append({"s": round(w.start + offset, 2), "e": round(w.end + offset, 2), "w": w.word.strip()})
    return {"words": words, "segments": segs}


def merge_ranges(ranges: list[tuple[float, float]], total: float) -> list[tuple[float, float]]:
    rs = sorted((max(0.0, a), min(total, b)) for a, b in ranges if b > a)
    out: list[list[float]] = []
    for a, b in rs:
        if out and a <= out[-1][1] + 5:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def chunks_for(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out = []
    for a, b in ranges:
        t = a
        while t < b - 0.5:
            out.append((t, min(b, t + CHUNK)))
            t += CHUNK
    return out


def transcribe(audio: Path, cache_dir: Path, ranges: list[tuple[float, float]], *, log=None,
               cancel: threading.Event | None = None, progress: Callable[[float], None] | None = None) -> dict:
    """Transcribe the given time ranges of `audio`, reusing cached chunks."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    chunks = chunks_for(ranges)
    words, segs = [], []
    todo = [c for c in chunks if not (cache_dir / f"t_{c[0]:.1f}_{c[1]:.1f}.json").exists()]
    if todo and log:
        log(f"Transcribing {sum(b - a for a, b in todo) / 60:.1f} min of audio "
            f"({len(chunks) - len(todo)} of {len(chunks)} chunks cached).")
    for i, (a, b) in enumerate(chunks):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        f = cache_dir / f"t_{a:.1f}_{b:.1f}.json"
        if not f.exists():
            wav = cache_dir / "chunk.wav"
            extract_wav(audio, wav, a, b - a, cancel)
            data = transcribe_wav(wav, a, log, cancel)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), "utf-8")
            tmp.replace(f)
            wav.unlink(missing_ok=True)
        data = json.loads(f.read_text("utf-8"))
        words += data["words"]
        segs += data["segments"]
        if progress:
            progress((i + 1) / max(1, len(chunks)))
    words.sort(key=lambda w: w["s"])
    segs.sort(key=lambda s: s["s"])
    return {"words": words, "segments": segs}


def window(words: list[dict], start: float, end: float) -> list[dict]:
    return [w for w in words if w["e"] > start and w["s"] < end]
