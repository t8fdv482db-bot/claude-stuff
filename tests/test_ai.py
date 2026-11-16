"""AI review: validation of model answers and filtering (no network: the API call is faked)."""
import json

from clipstudio import ai

CAND = {"start": 100.0, "end": 126.0, "peak": 118.0, "score": 3.1, "signals": {}, "title": "t", "hook": "", "reason": "r"}


def test_validate_good_answer_tightens_cut_and_cleans_text():
    res = {"score": 8, "start": 104.0, "end": 127.5, "title": "Lacy's car flips off a bridge and he can't believe it #gta6 #shorts",
           "hook": "HE DID NOT SEE THIS COMING AT ALL", "reason": "clear payoff"}
    v = ai.validate(res, CAND, min_len=20, max_len=60, duration=1000, streamer="Lacy")
    assert v["ai_score"] == 8 and (v["start"], v["end"]) == (104.0, 127.5)
    assert "#" not in v["title"] and len(v["title"]) < 70
    assert v["hook"] == "HE DID NOT SEE THIS COMING"


def test_validate_bad_cut_keeps_detector_cut():
    for s, e in [(50, 200), (119.5, 125), (130, 150), ("x", 5)]:
        v = ai.validate({"score": 7, "start": s, "end": e, "title": "Ok", "hook": "a b", "reason": ""}, CAND,
                        min_len=20, max_len=60, duration=1000, streamer="")
        assert (v["start"], v["end"]) == (100.0, 126.0)


def test_validate_rejects_garbage():
    assert ai.validate(None, CAND, min_len=20, max_len=60, duration=1000, streamer="") is None
    assert ai.validate({"score": 42}, CAND, min_len=20, max_len=60, duration=1000, streamer="") is None


def test_review_drops_low_scores_and_tracks_cost(home, monkeypatch):
    from clipstudio import db
    from clipstudio.worker import JobContext
    jid = db.insert("jobs", url="x", platform="youtube", created=db.now())
    answers = iter([{"score": 9, "start": 101, "end": 125, "title": "Lacy wins", "hook": "NO WAY", "reason": "great"},
                    {"score": 3, "start": 300, "end": 325, "title": "meh", "hook": "", "reason": "needs context"}])
    lock = __import__("threading").Lock()

    def fake_ask(prompt, max_tokens=2000):
        assert "Transcript" in prompt and "Chat reaction" in prompt
        with lock:
            return next(answers), 1500, 200, "claude-sonnet-5-5"

    monkeypatch.setattr(ai, "ask_json", fake_ask)
    c2 = dict(CAND, start=300.0, end=326.0, peak=318.0)
    kept = ai.review_candidates(JobContext(jid), [CAND, c2], words=[], chat=[{"t": 119, "m": "KEKW"}],
                                streamer={"name": "Lacy"}, min_len=20, max_len=60, duration=1000)
    assert len(kept) == 1
    job = db.get("jobs", jid)
    assert job["ai_input_tokens"] == 3000 and job["ai_output_tokens"] == 400
    assert abs(job["ai_cost"] - (3000 * 2 + 400 * 10) / 1e6) < 1e-9
    _ = json
