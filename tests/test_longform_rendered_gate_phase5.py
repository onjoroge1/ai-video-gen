import json
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

import explainer_pipeline as pipeline
from app import app as fastapi_app

from longform_rendered_gate import (
    PROVISIONAL_THRESHOLD_PROFILE,
    HUMAN_REVIEW_CHECKLIST,
    apply_human_review,
    build_animatic_gate,
    build_contact_sheet,
    create_human_review_record,
    cross_check_blind_observations,
    diagnostic_disposition,
    diagnostic_mode_allowed,
    inspect_rendered_opening,
    rendered_grade_summary,
    render_low_cost_animatic,
    score_rendered_contract,
    watermark_rejected_preview,
    calibrate_threshold_profile,
    validate_threshold_profile,
)


def _blind(**overrides):
    value = {
        "valid": True,
        "subject_readable": True,
        "objective_readable": True,
        "anomaly_readable": True,
        "investigation_develops": True,
        "evidence_accumulates": True,
        "causal_story": True,
        "belief_change_earned": True,
        "forward_question_readable": True,
        "multi_shot_storytelling": True,
        "slideshow": False,
        "bolt_useful": True,
        "captions_obscure_evidence": False,
        "comprehensible_audio_story": True,
        "observed_objective": "Alex tests the gauge",
        "observed_evidence_sequence": ["gauge rises", "float falls"],
        "reason_to_continue": "Why the two measurements disagree",
    }
    value.update(overrides)
    return value


def _facts(**overrides):
    value = {
        "decodable": True,
        "shot_count": 12,
        "distinct_source_count": 10,
        "source_change_ratio": 0.91,
        "pixel_boundary_change_ratio": 0.82,
        "verified_information_ratio": 0.83,
        "average_visual_state_sec": 2.6,
        "max_visual_state_sec": 3.2,
        "long_hold_count": 0,
        "bolt_shot_count": 3,
        "bolt_shot_ratio": 0.25,
        "pure_evidence_bolt_violations": 0,
        "continuity_failures": [],
        "slideshow": False,
        "threshold_profile": {
            "schema_version": 1, "profile_id": "test-calibrated-v1", "status": "calibrated",
            "pixel_delta_threshold": 0.035, "source_change_ratio_threshold": 0.45,
            "dataset_sha256": "test-dataset-hash", "reviewer": "Test Editor",
            "created_at": "2026-08-23T00:00:00+00:00",
            "method": "balanced_accuracy_human_labeled_real_video_v1",
            "sample_counts": {"meaningful_change": 20, "not_meaningful_change": 20,
                              "not_slideshow": 20, "slideshow": 20},
            "metrics": {
                "pixel_delta": {"balanced_accuracy": 0.9, "sensitivity": 0.9,
                                "specificity": 0.9},
                "source_change_ratio": {"balanced_accuracy": 0.9, "sensitivity": 0.9,
                                        "specificity": 0.9},
            },
        },
    }
    value.update(overrides)
    return value


def _story(errors=None):
    return {"passed": not errors, "errors": errors or [],
            "checks": {"first_act_continuity_hits": [1, 2, 3]}}


def _score(*, facts=None, blind=None, errors=None, claims=True, callback=True, review=None):
    return score_rendered_contract(
        deterministic=facts or _facts(), blind=blind or _blind(),
        story_validation=_story(errors), claim_validation={"passed": claims},
        callback_exact=callback, human_review=review)


def test_strong_automated_gate_never_reports_final_pass_without_human_review():
    report = _score()
    assert report["score"] == 100
    assert report["automated_pass"] is True
    assert report["passed"] is False
    assert report["publishable"] is False
    assert report["status"] == "AUTOMATED_PASS_AWAITING_HUMAN"


def test_zero_bolt_never_receives_full_credit_and_is_a_hard_failure():
    report = _score(facts=_facts(bolt_shot_count=0, bolt_shot_ratio=0.0))
    component = next(item for item in report["components"]
                     if item["name"] == "Bolt discipline and usefulness")
    assert component["score"] < component["max"]
    assert "bolt_absent" in report["hard_failures"]
    assert report["automated_pass"] is False


