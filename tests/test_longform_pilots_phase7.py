from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

import app as app_module
import durable_execution
import explainer_pipeline
from app import ExplainerPilotBatchRequest, ExplainerRequest
from longform_rendered_gate import create_human_review_record
from longform_pilots import (
    ControlledPilotError,
    PILOT_DURATION_SEC,
    PILOT_KINDS,
    PILOT_MOTION_MODE,
    build_pilot_pair,
    final_pilot_outcome,
    pilot_policy,
    validate_effective_story_format,
    validate_pilot_request,
    PILOT_REQUIRED_ARTIFACTS,
)


def _calibrated_profile() -> dict:
    return {
        "schema_version": 1,
        "profile_id": "pilot-calibrated-v1",
        "status": "calibrated",
        "pixel_delta_threshold": 0.035,
        "source_change_ratio_threshold": 0.45,
        "dataset_sha256": "dataset-hash",
        "reviewer": "Calibration Editor",
        "created_at": "2026-08-23T00:00:00+00:00",
        "method": "balanced_accuracy_human_labeled_real_video_v1",
        "sample_counts": {
            "meaningful_change": 20,
            "not_meaningful_change": 20,
            "not_slideshow": 20,
            "slideshow": 20,
        },
        "metrics": {
            "pixel_delta": {
                "balanced_accuracy": 0.9, "sensitivity": 0.9, "specificity": 0.9,
            },
            "source_change_ratio": {
                "balanced_accuracy": 0.9, "sensitivity": 0.9, "specificity": 0.9,
            },
        },
    }


def _review(decision: str = "approve") -> dict:
    approved = decision == "approve"
    return {
        "status": "completed",
        "decision": decision,
        "reviewer": "Editor",
        "checklist": [{"item": "story is legible", "approved": approved}],
    }


def _contract(**overrides) -> dict:
    value = {
        "score": 88,
        "automated_pass": True,
        "hard_failures": [],
        "threshold_profile": _calibrated_profile(),
    }
    value.update(overrides)
    return value


def test_pair_is_exactly_one_fixed_standard_and_mystery_request():
    pair = build_pilot_pair(
        batch_id="pr7-batch", standard_question="What if the Moon moved closer?",
        mystery_question="Why did the tide gauge move?", voice="echo")

    assert len(pair) == 2
    assert {item["pilot_kind"] for item in pair} == set(PILOT_KINDS)
    assert {item["story_format"] for item in pair} == {
        "standard_explainer", "evidence_led_mystery"}
    assert all(item["duration_sec"] == PILOT_DURATION_SEC for item in pair)
    assert all(item["motion_mode"] == PILOT_MOTION_MODE for item in pair)
    assert all(item["controlled_pilot"] is True for item in pair)
    assert all(item["pilot_policy"] == pilot_policy() for item in pair)


@pytest.mark.parametrize(("field", "value"), [
    ("duration_sec", 44),
    ("motion_mode", "stills"),
    ("fact_check", False),
    ("story_format", "standard_explainer"),
])
def test_pilot_request_mutations_fail_before_spend(field, value):
    request = build_pilot_pair(
        batch_id="pr7-batch", standard_question="Standard", mystery_question="Mystery")[1]
    request[field] = value
    with pytest.raises(ControlledPilotError):
        validate_pilot_request(request, expected_kind="evidence_mystery")


@pytest.mark.parametrize("field", [
    "threshold_profile", "threshold_overrides", "validation_overrides",
    "replacement_images", "manual_assets", "checkpoint_path", "resume",
])
def test_pilot_rejects_manual_or_threshold_override_fields(field):
    request = build_pilot_pair(
        batch_id="pr7-batch", standard_question="Standard", mystery_question="Mystery")[0]
    request[field] = {} if field != "resume" else True
    with pytest.raises(ControlledPilotError, match="forbidden pilot override"):
        validate_pilot_request(request)


def test_mystery_fallback_is_a_failed_mystery_not_a_standard_substitute():
    request = build_pilot_pair(
        batch_id="pr7-batch", standard_question="Standard", mystery_question="Mystery")[1]
    report = validate_effective_story_format({
        "_story_format": "standard_explainer",
        "_story_format_fallback_reason": "no genuine contradictory evidence",
    }, request)
    assert report["passed"] is False
    assert "fell back" in " ".join(report["errors"])


