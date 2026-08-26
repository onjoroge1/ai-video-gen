"""The evidence timing gate must guard both ends of the visual-state interval.

It guarded only the dense end. The rendered gate hard-fails the sparse end, so a plan
could pass every pre-spend check and still be rejectable on arithmetic already known --
with the rejection arriving after every image and every second of narration was bought.
"""

from longform_evidence import MAX_VISUAL_STATE_SECONDS, validate_evidence_timing
from longform_rendered_gate import OPENING_MAX_STATE_SECONDS


def _plan(state_counts):
    return {"scenes": [
        {"scene_index": i, "states": [{"state_id": f"s{i}_{j}"} for j in range(n)]}
        for i, n in enumerate(state_counts)
    ]}


def _timing(durations):
    return {"scenes": [{"duration_sec": d} for d in durations]}


def test_the_two_gates_agree_on_the_ceiling():
    # Same number in two files. They must not drift: the whole defect was one validator
    # approving what the other rejects.
    assert MAX_VISUAL_STATE_SECONDS == OPENING_MAX_STATE_SECONDS


def test_two_states_across_a_long_form_scene_is_rejected_before_visual_spend():
    # opening_state_count explicitly permits two states for an opening beat. At the ~13s
    # a long-form scene actually runs, two states hold for 6.5s each -- twice the ceiling.
    report = validate_evidence_timing(_plan([2]), _timing([13.3]))

    assert report["passed"] is False
    codes = [issue["code"] for issue in report["errors"]]
    assert "evidence_states_too_sparse" in codes
    assert "at least 4 states" in report["errors"][0]["message"]


def test_a_scene_short_enough_for_two_states_still_passes():
    # The ceiling is a statement about hold time, not about state count. Two states are
    # fine when the scene is short enough to keep each hold under 3.5s.
    report = validate_evidence_timing(_plan([2]), _timing([6.4]))

    assert report["passed"] is True


def test_both_ends_of_the_interval_are_still_enforced():
    # Sparse scene, dense scene, and one correct scene in between.
    report = validate_evidence_timing(_plan([2, 12, 4]), _timing([13.3, 6.0, 12.0]))

    codes = {issue["code"] for issue in report["errors"]}
    assert codes == {"evidence_states_too_sparse", "evidence_states_too_dense"}
    assert [issue["scene"] for issue in report["errors"]] == [1, 2]


def test_a_plan_the_rendered_gate_accepts_is_not_rejected_here():
    # Guard against over-rejection: 4 states across 12s is 3.0s per hold, inside the
    # ceiling, and must survive a gate that now checks the upper bound.
    report = validate_evidence_timing(_plan([4, 5, 4]), _timing([12.0, 13.0, 11.5]))

    assert report["passed"] is True, report["errors"]
