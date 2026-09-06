"""Four rules scoped to runtime, and the long-form contract left intact.

The causal contract was fitted to six references running 101-225 seconds, and it encoded their
length as if it were their shape: one-sentence hooks, a principle inside the first fifth, two
parallel cases, and a close that hands the opening object back. A 64-second telling of the SAME
story by the SAME engine breaks all four -- see fixtures/causal/cobra_bounty_short.json, which was
added failing for exactly that reason.

These tests pin both halves of the fix. Short form gets the compressed rules; long form keeps the
measured ones. A change that relaxes a rule for everyone fails here, and so does one that puts the
short-form boundary back where a 64-second reference cannot pass.
"""
import json
from pathlib import Path

import pytest

import causal_story as cs
import story_engines as se

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "causal"
LONG, SHORT = 220.0, 64.0


def _story(**over):
    """A minimal valid backfiring_solution chain; each test breaks one thing on purpose."""
    roles = ["setup", "intervention", "false_resolution", "hinge", "mechanism",
             "escalation", "escalation", "reversal", "generalization", "tool"]
    runtime = over.pop("runtime_sec", SHORT)
    mech_at = over.pop("mechanism_start", runtime * 0.30)
    steps = []
    for index, role in enumerate(roles):
        start = mech_at if role == "mechanism" else runtime * (index / len(roles))
        steps.append({
            "step_id": f"s{index:02d}", "role": role, "chapter": 1 + index // 3,
            "start_sec": round(start, 1),
            "situation": f"Step {index + 1}. The cobras keep arriving at the payout desk anyway.",
            "caused_by": f"s{index - 1:02d}" if index else "",
        })
    story = {
        "runtime_sec": runtime,
        "hook": {"line": "The government paid people to kill cobras."},
        "start_state": "the bounty sounds sensible",
        "opening_object": "a coin",
        "parallel_cases": [{"domain": "Hanoi", "problem": "rats", "solution": "tail bounty",
                            "result": "farmed rats"}],
        "steps": steps,
    }
    story.update(over)
    return story


def _codes(story):
    report = cs.validate_causal_story(story, se.get(se.BACKFIRING_SOLUTION))
    return {error["code"] for error in report["errors"]}


def test_the_operator_reference_now_validates():
    """The whole point: a 64-second telling of the cobra story passes."""
    payload = json.loads((FIXTURES / "cobra_bounty_short.json").read_text(encoding="utf-8"))
    report = cs.validate_causal_story(payload["story"], se.get(payload["story"]["engine"]))
    assert report["passed"] is True, report["errors"]
    assert payload["expect"]["pass"] is True


def test_the_two_hundred_second_reference_is_unaffected():
    """Loosened for short form, not for everyone. cobra_effect is the control."""
    payload = json.loads((FIXTURES / "cobra_effect.json").read_text(encoding="utf-8"))
    report = cs.validate_causal_story(payload["story"])
    assert report["passed"] is True, report["errors"]


@pytest.mark.parametrize("runtime,expected", [(60.0, True), (120.0, True), (121.0, False),
                                              (220.0, False), (0.0, False), (-5.0, False)])
def test_the_boundary_is_a_positive_runtime_under_the_limit(runtime, expected):
    """Unknown runtime keeps the stricter rules; a contract must not relax by omission."""
    assert cs.is_short_form(runtime) is expected


def test_a_two_sentence_hook_passes_short_and_fails_long():
    two = {"line": "The government paid people to kill cobras. So people started making cobras."}
    assert "MULTI_SENTENCE_HOOK" not in _codes(_story(runtime_sec=SHORT, hook=two))
    assert "MULTI_SENTENCE_HOOK" in _codes(
        _story(runtime_sec=LONG, hook=two, mechanism_start=LONG * 0.15))


def test_a_three_sentence_hook_fails_even_short():
    """Relaxed, not removed. Three sentences is a summary, not a promise."""
    three = {"line": "One. Two. Three."}
    assert "MULTI_SENTENCE_HOOK" in _codes(_story(runtime_sec=SHORT, hook=three))


def test_a_thirty_percent_mechanism_passes_short_and_fails_long():
    assert "LATE_MECHANISM" not in _codes(
        _story(runtime_sec=SHORT, mechanism_start=SHORT * 0.30))
    assert "LATE_MECHANISM" in _codes(
        _story(runtime_sec=LONG, mechanism_start=LONG * 0.30))


def test_the_short_deadline_is_still_a_deadline():
    assert "LATE_MECHANISM" in _codes(_story(runtime_sec=SHORT, mechanism_start=SHORT * 0.60))


