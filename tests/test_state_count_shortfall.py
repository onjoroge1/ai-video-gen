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


def _claim(claim_id, **over):
    base = {"claim_id": claim_id, "claim": "Kudzu was planted on 1.2 million acres.",
            "material": True, "allowed_exaggeration": False,
            "support_quote": "about 1.2 million acres were planted"}
    base.update(over)
    return base


def test_a_self_contradictory_claim_is_quarantined_not_fatal():
    """One bad row out of fifty must not cost the whole dossier.

    `material: true` with `allowed_exaggeration: true` asserts "load-bearing scientific claim" and
    "may overstate" at once. The writer was never going to be allowed to use it. Measured: exactly
    one such claim out of fifty killed a 300s run after the research was paid for -- and it gets
    likelier as the claim target scales, since one bad row in 22 is unlucky and one in 53 ordinary.
    """
    out = lr.quarantine_contradicted_claims(
        {"claims": [_claim("c01"), _claim("c02", allowed_exaggeration=True), _claim("c03")]})
    assert [c["claim_id"] for c in out["claims"]] == ["c01", "c03"]
    assert [(e["claim"]["claim_id"], e["reason"]) for e in out["excluded_claims"]] == [
        ("c02", "material_claim_permits_exaggeration")]
    assert out["semantic_source_filter"]["excluded_count"] == 1


def test_quarantining_does_not_weaken_the_rule_itself():
    """The dossier gate still rejects the shape; it simply no longer sees a removed row."""
    report = lr.validate_research_dossier({"claims": [_claim("c02", allowed_exaggeration=True)]})
    assert any(issue["code"] == "material_exaggeration" for issue in report["errors"])


def test_a_non_material_claim_may_permit_exaggeration():
    """The rule is about MATERIAL claims. Colour may be flagged as loose without being dropped."""
    out = lr.quarantine_contradicted_claims(
        {"claims": [_claim("c01", material=False, allowed_exaggeration=True)]})
    assert [c["claim_id"] for c in out["claims"]] == ["c01"]


def test_optional_attention_roles_are_spent_before_repeats():
    """The overcorrection the first version of this clause caused.

    Naming only the repeatable functions produced a delivered spine of
    setup/setup/intervention/intervention/mechanism/mechanism + escalation x16 + reversal x2 +
    generalization x2 -- sixteen consecutive escalations, `intended_effect` never used, and 83.3
    seconds before the first attention beat. The one optional role that could have supplied an
    earlier one was never asked for.
    """
    mapping = ef.map_for("removed_keystone")
    assert sc._early_attention_functions(mapping) == ("intended_effect",)
    clause = sc._repeat_to_reach_count(mapping, 300)
    assert "FIRST" in clause and "intended_effect" in clause
    # And the repeats still happen, for the remainder.
    assert "THEN supply" in clause


def test_an_engine_whose_required_set_already_turns_early_is_unchanged():
    """backfiring_solution REQUIRES apparent_success, a false_resolution in third position, so it
    never had this problem and must not be given busywork."""
    mapping = ef.map_for("backfiring_solution")
    assert sc._early_attention_functions(mapping) == ()
    clause = sc._repeat_to_reach_count(mapping, 300)
    assert "FIRST" not in clause
    assert clause.startswith("Every required function")


def test_early_attention_functions_are_derived_from_the_retention_vocabulary():
    """Not a hand-written list: what re-earns attention is longform_retention's definition."""
    import causal_story as cs
    attention = {cs.FALSE_RESOLUTION, cs.HINGE, cs.ESCALATION, cs.REVERSAL, *cs.CLOSING_ROLES}
    for engine_id in ("removed_keystone", "backfiring_solution"):
        mapping = ef.map_for(engine_id)
        for name in sc._early_attention_functions(mapping):
            assert name not in mapping.required, "required roles are already guaranteed"
            assert mapping.role_for(name) in attention