def test_uncalibrated_thresholds_are_reported_and_cannot_publish():
    facts = _facts()
    facts["threshold_profile"] = {
        "schema_version": 1, "profile_id": "provisional-defaults-v1",
        "status": "provisional_uncalibrated", "pixel_delta_threshold": 0.035,
        "source_change_ratio_threshold": 0.45, "dataset_sha256": "",
        "sample_counts": {"meaningful_change": 0, "not_meaningful_change": 0,
                          "not_slideshow": 0, "slideshow": 0},
    }
    report = _score(facts=facts)
    # Still reported and still unpublishable — but as an INSTRUMENT fault rather than a verdict on
    # the video. It no longer sits in hard_failures, because that list suppressed the score to 69
    # and aborted the run, which made "we cannot measure this yet" fatal in the same way that
    # "this is a slideshow" is.
    assert report["calibrated"] is False
    assert report["uncertified_reason"] == "uncalibrated_rendered_thresholds"
    assert "uncalibrated_rendered_thresholds" not in report["hard_failures"]
    assert report["threshold_calibration"]["calibrated"] is False
    assert report["publishable"] is False


def test_an_uncalibrated_run_may_finish_but_never_ships():
    """The split that unblocks long-form.

    An otherwise-sound opening on an uncalibrated instrument must be allowed to proceed — that is
    the difference between a video that gets made and reviewed, and one that dies before its
    remaining scenes are purchased. It must still be refused publication, and it must still carry
    the reason.
    """
    facts = _facts()
    facts["threshold_profile"] = dict(PROVISIONAL_THRESHOLD_PROFILE)
    report = _score(facts=facts, review={"status": "complete", "decision": "approve"})
    assert report["hard_failures"] == [], report["hard_failures"]
    assert report["score"] > 69, "an instrument fault must not suppress the score"
    assert report["automated_pass"] is True
    assert report["passed"] is True, "the run may proceed"
    assert report["publishable"] is False, "but it may not ship"
    assert report["status"] == "PASS_UNCERTIFIED"


def test_a_real_defect_still_blocks_regardless_of_calibration():
    """The property that must not regress: the eleven substantive failures are untouched."""
    facts = _facts()
    facts["threshold_profile"] = dict(PROVISIONAL_THRESHOLD_PROFILE)
    facts["slideshow"] = True
    report = _score(facts=facts, review={"status": "complete", "decision": "approve"})
    assert "slideshow_behavior" in report["hard_failures"]
    assert report["score"] <= 49
    assert report["automated_pass"] is False
    assert report["passed"] is False and report["publishable"] is False


def test_unavailable_blind_judge_is_unscored_not_a_fake_rejection():
    report = _score(blind={"valid": False, "judge_error": "ProviderUnavailable: timeout"})
    assert report["score"] is None
    assert report["grade"] == "UNSCORED"
    assert report["status"] == "UNSCORED_JUDGE_UNAVAILABLE"
    assert report["automated_pass"] is None
    assert report["automated_grade_available"] is False
    assert report["hard_failures"] == []


def test_unavailable_judge_does_not_hide_a_deterministic_failure():
    report = _score(
        facts=_facts(slideshow=True),
        blind={"valid": False, "judge_error": "ProviderUnavailable: timeout"},
    )
    assert report["status"] == "REJECT"
    assert report["automated_pass"] is False
    assert "slideshow_behavior" in report["hard_failures"]


def test_legacy_fake_low_score_is_reclassified_without_rewriting_evidence():
    legacy = {
        "score": 44,
        "status": "REJECT",
        "automated_pass": False,
        "hard_failures": [],
        "blind_story_judge": {
            "valid": False,
            "judge_error": "ProviderUnavailable: missing key",
        },
    }
    summary = rendered_grade_summary(legacy)
    assert legacy["score"] == 44
    assert summary["technical_status"] == "completed"
    assert summary["automated_score"] is None
    assert summary["automated_status"] == "UNSCORED_JUDGE_UNAVAILABLE"
    assert summary["promotion_status"] == "awaiting_editorial"


