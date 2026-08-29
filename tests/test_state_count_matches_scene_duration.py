"""State count must follow scene DURATION, because holds are duration/count.

The prompt asked for a fixed "2-4 states for EVERY scene", independent of how long the
scene runs. A 10-second scene with 2 states holds each for 5s, and the rendered gate rejects
any hold over 3.5s -- so the plan was unrenderable the moment it was written. Run 4a46ed72
logged exactly that ("2 state(s) across 9.60s holds each for 4.80s") and then died three
stages later on "Measured word timings cannot align every evidence state without invalid
cuts", which is the same fact arriving as a consequence.
"""

import math

import explainer_pipeline as ep
from longform_evidence import MAX_VISUAL_STATE_SECONDS

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

    assert f"N/{DIVISOR} states" in rule, "state count must be derived from scene length"
    assert str(MAX_VISUAL_STATE_SECONDS) in rule, "the ceiling it protects must be named"
    assert "2-4 states for EVERY scene" not in rule, "the fixed count must be gone"


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
