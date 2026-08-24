"""Corrective regression matrix for the remaining PR1–PR6 contract gaps."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import explainer_pipeline as pipeline
from app import (
    ExplainerStoryFormatReviewRequest,
    _checkpoint_generation_manifest,
    app as fastapi_app,
    explainer_jobs,
    explainer_record_story_format_review,
)
from longform_rendered_gate import PROVISIONAL_THRESHOLD_PROFILE
from longform_retention import (
    apply_story_format_review,
    create_story_format_review,
    validate_story_format_review,
)


def _fallback_script() -> dict:
    return {
        "title": "Why the gauge moved",
        "_story_format_requested": "evidence_led_mystery",
        "_story_format": "standard_explainer",
        "_story_format_fallback_reason": "no failed prediction or test",
        "_story_contract": {
            "story_format_requested": "evidence_led_mystery",
            "story_format_effective": "standard_explainer",
            "story_format_fallback_reason": "no failed prediction or test",
        },
        "scenes": [],
    }


def test_pr1_to_pr3_story_format_fallback_is_hash_bound_and_explicit(tmp_path):
    script = _fallback_script()
    path = tmp_path / "story_format_review.json"
    pending = create_story_format_review(script, str(path))
    assert pending["fallback"]["requested"] == "evidence_led_mystery"
    assert pending["fallback"]["effective"] == "standard_explainer"
    assert pending["fallback"]["reason"] == "no failed prediction or test"
    assert validate_story_format_review(pending, script) is False

    accepted = apply_story_format_review(
        pending, script=script, reviewer="Editor", decision="accept")
    assert validate_story_format_review(accepted, script) is True
    script["_story_contract"]["story_format_fallback_reason"] = "changed reason"
    assert validate_story_format_review(accepted, script) is False


def test_pr5_fallback_pause_occurs_before_tts_or_visual_generation():
    source = inspect.getsource(pipeline.run_explainer_pipeline)
    pause = source.index("raise StoryFormatAcknowledgementRequired(")
    tts = source.index('log("stage:Generating and measuring final-speed narration...")')
    visuals = source.index("def _gen_evidence_assets")
    assert pause < tts
    assert pause < visuals


def test_pr5_measured_evidence_timing_cannot_run_before_audio_exists():
    source = inspect.getsource(pipeline.run_explainer_pipeline)
    measured_audio = source.index("prepared, audio_timing = _prepare_longform_audio(")
    first_timing_gate = source.index("validate_evidence_timing(")
    assert measured_audio < first_timing_gate


def test_pr5_and_pr6_ui_api_expose_fallback_and_generation_manifest():
    paths = {getattr(route, "path", "") for route in fastapi_app.routes}
    assert {
        "/api/explainer/story-format-review/{job_id}",
        "/api/explainer/generation-manifest/{job_id}",
    }.issubset(paths)
    html = Path("static/index.html").read_text(encoding="utf-8")
    for marker in (
        'id="expl-format-review-panel"', "format_acknowledgement_required",
        "submitExplainerFormatReview('accept')", 'id="expl-generation-manifest-btn"',
    ):
        assert marker in html
    assert html.count("?after=${resumeAfter}") == 2
    charts_end = html.index("<!-- /charts-section -->")
    explainer_start = html.index('id="explainer-section"')
    explainer_end = html.index("<!-- /explainer-section -->")
    for panel in ('id="expl-format-review-panel"', 'id="expl-review-panel"'):
        position = html.index(panel)
        assert charts_end < explainer_start < position < explainer_end


def test_pr5_story_format_review_endpoint_records_operator_acceptance(tmp_path):
    job_id = "format-review-unit-job"
    script = _fallback_script()
    review_path = tmp_path / "story_format_review.json"
    create_story_format_review(script, str(review_path))
    explainer_jobs[job_id] = {
        "id": job_id, "status": "format_acknowledgement_required",
        "story_format_review_path": str(review_path), "script": script,
    }
    try:
        reviewed = asyncio.run(explainer_record_story_format_review(
            job_id, ExplainerStoryFormatReviewRequest(reviewer="Editor", decision="accept")))
        assert reviewed["decision"] == "accept"
        assert reviewed["reviewer"] == "Editor"
        assert explainer_jobs[job_id]["status"] == "format_acknowledged"
        assert validate_story_format_review(reviewed, script) is True
    finally:
        explainer_jobs.pop(job_id, None)


def test_pr6_manifest_records_exact_request_model_ids_and_stability(monkeypatch):
    monkeypatch.setattr(pipeline, "_I2V_CHAIN", ["fal"])
    manifest = pipeline._generation_manifest_payload(
        video_format="landscape", motion_mode="stills",
        threshold_profile=dict(PROVISIONAL_THRESHOLD_PROFILE))
    models = {(item["provider"], item["purpose"]): item for item in manifest["models"]}
    assert models[("anthropic", "research_script_factcheck_and_visual_judges")]["model_id"] \
        == pipeline.ANTHROPIC_MODEL
    assert models[("openai", "evidence_and_scene_images")]["model_id"] \
        == pipeline.IMAGE_MODEL
    assert models[("openai", "narration")]["model_id"] == pipeline.TTS_MODEL
    assert models[("openai", "word_timestamps")]["model_id"] \
        == pipeline.TRANSCRIPTION_MODEL
    # No entry may claim a pinned snapshot: current-generation Anthropic and OpenAI IDs are
    # undated request identifiers, and a provenance record that overstates one is worse than
    # no record at all.
    assert models[("anthropic", "research_script_factcheck_and_visual_judges")][
        "identifier_stability"] == "request_identifier"
    assert not any(item["identifier_stability"] == "pinned_snapshot"
                   for item in manifest["models"])
    assert models[("fal", "image_to_video")]["model_id"] == pipeline._FAL_MODEL
    assert all(item["model_id"] for item in manifest["models"])
    json.dumps(manifest)

    source = Path("explainer_pipeline.py").read_text(encoding="utf-8")
    assert 'model="claude-opus-4-8"' not in source
    assert "model=ANTHROPIC_MODEL" in source


def test_pr6_manifest_rejects_unknown_motion_provider(monkeypatch):
    monkeypatch.setattr(pipeline, "_I2V_CHAIN", ["invented-provider"])
    try:
        pipeline._generation_manifest_payload(
            video_format="landscape", motion_mode="full_motion",
            threshold_profile=dict(PROVISIONAL_THRESHOLD_PROFILE))
    except ValueError as exc:
        assert "Unsupported I2V provider" in str(exc)
    else:
        raise AssertionError("unknown provider must fail before generation spend")


def test_pr6_durable_resume_and_checkpoint_include_format_acknowledgement():
    source = Path("app.py").read_text(encoding="utf-8")
    assert '"story_format_review_path": "story_format_review.json"' in source
    assert '"generation_manifest_path": "generation_manifest.json"' in source
    assert '"format_acknowledged", "retry", "storage_error"' in source
    assert '"awaiting-format-acknowledgement"' in source


def test_pr6_paused_manifest_records_actual_audio_and_motion(tmp_path):
    (tmp_path / "generation_manifest.json").write_text(json.dumps({
        "schema_version": 1, "status": "started", "models": [],
    }), encoding="utf-8")
    (tmp_path / "audio_timing_report.json").write_text(json.dumps({
        "audio_transformations": [{"model": "tts-1-hd", "speed_multiplier": 1.0}],
    }), encoding="utf-8")
    (tmp_path / "motion_report.json").write_text(json.dumps({
        "candidates": [{"selected": True, "state_id": "s1", "provider": "fal",
                        "model_id": "fal-ai/model", "generation_status": "animated",
                        "provider_attempts": ["ok:fal"]}],
    }), encoding="utf-8")

    _checkpoint_generation_manifest(
        str(tmp_path), status="awaiting_human_review", error="approval required")
    manifest = json.loads((tmp_path / "generation_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "awaiting_human_review"
    assert manifest["actual_audio_transformations"][0]["speed_multiplier"] == 1.0
    assert manifest["actual_motion"][0]["model_id"] == "fal-ai/model"
    assert manifest["error"] == "approval required"