def test_legacy_bolt_adapter_miss_is_instrumentation_not_a_creative_failure():
    legacy = {
        "score": 44,
        "status": "REJECT",
        "automated_pass": False,
        "hard_failures": ["bolt_absent"],
        "blind_story_judge": {
            "valid": False,
        },
    }
    directed_spec = {
        "shots": [{
            "shot_id": "shot-1",
            "mode": "illustrated still",
            "visual": "Bolt points to the evidence map",
            "labels": ["BOLT_CAMEO"],
            "reference_ids": [],
        }],
    }

    summary = rendered_grade_summary(legacy, directed_spec)

    assert legacy["hard_failures"] == ["bolt_absent"]
    assert summary["hard_failures"] == []
    assert summary["automated_status"] == "UNSCORED_JUDGE_UNAVAILABLE"
    assert summary["instrumentation_failures"] == ["legacy_bolt_metadata_not_mapped"]
    assert summary["promotion_status"] == "awaiting_editorial"


def test_legacy_invalid_judge_without_error_text_is_still_unscored():
    legacy = {
        "score": 44,
        "status": "REJECT",
        "automated_pass": False,
        "hard_failures": [],
        "blind_story_judge": {"valid": False},
    }

    summary = rendered_grade_summary(legacy)

    assert summary["automated_score"] is None
    assert summary["automated_status"] == "UNSCORED_JUDGE_UNAVAILABLE"
    assert summary["promotion_status"] == "awaiting_editorial"


def test_legacy_bolt_failure_remains_a_rejection_without_directed_declaration():
    legacy = {
        "score": 44,
        "status": "REJECT",
        "automated_pass": False,
        "hard_failures": ["bolt_absent"],
        "blind_story_judge": {
            "valid": False,
            "judge_error": "ProviderUnavailable: missing key",
        },
    }

    summary = rendered_grade_summary(legacy)

    assert summary["hard_failures"] == ["bolt_absent"]
    assert summary["automated_status"] == "REJECT"
    assert summary["promotion_status"] == "blocked"


def test_real_calibration_requires_balanced_human_labeled_samples():
    samples = []
    for index in range(20):
        samples.append({
            "sample_id": f"change-{index}", "pixel_delta": 0.10 + index / 1000,
            "meaningful_change": True, "source_change_ratio": 0.80,
            "slideshow": False,
        })
        samples.append({
            "sample_id": f"hold-{index}", "pixel_delta": 0.005 + index / 10000,
            "meaningful_change": False, "source_change_ratio": 0.10,
            "slideshow": True,
        })
    profile = calibrate_threshold_profile(
        samples, reviewer="Editor", dataset_id="real-pilot-labels-v1")
    assert validate_threshold_profile(profile, require_calibrated=True)["passed"] is True
    assert profile["status"] == "calibrated"
    assert profile["dataset_sha256"]

    with pytest.raises(ValueError, match="needs at least 20"):
        calibrate_threshold_profile(samples[:10], reviewer="Editor")