def test_editorial_approval_cannot_promote_an_automated_failure():
    outcome = final_pilot_outcome(
        rendered_contract=_contract(
            score=92, automated_pass=False, hard_failures=["slideshow_behavior"]),
        human_review=_review("approve"),
        completeness={"passed": True, "missing": []},
    )
    assert outcome["status"] == "pilot_failed"
    assert outcome["pilot_passed"] is False
    assert outcome["publishable_full_video"] is False
    assert "automated_rendered_contract_failed" in outcome["failure_reasons"]


def test_uncalibrated_thresholds_cannot_pass_a_pilot():
    provisional = {
        "schema_version": 1,
        "profile_id": "provisional-defaults-v1",
        "status": "provisional_uncalibrated",
        "pixel_delta_threshold": 0.035,
        "source_change_ratio_threshold": 0.45,
        "dataset_sha256": "",
        "sample_counts": {
            "meaningful_change": 0, "not_meaningful_change": 0,
            "not_slideshow": 0, "slideshow": 0,
        },
    }
    outcome = final_pilot_outcome(
        rendered_contract=_contract(score=100, threshold_profile=provisional),
        human_review=_review("approve"),
        completeness={"passed": True, "missing": []},
    )
    assert outcome["pilot_passed"] is False
    assert outcome["automated"]["threshold_calibration"]["passed"] is False


def test_pilot_pass_requires_automated_editorial_and_artifact_gates():
    outcome = final_pilot_outcome(
        rendered_contract=_contract(), human_review=_review("approve"),
        completeness={"passed": True, "missing": []})
    assert outcome["status"] == "pilot_passed"
    assert outcome["automated"]["score_floor"] == 85
    assert outcome["publishable_full_video"] is False


def test_pipeline_controlled_pilot_returns_before_later_visual_purchase():
    source = inspect.getsource(explainer_pipeline.run_explainer_pipeline)
    stop = source.index("# PR7 stops here by contract")
    later = source.index("later = []", stop)
    controlled_return = source.index('"controlled_pilot": True', stop)
    assert stop < controlled_return < later
    assert pilot_policy()["full_video_purchase_allowed"] is False


class _ArtifactStore:
    def __init__(self):
        self.rows = []
        self.events_seen = []
        self.finalized = False

    def artifacts(self, _job_id):
        return list(self.rows)

    def register_artifact(self, job_id, kind, stage_key, artifact, *, provisional=True):
        self.rows.append({
            "job_id": job_id, "kind": kind, "stage_key": stage_key,
            "provisional": provisional, **artifact,
        })

    def mark_finalized(self, _job_id):
        self.finalized = True

    def append_event(self, _job_id, event_type, data, details=None):
        self.events_seen.append((event_type, data, details or {}))


class _ArtifactBlob:
    def __init__(self):
        self.uploads = []

    def upload(self, local_path, remote_path):
        payload = Path(local_path).read_bytes()
        artifact = {
            "url": f"https://blob.example/{len(self.uploads)}",
            "download_url": f"https://blob.example/{len(self.uploads)}?download=1",
            "pathname": remote_path,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "content_type": "application/octet-stream",
        }
        self.uploads.append((local_path, remote_path, artifact))
        return artifact

    def delete(self, _target):
        pass


def test_terminal_snapshot_uploads_every_file_including_failed_artifacts(tmp_path):
    (tmp_path / "pilot_failure.json").write_text('{"status":"pilot_failed"}')
    (tmp_path / "rendered_contract.json").write_text('{"score":39}')
    nested = tmp_path / "images"
    nested.mkdir()
    (nested / "evidence.png").write_bytes(b"pixels")
    store, blob = _ArtifactStore(), _ArtifactBlob()
    runtime = durable_execution.DurableRuntime(
        job_id="pilot-failed", worker_id="test", output_dir=str(tmp_path),
        store=store, blob=blob)

    receipt = runtime.persist_pilot_snapshot(
        "failed", metadata={"status": "pilot_failed"}, final=True, heartbeat=False)

    files_after = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert receipt["artifact_count"] == len(files_after)
    assert len(blob.uploads) == len(files_after)
    assert {Path(path).relative_to(tmp_path).as_posix() for path, _, _ in blob.uploads} \
        == {path.relative_to(tmp_path).as_posix() for path in files_after}
    assert "pilot_artifact_manifest.json" in {
        path.relative_to(tmp_path).as_posix() for path in files_after}
    assert store.finalized is True


