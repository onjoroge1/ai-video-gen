"""State count must follow scene DURATION, because holds are duration/count.

The prompt asked for a fixed "2-4 states for EVERY scene", independent of how long the
scene runs. A 10-second scene with 2 states holds each for 5s, and the rendered gate rejects
any hold over 3.5s -- so the plan was unrenderable the moment it was written. Run 4a46ed72
logged exactly that ("2 state(s) across 9.60s holds each for 4.80s") and then died three
stages later on "Measured word timings cannot align every evidence state without invalid
cuts", which is the same fact arriving as a consequence.
"""

import math
import re

import explainer_pipeline as ep
from longform_evidence import (
    MAX_VISUAL_STATE_SECONDS,
    SLOWEST_MEASURED_WORDS_PER_SECOND,
    states_required_for_words,
)

# The slowest words-per-second measured across real renders. The rule has to hold at the
# slow end, not at the average, or a slow scene breaks the ceiling.
SLOWEST_WPS = 2.588
DIVISOR = 9


def _rule_text() -> str:
    for value in vars(ep).values():
        if isinstance(value, str) and "EVIDENCE STATE MAP" in value:
            return value
    raise AssertionError("EVIDENCE STATE MAP instruction not found")


def test_the_rule_reaches_the_prompt_and_ties_count_to_duration():
    rule = _rule_text()

    assert str(MAX_VISUAL_STATE_SECONDS) in rule, "the ceiling it protects must be named"
    assert "2-4 states for EVERY scene" not in rule, "the fixed count must be gone"
    # The rule is generated from the constants now, so assert the arithmetic it states rather
    # than one phrasing of it. Still ~N/9, still derived from scene length.
    assert f"N/{DIVISOR}" in rule, "state count must be derived from scene length"
    assert str(SLOWEST_MEASURED_WORDS_PER_SECOND) in rule, "sized on the SLOW rate, not the mean"


def test_the_prompts_worked_examples_are_true():
    """The band was ignored partly because every worked example was a short scene -- the longest
    was 45 words against real scenes of 204. Examples are generated now, so they cannot go stale,
    but they must also be arithmetically correct and must reach the long end."""
    rule = _rule_text()
    pairs = [(int(w), int(n)) for w, n in
             re.findall(r"(\d+) words needs (\d+)", rule)]

    assert pairs, "the rule must show worked examples"
    for words, stated in pairs:
        assert stated == states_required_for_words(words), (
            f"{words} words: prompt says {stated}, the code requires "
            f"{states_required_for_words(words)}")
        assert (words / SLOWEST_WPS) / stated <= MAX_VISUAL_STATE_SECONDS, (
            f"{words} words at {stated} states still breaks the hold ceiling")
    assert max(w for w, _ in pairs) >= 150, (
        "examples must reach the long end; real scenes in this lane run past 200 words")


def test_the_fixed_band_that_beat_the_formula_is_gone():
    """Measured on a delivered 252.5s film: the model produced 3,3,3,3,4,4,5 states -- "first 30%
    use 3-4, later 2-4" almost exactly -- while the formula in the same paragraph demanded
    4,4,4,5,22,20,23. The band won in every scene. It must not come back."""
    rule = _rule_text()
    for banned in ("3-4 states", "later 2-4", "2-4 states"):
        assert banned not in rule, f"the fixed band is back: {banned!r}"


def test_the_requirement_matches_what_the_delivered_film_needed():
    """The seven scene lengths of the recorded 252.5s film, against what it actually planned."""
    produced = [3, 3, 3, 3, 4, 4, 5]
    words = [34, 34, 36, 39, 198, 177, 204]
    required = [states_required_for_words(w) for w in words]

    assert required == [4, 4, 4, 5, 22, 20, 23]
    assert all(got < need for got, need in zip(produced, required)), (
        "every scene of the delivered film was under-planned")


def test_the_divisor_keeps_every_realistic_scene_under_the_ceiling():
    # Every scene length the planner produces, at the slowest measured narration speed.
    violations = []
    for words in range(12, 60):
        seconds = words / SLOWEST_WPS
        states = max(1, math.ceil(words / DIVISOR))
        if seconds / states > MAX_VISUAL_STATE_SECONDS:
            violations.append((words, round(seconds / states, 2)))

    assert not violations, f"holds exceed {MAX_VISUAL_STATE_SECONDS}s at: {violations}"


def test_a_looser_divisor_would_not_be_safe():
    # Guards the choice of 9. N/10 was tried first and breaks at several real scene lengths,
    # so this fails if someone relaxes it back.
    broken = [
        words for words in range(12, 60)
        if (words / SLOWEST_WPS) / max(1, math.ceil(words / 10)) > MAX_VISUAL_STATE_SECONDS
    ]

    assert broken, "if N/10 is now safe the ceiling or the measured speed changed — recheck 9"