def test_calibration_rejects_coerced_labels_duplicate_ids_and_out_of_range_measurements():
    base = []
    for index in range(20):
        base.extend([
            {"sample_id": f"change-{index}", "pixel_delta": 0.1,
             "meaningful_change": True, "source_change_ratio": 0.8, "slideshow": False},
            {"sample_id": f"hold-{index}", "pixel_delta": 0.01,
             "meaningful_change": False, "source_change_ratio": 0.1, "slideshow": True},
        ])

    malformed = [dict(item) for item in base]
    malformed[0]["meaningful_change"] = "false"
    with pytest.raises(ValueError, match="invalid typed labels"):
        calibrate_threshold_profile(malformed, reviewer="Editor")

    duplicate = [dict(item) for item in base]
    duplicate[1]["sample_id"] = duplicate[0]["sample_id"]
    with pytest.raises(ValueError, match="sample_id values must be unique"):
        calibrate_threshold_profile(duplicate, reviewer="Editor")

    out_of_range = [dict(item) for item in base]
    out_of_range[0]["pixel_delta"] = 1.5
    with pytest.raises(ValueError, match="invalid typed labels"):
        calibrate_threshold_profile(out_of_range, reviewer="Editor")

    non_predictive = []
    for index in range(20):
        non_predictive.extend([
            {"sample_id": f"random-change-{index}", "pixel_delta": 0.1,
             "meaningful_change": True, "source_change_ratio": 0.5, "slideshow": False},
            {"sample_id": f"random-hold-{index}", "pixel_delta": 0.1,
             "meaningful_change": False, "source_change_ratio": 0.5, "slideshow": True},
        ])
    with pytest.raises(ValueError, match="do not support a viable threshold"):
        calibrate_threshold_profile(non_predictive, reviewer="Editor")


def test_calibration_cli_writes_a_valid_atomic_profile(tmp_path):
    samples = []
    for index in range(20):
        samples.extend([
            {"sample_id": f"change-{index}", "pixel_delta": 0.1,
             "meaningful_change": True, "source_change_ratio": 0.8, "slideshow": False},
            {"sample_id": f"hold-{index}", "pixel_delta": 0.01,
             "meaningful_change": False, "source_change_ratio": 0.1, "slideshow": True},
        ])
    dataset = tmp_path / "labels.json"
    output = tmp_path / "threshold-profile.json"
    dataset.write_text(json.dumps({"samples": samples}), encoding="utf-8")
    subprocess.run([
        sys.executable, "scripts/calibrate_rendered_gate.py", str(dataset), str(output),
        "--reviewer", "Editor", "--dataset-id", "pilot-v1",
    ], check=True, capture_output=True, text=True)
    profile = json.loads(output.read_text(encoding="utf-8"))
    assert validate_threshold_profile(profile, require_calibrated=True)["passed"] is True
    assert not (tmp_path / "threshold-profile.json.tmp").exists()


def test_opening_gate_log_formats_ratio_without_percent_crash():
    assert pipeline.opening_evidence_gate_message({"verified_information_ratio": 0.75}) \
        == "Opening evidence gate: PASS — 75% verified-information cuts"


@pytest.mark.parametrize(("facts", "errors", "failure"), [
    (_facts(bolt_shot_ratio=1.0), None, "bolt_everywhere"),
    (_facts(slideshow=True, distinct_source_count=1, source_change_ratio=0.0), None,
     "slideshow_behavior"),
    (_facts(long_hold_count=3, max_visual_state_sec=6.0), None, "long_visual_hold"),
    (_facts(continuity_failures=[{"state_id": "s2"}]), None, "broken_continuity"),
    (_facts(unverified_cut_count=1), None, "unverified_rendered_cut"),
    (_facts(), [{"code": "evidence_never_forces_decision"}],
     "false_belief_without_evidence"),
    (_facts(), [{"code": "consequence_enumeration"}], "consequence_list"),
])
def test_seeded_non_viable_openings_fail_closed(facts, errors, failure):
    report = _score(facts=facts, errors=errors)
    assert report["automated_pass"] is False
    assert report["passed"] is False
    assert failure in report["hard_failures"]


def test_automated_observations_cannot_overrule_deterministic_facts():
    checked = cross_check_blind_observations(
        _blind(multi_shot_storytelling=True, evidence_accumulates=True, slideshow=False),
        _facts(slideshow=True, verified_information_ratio=0.3))
    assert checked["multi_shot_storytelling"] is False
    assert checked["evidence_accumulates"] is False
    assert checked["slideshow"] is True
    assert len(checked["cross_check_contradictions"]) == 3


def test_invalid_blind_judge_response_fails_closed_as_unscored():
    checked = cross_check_blind_observations({"judge_error": "timeout"}, _facts())
    report = _score(blind=checked)
    assert checked["valid"] is False
    assert report["automated_pass"] is None
    assert report["score"] is None
    assert report["status"] == "UNSCORED_JUDGE_UNAVAILABLE"


