from pathlib import Path
import base64
import inspect
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import explainer_pipeline as pipeline
from openai.resources.images import Images
from app import ExplainerRequest
from longform_retention import validate_longform_story
from test_longform_retention import _passing_script


def _codes(script):
    return {item["code"] for item in validate_longform_story(script)["errors"]}


def test_request_exposes_only_the_two_approved_story_structures():
    assert ExplainerRequest(question="x").story_format == "standard_explainer"
    assert ExplainerRequest(question="x", story_format="evidence_led_mystery").story_format \
        == "evidence_led_mystery"
    with pytest.raises(ValidationError):
        ExplainerRequest(question="x", story_format="consequence_list")


def test_character_budget_makes_bolt_selective_and_keeps_useful_roles():
    beats = [
        {"n": i + 1, "role": "prediction_gate" if i == 2 else "escalation",
         "bolt_mode": "measurement"}
        for i in range(20)
    ]
    report = pipeline._apply_character_budget(beats)
    kept = [i for i, beat in enumerate(beats) if beat["bolt_mode"] != "absent"]
    assert len(kept) <= 6
    assert sum(1 for i in kept if i < 6) <= 2
    assert 2 in kept
    assert report["overrides"]


def test_bolt_is_forced_absent_from_pure_mechanism_beats():
    beats = [
        {"n": 1, "role": "mechanism", "bolt_mode": "measurement"},
        {"n": 2, "role": "rules", "bolt_mode": "demonstration"},
        {"n": 3, "role": "reversal", "bolt_mode": "reaction"},
        {"n": 4, "role": "payoff", "bolt_mode": "absent"},
    ]
    pipeline._apply_character_budget(beats)
    assert beats[0]["bolt_mode"] == "absent"
    assert beats[1]["bolt_mode"] == "absent"
    assert beats[2]["bolt_mode"] == "reaction"


def test_mystery_suitability_requires_real_test_and_belief_change():
    plan = {
        "anomaly": "The gauge rises in calm weather",
        "accepted_belief": "wind caused it",
        "contradictory_evidence": "the anemometer is still",
        "recurring_location": "tide observatory",
        "subject_goal": "explain the reading",
        "mystery_suitable": True,
    }
    weak = [{"visible_consequence": f"clue {i}"} for i in range(3)]
    suitable, reasons = pipeline._evaluate_mystery_suitability(plan, weak)
    assert suitable is False
    assert "no failed prediction or test" in reasons
    assert "no evidence-led belief change" in reasons

    strong = [
        {"visible_consequence": "water crosses the mark", "expected_outcome": "stays below",
         "actual_outcome": "crosses the mark", "belief_changed": "normal -> anomalous"},
        {"visible_consequence": "wind needle stays still", "actual_outcome": "calm"},
        {"visible_consequence": "record line is exceeded", "actual_outcome": "new maximum"},
    ]
    assert pipeline._evaluate_mystery_suitability(plan, strong) == (True, [])


def test_missing_human_goal_is_blocking():
    script = _passing_script()
    script["_story_contract"]["subject_goal"] = ""
    assert "incomplete_human_story_contract" in _codes(script)


def test_fake_knowledge_gap_is_blocking():
    script = _passing_script()
    for scene in script["scenes"]:
        scene["human_knows"] = scene["viewer_knows"]
    assert "no_viewer_human_knowledge_gap" in _codes(script)


def test_evidence_must_change_belief_and_force_a_decision():
    script = _passing_script()
    for scene in script["scenes"]:
        scene["belief_changed"] = ""
        scene["decision_caused"] = ""
    assert "evidence_never_forces_decision" in _codes(script)


def test_placeholder_belief_and_decision_values_do_not_pass():
    script = _passing_script()
    for scene in script["scenes"]:
        scene["belief_changed"] = "unchanged"
        scene["decision_caused"] = "none"
    assert "evidence_never_forces_decision" in _codes(script)


def test_three_uncausal_consequence_beats_are_rejected():
    script = _passing_script()
    for scene in script["scenes"][11:14]:
        for key in ("causal_link", "decision_caused", "belief_changed",
                    "question_answered", "new_complication"):
            scene[key] = ""
    assert "consequence_enumeration" in _codes(script)


def test_and_then_does_not_count_as_a_causal_link():
    script = _passing_script()
    for scene in script["scenes"][11:14]:
        scene["causal_link"] = "and then another consequence"
        for key in ("decision_caused", "belief_changed", "question_answered", "new_complication"):
            scene[key] = ""
    assert "consequence_enumeration" in _codes(script)