def test_public_generate_endpoint_cannot_smuggle_a_controlled_pilot():
    request = ExplainerRequest(question="test", controlled_pilot=True)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_module.explainer_generate(request, BackgroundTasks()))
    assert exc.value.status_code == 403


def test_pilot_batch_endpoint_queues_exact_pair_atomically(monkeypatch):
    captured = {}

    class Store:
        def enqueue_pilot_batch(self, **kwargs):
            captured.update(kwargs)
            return {
                "status": "queued",
                "jobs": [
                    {"id": item["job_id"], "request": item["request"]}
                    for item in kwargs["jobs"]
                ],
            }

    monkeypatch.setattr(app_module, "_require_render_storage", lambda: None)
    monkeypatch.setattr(app_module, "_durable_execution_required", lambda: True)
    monkeypatch.setattr(app_module, "_durable_components", lambda: (Store(), object()))
    monkeypatch.setattr(durable_execution, "version_hash", lambda _root: "pipeline-hash")
    response = asyncio.run(app_module.explainer_create_pilot_batch(
        ExplainerPilotBatchRequest(
            standard_question="Standard question", mystery_question="Mystery question")))

    assert len(captured["jobs"]) == 2
    assert {job["request"]["pilot_kind"] for job in captured["jobs"]} == set(PILOT_KINDS)
    assert response["pilots"]["standard"]["job_id"].endswith("-standard")
    assert response["pilots"]["evidence_mystery"]["job_id"].endswith("-mystery")


def test_pilot_batch_request_forbids_unadvertised_override_fields():
    with pytest.raises(Exception):
        ExplainerPilotBatchRequest(
            standard_question="Standard", mystery_question="Mystery",
            threshold_overrides={"pixel_delta_threshold": 0.0})


def test_pilot_batch_reports_storage_unavailability_as_retryable_503(monkeypatch):
    class Store:
        def enqueue_pilot_batch(self, **_kwargs):
            raise durable_execution.StorageUnavailable("database is offline")

    monkeypatch.setattr(app_module, "_require_render_storage", lambda: None)
    monkeypatch.setattr(app_module, "_durable_execution_required", lambda: True)
    monkeypatch.setattr(app_module, "_durable_components", lambda: (Store(), object()))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_module.explainer_create_pilot_batch(
            ExplainerPilotBatchRequest(
                standard_question="Standard question", mystery_question="Mystery question")))
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "PILOT_STORAGE_UNAVAILABLE"
    assert exc.value.detail["retryable"] is True


def test_pipeline_version_hash_tracks_the_controlled_pilot_contract(tmp_path):
    tracked = (
        "explainer_pipeline.py", "longform_retention.py", "longform_evidence.py",
        "longform_motion.py", "longform_pilots.py", "longform_rendered_gate.py",
        "durable_execution.py",
    )
    for name in tracked:
        (tmp_path / name).write_text(name, encoding="utf-8")
    before = durable_execution.version_hash(tmp_path)
    (tmp_path / "longform_pilots.py").write_text("changed policy", encoding="utf-8")
    assert durable_execution.version_hash(tmp_path) != before


class _TaskStore:
    def __init__(self):
        self.statuses = []
        self.events = []

    def set_status(self, job_id, status, **kwargs):
        self.statuses.append((job_id, status, kwargs))

    def append_event(self, job_id, event_type, data, details=None):
        self.events.append((job_id, event_type, data, details or {}))
        return len(self.events)