def test_one_parallel_case_passes_short_and_fails_long():
    one = [{"domain": "Hanoi", "problem": "rats", "solution": "tail bounty", "result": "more rats"}]
    assert "THIN_GENERALIZATION" not in _codes(
        _story(runtime_sec=SHORT, parallel_cases=one))
    assert "THIN_GENERALIZATION" in _codes(
        _story(runtime_sec=LONG, mechanism_start=LONG * 0.15, parallel_cases=one))


def test_zero_parallel_cases_still_fails_short():
    assert "THIN_GENERALIZATION" in _codes(_story(runtime_sec=SHORT, parallel_cases=[]))


def test_a_short_close_may_return_to_the_situation_instead_of_the_object():
    """"Where are the cobra farms?" never hands the coin back, and is the stronger close."""
    story = _story(runtime_sec=SHORT, opening_object="a coin")
    story["steps"][-1]["situation"] = "Ask: where are the cobra farms?"
    assert "NO_CALLBACK" not in _codes(story)

    long_story = _story(runtime_sec=LONG, mechanism_start=LONG * 0.15, opening_object="a coin")
    long_story["steps"][-1]["situation"] = "Ask: where are the cobra farms?"
    assert "NO_CALLBACK" in _codes(long_story)


def test_a_close_returning_to_neither_still_fails_short():
    story = _story(runtime_sec=SHORT, opening_object="a coin")
    story["steps"][-1]["situation"] = "Consider the weather in Lisbon this time of year."
    assert "NO_CALLBACK" in _codes(story)


def test_the_callback_match_tolerates_an_english_plural():
    """"cobras" in the setup against "cobra farms" in the close is the same subject."""
    story = _story(runtime_sec=SHORT, opening_object="a coin")
    story["steps"][0]["situation"] = "Delhi is overrun with cobras in the streets."
    story["steps"][-1]["situation"] = "Ask: where are the cobra farms?"
    assert "NO_CALLBACK" not in _codes(story)


# --- parallel cases belong in the generalization, and nowhere else -------------------------------

def _story_with_case(case_beat_role, case_text):
    """A valid chain where one beat mentions the parallel case's domain."""
    story = _story(runtime_sec=SHORT)
    story["parallel_cases"] = [
        {"domain": "public health (Hanoi, 1902)", "problem": "rats", "solution": "tail bounty",
         "result": "farmed rats"}]
    for step in story["steps"]:
        if step["role"] == case_beat_role:
            step["situation"] = case_text
            break
    return story


def test_a_parallel_case_in_an_escalation_beat_is_caught():
    """The defect a measured draft shipped: Delhi's story left for Vietnam before it resolved.

    Every structural check passed — a beat labelled escalation was present and in order — because
    nothing asked whether the escalation escalates THIS story.
    """
    story = _story_with_case(
        "escalation", "The same trap sprang shut in Hanoi in 1902, where officials paid per tail.")
    assert "PARALLEL_CASE_OUT_OF_PLACE" in _codes(story)


def test_the_same_case_in_the_generalization_is_fine():
    story = _story_with_case(
        "generalization", "The same trap sprang shut in Hanoi in 1902, where officials paid per tail.")
    assert "PARALLEL_CASE_OUT_OF_PLACE" not in _codes(story)


def test_a_word_the_story_already_uses_is_not_a_comparison():
    """"Colonial public health" shares "colonial" with a story about colonial officials.

    Matching that flagged the setup beat of a draft with nothing wrong with it. A word the story
    uses about itself is not evidence that a comparison has been imported.
    """
    story = _story(runtime_sec=SHORT)
    story["parallel_cases"] = [
        {"domain": "colonial public health (Hanoi)", "problem": "rats", "solution": "bounty",
         "result": "farmed rats"}]
    story["steps"][0]["situation"] = "Colonial officials in Delhi faced cobras in the streets."
    story["steps"][5]["situation"] = "Colonial clerks kept paying as the pens filled."
    assert "PARALLEL_CASE_OUT_OF_PLACE" not in _codes(story)


def test_the_check_is_silent_without_a_generalization():
    """No generalization means no parallel cases were promised, so there is nothing to misplace."""
    story = _story_with_case("escalation", "Hanoi tried the same thing in 1902.")
    for step in story["steps"]:
        if step["role"] == "generalization":
            step["role"] = "escalation"
    assert "PARALLEL_CASE_OUT_OF_PLACE" not in _codes(story)