def test_broken_opening_object_callback_is_rejected():
    script = _passing_script()
    script["_story_contract"]["final_callback_object"] = "a different gauge"
    assert "broken_opening_object_callback" in _codes(script)


def test_decorative_or_over_budget_bolt_is_rejected():
    script = _passing_script()
    for scene in script["scenes"][:12]:
        scene["mascot_present"] = True
        scene["bolt_mode"] = "observation"
    codes = _codes(script)
    assert "bolt_presence_budget_exceeded" in codes
    assert "decorative_bolt" in codes


def test_unsuitable_mystery_requires_standard_fallback_and_reason():
    script = _passing_script()
    contract = script["_story_contract"]
    contract["mystery_suitable"] = False
    contract["story_format_effective"] = "evidence_led_mystery"
    contract["story_format_fallback_reason"] = ""
    assert "invalid_mystery_fallback" in _codes(script)


def test_standard_structure_fixture_passes_the_same_human_contract():
    script = _passing_script()
    contract = script["_story_contract"]
    contract["story_format_requested"] = "standard_explainer"
    contract["story_format_effective"] = "standard_explainer"
    contract["mystery_suitable"] = False
    assert validate_longform_story(script)["passed"] is True


def test_human_reference_and_ui_controls_are_present():
    assert Path(pipeline.HUMAN_REF).is_file()
    html = Path("static/index.html").read_text()
    assert 'id="expl-story-format"' in html
    assert 'value="evidence_led_mystery"' in html
    assert 'id="expl-direction"' in html


def test_scene_identity_references_are_ordered_and_optional():
    both = pipeline._scene_reference_paths(
        {"human_present": True, "mascot_present": True}, human_ok=True, mascot_ok=True)
    assert both == [pipeline.HUMAN_REF, pipeline.MASCOT_REF]
    assert pipeline._scene_reference_paths(
        {"human_present": True, "mascot_present": False}, human_ok=True, mascot_ok=True
    ) == [pipeline.HUMAN_REF]
    assert pipeline._scene_reference_paths(
        {"human_present": False, "mascot_present": False}, human_ok=True, mascot_ok=True
    ) is None


def test_pinned_image_sdk_supports_the_parameters_used_by_the_renderer():
    params = inspect.signature(Images.edit).parameters
    assert {"image", "model", "prompt", "quality", "size"}.issubset(params)


def test_renderer_submits_both_identity_references_to_image_edit(monkeypatch, tmp_path):
    human = tmp_path / "human.png"
    bolt = tmp_path / "bolt.png"
    human.write_bytes(b"human")
    bolt.write_bytes(b"bolt")
    captured = {}

    class FakeImages:
        def edit(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                data=[SimpleNamespace(b64_json=base64.b64encode(b"result").decode())],
                usage=None,
            )

    monkeypatch.setattr(pipeline, "_openai", lambda: SimpleNamespace(images=FakeImages()))
    monkeypatch.setattr(pipeline, "_image_cost_from_usage", lambda _response: 0.0)
    output = tmp_path / "scene.jpg"
    pipeline.generate_image("Alex and Bolt test the gauge", str(output),
                            reference_paths=[str(human), str(bolt)])

    assert isinstance(captured["image"], list)
    assert [Path(item.name).name for item in captured["image"]] == ["human.png", "bolt.png"]
    assert captured["quality"] == "medium"
    assert captured["size"] == "1536x1024"
    assert output.read_bytes() == b"result"


def test_safe_fallback_respects_declared_cast():
    human_only = pipeline.safe_image_prompt({
        "human_present": True, "mascot_present": False, "text_overlay": "THE MARK"})
    evidence_only = pipeline.safe_image_prompt({
        "human_present": False, "mascot_present": False, "text_overlay": "THE MARK"})
    assert "Alex actively investigating" in human_only
    assert "Bolt" not in human_only
    assert "no characters" in evidence_only


def test_mystery_expansion_preserves_delayed_reveal_and_avoids_roadmap():
    mystery = pipeline._opening_expansion_direction("evidence_led_mystery", True)
    standard = pipeline._opening_expansion_direction("standard_explainer", True)
    assert "MYSTERY OPENING" in mystery
    assert "do not announce stages" in mystery
    assert "deepest cause" in mystery
    assert "ANSWER FAST" not in mystery
    assert "ANSWER FAST" in standard
    assert pipeline._opening_expansion_direction("evidence_led_mystery", False) == ""


