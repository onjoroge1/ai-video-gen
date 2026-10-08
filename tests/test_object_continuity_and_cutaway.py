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
    # Flow validation 2026-10-07, item 2: arrows are allowed on the cutaway plate only; text
    # stays banned everywhere.
    assert "ARROWS may show direction" in cut and "nothing written on it" in cut
    assert "arrows" in plain and "ARROWS may show direction" not in plain
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


def test_an_empty_state_before_is_repaired_from_the_previous_shot():
    """V13 (2026-10-08): one master state with a blank state_before failed the evidence plan
    after the script, ledger and storyboard were paid for. Same repair as before == after."""
    script = _script()
    beat = script["scenes"][1]["visual_beats"][1]
    beat["state_before"] = ""
    plan = le.compile_evidence_plan(script)
    state = plan["scenes"][1]["states"][1]
    assert state["state_before"], "the previous shot stands in for the missing before"
    assert state["state_before"].casefold() != state["state_after"].casefold()
    codes = {r["code"] for r in plan["repairs"]}
    assert "missing_evidence_state_before_repaired" in codes
    assert plan["validation"]["passed"]


def test_the_ladder_opening_ends_before_the_mechanism_scene():
    """V13 (2026-10-08): the 30% window pinned ten scenes to the first-act location while the
    mechanism was set in the forest; every forest master was refused as the wrong location."""
    roles = ["setup", "setup", "intervention", "intervention", "hinge", "mechanism", "mechanism",
             "escalation", "escalation", "escalation", "escalation", "reversal", "synthesis", "tool"]
    scenes = [{"causal_role": role} for role in roles]
    assert le._opening_scene_count(scenes) == 4, "the 30% window, unchanged for other lanes"
    assert le._opening_scene_count(scenes, ladder=True) == 4
    long = [{"causal_role": "setup"} for _ in range(6)] + scenes[2:]
    assert le._opening_scene_count(long) == 5
    assert le._opening_scene_count(long, ladder=True) == 5, "the 30% window still caps the ladder"
    late = scenes[:5] + [{"causal_role": "escalation"}] * 20
    assert le._opening_scene_count(late) == 8
    assert le._opening_scene_count(late + [{"causal_role": "mechanism"}], ladder=True) == 8
    pinned = [{"causal_role": r} for r in ["setup"] * 2 + ["intervention"] * 2 + ["hinge"]
              + ["mechanism"] * 2 + ["escalation"] * 21]
    assert le._opening_scene_count(pinned) == 8, "V13's shape: 28 scenes, 30% is eight"
    assert le._opening_scene_count(pinned, ladder=True) == 5, "ends before the mechanism"
    script = {"_opening_contract": "ladder_v1", "_story_contract": {}, "scenes": pinned}
    assert le.build_continuity_pack(script)["opening_scene_count"] == 5
