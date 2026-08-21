import pytest

from longform_shots import (
    compile_scene_shots,
    compile_shot_plan,
    select_alternate_image_indices,
    shot_plan_metrics,
)


def test_long_scene_cuts_stills_faster_than_old_five_second_cadence():
    shots = compile_scene_shots({"story_role": "escalation"}, 9.0, 0)

    assert len(shots) == 3
    assert sum(s["duration"] for s in shots) == pytest.approx(9.0)
    assert max(s["duration"] for s in shots) <= 3.5


def test_generated_motion_keeps_five_seconds_then_returns_to_fast_stills():
    shots = compile_scene_shots(
        {"story_role": "prediction_gate"}, 10.0, 1,
        has_i2v=True, has_alternate=True,
    )

    assert shots[0]["kind"] == "i2v"
    assert shots[0]["duration"] == 5.0
    assert all(s["duration"] <= 3.5 for s in shots[1:])
    assert any(s["source"] == "alternate" for s in shots)
    assert sum(s["duration"] for s in shots) == pytest.approx(10.0)


def test_short_scene_does_not_stretch_i2v_past_narration():
    shots = compile_scene_shots({"story_role": "payoff"}, 3.2, 0, has_i2v=True)

    assert shots == [{
        "kind": "i2v", "source": "master", "duration": 3.2,
        "motion": "generated_motion", "story_role": "payoff",
    }]


def test_plan_metrics_make_visual_cadence_a_testable_contract():
    plan = compile_shot_plan(
        [{"story_role": "mechanism"}, {"story_role": "final_payoff"}],
        [8.0, 9.0], i2v_indices={1}, alternate_indices={0, 1},
    )
    metrics = shot_plan_metrics(plan)

    assert metrics["shot_count"] >= 5
    assert metrics["avg_still_seconds"] < 4.0
    assert metrics["max_still_seconds"] <= 4.5
    assert metrics["i2v_seconds"] == 5.0


def test_alternate_generation_is_bounded_and_prioritizes_retention_turns():
    scenes = [{"story_role": "escalation", "narration": "plain beat"} for _ in range(40)]
    scenes[12]["story_role"] = "reversal"
    scenes[30]["story_role"] = "final_payoff"

    selected = select_alternate_image_indices(scenes, max_images=4)

    assert len(selected) == 4
    assert {12, 30}.issubset(selected)
