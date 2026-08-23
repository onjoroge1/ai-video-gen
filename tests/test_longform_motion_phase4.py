import inspect
import json
from pathlib import Path

import explainer_pipeline as pipeline
from app import ExplainerRequest, app as fastapi_app
from longform_evidence import compile_evidence_plan
from longform_motion import (
    compile_motion_plan,
    freeze_opening_manifest,
    motion_prompt,
    normalize_motion_mode,
    validate_frozen_opening,
    validate_motion_plan,
)
from longform_shots import compile_scene_shots, shot_plan_metrics


def _beat(anchor, before, after, *, purpose="action", pure=False):
    return {
        "anchor_phrase": anchor,
        "purpose": purpose,
        "visual": after,
        "source": "distinct",
        "asset_strategy": "distinct",
        "state_before": before,
        "state_after": after,
        "required_objects": [after],
        "forbidden_objects": [],
        "pure_evidence": pure,
        "human_visible": not pure,
    }


def _script_and_evidence():
    specs = [
        (4, "cold_consequence", "Alex sees the red gauge jump", "red gauge jump", "still gauge", "jumped gauge"),
        (18, "prediction_test", "Alex releases the marked float", "releases the marked float", "held float", "released float"),
        (42, "reversal", "But the second marker rises instead", "second marker rises", "low marker", "high marker"),
        (58, "reveal", "The hidden current turns the wheel", "hidden current turns", "still wheel", "turning wheel"),
        (76, "mechanism", "The archive diagram records the result", "diagram records the result", "blank record", "completed record"),
        (96, "final_payoff", "Alex returns to the red gauge mark", "returns to the red gauge mark", "unread mark", "understood mark"),
    ]
    scenes = []
    for index, (pct, role, narration, anchor, before, after) in enumerate(specs):
        beats = [_beat(anchor, before, after,
                       purpose="diagram" if role == "mechanism" else "action",
                       pure=role == "mechanism")]
        if pct <= 30:
            beats.append(_beat("red gauge jump" if index == 0 else "marked float",
                               "missing corroboration", "visible corroborating evidence",
                               purpose="evidence", pure=True))
            if index == 1:
                narration += " beside the marked float"
        scenes.append({
            "story_pct": pct,
            "story_role": role,
            "narration": narration,
            "motion_anchor_phrase": anchor,
            "human_present": role != "mechanism",
            "mascot_present": False,
            "continuity_anchor": "Alex at the harbor tide gauge",
            "visual_beats": beats,
        })
    script = {
        "_story_contract": {
            "opening_object": "the red gauge mark",
            "final_callback_object": "the red gauge mark",
            "recurring_location": "the harbor tide gauge",
        },
        "scenes": scenes,
    }
    evidence = compile_evidence_plan(script)
    assert evidence["validation"]["passed"] is True
    return script, evidence


def test_motion_modes_normalize_and_legacy_false_maps_to_stills():
    assert normalize_motion_mode("Stills") == "stills"
    assert normalize_motion_mode("Full Motion") == "full_motion"
    assert normalize_motion_mode(None, legacy_i2v=False) == "stills"
    assert normalize_motion_mode(None) == "standard"


def test_stills_selects_and_purchases_zero_motion():
    script, evidence = _script_and_evidence()
    plan = compile_motion_plan(script, evidence, mode="stills", max_requests=12)
    assert plan["selected_count"] == 0
    assert not [candidate for candidate in plan["candidates"] if candidate["selected"]]
    assert plan["validation"]["passed"] is True


def test_standard_reserves_hook_test_reversal_reveal_and_callback():
    script, evidence = _script_and_evidence()
    plan = compile_motion_plan(script, evidence, mode="standard", max_requests=12)
    classes = {candidate["priority_class"] for candidate in plan["candidates"]
               if candidate["selected"]}
    assert {"hook", "test", "reversal", "reveal", "callback"}.issubset(classes)
    assert plan["validation"]["passed"] is True


def test_full_motion_requests_every_eligible_state_within_cap():
    script, evidence = _script_and_evidence()
    plan = compile_motion_plan(script, evidence, mode="full_motion", max_requests=4)
    eligible = [candidate for candidate in plan["candidates"] if candidate["eligible"]]
    selected = [candidate for candidate in plan["candidates"] if candidate["selected"]]
    assert plan["selected_count"] == 4
    assert plan["capped_out_count"] == len(eligible) - 4
    assert selected[0]["motion_id"] == eligible[0]["motion_id"]
    assert selected[-1]["motion_id"] == eligible[-1]["motion_id"]


