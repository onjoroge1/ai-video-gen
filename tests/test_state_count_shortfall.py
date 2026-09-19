"""The state count is bounded by what the writer returns, so every budget derives from that.

MEASURED across four delivered films. states_required_for_words asks a 122-word scene for 18
states; the per-scene counts actually returned were

    [3, 3, 3, 3, 3, 7, 7, 7, 6, 7]   [4, 4, 3, 4, 9, 7, 7, 6, 8]
    [4, 4, 4, 7, 7, 7, 6, 7]         [3, 3, 3, 3, 4, 4, 5]

never above 9, with 7 the mode of every long scene, and uncorrelated with the ask past that point:
one 15.2s scene needing 6 returned 7, while scenes needing 14, 16 and 17 returned 7, 6 and 7.

So the ceiling is a property of the producer. A scene longer than it can cover at target cadence
cannot be cut to cadence however the prompt is worded, and the whole chain -- scene length, event
count, claim target, per-beat words -- has to be derived from it instead of from the ask.
"""
import math

import pytest

import event_functions as ef
import longform_research as lr
import story_compiler as sc
from longform_evidence import (MAX_STATES_PER_SCENE, TARGET_VISUAL_STATE_SECONDS,
                               SLOWEST_MEASURED_WORDS_PER_SECOND,
                               cadence_feasible_seconds, illustratable_scene_seconds)


def test_the_scene_length_target_is_derived_from_the_state_ceiling():
    """One definition, not a hand-picked number that disagrees with it.

    SECONDS_PER_SCENE_TARGET was 25.0, reasoned from "6-8 states at the 3.5s ceiling". Both halves
    were wrong the same way: the cadence target is 2.75s, not the rejection line, and the ceiling is
    a measured 7. 25-second scenes asked for ~9 states from a writer that returns 7, and that
    per-scene shortfall is what the rendered gate reports as long_visual_hold.
    """
    assert illustratable_scene_seconds() == MAX_STATES_PER_SCENE * TARGET_VISUAL_STATE_SECONDS
    assert lr.SECONDS_PER_SCENE_TARGET == illustratable_scene_seconds()


def test_the_event_ask_is_self_consistent_with_the_runtime():
    """Asking for N events must mean N scenes can actually carry the runtime.

    This is the check that was missing. At 300s the ask was 12 events, and 12 scenes carry 231s --
    so the ask itself guaranteed a 69-second shortfall before anyone wrote a word.
    """
    for duration in (60, 90, 180, 240, 300):
        events = lr.events_for_runtime(duration)
        assert cadence_feasible_seconds(events) + 1e-9 >= duration, (
            f"{duration}s asks for {events} events, which carry only "
            f"{cadence_feasible_seconds(events)}s at target cadence")


def test_per_beat_words_use_the_slowest_measured_rate():
    """A scene written to the average and read slowly overruns, and the overrun does not spread.

    It lands on whichever picture was already holding longest -- the one at the ceiling.
    """
    assert lr.illustratable_beat_words() == int(
        lr.SECONDS_PER_SCENE_TARGET * SLOWEST_MEASURED_WORDS_PER_SECOND)
    assert lr.illustratable_beat_words() < int(lr.SECONDS_PER_SCENE_TARGET * 2.86)


def test_the_claim_target_still_never_drops_below_the_tuned_floor():
    """Short films were calibrated on 22-28. Deriving the chain must not regress them."""
    for duration in (30, 60, 90, 120):
        low, high = lr.research_claim_target(duration)
        assert low >= lr.MIN_CLAIM_REQUEST and high > low


def test_claims_scale_with_the_larger_event_count():
    assert lr.research_claim_target(300)[0] > lr.research_claim_target(90)[0]


@pytest.mark.parametrize("engine_id", ["removed_keystone", "backfiring_solution"])
def test_the_prompt_says_how_to_reach_the_count_not_only_what_it_is(engine_id):
    """The gap the ask never explained.

    Required functions are singletons, so asking a 5-required-function engine for 16 events is
    asking for 11 from somewhere, and the only somewhere the compiler accepts is the repeatable
    roles. Measured: the planner returned 8 against an ask of 12, three runs running, filling the
    gap with `context` beats that were then pruned for lack of evidence -- leaving eight 40-second
    scenes. It was never told escalation may recur.
    """
    mapping = ef.map_for(engine_id)
    clause = sc._repeat_to_reach_count(mapping, 300)
    assert clause, "no guidance on reaching the event count"
    for name in sc._repeatable_functions(mapping):
        assert name in clause
    # And it must refuse the route that silently fails: context beats get pruned.
    assert "context" in clause


def test_repeatable_functions_come_from_the_compiler_not_a_list():
    """A hand-written list would let the prompt ask for something the compiler then rejects."""
    import causal_story as cs
    for engine_id in ("removed_keystone", "backfiring_solution"):
        mapping = ef.map_for(engine_id)
        for name in sc._repeatable_functions(mapping):
            assert mapping.role_for(name) in cs._REPEATABLE
        # Required singletons must never be offered as repeatable.
        for name in sc._repeatable_functions(mapping):
            assert mapping.role_for(name) not in {"setup", "intervention", "mechanism"}


def test_an_engine_with_no_repeatable_function_gets_no_clause():
    """Fail quiet, not wrong: inventing a repeat instruction for such an engine would be a lie."""
    class _NoRepeat:
        to_role = {"establishes_problem": "setup"}
        required = ("establishes_problem",)
        def role_for(self, name):
            return self.to_role.get(name, "")
    assert sc._repeat_to_reach_count(_NoRepeat(), 300) == ""


def test_cadence_feasibility_reproduces_the_recorded_shortfall():
    """The 300s film that came back with 8 beats. Decidable at plan time; reported only by the gate.

    98 states wanted against 56 available. The numbers all existed and nothing read them together.
    """
    fit = lr.cadence_feasibility(8, 300, 700)
    assert fit["feasible"] is False
    assert fit["cadence_feasible_seconds"] == pytest.approx(154.0, abs=0.1)
    assert fit["states_available"] == 8 * MAX_STATES_PER_SCENE
    assert fit["states_needed"] == math.ceil(300 / TARGET_VISUAL_STATE_SECONDS)
    assert fit["beats_needed_for_requested_runtime"] == 16
    assert fit["shortfall_seconds"] > 100


def test_cadence_feasibility_passes_when_the_beats_are_there():
    fit = lr.cadence_feasibility(16, 300, 700)
    assert fit["feasible"] is True and fit["shortfall_seconds"] == 0.0


def test_cadence_feasibility_is_a_report_not_a_gate():
    """It must never raise. Whether to shorten, demand beats or accept holds is editorial."""
    for beats, duration in ((0, 0), (0, 300), (1, 1), (200, 30)):
        assert isinstance(lr.cadence_feasibility(beats, duration, 0), dict)
