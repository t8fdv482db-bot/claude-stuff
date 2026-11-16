"""ASS caption timing: events never overlap and the highlight follows each spoken word."""
import re

from clipstudio.render import ass_color, ass_time, build_ass, caption_events, group_words


def words_from(spec):
    """spec: list of (start, end, word)."""
    return [{"s": s, "e": e, "w": w} for s, e, w in spec]


WORDS = words_from([
    (100.0, 100.3, "No"), (100.35, 100.7, "way"), (100.75, 101.2, "bro!"),
    (101.3, 101.6, "Look"), (101.65, 101.9, "at"), (101.95, 102.4, "this,"),
    (104.0, 104.4, "chat"), (104.45, 104.9, "clip"), (104.95, 105.5, "it."),
    (99.0, 99.5, "before"),          # outside the clip — must be dropped
])


def test_events_are_ordered_and_never_overlap():
    ev = caption_events(sorted(WORDS, key=lambda w: w["s"]), 100.0, 130.0, per_line=3)
    assert ev, "no events"
    for a, b in zip(ev, ev[1:]):
        assert a["end"] <= b["start"] + 1e-9, (a, b)
        assert a["start"] < a["end"]


def test_highlight_follows_each_word():
    ws = sorted(WORDS, key=lambda w: w["s"])
    ev = caption_events(ws, 100.0, 130.0, per_line=3)
    spoken = [w for w in ws if w["s"] >= 100]
    assert len(ev) == len(spoken)
    for e, w in zip(ev, spoken):
        assert e["words"][e["hi"]] == re.sub(r"[^\w'!?]", "", w["w"].upper())
        assert abs(e["start"] - (w["s"] - 100)) < 0.01           # highlight starts exactly with the word


def test_lines_hold_two_or_three_words_and_break_on_pauses():
    groups = group_words(sorted(WORDS, key=lambda w: w["s"])[1:], per_line=3)
    assert all(1 <= len(g) <= 3 for g in groups)
    # "this," (ends 102.4) and "chat" (starts 104.0) are separated by a pause: different lines
    assert not any({"this,", "chat"} <= {w["w"] for w in g} for g in groups)


def test_ass_file_has_styles_hook_and_disclosure():
    txt = build_ass(WORDS, 100.0, 130.0, style={"caption_font": "Arial", "caption_size": 80,
                    "caption_highlight": "#FFE600"}, caption_y=730, hook="He didn't see it", disclosure="#ad Paid")
    assert "PlayResX: 1080" in txt and "PlayResY: 1920" in txt
    assert "\\pos(540,730)" in txt
    assert "&H0000E6FF&" in txt                                    # yellow in ASS BGR order
    assert re.search(r"Dialogue: 1,0:00:00\.00,0:00:03\.00,Hook", txt)
    assert re.search(r"Dialogue: 2,0:00:00\.00,0:00:03\.00,Disclosure,,0,0,0,,#ad Paid", txt)
    assert "BEFORE" not in txt


def test_helpers():
    assert ass_time(3661.239) == "1:01:01.24"
    assert ass_color("#FF0000") == "&H000000FF"
