import pytest
from pydantic import ValidationError

from app import ExplainerRequest
from illustrated_story import (
    CINEMATIC,
    ILLUSTRATED_STORY,
    build_storyboard,
    is_enabled,
    story_direction,
    validate_request,
    visual_style_suffix,
)


def _script(count=8):
    scenes = []
    for index in range(count):
        scenes.append({
            "narration": f"Alex takes action {index + 1}, and the result changes what he tries next.",
            "human_intention": "solve the visible problem",
            "human_belief": "the simple plan should work",
            "expected_outcome": "the problem gets smaller",
            "actual_outcome": f"consequence {index + 1} appears",
            "continuity_anchor": "Alex beside the same workshop table",
            "visual_beats": [{
                "anchor_phrase": f"action {index + 1}",
                "purpose": "action",
                "visual": f"Alex performs action {index + 1}",
                "state_before": f"state {index}",
                "state_after": f"state {index + 1}",
                "required_objects": ["Alex", "workshop table"],
            }],
        })
    return {
        "title": "The Plan That Backfired",
        "_story_contract": {
            "human_subject": "Alex",
            "subject_goal": "solve the visible problem",
            "accepted_belief": "the simple plan should work",
            "replacement_model": "each reaction changes the system",
            "opening_object": "Alex's original plan",
        },
        "scenes": scenes,
    }


def test_request_defaults_to_existing_visual_lane_and_accepts_illustrated():
    assert ExplainerRequest(question="x").visual_style == CINEMATIC
    assert ExplainerRequest(
        question="x", visual_style=ILLUSTRATED_STORY).visual_style == ILLUSTRATED_STORY
    with pytest.raises(ValidationError):
        ExplainerRequest(question="x", visual_style="watercolor")


def test_illustrated_lane_isolated_to_ordinary_standard_landscape():
    assert is_enabled(
        visual_style=ILLUSTRATED_STORY,
        video_format="landscape",
        story_format="standard_explainer",
        controlled_pilot=False,
    )
    validate_request(
        visual_style=CINEMATIC,
        video_format="social",
        story_format="evidence_led_mystery",
        controlled_pilot=True,
    )
    with pytest.raises(ValueError, match="landscape"):
        validate_request(
            visual_style=ILLUSTRATED_STORY,
            video_format="social",
            story_format="standard_explainer",
            controlled_pilot=False,
        )
    with pytest.raises(ValueError, match="Standard"):
        validate_request(
            visual_style=ILLUSTRATED_STORY,
            video_format="landscape",
            story_format="evidence_led_mystery",
            controlled_pilot=False,
        )
    with pytest.raises(ValueError, match="pilots"):
        validate_request(
            visual_style=ILLUSTRATED_STORY,
            video_format="landscape",
            story_format="standard_explainer",
            controlled_pilot=True,
        )


def test_story_direction_keeps_operator_input_and_forbids_fact_lists():
    direction = story_direction("Why did the plan fail?", "Keep the narration dry and funny.")
    assert "decision -> action ->" in direction
    assert "Do not write an enumerated fact list" in direction
    assert "Keep the narration dry and funny." in direction


def test_storyboard_is_deterministic_intent_led_and_returns_to_opening():
    script = _script()
    board = build_storyboard(script, "Why did the plan fail?")

    assert board["schema_version"] == "illustrated_story_v1"
    assert board["validation"]["passed"] is True
    assert board["story"]["goal"] == "solve the visible problem"
    assert board["beats"][0]["role"] == "hook"
    assert board["beats"][-1]["role"] == "callback"
    assert board["beats"][-1]["return_object"] == "Alex's original plan"
    assert len(board["visual_bible"]["locations"]) <= 4
    assert all(beat["intent"] for beat in board["beats"])
    assert all(scene["_illustrated_beat"]["scene_index"] == index
               for index, scene in enumerate(script["scenes"]))
    assert script["_illustrated_story"] == board


def test_storyboard_refuses_a_scene_without_narration():
    script = _script()
    script["scenes"][3]["narration"] = ""
    with pytest.raises(ValueError, match="scene 4 has no narration"):
        build_storyboard(script, "Why did the plan fail?")


def test_visual_style_is_consistent_and_keeps_generated_text_out():
    suffix = visual_style_suffix(" Keep the top edge clear.")
    assert "hand-drawn editorial storybook" in suffix
    assert "Not photorealistic" in suffix
    assert "same illustrated Alex identity" in suffix
    assert "No text" in suffix
    assert "Keep the top edge clear" in suffix