def test_string_false_values_do_not_turn_characters_or_mystery_on():
    assert pipeline._plan_bool("false", True) is False
    plan = {
        "anomaly": "a", "accepted_belief": "b", "contradictory_evidence": "c",
        "recurring_location": "d", "subject_goal": "e", "mystery_suitable": "false",
    }
    beats = [
        {"visible_consequence": str(i), "expected_outcome": "x", "actual_outcome": "y",
         "belief_changed": "x -> y"} for i in range(3)
    ]
    assert pipeline._evaluate_mystery_suitability(plan, beats)[0] is False


def test_chunked_planner_carries_human_causality_into_mystery_expansion(monkeypatch):
    beats = []
    roles = ["cold_consequence", "prediction_gate", "payoff", "final_payoff"]
    for i, role in enumerate(roles):
        beats.append({
            "n": i + 1, "pct": i * 33, "beat": f"Evidence move {i + 1}", "role": role,
            "human_present": True, "human_intention": f"Alex tests clue {i + 1}",
            "human_belief": "The old explanation still holds" if i < 2 else "The gauge disproves it",
            "viewer_knows": "The gauge is moving" if i == 0 else f"Clue {i + 1}",
            "human_knows": "The gauge seems normal" if i == 0 else f"Clue {i + 1}",
            "expected_outcome": "The mark stays dry", "actual_outcome": f"Water reaches mark {i + 1}",
            "belief_changed": "normal -> anomalous" if i == 2 else "",
            "decision_caused": "Alex checks the archive" if i == 2 else "",
            "continuity_anchor": "red tide gauge", "causal_link": "therefore Alex tests the next mark",
            "visible_consequence": f"Water reaches mark {i + 1}",
            "bolt_mode": "measurement" if i == 1 else "absent",
        })
    plan = {
        "title": "Why Is the Tide Gauge Moving?", "hook": "The red mark is underwater.",
        "thumbnail_promise": "The impossible gauge reading", "throughline": "Explain the moving gauge",
        "false_model": "Wind moved it", "replacement_model": "A remote surge reached the bay",
        "personal_stake": "Alex must decide whether to warn the harbor", "anomaly": "A calm-day surge",
        "human_subject": "Alex", "human_role": "harbor observer", "recurring_location": "tide station",
        "subject_goal": "explain the reading", "antagonistic_force": "the hidden surge",
        "accepted_belief": "calm water cannot rise", "contradictory_evidence": "the red mark is submerged",
        "viewer_initial_belief": "the gauge failed", "viewer_belief_after_reveal": "the surge is real",
        "opening_object": "red tide-gauge mark", "final_callback_object": "red tide-gauge mark",
        "mystery_suitable": True, "mystery_unsuitable_reason": "", "style_mode": "cinematic",
        "stages": ["THE MARK", "THE ARCHIVE"], "peak_scene": 3, "payoffs": [3, 4], "beats": beats,
    }
    scenes = [{
        "narration": f"The tide gauge reveals clue {i + 1}.",
        "image_prompt": f"Alex tests the red tide gauge for clue {i + 1}",
        "scene_type": "experiment_lab", "environment_type": "nature", "shot_type": "medium",
        "text_overlay": "", "text_sub": "", "visual_beats": [],
    } for i in range(4)]
    responses = [plan, {"scenes": scenes}]
    prompts = []

    class FakeMessages:
        def create(self, **kwargs):
            prompts.append(kwargs["messages"][0]["content"])
            payload = responses.pop(0)
            return SimpleNamespace(
                content=[SimpleNamespace(text=json.dumps(payload))],
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            )

    monkeypatch.setattr(pipeline, "_claude", lambda: SimpleNamespace(messages=FakeMessages()))
    monkeypatch.setattr(pipeline, "_dedupe_narration", lambda current, *_args: (current, 0.0))

    script = pipeline._generate_script_chunked(
        "Why is the tide gauge moving?", 90, "cinematic", "", 4,
        story_format="evidence_led_mystery")

    assert script["_story_format"] == "evidence_led_mystery"
    assert all(scene["human_present"] for scene in script["scenes"])
    assert script["scenes"][1]["bolt_mode"] == "measurement"
    assert '"human_intention": "Alex tests clue 1"' in prompts[1]
    assert "MYSTERY OPENING" in prompts[1]
    assert "do not announce stages" in prompts[1]
