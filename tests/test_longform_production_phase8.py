"""PR8 controlled 90-second production pilot contract tests.

Every gate is exercised with an adversarial negative as well as a positive: the point of PR8 is
that a 90-second purchase cannot be talked into passing.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from longform_motion import freeze_opening_manifest
from longform_production import (
    FILLER_PHRASES,
    PRODUCTION_DURATION_SEC,
    PRODUCTION_RELEASE_SCORE,
    PRODUCTION_RUNTIME_MAX,
    PRODUCTION_RUNTIME_MIN,
    ControlledProductionError,
    artifact_completeness,
    build_production_request,
    final_production_outcome,
    find_filler_phrases,
    inspect_fast_start,
    production_policy,
    select_production_structure,
    validate_artifact_provenance,
    validate_claim_visual_reconciliation,
    validate_cross_worker_recovery,
    validate_effective_story_format,
    validate_narration_integrity,
    validate_opening_object_return,
    validate_production_request,
    validate_production_runtime,
    validate_resolved_questions,
)


# ---------------------------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------------------------

def _calibrated_profile() -> dict:
    return {
        "schema_version": 1,
        "profile_id": "production-calibrated-v1",
        "status": "calibrated",
        "pixel_delta_threshold": 0.035,
        "source_change_ratio_threshold": 0.45,
        "dataset_sha256": "dataset-hash",
        "reviewer": "Calibration Editor",
        "created_at": "2026-08-23T00:00:00+00:00",
        "method": "balanced_accuracy_human_labeled_real_video_v1",
        "sample_counts": {
            "meaningful_change": 20, "not_meaningful_change": 20,
            "not_slideshow": 20, "slideshow": 20,
        },
        "metrics": {
            "pixel_delta": {"balanced_accuracy": 0.9, "sensitivity": 0.9, "specificity": 0.9},
            "source_change_ratio": {"balanced_accuracy": 0.9, "sensitivity": 0.9,
                                    "specificity": 0.9},
        },
    }


def _outcome(kind: str, score: int, *, passed: bool = True, hard_failures=None) -> dict:
    return {
        "pilot_kind": kind,
        "pilot_passed": passed,
        "job_id": f"pr7-abc-{kind}",
        "automated": {"score": score, "hard_failures": list(hard_failures or [])},
    }


def _pair(standard: int = 92, mystery: int = 88) -> list[dict]:
    return [_outcome("standard", standard), _outcome("evidence_mystery", mystery)]


def _freeze(tmp_path: Path, *, name: str = "opening.png", body: bytes = b"opening-object-bytes"):
    asset = tmp_path / name
    asset.write_bytes(body)
    manifest = freeze_opening_manifest(
        {1: str(asset)}, {}, str(tmp_path / "opening_freeze.json"))
    return manifest, asset


def _request(tmp_path: Path, **overrides) -> dict:
    manifest, _ = _freeze(tmp_path)
    request = build_production_request(
        production_id="pr8-0001",
        selection=select_production_structure(_pair()),
        question="Why does the deep ocean run out of oxygen first?",
        frozen_opening=manifest,
    )
    request.update(overrides)
    return request


def _timing(measured: float = 90.0, *, scenes: int = 3, natural: bool = True) -> dict:
    return {
        "passed": True,
        "natural_speed": natural,
        "post_stretched": not natural,
        "measured_seconds": measured,
        "scenes": [{"scene": i, "timed_words": 40, "timing_coverage": 1.0}
                   for i in range(1, scenes + 1)],
    }


def _script(scenes: int = 3, **scene_overrides) -> dict:
    built = []
    for index in range(scenes):
        scene = {
            "narration": f"The measured oxygen minimum zone expanded by {index + 4} percent.",
            "claim_refs": [{"claim_id": f"claim-{index}", "narration_phrase": "measured"}],
            "visible_consequence": "the sensor trace bends downward",
            "opens_loop": f"loop-{index}",
            "closes_loop": f"loop-{index}",
        }
        scene.update(scene_overrides)
        built.append(scene)
    return {"scenes": built, "_story_format": "standard_explainer"}


def _evidence_plan(scenes: int = 3, *, verified: bool = True) -> dict:
    return {
        "scenes": [
            {
                "scene_index": index,
                "states": [{
                    "state_id": f"state:s{index + 1:03d}:e01",
                    "verified_visible_information": verified,
                }],
            }
            for index in range(scenes)
        ],
    }


def _retention(unresolved=None) -> dict:
    return {
        "checks": {
            "opened_loops": ["loop-0", "loop-1"],
            "closed_loops": ["loop-0", "loop-1"],
            "unresolved_loops": list(unresolved or []),
        },
    }


def _review(decision: str = "approve") -> dict:
    approved = decision == "approve"
    return {
        "status": "completed", "decision": decision, "reviewer": "Editor",
        "checklist": [{"item": "story is legible", "approved": approved}],
    }


def _contract(**overrides) -> dict:
    value = {
        "score": 93,
        "automated_pass": True,
        "hard_failures": [],
        "threshold_profile": _calibrated_profile(),
    }
    value.update(overrides)
    return value


def _gates(**overrides) -> dict:
    gates = {name: {"passed": True, "errors": []} for name in (
        "runtime", "narration", "questions", "claims", "opening_reuse",
        "provenance", "fast_start", "recovery")}
    gates.update(overrides)
    return gates


def _encode(path: Path, *, seconds: float = 2.0, faststart: bool = True) -> Path:
    raw = path.with_name(path.stem + "-raw.mp4")
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"testsrc=size=160x120:rate=10:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(raw)], check=True)
    movflags = "+faststart" if faststart else "-faststart"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(raw),
         "-c", "copy", "-movflags", movflags, str(path)], check=True)
    return path


# ---------------------------------------------------------------------------------------------
# Structure selection
# ---------------------------------------------------------------------------------------------

def test_production_structure_selects_the_higher_pr7_score():
    selection = select_production_structure(_pair(standard=92, mystery=88))
    assert selection["winning_pilot_kind"] == "standard"
    assert selection["story_format"] == "standard_explainer"
    assert selection["score_margin"] == 4
    assert selection["tie_break"] is None

    other = select_production_structure(_pair(standard=86, mystery=91))
    assert other["winning_pilot_kind"] == "evidence_mystery"
    assert other["story_format"] == "evidence_led_mystery"


def test_a_failed_pr7_pilot_blocks_the_90_second_purchase():
    outcomes = [_outcome("standard", 92), _outcome("evidence_mystery", 80, passed=False)]
    with pytest.raises(ControlledProductionError, match="did not pass"):
        select_production_structure(outcomes)


def test_pr7_hard_failures_cannot_be_promoted_into_production():
    outcomes = [_outcome("standard", 92, hard_failures=["slideshow_behavior"]),
                _outcome("evidence_mystery", 88)]
    with pytest.raises(ControlledProductionError, match="hard failures"):
        select_production_structure(outcomes)


def test_reviewer_cannot_override_the_stronger_structure():
    with pytest.raises(ControlledProductionError, match="cannot override"):
        select_production_structure(
            _pair(standard=92, mystery=88),
            tie_break={"reviewer": "Editor", "reason": "I prefer mystery",
                       "pilot_kind": "evidence_mystery"})


def test_exact_tie_requires_an_identified_reviewer_and_written_reason():
    tied = _pair(standard=90, mystery=90)
    with pytest.raises(ControlledProductionError, match="tie-break"):
        select_production_structure(tied)
    with pytest.raises(ControlledProductionError, match="reviewer identity and a written reason"):
        select_production_structure(tied, tie_break={"reviewer": "Editor", "pilot_kind": "standard"})

    selection = select_production_structure(
        tied, tie_break={"reviewer": "Editor", "reason": "Mystery reads clearer on mobile.",
                         "pilot_kind": "evidence_mystery"})
    assert selection["winning_pilot_kind"] == "evidence_mystery"
    assert selection["tie_break"]["reviewer"] == "Editor"


@pytest.mark.parametrize("outcomes", [
    [],
    [_outcome("standard", 92)],
    [_outcome("standard", 92), _outcome("standard", 90)],
    [_outcome("standard", 92), _outcome("evidence_mystery", 90), _outcome("standard", 88)],
])
def test_selection_requires_exactly_one_graded_pilot_of_each_kind(outcomes):
    with pytest.raises(ControlledProductionError):
        select_production_structure(outcomes)


def test_selection_requires_a_recorded_automated_score():
    outcomes = [_outcome("standard", 92), _outcome("evidence_mystery", 88)]
    outcomes[1]["automated"] = {}
    with pytest.raises(ControlledProductionError, match="no recorded automated score"):
        select_production_structure(outcomes)


# ---------------------------------------------------------------------------------------------
# Request contract
# ---------------------------------------------------------------------------------------------

def test_production_request_is_fixed_at_ninety_seconds(tmp_path):
    request = _request(tmp_path)
    assert request["duration_sec"] == PRODUCTION_DURATION_SEC == 90
    assert request["controlled_production"] is True
    assert request["production_policy"] == production_policy()
    assert validate_production_request(request)["passed"] is True


@pytest.mark.parametrize("field,value", [
    ("duration_sec", 45),
    ("duration_sec", 120),
    ("motion_mode", "stills"),
    ("video_format", "social"),
    ("fact_check", False),
    ("story_format", "evidence_led_mystery"),
    ("controlled_production", False),
])
def test_production_request_mutations_fail_before_spend(tmp_path, field, value):
    request = _request(tmp_path, **{field: value})
    with pytest.raises(ControlledProductionError):
        validate_production_request(request)


@pytest.mark.parametrize("field", [
    "threshold_profile", "threshold_overrides", "validation_overrides", "replacement_images",
    "manual_assets", "checkpoint_path", "resume", "runtime_override", "score_floor_override",
])
def test_production_request_rejects_override_fields(tmp_path, field):
    request = _request(tmp_path, **{field: "anything"})
    with pytest.raises(ControlledProductionError, match="forbidden production override"):
        validate_production_request(request)


def test_a_loosened_policy_cannot_be_smuggled_into_a_request(tmp_path):
    request = _request(tmp_path)
    request["production_policy"] = {**production_policy(), "rendered_score_floor": 85}
    with pytest.raises(ControlledProductionError, match="production_policy"):
        validate_production_request(request)


def test_tampered_structure_selection_hash_is_rejected(tmp_path):
    manifest, _ = _freeze(tmp_path)
    selection = select_production_structure(_pair(standard=92, mystery=88))
    selection["winning_pilot_kind"] = "evidence_mystery"
    with pytest.raises(ControlledProductionError, match="selection hash"):
        build_production_request(
            production_id="pr8-0001", selection=selection, question="Why?",
            frozen_opening=manifest)


def test_production_requires_the_approved_frozen_opening(tmp_path):
    selection = select_production_structure(_pair())
    with pytest.raises(ControlledProductionError, match="opening freeze manifest is required"):
        build_production_request(
            production_id="pr8-0001", selection=selection, question="Why?", frozen_opening={})


def test_story_format_drift_is_a_failed_production_run(tmp_path):
    request = _request(tmp_path)
    drifted = validate_effective_story_format(
        {"_story_format": "evidence_led_mystery"}, request)
    assert not drifted["passed"]

    fell_back = validate_effective_story_format(
        {"_story_format": "standard_explainer",
         "_story_format_fallback_reason": "topic unsuitable"}, request)
    assert not fell_back["passed"]

    assert validate_effective_story_format({"_story_format": "standard_explainer"},
                                           request)["passed"]


# ---------------------------------------------------------------------------------------------
# Runtime window
# ---------------------------------------------------------------------------------------------

def test_runtime_window_is_the_natural_speed_tolerance_at_ninety_seconds():
    assert (PRODUCTION_RUNTIME_MIN, PRODUCTION_RUNTIME_MAX) == (87.3, 92.7)


@pytest.mark.parametrize("measured,encoded,ok", [
    (90.0, 90.0, True),
    (87.3, 87.3, True),
    (92.7, 92.7, True),
    (87.2, 87.2, False),
    (92.8, 92.8, False),
    (95.0, 95.0, False),
])
def test_runtime_window_boundaries_are_enforced(measured, encoded, ok):
    report = validate_production_runtime(_timing(measured), encoded_duration_sec=encoded)
    assert report["passed"] is ok


def test_post_stretched_narration_cannot_buy_the_runtime_window():
    report = validate_production_runtime(_timing(90.0, natural=False), encoded_duration_sec=90.0)
    assert not report["passed"]
    codes = {item["code"] for item in report["errors"]}
    assert "narration_not_natural_speed" in codes
    assert "narration_post_stretched" in codes


def test_encoded_video_that_lost_narration_fails_reconciliation():
    # In-window narration, in-window encode, but the encode is 4s shorter than the speech.
    report = validate_production_runtime(_timing(92.0), encoded_duration_sec=88.0)
    assert not report["passed"]
    assert "encoded_narration_mismatch" in {item["code"] for item in report["errors"]}


def test_missing_encoded_duration_fails_closed():
    report = validate_production_runtime(_timing(90.0), encoded_duration_sec=0)
    assert not report["passed"]
    assert "encoded_duration_missing" in {item["code"] for item in report["errors"]}


# ---------------------------------------------------------------------------------------------
# Narration integrity
# ---------------------------------------------------------------------------------------------

def test_clean_production_narration_passes():
    report = validate_narration_integrity(
        _script(), _timing(scenes=3), dropped_scene_count=0, filler_frame_count=0)
    assert report["passed"], report["errors"]


@pytest.mark.parametrize("dropped,filler,code", [
    (1, 0, "dropped_narration"),
    (0, 1, "filler_frames"),
])
def test_dropped_narration_and_filler_frames_are_production_failures(dropped, filler, code):
    report = validate_narration_integrity(
        _script(), _timing(scenes=3), dropped_scene_count=dropped, filler_frame_count=filler)
    assert not report["passed"]
    assert code in {item["code"] for item in report["errors"]}


def test_every_frozen_filler_phrase_is_detected():
    for phrase in FILLER_PHRASES:
        script = {"scenes": [{"narration": f"Right, {phrase} the sensors drifted."}]}
        assert find_filler_phrases(script) == [{"scene": 1, "phrase": phrase}]


def test_filler_detection_does_not_fire_inside_a_longer_word():
    # "but first" must not match "halibut first-year growth".
    assert find_filler_phrases({"scenes": [{"narration": "Halibut firstborn growth slowed."}]}) == []


def test_a_scene_that_does_no_story_work_is_structural_filler():
    script = _script(scenes=2)
    script["scenes"].append({"narration": "The ocean is very large and very old."})
    report = validate_narration_integrity(
        script, _timing(scenes=3), dropped_scene_count=0, filler_frame_count=0)
    assert not report["passed"]
    assert "scene_does_no_story_work" in {item["code"] for item in report["errors"]}


def test_a_silent_scene_fails_narration_integrity():
    timing = _timing(scenes=3)
    timing["scenes"][1]["timed_words"] = 0
    report = validate_narration_integrity(
        _script(), timing, dropped_scene_count=0, filler_frame_count=0)
    assert not report["passed"]
    assert "scene_narration_missing" in {item["code"] for item in report["errors"]}


def test_script_and_timing_scene_counts_must_match():
    report = validate_narration_integrity(
        _script(4), _timing(scenes=3), dropped_scene_count=0, filler_frame_count=0)
    assert not report["passed"]
    assert "narration_scene_count_mismatch" in {item["code"] for item in report["errors"]}


# ---------------------------------------------------------------------------------------------
# Resolved questions
# ---------------------------------------------------------------------------------------------

def test_resolved_questions_pass_and_unresolved_ones_fail():
    assert validate_resolved_questions(_retention())["passed"]

    unresolved = validate_resolved_questions(_retention(["loop-1"]))
    assert not unresolved["passed"]
    assert "unresolved_questions" in {item["code"] for item in unresolved["errors"]}


def test_a_story_tracking_no_question_fails():
    report = validate_resolved_questions({"checks": {"opened_loops": [], "closed_loops": [],
                                                     "unresolved_loops": []}})
    assert not report["passed"]
    assert "no_tracked_questions" in {item["code"] for item in report["errors"]}


@pytest.mark.parametrize("report", [{}, None, [], {"checks": "not-a-mapping"}])
def test_a_missing_or_malformed_retention_report_fails_closed(report):
    result = validate_resolved_questions(report)
    assert not result["passed"]
    assert "retention_validation_missing" in {item["code"] for item in result["errors"]}


# ---------------------------------------------------------------------------------------------
# Claim / visual reconciliation
# ---------------------------------------------------------------------------------------------

def test_claims_and_visuals_reconcile():
    report = validate_claim_visual_reconciliation(
        script=_script(), claim_validation={"passed": True}, evidence_plan=_evidence_plan())
    assert report["passed"], report["errors"]
    assert report["claimed_scene_count"] == 3


def test_a_claim_without_a_verified_visual_state_fails():
    report = validate_claim_visual_reconciliation(
        script=_script(), claim_validation={"passed": True},
        evidence_plan=_evidence_plan(verified=False))
    assert not report["passed"]
    assert "claim_without_verified_visual" in {item["code"] for item in report["errors"]}


def test_a_claim_with_no_compiled_visual_state_fails():
    plan = _evidence_plan()
    plan["scenes"][1]["states"] = []
    report = validate_claim_visual_reconciliation(
        script=_script(), claim_validation={"passed": True}, evidence_plan=plan)
    assert not report["passed"]
    assert "claim_without_visual_state" in {item["code"] for item in report["errors"]}


def test_visual_spend_without_a_story_join_fails():
    script = _script()
    script["scenes"][2] = {"narration": "A wide shot of the ship.", "opens_loop": "x",
                           "closes_loop": "x"}
    report = validate_claim_visual_reconciliation(
        script=script, claim_validation={"passed": True}, evidence_plan=_evidence_plan())
    assert not report["passed"]
    assert "visual_without_story_join" in {item["code"] for item in report["errors"]}


def test_a_failed_claim_ledger_fails_reconciliation():
    report = validate_claim_visual_reconciliation(
        script=_script(), claim_validation={"passed": False}, evidence_plan=_evidence_plan())
    assert not report["passed"]
    assert "claim_ledger_failed" in {item["code"] for item in report["errors"]}


# ---------------------------------------------------------------------------------------------
# Opening object exact reuse
# ---------------------------------------------------------------------------------------------

def test_callback_reusing_the_exact_opening_bytes_passes(tmp_path):
    manifest, asset = _freeze(tmp_path)
    callback = tmp_path / "callback.png"
    callback.write_bytes(asset.read_bytes())
    report = validate_opening_object_return(
        opening_freeze=manifest, callback_asset_path=str(callback),
        opening_asset_path=str(asset))
    assert report["passed"], report["errors"]
    assert report["opening_sha256"] == report["callback_sha256"]


def test_a_regenerated_callback_object_fails_exact_reuse(tmp_path):
    manifest, asset = _freeze(tmp_path)
    callback = tmp_path / "callback.png"
    # A visually similar regeneration differs by a single byte and must not pass as reuse.
    callback.write_bytes(asset.read_bytes() + b"!")
    report = validate_opening_object_return(
        opening_freeze=manifest, callback_asset_path=str(callback),
        opening_asset_path=str(asset))
    assert not report["passed"]
    assert "opening_object_regenerated" in {item["code"] for item in report["errors"]}


def test_an_opening_asset_edited_after_approval_fails(tmp_path):
    manifest, asset = _freeze(tmp_path)
    asset.write_bytes(b"re-rendered after approval")
    callback = tmp_path / "callback.png"
    callback.write_bytes(asset.read_bytes())
    report = validate_opening_object_return(
        opening_freeze=manifest, callback_asset_path=str(callback),
        opening_asset_path=str(asset))
    assert not report["passed"]
    codes = {item["code"] for item in report["errors"]}
    assert "frozen_opening_invalid" in codes
    assert "opening_asset_not_frozen" in codes


def test_a_missing_callback_asset_fails_closed(tmp_path):
    manifest, asset = _freeze(tmp_path)
    report = validate_opening_object_return(
        opening_freeze=manifest, callback_asset_path=str(tmp_path / "absent.png"),
        opening_asset_path=str(asset))
    assert not report["passed"]
    assert "callback_asset_missing" in {item["code"] for item in report["errors"]}


# ---------------------------------------------------------------------------------------------
# Artifact provenance
# ---------------------------------------------------------------------------------------------

def _manifest_for(paths: list[Path]) -> dict:
    from longform_motion import sha256_file
    return {"actual_motion": [{"state_id": path.stem, "output_sha256": sha256_file(str(path))}
                              for path in paths]}


def test_declared_media_passes_provenance(tmp_path):
    media = tmp_path / "scene1.png"
    media.write_bytes(b"scene-one")
    report = validate_artifact_provenance(str(tmp_path), _manifest_for([media]))
    assert report["passed"], report["errors"]
    assert report["media_count"] == 1


def test_an_unexplained_media_file_fails_provenance(tmp_path):
    declared = tmp_path / "scene1.png"
    declared.write_bytes(b"scene-one")
    stray = tmp_path / "scene2.png"
    stray.write_bytes(b"where-did-this-come-from")
    report = validate_artifact_provenance(str(tmp_path), _manifest_for([declared]))
    assert not report["passed"]
    assert report["unexplained"] == ["scene2.png"]


def test_renaming_a_file_cannot_launder_provenance(tmp_path):
    declared = tmp_path / "scene1.png"
    declared.write_bytes(b"scene-one")
    manifest = _manifest_for([declared])
    declared.rename(tmp_path / "scene1-final.png")
    # Same bytes under a new name still resolve, because provenance is matched by hash.
    assert validate_artifact_provenance(str(tmp_path), manifest)["passed"]
    # Different bytes under the declared name do not.
    (tmp_path / "scene1.png").write_bytes(b"substituted")
    assert not validate_artifact_provenance(str(tmp_path), manifest)["passed"]


def test_json_reports_are_not_treated_as_unexplained_media(tmp_path):
    (tmp_path / "rendered_contract.json").write_text("{}", encoding="utf-8")
    assert validate_artifact_provenance(str(tmp_path), {})["passed"]


# ---------------------------------------------------------------------------------------------
# Fast-start delivery (real encoded files)
# ---------------------------------------------------------------------------------------------

def test_real_faststart_and_non_faststart_mp4s_are_distinguished(tmp_path):
    fast = _encode(tmp_path / "fast.mp4", faststart=True)
    slow = _encode(tmp_path / "slow.mp4", faststart=False)

    fast_report = inspect_fast_start(str(fast))
    assert fast_report["passed"] and fast_report["fast_start"]
    assert fast_report["boxes"].index("moov") < fast_report["boxes"].index("mdat")

    slow_report = inspect_fast_start(str(slow))
    assert not slow_report["passed"]
    assert slow_report["fast_start"] is False
    assert "not_fast_start" in {item["code"] for item in slow_report["errors"]}


def test_a_missing_or_unreadable_deliverable_fails_closed(tmp_path):
    assert not inspect_fast_start(str(tmp_path / "absent.mp4"))["passed"]

    not_a_video = tmp_path / "broken.mp4"
    not_a_video.write_bytes(b"\x00\x00\x00\x08free" + b"\x00" * 4)
    report = inspect_fast_start(str(not_a_video))
    assert not report["passed"]
    codes = {item["code"] for item in report["errors"]}
    assert "missing_ftyp" in codes and "missing_moov" in codes


def test_a_truncated_mp4_does_not_hang_the_parser(tmp_path):
    fast = _encode(tmp_path / "fast.mp4", faststart=True)
    truncated = tmp_path / "truncated.mp4"
    truncated.write_bytes(fast.read_bytes()[: fast.stat().st_size // 2])
    report = inspect_fast_start(str(truncated))
    assert not report["passed"]


# ---------------------------------------------------------------------------------------------
# Cross-worker recovery
# ---------------------------------------------------------------------------------------------

def _events(workers: list[str], *, resumed: bool = True, reused: int = 4,
            terminal: str = "done") -> list[dict]:
    rows = [{"type": "queued", "worker_id": ""}]
    for index, worker in enumerate(workers):
        rows.append({"type": "leased", "worker_id": worker})
        if index and resumed:
            rows.append({"type": "resumed", "worker_id": worker,
                         "data": {"reused_artifact_count": reused}})
    rows.append({"type": terminal, "worker_id": workers[-1] if workers else ""})
    return rows


def test_a_job_that_changed_workers_and_reused_work_proves_recovery():
    report = validate_cross_worker_recovery(
        _events(["worker-a", "worker-b"]), job_id="pr8-0001")
    assert report["passed"], report["errors"]
    assert report["distinct_workers"] == ["worker-a", "worker-b"]
    assert report["reused_artifact_count"] == 4


def test_a_single_worker_job_cannot_prove_cross_worker_recovery():
    report = validate_cross_worker_recovery(_events(["worker-a"]), job_id="pr8-0001")
    assert not report["passed"]
    assert "no_worker_handover" in {item["code"] for item in report["errors"]}


def test_recovery_that_reused_no_work_is_indistinguishable_from_a_rerun():
    report = validate_cross_worker_recovery(
        _events(["worker-a", "worker-b"], reused=0), job_id="pr8-0001")
    assert not report["passed"]
    assert "no_reused_work" in {item["code"] for item in report["errors"]}


def test_recovery_without_a_recorded_resume_fails():
    report = validate_cross_worker_recovery(
        _events(["worker-a", "worker-b"], resumed=False), job_id="pr8-0001")
    assert not report["passed"]
    assert "no_recorded_resume" in {item["code"] for item in report["errors"]}


def test_a_job_that_ended_in_error_does_not_prove_recovery():
    report = validate_cross_worker_recovery(
        _events(["worker-a", "worker-b"], terminal="error"), job_id="pr8-0001")
    assert not report["passed"]
    assert "job_not_completed" in {item["code"] for item in report["errors"]}


# ---------------------------------------------------------------------------------------------
# Artifact completeness
# ---------------------------------------------------------------------------------------------

def test_artifact_completeness_names_every_missing_proof(tmp_path):
    (tmp_path / "rendered_contract.json").write_text("{}", encoding="utf-8")
    report = artifact_completeness(str(tmp_path))
    assert not report["passed"]
    assert "publish_recommendation.json" in report["missing"]
    assert "rendered_contract.json" not in report["missing"]


def test_artifact_completeness_passes_once_every_proof_exists(tmp_path):
    for name in artifact_completeness(str(tmp_path))["required"]:
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert artifact_completeness(str(tmp_path))["passed"]


# ---------------------------------------------------------------------------------------------
# Final outcome and publish recommendation
# ---------------------------------------------------------------------------------------------

def _outcome_for(**kwargs) -> dict:
    base = {
        "rendered_contract": _contract(),
        "human_review": _review(),
        "completeness": {"passed": True},
        "gates": _gates(),
    }
    base.update(kwargs)
    return final_production_outcome(**base)


def test_a_complete_pass_recommends_publish():
    result = _outcome_for()
    assert result["production_passed"] is True
    assert result["publish_recommendation"] == "publish"
    assert result["failure_reasons"] == []


def test_the_ordinary_eighty_five_release_floor_is_not_enough_for_production():
    result = _outcome_for(rendered_contract=_contract(score=88))
    assert result["production_passed"] is False
    assert result["publish_recommendation"] == "do_not_publish"
    assert "rendered_contract_below_production_floor" in result["failure_reasons"]
    assert result["automated"]["score_floor"] == PRODUCTION_RELEASE_SCORE == 90


def test_editorial_approval_cannot_promote_a_failed_gate():
    result = _outcome_for(gates=_gates(fast_start={"passed": False, "errors": []}))
    assert result["production_passed"] is False
    assert "mp4_not_fast_start" in result["failure_reasons"]
    assert result["editorial"]["passed"] is True


@pytest.mark.parametrize("gate,reason", [
    ("runtime", "runtime_window_failed"),
    ("narration", "narration_integrity_failed"),
    ("questions", "unresolved_questions"),
    ("claims", "claim_visual_reconciliation_failed"),
    ("opening_reuse", "opening_object_not_reused"),
    ("provenance", "unexplained_artifacts"),
    ("fast_start", "mp4_not_fast_start"),
    ("recovery", "cross_worker_recovery_unproven"),
])
def test_every_production_gate_can_independently_block_publication(gate, reason):
    result = _outcome_for(gates=_gates(**{gate: {"passed": False, "errors": []}}))
    assert result["production_passed"] is False
    assert reason in result["failure_reasons"]


def test_a_missing_gate_report_fails_closed():
    gates = _gates()
    del gates["recovery"]
    result = _outcome_for(gates=gates)
    assert result["production_passed"] is False
    assert "cross_worker_recovery_unproven" in result["failure_reasons"]


def test_uncalibrated_thresholds_cannot_publish_a_production_video():
    profile = {**_calibrated_profile(), "status": "provisional_uncalibrated"}
    result = _outcome_for(rendered_contract=_contract(threshold_profile=profile))
    assert result["production_passed"] is False
    assert result["automated"]["threshold_calibration"]["passed"] is False


def test_a_rejected_editorial_review_blocks_a_perfect_automated_score():
    result = _outcome_for(rendered_contract=_contract(score=100),
                          human_review=_review("reject"))
    assert result["production_passed"] is False
    assert "editorial_review_failed" in result["failure_reasons"]


def test_missing_artifacts_block_publication():
    result = _outcome_for(completeness={"passed": False, "missing": ["publish_recommendation.json"]})
    assert result["production_passed"] is False
    assert "required_artifacts_missing" in result["failure_reasons"]


def test_a_failed_production_outcome_records_no_promotion_route():
    result = _outcome_for(rendered_contract=_contract(score=70, automated_pass=False))
    assert result["status"] == "production_failed"
    assert "cannot be promoted in place" in result["promotion_rule"]
    assert json.dumps(result)  # the outcome must be persistable as-is


# ---------------------------------------------------------------------------------------------
# Boundary integration: durable store, API surface, pipeline carry-through
# ---------------------------------------------------------------------------------------------

def test_pipeline_version_hash_tracks_the_production_contract(tmp_path):
    import durable_execution

    tracked = (
        "explainer_pipeline.py", "longform_retention.py", "longform_evidence.py",
        "longform_motion.py", "longform_pilots.py", "longform_production.py",
        "longform_rendered_gate.py", "durable_execution.py",
    )
    for name in tracked:
        (tmp_path / name).write_text(name, encoding="utf-8")
    before = durable_execution.version_hash(tmp_path)
    (tmp_path / "longform_production.py").write_text("changed floor", encoding="utf-8")
    assert durable_execution.version_hash(tmp_path) != before


def test_public_generate_endpoint_cannot_smuggle_a_controlled_production():
    import asyncio

    import app as app_module
    from fastapi import BackgroundTasks, HTTPException
    from app import ExplainerRequest

    request = ExplainerRequest(question="test", controlled_production=True)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_module.explainer_generate(request, BackgroundTasks()))
    assert exc.value.status_code == 403


def test_production_request_model_forbids_unadvertised_override_fields():
    from app import ExplainerProductionRequest

    with pytest.raises(Exception):
        ExplainerProductionRequest(batch_id="pr7-1", question="Why?", duration_sec=45)
    with pytest.raises(Exception):
        ExplainerProductionRequest(batch_id="pr7-1", question="Why?",
                                   threshold_overrides={"pixel_delta_threshold": 0.0})


def _batch(tmp_path, *, standard: int = 92, mystery: int = 88,
           standard_status: str = "pilot_passed", mystery_status: str = "pilot_passed") -> dict:
    manifest, _ = _freeze(tmp_path)
    return {
        "id": "pr7-abc",
        "jobs": [
            {"id": "pr7-abc-standard", "status": standard_status,
             "request": {"pilot_kind": "standard"},
             "result": {"rendered_contract": {"score": standard, "hard_failures": []},
                        "opening_freeze": manifest}},
            {"id": "pr7-abc-mystery", "status": mystery_status,
             "request": {"pilot_kind": "evidence_mystery"},
             "result": {"rendered_contract": {"score": mystery, "hard_failures": []},
                        "opening_freeze": manifest}},
        ],
    }


def _production_endpoint(monkeypatch, store, batch):
    import app as app_module
    import durable_execution

    class Store:
        def get_pilot_batch(self, _batch_id):
            return batch

        def enqueue_production_run(self, **kwargs):
            return store(**kwargs)

    monkeypatch.setattr(app_module, "_require_render_storage", lambda: None)
    monkeypatch.setattr(app_module, "_durable_execution_required", lambda: True)
    monkeypatch.setattr(app_module, "_durable_components", lambda: (Store(), object()))
    monkeypatch.setattr(durable_execution, "version_hash", lambda _root: "pipeline-hash")
    return app_module


def test_production_endpoint_queues_one_run_for_the_stronger_structure(monkeypatch, tmp_path):
    import asyncio

    from app import ExplainerProductionRequest

    captured = {}

    def enqueue(**kwargs):
        captured.update(kwargs)
        return {"status": "queued", "job": {"id": f"{kwargs['production_id']}-video"}}

    app_module = _production_endpoint(monkeypatch, enqueue, _batch(tmp_path))
    response = asyncio.run(app_module.explainer_create_production_run(
        ExplainerProductionRequest(batch_id="pr7-abc",
                                   question="Why does the deep ocean lose oxygen first?")))

    assert response["selection"]["winning_pilot_kind"] == "standard"
    assert captured["source_batch_id"] == "pr7-abc"
    assert captured["request"]["duration_sec"] == 90
    assert captured["request"]["story_format"] == "standard_explainer"
    assert captured["request"]["controlled_production"] is True
    assert response["job_id"].endswith("-video")


def test_production_endpoint_refuses_a_batch_whose_pilot_failed(monkeypatch, tmp_path):
    import asyncio

    from fastapi import HTTPException

    from app import ExplainerProductionRequest

    app_module = _production_endpoint(
        monkeypatch, lambda **_kwargs: {},
        _batch(tmp_path, mystery_status="pilot_failed"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_module.explainer_create_production_run(
            ExplainerProductionRequest(batch_id="pr7-abc", question="Why?")))
    assert exc.value.status_code == 409
    assert "did not pass" in str(exc.value.detail)


def test_production_endpoint_refuses_a_pilot_without_a_frozen_opening(monkeypatch, tmp_path):
    import asyncio

    from fastapi import HTTPException

    from app import ExplainerProductionRequest

    batch = _batch(tmp_path)
    batch["jobs"][0]["result"]["opening_freeze"] = {}
    app_module = _production_endpoint(monkeypatch, lambda **_kwargs: {}, batch)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_module.explainer_create_production_run(
            ExplainerProductionRequest(batch_id="pr7-abc", question="Why?")))
    assert exc.value.status_code == 409
    assert "opening freeze manifest is required" in str(exc.value.detail)


def test_production_endpoint_reports_storage_unavailability_as_retryable_503(monkeypatch,
                                                                             tmp_path):
    import asyncio

    import durable_execution
    from fastapi import HTTPException

    from app import ExplainerProductionRequest

    def enqueue(**_kwargs):
        raise durable_execution.StorageUnavailable("database is offline")

    app_module = _production_endpoint(monkeypatch, enqueue, _batch(tmp_path))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_module.explainer_create_production_run(
            ExplainerProductionRequest(batch_id="pr7-abc", question="Why?")))
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "PRODUCTION_STORAGE_UNAVAILABLE"
    assert exc.value.detail["retryable"] is True


def test_production_endpoint_surfaces_a_tie_break_to_the_frozen_selection(monkeypatch, tmp_path):
    import asyncio

    from app import ExplainerProductionRequest

    captured = {}

    def enqueue(**kwargs):
        captured.update(kwargs)
        return {"status": "queued", "job": {"id": f"{kwargs['production_id']}-video"}}

    app_module = _production_endpoint(monkeypatch, enqueue,
                                      _batch(tmp_path, standard=90, mystery=90))
    response = asyncio.run(app_module.explainer_create_production_run(
        ExplainerProductionRequest(
            batch_id="pr7-abc", question="Why?", tie_break_reviewer="Editor",
            tie_break_reason="Mystery reads clearer on mobile.",
            tie_break_pilot_kind="evidence_mystery")))
    assert response["selection"]["winning_pilot_kind"] == "evidence_mystery"
    assert response["selection"]["tie_break"]["reviewer"] == "Editor"
    assert captured["request"]["story_format"] == "evidence_led_mystery"


def test_durable_production_status_transitions_are_terminal():
    import inspect

    import durable_execution

    source = inspect.getsource(durable_execution.PostgresStore.set_status)
    assert "production_passed" in source and "production_failed" in source


def test_pilot_result_carries_the_frozen_opening_into_durable_storage():
    import inspect

    import app as app_module
    import explainer_pipeline

    # PR8 runs in a later container, so the approved manifest must be persisted as data rather
    # than left behind as a local path on the pilot's filesystem.
    assert '"opening_freeze": opening_freeze' in inspect.getsource(
        explainer_pipeline.run_explainer_pipeline)
    assert '"opening_freeze": result.get("opening_freeze")' in inspect.getsource(
        app_module.run_explainer_task)
