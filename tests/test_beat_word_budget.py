"""The per-beat word budget, and the boundary it must not cross to fix a scene length.

A beat becomes exactly one scene, so its word budget IS that scene's length, and the scene's
length decides how many evidence states can fill it. Two contracts meet here and they pull in
opposite directions:

  * causal_story:450  LATE_MECHANISM -- the mechanism must START by runtime_sec * pct
  * longform_evidence MAX_VISUAL_STATE_SECONDS -- no picture may hold longer than 3.5s

Satisfying either one by breaking the other is the failure mode these tests exist to catch.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

import causal_story as cs
import explainer_pipeline as ep
import longform_research as research
import story_compiler as sc
import story_engines as se
from runtime_planner import DEFAULT_WORDS_PER_SECOND as WPS, runtime_word_bounds

ENGINE = "backfiring_solution"
HOOK = "How a bounty meant to kill rats in colonial Hanoi ended up paying people to farm them"

# The plan the recorded 300s run actually produced: four context events shoved in front of the
# intervention, so the derived mechanism landed at beat 7 of 11.
RUN_10_ROLES = ["setup", "context", "context", "context", "intervention", "false_resolution",
                "mechanism", "false_resolution", "escalation", "reversal", "context"]

# What the deadline actually permits: the incentive changes early, and the consequences get the
# rest of the film to play out in.
SHAPED_ROLES = ["setup", "intervention", "mechanism", "false_resolution", "escalation",
                "escalation", "reversal", "escalation", "generalization", "generalization",
                "tool", "verdict"]


def _budgets(roles, duration=300):
    beats = [{"n": i + 1, "causal_role": role} for i, role in enumerate(roles)]
    total = runtime_word_bounds(duration, len(beats))[0]
    return beats, ep._causal_word_budgets(beats, total, ENGINE, HOOK)


def _mechanism_start_sec(roles, beats, budgets):
    index = roles.index("mechanism")
    return sum(budgets[beats[i]["n"]] for i in range(index)) / WPS


def _deadline_sec(duration=300):
    pct = se.mechanism_deadline_pct(se.get(ENGINE), cs.MECHANISM_DEADLINE_PCT)
    return duration * pct


def test_surplus_never_crosses_the_group_boundary():
    """The exact bug this guard exists for.

    Letting the post-mechanism group's overflow cascade into the starved opening evens the film
    out to ~76 words a beat and a 25.9s worst scene -- which clears the hold checks and moves the
    mechanism from 51s to 155s, straight into LATE_MECHANISM. A fix that swaps one hard failure
    for another is not a fix, and the allocator must refuse it even though the resulting numbers
    look better on the axis being worked on.
    """
    beats, budgets = _budgets(RUN_10_ROLES)
    start = _mechanism_start_sec(RUN_10_ROLES, beats, budgets)
    assert start <= _deadline_sec(), (
        f"mechanism moved to {start:.0f}s against a {_deadline_sec():.0f}s deadline -- "
        "surplus escaped its group")
    # The opening group stays exactly as starved as the deadline requires it to be. If these grow,
    # words came across the boundary.
    opening = [budgets[beats[i]["n"]] for i in range(RUN_10_ROLES.index("mechanism"))]
    assert max(opening) < research.illustratable_beat_words()


def test_an_infeasible_plan_is_reported_not_smoothed():
    """11 beats cannot carry 833 words under both contracts, and the allocator must not pretend.

    The honest outcome is that the long scenes stay long and visibly wrong. Runtime is preserved
    -- dropping the words reappears as a short film, which the audio gate fails harder -- so the
    overflow stays where it can be seen.
    """
    beats, budgets = _budgets(RUN_10_ROLES)
    worst = max(budgets.values()) / WPS
    assert worst > research.SECONDS_PER_SCENE_TARGET, (
        "a plan with 5 post-mechanism beats and 666 words to place cannot produce short scenes; "
        "if this passes, the allocator is hiding the shortfall somewhere")
    assert research.beats_required_for_words(sum(budgets.values())) > len(RUN_10_ROLES)


def test_a_deadline_shaped_plan_satisfies_both_contracts():
    """The shape the planner is now asked for clears the mechanism deadline AND the hold ceiling."""
    beats, budgets = _budgets(SHAPED_ROLES)
    start = _mechanism_start_sec(SHAPED_ROLES, beats, budgets)
    worst = max(budgets.values()) / WPS
    assert start <= _deadline_sec(), f"mechanism at {start:.0f}s"
    # One scene target of slack: the cap is words, and words divide unevenly.
    assert worst <= research.SECONDS_PER_SCENE_TARGET + 1.0, f"worst scene {worst:.1f}s"


def test_the_cap_binds_wherever_the_group_can_hold_its_words():
    """Small overshoot is expected and honest; a 2-beat opening group holding 145 words cannot
    fit under a 71-word cap, and losing those words would shorten the film. What must not happen
    is a beat running away to 2-3x the ceiling."""
    beats, budgets = _budgets(SHAPED_ROLES)
    ceiling = research.illustratable_beat_words()
    runaway = {n: w for n, w in budgets.items() if w > ceiling + 3}
    assert not runaway, f"beats far above the {ceiling}-word ceiling: {runaway}"


def test_the_hinge_keeps_its_own_shorter_ceiling():
    """A long hinge is not a hinge; the illustratable cap must not raise its limit."""
    roles = ["setup", "intervention", "mechanism", "hinge", "escalation", "reversal"]
    beats, budgets = _budgets(roles)
    hinge = budgets[beats[roles.index("hinge")]["n"]]
    assert hinge <= cs.MAX_HINGE_WORDS, f"hinge got {hinge} words"


def test_short_form_is_not_regressed():
    """90s films worked before this change and must still allocate sanely."""
    roles = ["setup", "intervention", "mechanism", "escalation", "reversal", "verdict"]
    beats, budgets = _budgets(roles, duration=90)
    start = _mechanism_start_sec(roles, beats, budgets)
    assert start <= _deadline_sec(90)
    assert max(budgets.values()) / WPS <= research.SECONDS_PER_SCENE_TARGET + 1.0
    assert min(budgets.values()) > 0


def test_runtime_is_preserved_by_the_cap():
    """Capping must not quietly shorten the film."""
    for roles in (RUN_10_ROLES, SHAPED_ROLES):
        beats, budgets = _budgets(roles)
        total = runtime_word_bounds(300, len(beats))[0]
        # The hook is prepended by the finalizer and its words are reserved out of the budget
        # before allocation, so the beats sum to slightly under the runtime target by design.
        # What matters is that capping did not silently drop a chunk of the film.
        assert sum(budgets.values()) >= total * 0.95


@pytest.mark.parametrize("duration,expected", [(90, 1), (180, 1), (300, 2)])
def test_the_planner_is_given_a_pre_incentive_budget(duration, expected):
    """The rule that produced the bad plan was never stated to the planner."""
    assert sc._max_events_before_incentive(duration, ENGINE) == expected
    prompt = sc.factual_plan_prompt("Why Hanoi's rat bounty created rat farms",
                                    duration, 60, ENGINE)
    assert f"At most {expected} event(s) may come BEFORE" in prompt
    import event_functions as ef
    required = len(ef.map_for(ENGINE).required)
    expected_events = max(required, research.events_for_runtime(duration))
    assert f"Return about {expected_events} distinct" in prompt


def test_the_event_ask_is_not_scene_count_noise():
    """`count - 3` asked for 57 events at 300s. The ask must track what research can support."""
    prompt = sc.factual_plan_prompt("q", 300, 60, ENGINE)
    assert "Return about 57" not in prompt
    assert f"Return about {research.events_for_runtime(300)} distinct" in prompt