def test_static_diagram_is_not_motion_eligible():
    script, evidence = _script_and_evidence()
    plan = compile_motion_plan(script, evidence, mode="full_motion", max_requests=12)
    diagram = next(candidate for candidate in plan["candidates"]
                   if candidate["purpose"] == "diagram")
    assert diagram["eligible"] is False
    assert diagram["selected"] is False
    assert "static diagram" in diagram["ineligible_reason"]


def test_motion_alignment_below_ninety_percent_fails():
    script, evidence = _script_and_evidence()
    plan = compile_motion_plan(script, evidence, mode="full_motion", max_requests=12)
    selected = [candidate for candidate in plan["candidates"] if candidate["selected"]]
    for candidate in selected[:2]:
        candidate["semantic_aligned"] = False
    report = validate_motion_plan(plan)
    assert report["passed"] is False
    assert report["semantic_alignment_ratio"] < 0.90
    assert {error["code"] for error in report["errors"]} == {"motion_semantic_alignment"}


def test_pure_evidence_motion_prompt_forbids_character_invention():
    candidate = {
        "anchor_phrase": "the waterline falls", "state_before": "high water",
        "state_after": "low water", "story_role": "test", "purpose": "evidence",
        "pure_evidence": True,
    }
    prompt = motion_prompt(candidate)
    assert "Do not introduce Bolt or any character" in prompt
    assert "no camera move presented as evidence" in prompt


def test_frozen_opening_detects_any_changed_segment(tmp_path):
    segment = tmp_path / "opening.mp4"
    clip = tmp_path / "motion.mp4"
    segment.write_bytes(b"approved segment")
    clip.write_bytes(b"approved motion")
    manifest_path = tmp_path / "opening_freeze.json"
    manifest = freeze_opening_manifest({0: str(segment)}, {"state:1": str(clip)}, str(manifest_path))
    assert validate_frozen_opening(manifest)["passed"] is True
    segment.write_bytes(b"changed segment")
    report = validate_frozen_opening(manifest)
    assert report["passed"] is False
    assert report["errors"][0]["code"] == "frozen_opening_changed"


def test_motion_does_not_create_an_evidence_event_without_pixel_verification():
    scene = {"story_role": "test", "narration": "The marked float drops now"}
    states = [{
        "state_id": "state:s001:e01", "asset_id": "asset:s001:e01",
        "asset_strategy": "master", "asset_status": "accepted",
        "anchor_phrase": "marked float drops", "purpose": "action",
        "verified_visible_information": False,
    }]
    shots = compile_scene_shots(
        scene, 5.0, 0, evidence_states=states,
        motion_state_ids={"state:s001:e01"})
    assert shots[0]["kind"] == "i2v"
    assert shots[0]["new_information"] is False
    metrics = shot_plan_metrics([shots])
    assert metrics["verified_information_shot_count"] == 0


def test_opening_motion_generation_precedes_gate_render_in_orchestrator():
    source = inspect.getsource(pipeline.run_explainer_pipeline)
    assert source.index("_generate_longform_motion(opening_results") < source.index(
        "_render_first_minute_preview(")
    assert "frozen approved opening reused" in source


def test_motion_controls_and_reports_are_exposed_in_ui_and_api():
    html = Path("static/index.html").read_text()
    assert 'id="expl-motion-mode"' in html
    for value in ("stills", "standard", "full_motion"):
        assert f'value="{value}"' in html
    request = ExplainerRequest(question="Why does the tide move?", motion_mode="full_motion")
    assert request.motion_mode == "full_motion"
    paths = {getattr(route, "path", "") for route in fastapi_app.routes}
    assert {
        "/api/explainer/motion/{job_id}",
        "/api/explainer/opening-freeze/{job_id}",
    }.issubset(paths)


def test_motion_report_is_json_serializable():
    script, evidence = _script_and_evidence()
    plan = compile_motion_plan(script, evidence, mode="standard", max_requests=12)
    assert json.loads(json.dumps(plan))["validation"]["passed"] is True