def test_old_moon_diagnostic_is_frozen_at_39_percent():
    # Frozen reconstruction of the previously graded Moon opening: topic readable, a nominal
    # human objective, but Bolt everywhere, 5.08-second states, slideshow reuse, weak evidence,
    # broken continuity, and captions competing with the frame.
    moon_facts = _facts(
        distinct_source_count=3, source_change_ratio=0.2, pixel_boundary_change_ratio=0.2,
        verified_information_ratio=0.25, average_visual_state_sec=5.08,
        max_visual_state_sec=5.4, long_hold_count=8, bolt_shot_ratio=1.0,
        pure_evidence_bolt_violations=4,
        continuity_failures=[{"state_id": "moon:s2", "field": "location_matches"}],
        slideshow=True)
    moon_blind = _blind(
        objective_readable=True, investigation_develops=False, belief_change_earned=False,
        observed_objective="A person watches the Moon", evidence_accumulates=False,
        causal_story=True, forward_question_readable=False,
        observed_evidence_sequence=["the Moon appears larger"], reason_to_continue="",
        multi_shot_storytelling=False, slideshow=True, bolt_useful=False,
        captions_obscure_evidence=True)
    report = _score(facts=moon_facts, blind=moon_blind)
    assert report["score"] == 39
    assert report["percent"] == 39
    assert report["grade"] == "F"
    assert report["automated_pass"] is False


def test_animatic_requires_all_six_recoverable_story_facts():
    script = {
        "_story_contract": {"human_subject": "Alex", "subject_goal": "measure the tide",
                            "anomaly": "the gauge rises while water falls"},
        "scenes": [
            {"belief_changed": "the gauge is not measuring sea level",
             "question_opened": "what is moving it?"},
            {},
        ],
    }
    evidence = {"scenes": [
        {"states": [{"state_id": "s1", "anchor_phrase": "gauge rises",
                     "state_after": "raised gauge"}]},
        {"states": [{"state_id": "s2", "anchor_phrase": "float falls",
                     "state_after": "fallen float"}]},
    ]}
    timing = {"scenes": [{}, {}]}
    report = build_animatic_gate(script, evidence, timing)
    assert report["passed"] is True
    assert all(report["recoverable_story_facts"].values())
    del script["_story_contract"]["subject_goal"]
    assert build_animatic_gate(script, evidence, timing)["passed"] is False


def test_low_cost_animatic_uses_final_tts_and_local_storyboard_cards(tmp_path):
    audio = {}
    for index in range(2):
        path = tmp_path / f"audio_{index}.wav"
        subprocess.run([
            "ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
            "anullsrc=r=44100:cl=mono", "-t", "1.6", str(path),
        ], check=True)
        audio[index] = {"aud": str(path)}
    script = {"scenes": [
        {"story_role": "cold_consequence", "human_intention": "test the gauge"},
        {"story_role": "prediction_test", "question_opened": "why did it reverse?"},
    ]}
    evidence = {"scenes": [
        {"states": [{"state_after": "the gauge jumps"}]},
        {"states": [{"state_after": "the float falls"}]},
    ]}
    output = render_low_cost_animatic(
        script, evidence, audio, str(tmp_path / "animatic.mp4"), width=320, height=180)
    assert Path(output).is_file()
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", output,
    ], check=True, capture_output=True, text=True)
    assert float(probe.stdout.strip()) >= 3.0


def test_human_approval_is_bound_to_exact_report_preview_and_complete_checklist(tmp_path):
    report_path = tmp_path / "report.json"
    preview_path = tmp_path / "preview.mp4"
    review_path = tmp_path / "review.json"
    report_path.write_text('{"score": 90}')
    preview_path.write_bytes(b"approved opening bytes")
    record = create_human_review_record(str(report_path), str(preview_path), str(review_path))
    checklist = [{"item": item, "approved": True, "note": "checked"}
                 for item in HUMAN_REVIEW_CHECKLIST]
    approved = apply_human_review(
        record, reviewer="Editor", decision="approve", checklist=checklist,
        report_path=str(report_path), preview_path=str(preview_path))
    assert approved["decision"] == "approve"
    preview_path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="preview changed"):
        apply_human_review(
            record, reviewer="Editor", decision="approve", checklist=checklist,
            report_path=str(report_path), preview_path=str(preview_path))


