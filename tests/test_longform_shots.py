import pytest

from longform_shots import (
    MIN_SHOT_SECONDS,
    compile_scene_shots,
    compile_shot_plan,
    select_alternate_image_indices,
    shot_plan_metrics,
)


def _scene():
    return {
        "story_role": "mechanism",
        "narration": (
            "The water pulls away from the coast. "
            "Then the continental shelf appears, exposing drowned river valleys."
        ),
        "motion_anchor_phrase": "water pulls away",
        "visual_beats": [
            {
                "anchor_phrase": "The water pulls away",
                "purpose": "action",
                "visual": "water draining toward the deep basin",
                "source": "master",
                "new_information": True,
            },
            {
                "anchor_phrase": "the continental shelf appears",
                "purpose": "evidence",
                "visual": "exposed shelf and drowned river valleys",
                "source": "broll",
                "new_information": True,
            },
        ],
    }


def test_one_image_uses_one_continuous_camera_path_not_timer_cuts():
    shots = compile_scene_shots(_scene(), 9.0, 0)

    assert len(shots) == 1
    assert shots[0]["duration"] == 9.0
    assert shots[0]["transition"] == "continuous"
    assert shots[0]["motion"] == "continuous_reframe"


def test_broll_cut_lands_on_exact_narration_phrase():
    scene = _scene()
    words = scene["narration"].split()
    step = 8.0 / len(words)
    timings = [(word, i * step, (i + 1) * step) for i, word in enumerate(words)]

    shots = compile_scene_shots(
        scene, 8.0, 0, has_alternate=True, word_times=timings)

    expected_index = words.index("the", words.index("Then"))
    assert len(shots) == 2
    assert shots[1]["start_sec"] == pytest.approx(expected_index * step, abs=0.01)
    assert shots[1]["anchor_phrase"] == "the continental shelf appears"
    assert shots[1]["transition"] == "hard_cut"
    assert shots[1]["new_information"] is True


def test_phrase_alignment_uses_spoken_clock_even_when_transcript_token_count_differs():
    scene = _scene()
    # Whisper can split or omit a token relative to the source narration. The
    # semantic anchor should still use its actual spoken timestamps.
    timings = [
        ("The", 0.0, 0.2),
        ("water", 0.2, 0.6),
        ("pulls", 0.6, 0.9),
        ("away", 0.9, 1.2),
        ("Then", 3.1, 3.4),
        ("the", 3.4, 3.6),
        ("continental", 3.6, 4.0),
        ("shelf", 4.0, 4.3),
        ("appears", 4.3, 4.7),
    ]

    shots = compile_scene_shots(
        scene, 8.0, 0, has_alternate=True, word_times=timings)

    assert shots[1]["start_sec"] == pytest.approx(3.4)


def test_i2v_absorbs_small_remainder_instead_of_flash_frame():
    shots = compile_scene_shots(
        _scene(), 5.38, 0, has_i2v=True, i2v_seconds=5.0)

    assert len(shots) == 1
    assert shots[0]["kind"] == "i2v"
    assert shots[0]["duration"] == pytest.approx(5.38)
    assert all(s["duration"] >= MIN_SHOT_SECONDS for s in shots)


def test_motion_begins_at_semantic_action_when_room_exists():
    scene = _scene()
    scene["narration"] = (
        "At first the coast looks normal and quiet. "
        "Then the water pulls away from the coast with shocking speed."
    )
    scene["motion_anchor_phrase"] = "water pulls away"
    shots = compile_scene_shots(
        scene, 10.0, 0, has_i2v=True, i2v_seconds=5.0)

    assert shots[0]["kind"] == "still"
    assert shots[0]["motion"] == "locked"
    assert shots[1]["kind"] == "i2v"
    assert shots[1]["start_sec"] >= MIN_SHOT_SECONDS
    assert shots[1]["anchor_phrase"] == "water pulls away"


def test_motion_hands_off_to_broll_at_the_evidence_phrase():
    scene = _scene()
    shots = compile_scene_shots(
        scene,
        9.0,
        0,
        has_i2v=True,
        has_alternate=True,
        i2v_seconds=5.0,
    )

    assert [shot["kind"] for shot in shots] == ["i2v", "still"]
    assert shots[1]["source"] == "alternate"
    assert shots[1]["anchor_phrase"] == "the continental shelf appears"
    assert shots[1]["start_sec"] == shots[0]["end_sec"]
    assert all(shot["duration"] >= MIN_SHOT_SECONDS for shot in shots)


def test_plan_metrics_measure_flow_not_only_cut_frequency():
    plan = compile_shot_plan(
        [_scene(), _scene()],
        [8.0, 8.0],
        i2v_indices={1},
        alternate_indices={0},
    )
    metrics = shot_plan_metrics(plan)

    assert metrics["sub_min_shot_count"] == 0
    assert metrics["semantic_sync_ratio"] == 1.0
    assert metrics["meaningful_cut_ratio"] == 1.0
    assert metrics["same_source_hard_cut_count"] == 0
    assert metrics["broll_clause_count"] >= 1


def test_alternate_generation_is_bounded_and_prioritizes_semantic_broll():
    scenes = [{"story_role": "escalation", "narration": "plain beat"} for _ in range(40)]
    scenes[12] = _scene()
    scenes[30]["story_role"] = "final_payoff"

    selected = select_alternate_image_indices(scenes, max_images=4)

    assert selected == {12}


def test_missing_semantic_broll_anchor_never_creates_a_midpoint_hard_cut():
    scene = _scene()
    scene["visual_beats"] = [scene["visual_beats"][0]]

    shots = compile_scene_shots(scene, 8.0, 0, has_alternate=True)

    assert len(shots) == 1
    assert shots[0]["source"] == "master"
