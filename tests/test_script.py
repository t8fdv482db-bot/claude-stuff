import json
from types import SimpleNamespace

import pytest

from adgen.models import AdScript, AvatarSpec, ScriptSegment
from adgen.safety import SafetyError, check_avatar_spec, check_timing, lint_script
from adgen.script.claude import ClaudeScriptWriter, ScriptRejected
from adgen.script.mock import MockScriptWriter


def _variant(hook, problem, solution, cta, angle="x"):
    return {
        "angle": angle,
        "segments": [
            {"role": "hook", "text": hook, "delivery": "curious", "visual": "avatar", "broll_focus": ""},
            {"role": "problem", "text": problem, "delivery": "warm", "visual": "avatar", "broll_focus": ""},
            {"role": "solution", "text": solution, "delivery": "confident", "visual": "broll", "broll_focus": "lid"},
            {"role": "cta", "text": cta, "delivery": "excited", "visual": "avatar", "broll_focus": ""},
        ],
        "on_screen_cta": "Get yours at pocketbrew.example",
        "claims_used": ["Leak-proof lid"],
    }


GOOD_SOLUTION = (
    "Pocket Brew brews smooth cold brew overnight in the fridge, and the leak-proof lid goes anywhere."
)
GOOD = _variant(
    "Still paying cafe prices for iced coffee?",
    "Every morning it's the same line, the same wait, and the same receipt.",
    GOOD_SOLUTION,
    "Get yours at pocketbrew.example today.",
)
BAD = _variant(
    "I've been using this for months.",
    "Cafe coffee costs a fortune and takes forever every single morning.",
    "Pocket Brew saves you 50% and the lid never leaks, so you can throw it in any bag at all.",
    "Get yours at pocketbrew.example today.",
)


class FakeClient:
    """Stands in for anthropic.Anthropic; returns queued JSON payloads in order."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        payload = self.payloads.pop(0)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(payload))],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=2000),
            stop_reason="end_turn",
            model="claude-opus-5-5",
        )


@pytest.mark.parametrize("length", [15, 20, 30])
def test_mock_writer_passes_lint(brief, length):
    brief = brief.model_copy(update={"length": length})
    ss = MockScriptWriter().write(brief)
    assert [v.variant for v in ss.variants] == ["A", "B", "C"]
    for v in ss.variants:
        assert lint_script(v, brief) == []
        assert check_timing(v, brief, 2.5) == []
        assert v.segments[0].role == "hook" and v.segments[-1].role == "cta"
        assert any(s.visual == "broll" for s in v.segments)


def test_lint_flags_testimonials_and_invented_numbers(brief):
    script = AdScript(variant="B", angle="x", segments=[ScriptSegment(**s) for s in BAD["segments"]], on_screen_cta="Shop")
    problems = lint_script(script, brief)
    assert any("i've been using" in p for p in problems)
    assert any("50%" in p for p in problems)


def test_lint_allows_numbers_from_brief(brief):
    seg = ScriptSegment(role="hook", text="One liter of cold brew, ready overnight.")
    seg2 = ScriptSegment(role="cta", text="Holds 1 liter. Get yours at pocketbrew.example.")
    script = AdScript(variant="A", angle="x", segments=[seg, seg2], on_screen_cta="Shop")
    assert lint_script(script, brief) == []


def test_claude_writer_revises_bad_variant(brief):
    client = FakeClient(
        [
            {"variants": [GOOD, BAD, GOOD]},  # draft
            {"reviews": [{"variant": "A", "problems": []}, {"variant": "B", "problems": ["invented testimonial"]}, {"variant": "C", "problems": []}]},
            {"variants": [GOOD]},  # revision of B
            {"reviews": [{"variant": "B", "problems": []}]},
        ]
    )
    writer = ClaudeScriptWriter(client=client)
    ss = writer.write(brief)
    assert [v.variant for v in ss.variants] == ["A", "B", "C"]
    assert "I've been using" not in ss.get("B").full_text
    assert ss.cost_usd > 0
    # Revision prompt carries the rejection reasons back to the model.
    assert "invented testimonial" in client.calls[2]["messages"][0]["content"]
    first = client.calls[0]
    assert first["model"] == "claude-opus-5-5"
    assert first["output_config"]["format"]["type"] == "json_schema"
    assert first["fallbacks"] == "default"


def test_claude_writer_gives_up_after_revisions(brief):
    audit_bad = {"reviews": [{"variant": "A", "problems": ["made-up stat"]}]}
    client = FakeClient(
        [{"variants": [BAD]}, audit_bad, {"variants": [BAD]}, audit_bad, {"variants": [BAD]}, audit_bad]
    )
    with pytest.raises(ScriptRejected):
        ClaudeScriptWriter(client=client).write(brief, n_variants=1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("extra", "looks like a famous actress"),
        ("voice_description", "sounds like Morgan Freeman"),
        ("outfit", "dressed as Taylor Swift on tour"),
        ("extra", "celebrity lookalike"),
    ],
)
def test_avatar_spec_rejects_real_people(field, value):
    with pytest.raises(SafetyError):
        check_avatar_spec(AvatarSpec(**{field: value}))


def test_avatar_spec_accepts_generic_description():
    check_avatar_spec(AvatarSpec(age="mid 30s", gender="man", ethnicity="South Asian", outfit="navy hoodie", extra="short beard, friendly smile"))
