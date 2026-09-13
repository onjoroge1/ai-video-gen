from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import explainer_pipeline as pipeline
from app import app as fastapi_app
from longform_evidence import (
    build_continuity_pack,
    compile_evidence_plan,
    evidence_asset_counts,
    record_asset_verification,
    reuse_exact_asset,
    validate_evidence_plan,
    validate_evidence_timing,
)


def _beat(anchor, before, after, *, purpose="evidence", source="distinct", **extra):
    beat = {
        "anchor_phrase": anchor,
        "purpose": purpose,
        "visual": after,
        "source": source,
        "state_before": before,
        "state_after": after,
        "required_objects": [after],
        "forbidden_objects": [],
    }
    beat.update(extra)
    return beat


def _script():
    return {
        "_story_contract": {
            "opening_object": "Alex's red tide-gauge mark",
            "final_callback_object": "Alex's red tide-gauge mark",
            "recurring_location": "the century-old coastal tide gauge",
        },
        "scenes": [
            {
                "story_pct": 4,
                "story_role": "cold_consequence",
                "human_present": True,
                "mascot_present": True,
                "continuity_anchor": "Alex at the century-old coastal tide gauge",
                "visual_beats": [
                    _beat("the red mark is dry", "red mark at the waterline",
                          "the same red mark visibly above the water", source="master",
                          purpose="action", pure_evidence=False, human_visible=True,
                          bolt_visible=True, bolt_action="measures the exposed red mark"),
                    _beat("wet mud below it", "unreadable shoreline",
                          "fresh wet mud and shell line below the red mark"),
                ],
            },
            {
                "story_pct": 22,
                "story_role": "mechanism",
                "human_present": False,
                "mascot_present": True,
                "continuity_anchor": "the century-old coastal tide gauge",
                "visual_beats": [
                    _beat("the float drops", "float aligned with the red mark",
                          "gauge float physically lower than the red mark", source="master"),
                    _beat("the ruler confirms it", "unmeasured gap",
                          "ruler showing the gap beside the gauge"),
                ],
            },
            {
                "story_pct": 96,
                "story_role": "final_payoff",
                "human_present": True,
                "mascot_present": False,
                "continuity_anchor": "Alex at the century-old coastal tide gauge",
                "visual_beats": [
                    _beat("Alex reads the answer", "Alex uncertain",
                          "Alex understands the measurement", source="master",
                          purpose="decision", pure_evidence=False, human_visible=True),
                ],
            },
        ],
    }


def _accept_all(plan, tmp_path):
    for scene in plan["scenes"]:
        for state in scene["states"]:
            path = tmp_path / (state["asset_id"].replace(":", "-") + ".jpg")
            path.write_bytes(b"image")
            record_asset_verification(
                state, asset_path=str(path),
                verification={"passed": True, "visible_information": True, "reasons": []})


def _codes(report):
    return {error["code"] for error in report["errors"]}


def test_opening_beats_compile_to_two_distinct_evidence_states():
    plan = compile_evidence_plan(_script())
    assert plan["validation"]["passed"] is True
    opening = [scene for scene in plan["scenes"] if scene["opening"]]
    assert [len(scene["states"]) for scene in opening] == [2, 2]
    assert all(len({state["asset_id"] for state in scene["states"]}) >= 2 for scene in opening)


def test_pure_evidence_deterministically_omits_bolt_and_reference():
    plan = compile_evidence_plan(_script())
    mechanism_states = plan["scenes"][1]["states"]
    assert all(state["pure_evidence"] for state in mechanism_states)
    assert all(state["include_bolt"] is False for state in mechanism_states)
    assert all("reference:bolt:mascot:v1" not in state["reference_ids"]
               for state in mechanism_states)


def test_bolt_is_opted_in_per_compiled_state_and_frequency_is_state_based():
    plan = compile_evidence_plan(_script())
    first = plan["scenes"][0]["states"]
    assert [state["include_bolt"] for state in first] == [True, False]
    validation = plan["validation"]
    assert validation["useful_bolt_state_count"] == 1
    assert validation["compiled_visual_state_count"] > len(plan["scenes"])
    assert 0 < validation["bolt_visual_state_ratio"] <= 0.35