class _TaskRuntime:
    def __init__(self, output_dir):
        self.output_dir = str(output_dir)
        self.worker_id = "pilot-worker"
        self.store = _TaskStore()
        self.snapshots = []
        self.checkpoints = []

    def event(self, event_type, data, details=None):
        self.store.append_event("pilot-job", event_type, data, details)

    def checkpoint(self, label, heartbeat=False):
        self.checkpoints.append((label, heartbeat))
        return {"sha256": f"checkpoint-{label}"}

    def persist_pilot_snapshot(self, label, **kwargs):
        self.snapshots.append((label, kwargs))
        return {"artifact_count": 3, "label": label}


def test_failed_pipeline_attempt_is_terminal_and_snapshotted_without_retry(monkeypatch, tmp_path):
    request_payload = build_pilot_pair(
        batch_id="pr7-batch", standard_question="Standard", mystery_question="Mystery")[0]
    request = ExplainerRequest(**request_payload)
    runtime = _TaskRuntime(tmp_path)

    def fail(**_kwargs):
        raise RuntimeError("seeded rendered-gate failure")

    monkeypatch.setattr(explainer_pipeline, "run_explainer_pipeline", fail)
    job_id = "pilot-failure-job"
    app_module.explainer_jobs[job_id] = {
        "id": job_id, "status": "queued", "events": [], "error": None,
    }
    try:
        asyncio.run(app_module.run_explainer_task(
            job_id, request, str(tmp_path), durable_runtime=runtime))
        assert app_module.explainer_jobs[job_id]["status"] == "pilot_failed"
        assert json.loads((tmp_path / "pilot_failure.json").read_text())["status"] \
            == "pilot_failed"
        assert runtime.snapshots[0][0] == "failed"
        assert runtime.snapshots[0][1]["final"] is True
        assert runtime.store.statuses[-1][1] == "pilot_failed"
        assert not any(status == "retry" for _, status, _ in runtime.store.statuses)
    finally:
        app_module.explainer_jobs.pop(job_id, None)


def test_editorial_approval_still_records_failed_outcome_when_automation_failed(
        monkeypatch, tmp_path):
    report_path = tmp_path / "rendered_contract.json"
    preview_path = tmp_path / "first_minute_preview.mp4"
    review_path = tmp_path / "human_review.json"
    report_path.write_text(json.dumps(_contract(
        score=92, automated_pass=False, hard_failures=["slideshow_behavior"])))
    preview_path.write_bytes(b"encoded pilot opening")
    pending = create_human_review_record(str(report_path), str(preview_path), str(review_path))
    for relative in PILOT_REQUIRED_ARTIFACTS:
        path = tmp_path / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"artifact")

    store = _TaskStore()

    class EditorialRuntime:
        def __init__(self, **_kwargs):
            pass

        def checkpoint(self, label, heartbeat=False):
            return {"sha256": f"checkpoint-{label}"}

        def persist_pilot_snapshot(self, label, **_kwargs):
            return {"artifact_count": len(PILOT_REQUIRED_ARTIFACTS), "label": label}

    monkeypatch.setattr(app_module, "_durable_execution_required", lambda: True)
    monkeypatch.setattr(app_module, "_durable_components", lambda: (store, object()))
    monkeypatch.setattr(durable_execution, "DurableRuntime", EditorialRuntime)
    job_id = "pilot-editorial-failure"
    app_module.explainer_jobs[job_id] = {
        "id": job_id,
        "status": "pilot_awaiting_editorial",
        "controlled_pilot": True,
        "_materialized_dir": str(tmp_path),
        "human_review_path": str(review_path),
        "rendered_contract_path": str(report_path),
        "first_minute_preview_path": str(preview_path),
    }
    checklist = [
        {"item": item["item"], "approved": True, "note": "reviewed"}
        for item in pending["checklist"]
    ]
    try:
        response = asyncio.run(app_module.explainer_record_human_review(
            job_id,
            app_module.ExplainerHumanReviewRequest(
                reviewer="Editor", decision="approve", checklist=checklist),
        ))
        assert response["pilot_outcome"]["status"] == "pilot_failed"
        assert response["pilot_outcome"]["pilot_passed"] is False
        assert response["resume_allowed"] is False
        assert store.statuses[-1][1] == "pilot_failed"
    finally:
        app_module.explainer_jobs.pop(job_id, None)
