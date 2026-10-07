"""One consistent hive, and one frame that explains (operator brief, 2026-10-07).

The Phase 0 clip drew three different hive boxes under one story and showed the grid as scenery
rather than as a relationship. A beat may now declare object_reference: "opening" (drawn and
verified against the opening object's accepted plate) and explains: true (the one plate that
takes the cutaway instead of the draw-the-moment rule).
"""
import os
import explainer_pipeline as ep
import illustrated_story as lane
import longform_evidence as le
from test_longform_evidence_phase3 import _script


def _plan_with(flags):
    script = _script()
    beat = script["scenes"][1]["visual_beats"][1]
    beat.update(flags)
    return le.compile_evidence_plan(script), script


def test_the_opening_plate_becomes_a_reference_for_a_flagged_state():
    plan, _ = _plan_with({"object_reference": "opening"})
    state = plan["scenes"][1]["states"][1]
    opening_asset = plan["continuity_pack"]["opening_object"]["opening_source_asset_id"]
    assert state["object_reference_asset_id"] == opening_asset == "asset:s001:e01"
    assert opening_asset in state["reference_ids"]
    plain = plan["scenes"][1]["states"][0]
    assert plain["object_reference_asset_id"] == "" and opening_asset not in plain["reference_ids"]
    assert le.validate_evidence_plan(plan)["passed"], "a continuity reference is not a plan defect"


def test_explains_is_carried_and_swaps_the_diagram_rule_for_one_state():
    plan, _ = _plan_with({"explains": True})
    states = plan["scenes"][1]["states"]
    assert states[1]["explains"] is True and states[0]["explains"] is False
    scene = {"causal_role": "false_resolution", "shot_type": "close"}
    cut = ep._scene_style_suffix(lane, scene, states[1], "", True, "")
    plain = ep._scene_style_suffix(lane, scene, states[0], "", True, "")
    assert "EXPLANATORY CUTAWAY" in cut and "never a diagram" not in cut
    assert "never a diagram" in plain and "EXPLANATORY CUTAWAY" not in plain
    assert "no arrows" in cut, "the renderer still owns arrows and text"
    assert ep._scene_style_suffix(lane, scene, states[1], "", False, "legacy") == "legacy"


def test_the_object_reference_reaches_the_generator_and_the_prompt(tmp_path):
    ref = tmp_path / "s001e01.png"
    ref.write_bytes(b"png")
    state = {"include_human": False, "include_bolt": False, "pure_evidence": True,
             "object_reference_asset_id": "asset:s001:e01", "anchor_phrase": "the grid",
             "purpose": "evidence", "state_before": "a", "state_after": "b",
             "required_objects": ["metal grid"], "forbidden_objects": []}
    refs = ep._evidence_reference_paths(state, human_ok=False, mascot_ok=False,
                                        continuity_source=None, object_reference=str(ref))
    assert refs == [str(ref)], "pure evidence still receives the object it is evidence of"
    assert ep._evidence_reference_paths(state, human_ok=False, mascot_ok=False,
                                        object_reference=str(tmp_path / "missing.png")) is None
    pack = {"opening_object": {"label": "a white hive box with a metal grid"}, "first_act_location": {}}
    prompt = ep._evidence_state_prompt({}, state, pack, "")
    assert "OBJECT CONTINUITY" in prompt and "a white hive box with a metal grid" in prompt
    assert "OBJECT CONTINUITY" not in ep._evidence_state_prompt({}, dict(state, object_reference_asset_id=""), pack, "")
