import pytest

import tempfile
from pathlib import Path

from longform_shots import (
    MIN_SHOT_SECONDS,
    compile_scene_shots,
    compile_shot_plan,
    select_alternate_image_indices,
    shot_plan_metrics,
)


_TMP = Path(tempfile.mkdtemp(prefix='shot_bed_'))


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


def _measured(scene, duration):
    words = scene["narration"].split()
    step = duration / len(words)
    return [(word, i * step, (i + 1) * step) for i, word in enumerate(words)]


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
    assert shots[0]["new_information"] is False


def test_verified_evidence_states_become_real_asset_aligned_cuts():
    states = [
        {
            "state_id": "state:s001:e01", "asset_id": "asset:s001:e01",
            "asset_strategy": "master", "asset_status": "accepted",
            "anchor_phrase": "The water pulls away", "purpose": "action",
            "verified_visible_information": True,
        },
        {
            "state_id": "state:s001:e02", "asset_id": "asset:s001:e02",
            "asset_strategy": "distinct", "asset_status": "accepted",
            "anchor_phrase": "the continental shelf appears", "purpose": "evidence",
            "verified_visible_information": True,
        },
    ]
    scene = _scene()
    shots = compile_scene_shots(
        scene, 8.0, 0, evidence_states=states, word_times=_measured(scene, 8.0))
    assert [shot["source"] for shot in shots] == ["asset:s001:e01", "asset:s001:e02"]
    assert shots[1]["transition"] == "hard_cut"
    assert shots[1]["new_information"] is True
    metrics = shot_plan_metrics([shots])
    assert metrics["distinct_source_count"] == 2
    assert metrics["meaningful_cut_ratio"] == 1.0


def test_unverified_detail_reframe_does_not_count_as_new_information():
    states = [
        {
            "state_id": "state:s001:e01", "asset_id": "asset:s001:e01",
            "asset_strategy": "master", "asset_status": "accepted",
            "anchor_phrase": "The water pulls away", "purpose": "action",
            "verified_visible_information": True,
        },
        {
            "state_id": "state:s001:e02", "asset_id": "asset:s001:e02",
            "source_asset_id": "asset:s001:e01", "asset_strategy": "detail_reframe",
            "asset_status": "accepted", "anchor_phrase": "the continental shelf appears",
            "purpose": "evidence", "verified_visible_information": False,
        },
    ]
    scene = _scene()
    shots = compile_scene_shots(
        scene, 8.0, 0, evidence_states=states, word_times=_measured(scene, 8.0))
    metrics = shot_plan_metrics([shots])
    assert shots[1]["new_information"] is False
    assert metrics["reframe_shot_count"] == 1
    assert metrics["meaningful_cut_ratio"] == 0.0
    # No longer a cut at all. A reframe that crops the shot before it is rendered as a continuous
    # push from the master onto the crop's framing (explainer_pipeline._make_multishot_background),
    # so there is no same-source hard cut left to count. The count drops because the edit changed,
    # not because the rule did -- see the non-adjacent case below, which still counts.
    assert shots[1]["transition"] == "push_to_detail"
    assert metrics["same_source_hard_cut_count"] == 0


def test_a_reframe_of_a_non_adjacent_asset_stays_a_cut_and_is_not_a_jump_cut():
    """Only the crop of the IMMEDIATELY preceding shot becomes a push.

    Pushing from a master two shots back would invent a camera move the story never asked for.
    It stays a hard cut -- and it is correctly NOT a same-source jump cut either, because the
    picture on screen before it is a different asset.
    """
    states = [
        {"state_id": "state:s001:e01", "asset_id": "asset:s001:e01",
         "asset_strategy": "master", "asset_status": "accepted",
         "anchor_phrase": "The water pulls away", "purpose": "action",
         "verified_visible_information": True},
        {"state_id": "state:s001:e02", "asset_id": "asset:s001:e02",
         "asset_strategy": "distinct", "asset_status": "accepted",
         "anchor_phrase": "the continental shelf appears", "purpose": "evidence",
         "verified_visible_information": True},
        {"state_id": "state:s001:e03", "asset_id": "asset:s001:e03",
         "source_asset_id": "asset:s001:e01",          # crops the FIRST shot, not the previous one
         "asset_strategy": "detail_reframe", "asset_status": "accepted",
         "anchor_phrase": "a drowned riverbed", "purpose": "evidence",
         "verified_visible_information": True},
    ]
    scene = _scene()
    shots = compile_scene_shots(
        scene, 12.0, 0, evidence_states=states, word_times=_measured(scene, 12.0))
    assert shots[2]["transition"] == "hard_cut"
    assert shot_plan_metrics([shots])["same_source_hard_cut_count"] == 0


def test_a_push_that_cannot_be_rendered_is_reported_as_the_jump_cut_it_becomes():
    """The metric's remaining live path, and it must stay live.

    `_make_multishot_background` needs the master on disk to push from. Without it the edit really
    is a cut to a crop of the previous picture, and the shot is downgraded to `hard_cut` on the
    CALLER's list so `shot_plan_metrics` can still see it. A fallback nobody can measure is how a
    quality gate quietly stops measuring anything.
    """
    import explainer_pipeline as ep

    shots = [
        {"kind": "still", "duration": 4.0, "source": "asset:e01", "transition": "continuous",
         "asset_strategy": "master"},
        {"kind": "still", "duration": 4.0, "source": "asset:e02", "transition": "push_to_detail",
         "asset_strategy": "detail_reframe", "source_asset_id": "asset:e01"},
    ]
    output = str(_TMP / "bed.mp4")
    original_segment, original_ffmpeg = ep._make_scene_segment, ep._run_ffmpeg
    try:
        # Write plausible bytes so the render cache and the concat both find their files.
        ep._make_scene_segment = lambda *a, **k: open(a[2], "wb").write(b"\0" * 16)
        ep._run_ffmpeg = lambda cmd, **k: open(cmd[-1], "wb").write(b"\0" * 16)
        # No `evidence_assets`, so the master cannot be found and the push cannot be performed.
        ep._make_multishot_background({"img": str(_TMP / "master.jpg"), "aud": str(_TMP / "a.wav")},
                                      shots, output, 1920, 1080)
    finally:
        ep._make_scene_segment, ep._run_ffmpeg = original_segment, original_ffmpeg

    assert shots[1]["transition"] == "hard_cut", "the caller's shot must record the downgrade"
    assert shot_plan_metrics([shots])["same_source_hard_cut_count"] == 1


def test_too_many_evidence_states_for_audio_duration_fail_instead_of_flash_frames():
    states = [
        {"state_id": f"state:{i}", "asset_id": f"asset:{i}",
         "asset_strategy": "distinct", "asset_status": "accepted",
         "verified_visible_information": True}
        for i in range(4)
    ]
    scene = _scene()
    with pytest.raises(ValueError, match="cannot fit"):
        compile_scene_shots(
            scene, 5.0, 0, evidence_states=states, word_times=_measured(scene, 5.0))


def test_longform_evidence_shots_fail_closed_without_measured_word_timings():
    states = [{
        "state_id": "state:s001:e01", "asset_id": "asset:s001:e01",
        "asset_strategy": "master", "asset_status": "accepted",
        "anchor_phrase": "The water pulls away", "purpose": "action",
        "verified_visible_information": True,
    }]
    with pytest.raises(ValueError, match="Measured word timings are required"):
        compile_scene_shots(_scene(), 8.0, 0, evidence_states=states)
