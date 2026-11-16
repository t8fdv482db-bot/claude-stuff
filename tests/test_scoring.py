"""Scorer unit tests on synthetic per-second signals (fast, no ffmpeg)."""
import numpy as np

from clipstudio import scoring


def test_rolling_z_spike_and_flat():
    x = np.ones(600)
    x[400] = 10
    z = scoring.rolling_z(x, 300)
    assert z[400] > 5 and abs(z[200]) < 1e-6
    assert np.all(scoring.rolling_z(np.zeros(100)) == 0)


def test_chat_shift_and_tokens():
    msgs = [{"t": 105.2, "m": "KEKW"}, {"t": 105.5, "m": "hello"}, {"t": 105.7, "m": "no way bro"}]
    s = scoring.chat_signal(msgs, 200, ["KEKW", "no way"], shift=5)
    assert abs(int(np.argmax(s)) - 100) <= 1
    assert s.sum() > 4.9                                   # 3 msgs + 2 hype bonuses


def test_word_tokens_match_whole_words_only():
    msgs = [{"t": 10, "m": "Wow"}, {"t": 20, "m": "W"}]
    s = scoring.chat_signal(msgs, 40, ["W"], shift=0)
    assert s[18:23].sum() > s[8:13].sum()


def test_find_moments_nms_and_lengths():
    n = 1200
    rng = np.random.default_rng(0)
    loud = rng.normal(-30, 1, n)
    for t in (200, 240, 700):                              # 240 is within 90 s of 200: suppressed
        loud[t:t + 3] += 25
    sig = scoring.Signals(n=n, audio={"loud": loud, "jump": np.zeros(n), "burst": np.zeros(n)})
    m = scoring.find_moments(sig, {"audio": 1}, 3, min_len=20, max_len=60)
    peaks = sorted(c["peak"] for c in m)
    assert any(abs(p - 701) <= 5 for p in peaks)
    near = [p for p in peaks if 190 <= p <= 250]          # two spikes 40 s apart: NMS keeps exactly one
    assert len(near) == 1
    assert all(20 <= c["end"] - c["start"] <= 60 for c in m)


def test_window_snaps_to_sentences_and_respects_limits():
    words = [{"s": t, "e": t + 0.4, "w": "word." if i % 8 == 7 else "word"} for i, t in enumerate(np.arange(0, 300, 0.5))]
    s, e = scoring.make_window(150, 300, words=words, min_len=20, max_len=60)
    assert 20 <= e - s <= 60
    starts, ends = scoring.sentence_bounds(words)
    assert min(abs(s - x) for x in starts) < 0.2           # starts at a sentence start
    assert not any(w["s"] < s < w["e"] or w["s"] < e < w["e"] for w in words)   # never mid-word
    s, e = scoring.make_window(5, 300, min_len=20, max_len=60)
    assert s == 0 and e - s >= 20
    s, e = scoring.make_window(295, 300, min_len=20, max_len=60)
    assert e == 300 and e - s >= 20


def test_windows_without_speech_are_demoted():
    n = 1000
    loud = np.full(n, -30.0)
    loud[200:203] += 30          # loudest spike, but nobody talks (intro music)
    loud[600:603] += 20          # smaller spike with speech
    words = [{"s": t, "e": t + 0.4, "w": "word"} for t in np.arange(560, 640, 0.5)]
    sig = scoring.Signals(n=n, audio={"loud": loud, "jump": np.zeros(n), "burst": np.zeros(n)})
    m = scoring.find_moments(sig, {"audio": 1}, 1, words=words)
    assert abs(m[0]["peak"] - 601) <= 5 and m[0]["speech"] > 0.9