def test_zero_or_over_budget_compiled_bolt_states_fail_before_assets():
    plan = compile_evidence_plan(_script())
    for scene in plan["scenes"]:
        for state in scene["states"]:
            state["include_bolt"] = False
            state["bolt_action"] = ""
            state["reference_ids"] = [item for item in state.get("reference_ids") or []
                                      if item != "reference:bolt:mascot:v1"]
    assert "missing_useful_bolt_state" in _codes(validate_evidence_plan(plan))

    plan = compile_evidence_plan(_script())
    bolt_state = next(
        state for scene in plan["scenes"] for state in scene["states"]
        if state.get("include_bolt"))
    bolt_state["bolt_action"] = "measurement"
    assert "bolt_without_useful_action" in _codes(validate_evidence_plan(plan))

    plan = compile_evidence_plan(_script())
    for scene in plan["scenes"]:
        for state in scene["states"]:
            if state.get("purpose") == "callback":
                continue
            state.update(include_bolt=True, pure_evidence=False, purpose="action",
                         bolt_action="actively measures the evidence")
            state["reference_ids"] = list(dict.fromkeys(
                (state.get("reference_ids") or []) + ["reference:bolt:mascot:v1"]))
    assert "bolt_state_budget_exceeded" in _codes(validate_evidence_plan(plan))


def _opening_with_a_surviving_reframe():
    """An opening that already carries two generated assets, so its reframe is not promoted.

    These two tests used to set the OPENING'S SECOND beat to a reframe, which left the opening with
    one generated asset. That configuration is now repaired rather than rejected (see
    `test_an_opening_reframe_is_promoted_rather_than_deadlocking`), so the reframe's own properties
    have to be asserted where a reframe legitimately survives: third state, after master+distinct.
    """
    script = _script()
    script["scenes"][0]["visual_beats"].append(
        _beat("the shell line above it", "fresh wet mud and shell line below the red mark",
              "a close crop of the shell line above the red mark", source="reframe"))
    return script


def test_opening_object_can_transform_and_reframe_uses_previous_evidence_state():
    plan = compile_evidence_plan(_opening_with_a_surviving_reframe())
    first, second, third = plan["scenes"][0]["states"][:3]
    assert "Alex's red tide-gauge mark" in first["required_objects"]
    assert "Alex's red tide-gauge mark" not in second["required_objects"]
    assert third["asset_strategy"] == "detail_reframe", "not promoted: the opening already has two"
    # The PREVIOUS evidence state, which is what this test's name is about -- a reframe crops the
    # state immediately before it, not always the scene's master.
    assert third["source_asset_id"] == second["asset_id"]


def test_reframe_never_claims_information_before_detail_verification():
    plan = compile_evidence_plan(_opening_with_a_surviving_reframe())
    state = plan["scenes"][0]["states"][2]
    assert state["asset_strategy"] == "detail_reframe"
    assert state["new_information"] is False


def test_an_opening_reframe_is_promoted_rather_than_deadlocking():
    """The gate this replaces was unsatisfiable at plan time, and it cost a live run.

    `insufficient_distinct_evidence_assets` wants two generated opening assets OR a pixel-verified
    reframe. `detail_verification_passed` is only written after generation, so at plan time the
    second option can never be true. Whether the opening's second beat is a reframe is the model's
    choice, so the abort was a coin flip on one token -- after research, script, fact-check and
    claim repair were all paid for.
    """
    script = _script()
    script["scenes"][0]["visual_beats"][1]["source"] = "reframe"
    plan = compile_evidence_plan(script)

    assert "insufficient_distinct_evidence_assets" not in _codes(plan["validation"])
    assert plan["validation"]["passed"], plan["validation"]["errors"]

    promoted = plan["scenes"][0]["states"][1]
    assert promoted["asset_strategy"] == "distinct"
    # Required, not cosmetic: a distinct state that still names a source trips missing_source_asset.
    assert promoted["source_asset_id"] == ""
    assert promoted["detail_target"] == ""
    assert promoted["new_information"] is False, "a promoted state has still not been verified"

    # The change is recorded, not silent -- the plan differs from the script the model wrote.
    assert [r["code"] for r in plan["repairs"]] == ["opening_reframe_promoted"]
    assert plan["repairs"][0]["state_id"] == promoted["state_id"]