def test_diagnostic_mode_is_developer_only_and_never_publishable():
    assert diagnostic_mode_allowed({"LONGFORM_DIAGNOSTIC_MODE": "1", "APP_ENV": "development"})
    assert not diagnostic_mode_allowed({"LONGFORM_DIAGNOSTIC_MODE": "1", "APP_ENV": "production"})
    result = diagnostic_disposition(_score(), allowed=True)
    assert result["status"] == "REJECTED_DIAGNOSTIC"
    assert result["passed"] is False
    assert result["publishable"] is False
    assert result["watermark"]


def test_pipeline_orders_animatic_before_visual_purchase_and_rendered_gate_before_later_assets():
    source = inspect.getsource(pipeline.run_explainer_pipeline)
    assert source.index("build_animatic_gate(") < source.index("def _gen_evidence_assets")
    assert source.index("inspect_rendered_opening(") < source.rindex(
        "generating the remaining")
    assert source.index("raise HumanReviewRequired(") < source.rindex(
        "_gen_assets, all_indexed[opening_stop:]")
    assert "not rendered_contract.get(\"automated_pass\")" in source


def test_phase5_artifact_routes_and_ui_controls_exist():
    paths = {getattr(route, "path", "") for route in fastapi_app.routes}
    assert {
        "/api/explainer/animatic/{job_id}",
        "/api/explainer/animatic-preview/{job_id}",
        "/api/explainer/opening-preview/{job_id}",
        "/api/explainer/rendered-contract/{job_id}",
        "/api/explainer/rendered-contact-sheet/{job_id}",
        "/api/explainer/human-review/{job_id}",
        "/api/explainer/diagnostic-preview/{job_id}",
    }.issubset(paths)
    html = Path("static/index.html").read_text()
    for identity in ("expl-animatic-btn", "expl-animatic-preview-btn",
                     "expl-rendered-contract-btn", "expl-rendered-contact-sheet-btn",
                     "expl-human-review-btn", "expl-review-panel"):
        assert f'id="{identity}"' in html


def test_real_encoded_midpoint_and_boundary_inspection(tmp_path):
    video = tmp_path / "opening.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=red:s=320x180:d=2",
        "-f", "lavfi", "-i", "color=c=green:s=320x180:d=2",
        "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=2",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
    ], check=True)
    plan = [[
        {"duration": 2.0, "source": "a1", "state_id": "s1",
         "verified_visible_information": True},
        {"duration": 2.0, "source": "a2", "state_id": "s2",
         "verified_visible_information": True},
        {"duration": 2.0, "source": "a3", "state_id": "s3",
         "verified_visible_information": True},
    ]]
    evidence = {"scenes": [{"states": [
        {"state_id": "s1", "verification": {}},
        {"state_id": "s2", "verification": {}},
        {"state_id": "s3", "verification": {}},
    ]}]}
    inspection = inspect_rendered_opening(str(video), plan, str(tmp_path), evidence)
    facts = inspection["deterministic"]
    assert facts["decodable"] is True
    assert facts["shot_count"] == 3
    assert facts["distinct_source_count"] == 3
    assert facts["pixel_boundary_change_ratio"] == 1.0
    sheet = build_contact_sheet(inspection, str(tmp_path / "sheet.jpg"))
    assert Path(sheet).is_file()
    assert ImageSize(sheet)[0] == 960
    rejected = watermark_rejected_preview(str(video), str(tmp_path / "rejected.mp4"))
    assert Path(rejected).is_file()


def ImageSize(path):
    from PIL import Image
    with Image.open(path) as image:
        return image.size
