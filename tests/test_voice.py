from adgen import ffmpeg
from adgen.models import AdScript, ScriptSegment
from adgen.script.mock import MockScriptWriter
from adgen.voice import fit_to_length
from adgen.voice.base import build_tts_text, words_from_alignment
from adgen.voice.mock import MockVoice


def _script():
    return AdScript(
        variant="A",
        angle="x",
        on_screen_cta="Shop",
        segments=[
            ScriptSegment(role="hook", text="Wait, what?", delivery="curious"),
            ScriptSegment(role="cta", text="Shop now.", delivery="excited"),
        ],
    )


def test_build_tts_text_with_tags():
    text, ranges = build_tts_text(_script(), with_tags=True)
    assert text == "[curious] Wait, what? [excited] Shop now."
    assert [text[a:b] for a, b in ranges] == ["[curious] Wait, what?", "[excited] Shop now."]


def test_words_from_alignment_drops_tags_and_maps_segments():
    text, ranges = build_tts_text(_script(), with_tags=True)
    chars = list(text)
    starts = [i * 0.05 for i in range(len(chars))]
    ends = [s + 0.05 for s in starts]
    words = words_from_alignment(chars, starts, ends, ranges)
    assert [w.text for w in words] == ["Wait,", "what?", "Shop", "now."]
    assert [w.segment for w in words] == [0, 0, 1, 1]
    assert words[0].start == starts[text.index("Wait")]
    assert words[1].end == ends[text.index("what?") + 4]


def test_mock_voice_and_fit(tmp_path, brief):
    script = MockScriptWriter().write(brief).get("A")
    track = MockVoice().synthesize(script, "mock-205", "en", tmp_path)
    assert len(track.words) == script.word_count
    assert abs(ffmpeg.duration(track.audio_path) - track.duration) < 0.05
    assert track.words == sorted(track.words, key=lambda w: w.start)

    # Force a speed-up and check timings scale with it.
    limit = track.duration / 1.1
    fitted = fit_to_length(track, limit, tmp_path)
    assert 1.09 < fitted.tempo < 1.11
    assert abs(fitted.duration - limit) < 0.1
    assert abs(fitted.words[-1].end - track.words[-1].end / fitted.tempo) < 0.01

    bounds = fitted.segment_bounds(len(script.segments))
    assert bounds[0][0] == 0.0 and abs(bounds[-1][1] - fitted.duration) < 1e-3
    for (a, b), (c, d) in zip(bounds, bounds[1:]):
        assert b == c and a <= b
    # Every word starts inside its segment's span.
    for w in fitted.words:
        s, e = bounds[w.segment]
        assert s <= w.start + 1e-6 and w.start < e