def test_promotion_touches_only_the_opening_and_only_when_it_is_short():
    """A reframe outside the opening, or one the opening does not need, is left alone."""
    script = _script()
    # Past the opening tranche, not merely past scene zero: build_continuity_pack reports an
    # opening_scene_count of 2 here, so scene 1 is still an opening scene. No non-opening scene in
    # the fixture has a second beat, so give the last one a reframe to crop.
    opening_count = int(build_continuity_pack(script)["opening_scene_count"])
    later_index = next(index for index in range(len(script["scenes"]))
                       if index >= opening_count)
    script["scenes"][later_index]["visual_beats"].append(
        _beat("a close crop of it", "the wider shot",
              "a close crop of the same detail", source="reframe"))
    plan = compile_evidence_plan(script)

    assert plan["repairs"] == [], "a non-opening reframe is not the deadlock and is not touched"
    assert any(state["asset_strategy"] == "detail_reframe"
               for state in plan["scenes"][later_index]["states"]), "the reframe survived"

    # And an opening that already carries two generated assets is left alone too.
    untouched = compile_evidence_plan(_opening_with_a_surviving_reframe())
    assert untouched["repairs"] == []


def test_unverified_reframe_cannot_be_manually_marked_as_new_information():
    plan = compile_evidence_plan(_script())
    state = plan["scenes"][0]["states"][1]
    state["asset_strategy"] = "detail_reframe"
    state["new_information"] = True
    assert "unverified_reframe_information" in _codes(validate_evidence_plan(plan))


def test_opening_state_failure_is_explicit_rejection_not_silent_reframe(tmp_path):
    plan = compile_evidence_plan(_script())
    state = plan["scenes"][0]["states"][1]
    record_asset_verification(
        state, asset_path=str(tmp_path / "missing.jpg"), verification=None,
        generation_error="provider timeout")
    assert state["asset_status"] == "rejected"
    assert state["asset_strategy"] == "distinct"
    assert state["new_information"] is False
    assert "provider timeout" in state["rejection_reasons"]


def test_verified_opening_information_ratio_must_reach_seventy_percent(tmp_path):
    plan = compile_evidence_plan(_script())
    _accept_all(plan, tmp_path)
    assert validate_evidence_plan(plan, require_verified_assets=True)["passed"] is True

    plan["scenes"][0]["states"][1]["verified_visible_information"] = False
    plan["scenes"][1]["states"][1]["verified_visible_information"] = False
    report = validate_evidence_plan(plan, require_verified_assets=True)
    assert "opening_visible_information_ratio" in _codes(report)


def test_continuity_ids_are_stable_and_bind_identity_clothing_location_object():
    first = build_continuity_pack(_script())
    second = build_continuity_pack(deepcopy(_script()))
    assert first == second
    assert first["human"]["identity_id"] == "character:alex:v1"
    assert first["human"]["clothing_id"].startswith("clothing:alex:")
    assert first["first_act_location"]["location_id"].startswith("location:")
    assert first["opening_object"]["object_id"].startswith("object:")


def test_ending_reuses_exact_opening_asset_id():
    plan = compile_evidence_plan(_script())
    opening_asset = plan["scenes"][0]["states"][0]["asset_id"]
    callback = plan["scenes"][-1]["states"][-1]
    assert callback["asset_strategy"] == "exact_reuse"
    assert callback["source_asset_id"] == opening_asset
    assert callback["anchor_phrase"] == "Alex reads the answer"


def test_exact_callback_reuse_is_byte_identical(tmp_path):
    source = tmp_path / "opening.jpg"
    callback = tmp_path / "callback.jpg"
    source.write_bytes(b"opening-object-pixels\x00\x01")
    report = reuse_exact_asset(str(source), str(callback))
    assert report["passed"] is True
    assert report["source_sha256"] == report["exact_reuse_sha256"]
    assert callback.read_bytes() == source.read_bytes()


def test_asset_accounting_separates_distinct_reframe_and_reuse():
    plan = compile_evidence_plan(_script())
    plan["scenes"][0]["states"][1]["asset_strategy"] = "detail_reframe"
    counts = evidence_asset_counts(plan)
    assert counts["reframe_count"] == 1
    assert counts["exact_reuse_count"] == 1
    assert counts["distinct_source_count"] == counts["planned_state_count"] - 2


def test_missing_opening_state_is_fail_closed():
    script = _script()
    script["scenes"][0]["visual_beats"] = script["scenes"][0]["visual_beats"][:1]
    report = compile_evidence_plan(script)["validation"]
    assert "opening_state_count" in _codes(report)


def test_zero_percent_scene_is_part_of_opening():
    script = _script()
    script["scenes"][0]["story_pct"] = 0
    assert build_continuity_pack(script)["opening_scene_count"] == 2


