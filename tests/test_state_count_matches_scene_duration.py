"""State count follows scene duration and plans below the rendered rejection ceiling."""

import math
import re

import explainer_pipeline as ep
from longform_evidence import (
    MAX_VISUAL_STATE_SECONDS,
    TARGET_VISUAL_STATE_SECONDS,
    SLOWEST_MEASURED_WORDS_PER_SECOND,
    states_required_for_words,
)

SLOWEST_WPS = 2.588


def _rule_text() -> str:
    for value in vars(ep).values():
        if isinstance(value, str) and "EVIDENCE STATE MAP" in value:
            return value
    raise AssertionError("EVIDENCE STATE MAP instruction not found")


def test_the_rule_reaches_the_prompt_and_ties_count_to_duration():
    rule = _rule_text()

    assert str(MAX_VISUAL_STATE_SECONDS) in rule
    assert str(TARGET_VISUAL_STATE_SECONDS) in rule
    assert "2-4 states for EVERY scene" not in rule
    assert "N/7" in rule
    assert str(SLOWEST_MEASURED_WORDS_PER_SECOND) in rule


def test_the_prompts_worked_examples_are_true():
    rule = _rule_text()
    pairs = [(int(words), int(states)) for words, states in
             re.findall(r"(\d+) words needs (\d+)", rule)]

    assert pairs
    for words, stated in pairs:
        assert stated == states_required_for_words(words)
        assert (words / SLOWEST_WPS) / stated <= TARGET_VISUAL_STATE_SECONDS
    assert max(words for words, _ in pairs) >= 150


def test_the_fixed_band_that_beat_the_formula_is_gone():
    rule = _rule_text()
    for banned in ("3-4 states", "later 2-4", "2-4 states"):
        assert banned not in rule


def test_the_requirement_matches_the_delivered_film_at_the_new_target():
    produced = [3, 3, 3, 3, 4, 4, 5]
    words = [34, 34, 36, 39, 198, 177, 204]
    required = [states_required_for_words(word_count) for word_count in words]

    assert required == [5, 5, 6, 6, 28, 25, 29]
    assert all(got < need for got, need in zip(produced, required))


def test_target_divisor_keeps_realistic_scenes_below_target():
    violations = []
    for words in range(12, 60):
        seconds = words / SLOWEST_WPS
        states = states_required_for_words(words)
        if seconds / states > TARGET_VISUAL_STATE_SECONDS:
            violations.append((words, round(seconds / states, 2)))

    assert not violations


def test_planning_at_the_hard_ceiling_has_no_slow_read_margin():
    cliff_count = math.ceil((36 / SLOWEST_WPS) / MAX_VISUAL_STATE_SECONDS)
    target_count = states_required_for_words(36)

    assert target_count > cliff_count