def test_measured_audio_rejects_evidence_states_that_would_flash():
    plan = compile_evidence_plan(_script())
    timing = {"scenes": [
        {"duration_sec": 2.5}, {"duration_sec": 8.0}, {"duration_sec": 8.0},
    ]}
    report = validate_evidence_timing(plan, timing)
    assert report["passed"] is False
    assert "evidence_states_too_dense" in _codes(report)


def test_reference_routing_is_identity_first_and_never_sends_bolt_to_pure_evidence(
        monkeypatch, tmp_path):
    human, bolt, continuity = tmp_path / "human.png", tmp_path / "bolt.png", tmp_path / "master.jpg"
    for path in (human, bolt, continuity):
        path.write_bytes(b"asset")
    monkeypatch.setattr(pipeline, "HUMAN_REF", str(human))
    monkeypatch.setattr(pipeline, "MASCOT_REF", str(bolt))
    refs = pipeline._evidence_reference_paths(
        {"include_human": True, "include_bolt": True, "pure_evidence": False},
        human_ok=True, mascot_ok=True, continuity_source=str(continuity))
    assert refs == [str(human), str(bolt), str(continuity)]
    evidence_refs = pipeline._evidence_reference_paths(
        {"include_human": False, "include_bolt": True, "pure_evidence": True},
        human_ok=True, mascot_ok=True, continuity_source=str(continuity))
    assert evidence_refs is None


def test_pixel_verifier_fails_when_required_object_is_missing(monkeypatch, tmp_path):
    image = tmp_path / "evidence.jpg"
    image.write_bytes(b"jpeg")
    state = compile_evidence_plan(_script())["scenes"][0]["states"][0]
    required = state["required_objects"]
    payload = {
        "required_objects": {item: False for item in required},
        "forbidden_objects_absent": {},
        "visible_information": True,
        "human_identity_matches": True,
        "clothing_matches": True,
        "location_matches": True,
        "opening_object_matches": False,
        "bolt_present": False,
        "reasons": ["the red gauge mark is not visible"],
    }

    class Messages:
        def create(self, **_kwargs):
            return SimpleNamespace(
                content=[SimpleNamespace(text=json.dumps(payload))],
                usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    monkeypatch.setattr(pipeline, "_claude", lambda: SimpleNamespace(messages=Messages()))
    report = pipeline.verify_evidence_asset(
        str(image), state, compile_evidence_plan(_script())["continuity_pack"])
    assert report["passed"] is False
    assert report["visible_information"] is True
    assert "red gauge mark" in report["reasons"][0]


def test_pixel_verifier_detects_png_bytes_even_when_path_ends_in_jpg(monkeypatch, tmp_path):
    from PIL import Image

    image = tmp_path / "evidence.jpg"
    Image.new("RGB", (8, 8), "red").save(image, format="PNG")
    state = compile_evidence_plan(_script())["scenes"][0]["states"][0]
    seen = {}
    payload = {
        "required_objects": {item: True for item in state["required_objects"]},
        "forbidden_objects_absent": {}, "visible_information": True,
        "human_identity_matches": True, "clothing_matches": True,
        "location_matches": True, "opening_object_matches": True,
        "bolt_present": True, "reasons": [],
    }

    class Messages:
        def create(self, **kwargs):
            seen["content"] = kwargs["messages"][0]["content"]
            return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))],
                                   usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    monkeypatch.setattr(pipeline, "_claude", lambda: SimpleNamespace(messages=Messages()))
    report = pipeline.verify_evidence_asset(
        str(image), state, compile_evidence_plan(_script())["continuity_pack"])
    image_blocks = [item for item in seen["content"] if item.get("type") == "image"]
    assert report["passed"] is True
    assert image_blocks[0]["source"]["media_type"] == "image/png"


def test_phase_three_reports_are_exposed_in_ui_and_api():
    html = Path("static/index.html").read_text()
    for control in (
        "expl-evidence-plan-btn", "expl-evidence-validation-btn", "expl-continuity-btn",
    ):
        assert f'id="{control}"' in html
    paths = {getattr(route, "path", "") for route in fastapi_app.routes}
    assert {
        "/api/explainer/evidence-plan/{job_id}",
        "/api/explainer/evidence-validation/{job_id}",
        "/api/explainer/continuity/{job_id}",
    }.issubset(paths)
