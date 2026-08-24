"""Controlled PR7 45-second pilot contract.

The pilot workflow is intentionally narrower than ordinary explainer generation.  A pilot is an
immutable evaluation run, not a draft editor: it has a fixed runtime/rubric, stops after the
rendered opening, and records failures without offering a route that can turn them into passes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from longform_rendered_gate import RELEASE_SCORE, validate_threshold_profile


PILOT_SCHEMA_VERSION = 1
PILOT_DURATION_SEC = 45
PILOT_MOTION_MODE = "standard"
PILOT_KINDS = ("standard", "evidence_mystery")
PILOT_STORY_FORMATS = {
    "standard": "standard_explainer",
    "evidence_mystery": "evidence_led_mystery",
}

# These are the minimum independently addressable proof artifacts.  The Blob snapshot persists
# every additional file as well; this list only decides whether a pilot is complete enough to grade.
PILOT_REQUIRED_ARTIFACTS = {
    "pilot_control.json",
    "pilot_script.json",
    "research_dossier.json",
    "claim_ledger_report.json",
    "audio_timing_report.json",
    "evidence_asset_plan.json",
    "evidence_validation.json",
    "pilot_cost_report.json",
    "generation_manifest.json",
    "first_minute_preview.mp4",
    "rendered_contact_sheet.jpg",
    "rendered_contract.json",
    "human_review.json",
}


class ControlledPilotError(ValueError):
    """A PR7 pilot request or outcome violates the frozen pilot contract."""


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def pilot_policy() -> dict:
    """Return the frozen validation/spend policy embedded in every pilot request."""
    policy = {
        "schema_version": PILOT_SCHEMA_VERSION,
        "duration_sec": PILOT_DURATION_SEC,
        "rendered_score_floor": RELEASE_SCORE,
        "hard_failures_allowed": 0,
        "motion_mode": PILOT_MOTION_MODE,
        "full_video_purchase_allowed": False,
        "manual_checkpoint_editing_allowed": False,
        "manual_asset_replacement_allowed": False,
        "per_run_threshold_override_allowed": False,
        "failed_result_may_be_promoted": False,
        "required_story_formats": dict(PILOT_STORY_FORMATS),
    }
    return {**policy, "policy_sha256": _canonical_hash(policy)}


def build_pilot_request(*, batch_id: str, pilot_kind: str, question: str,
                        voice: str = "echo", operator_direction: str = "") -> dict:
    """Build one fixed request.  Callers cannot supply runtime, thresholds, or media replacements."""
    if pilot_kind not in PILOT_KINDS:
        raise ControlledPilotError(f"Unknown pilot kind: {pilot_kind!r}")
    batch_id = str(batch_id or "").strip()
    question = str(question or "").strip()
    if not batch_id:
        raise ControlledPilotError("pilot batch_id is required")
    if not question:
        raise ControlledPilotError(f"{pilot_kind} pilot question is required")
    request = {
        "question": question,
        "duration_sec": PILOT_DURATION_SEC,
        "voice": str(voice or "echo").strip() or "echo",
        "style": "evidence-led human story with scientific clarity",
        "image_guidance": "",
        "fact_check": True,
        "video_format": "landscape",
        "speech_bubble": False,
        "i2v": None,
        "motion_mode": PILOT_MOTION_MODE,
        "series": "PR7 Controlled Pilot",
        "short_template": "auto",
        "n_items": 3,
        "operator_direction": str(operator_direction or "").strip(),
        "story_format": PILOT_STORY_FORMATS[pilot_kind],
        "controlled_pilot": True,
        "pilot_batch_id": batch_id,
        "pilot_kind": pilot_kind,
        "pilot_policy": pilot_policy(),
    }
    validate_pilot_request(request, expected_kind=pilot_kind)
    return request


def build_pilot_pair(*, batch_id: str, standard_question: str, mystery_question: str,
                     voice: str = "echo", standard_direction: str = "",
                     mystery_direction: str = "") -> list[dict]:
    """Return exactly one Standard and one Evidence Mystery request."""
    pair = [
        build_pilot_request(
            batch_id=batch_id, pilot_kind="standard", question=standard_question,
            voice=voice, operator_direction=standard_direction),
        build_pilot_request(
            batch_id=batch_id, pilot_kind="evidence_mystery", question=mystery_question,
            voice=voice, operator_direction=mystery_direction),
    ]
    if {item["pilot_kind"] for item in pair} != set(PILOT_KINDS) or len(pair) != 2:
        raise ControlledPilotError("A PR7 batch requires exactly one pilot of each kind")
    return pair


def validate_pilot_request(request: dict, *, expected_kind: str | None = None) -> dict:
    """Reject a mutated pilot request before any provider or visual spend."""
    errors: list[str] = []
    kind = str(request.get("pilot_kind") or "")
    if kind not in PILOT_KINDS:
        errors.append("pilot_kind must be standard or evidence_mystery")
    if expected_kind and kind != expected_kind:
        errors.append(f"pilot_kind must remain {expected_kind}")
    expected = {
        "controlled_pilot": True,
        "duration_sec": PILOT_DURATION_SEC,
        "video_format": "landscape",
        "motion_mode": PILOT_MOTION_MODE,
        "fact_check": True,
        "story_format": PILOT_STORY_FORMATS.get(kind),
    }
    for field, value in expected.items():
        if request.get(field) != value:
            errors.append(f"{field} must equal {value!r}")
    policy = request.get("pilot_policy") if isinstance(request.get("pilot_policy"), dict) else {}
    frozen = pilot_policy()
    if policy != frozen:
        errors.append("pilot_policy does not match the frozen PR7 policy")
    forbidden = {
        "threshold_profile", "threshold_overrides", "validation_overrides",
        "replacement_images", "manual_assets", "checkpoint_path", "resume",
    }
    present = sorted(field for field in forbidden if field in request)
    if present:
        errors.append("forbidden pilot override fields: " + ", ".join(present))
    if not str(request.get("pilot_batch_id") or "").strip():
        errors.append("pilot_batch_id is required")
    if not str(request.get("question") or "").strip():
        errors.append("question is required")
    if errors:
        raise ControlledPilotError("; ".join(errors))
    return {"passed": True, "pilot_kind": kind, "policy_sha256": frozen["policy_sha256"]}


def validate_effective_story_format(script: dict, request: dict) -> dict:
    """A Mystery→Standard fallback is a failed Mystery pilot, never a substituted pilot."""
    validate_pilot_request(request)
    expected = PILOT_STORY_FORMATS[request["pilot_kind"]]
    effective = str(script.get("_story_format") or expected).strip()
    errors = []
    if effective != expected:
        errors.append(
            f"{request['pilot_kind']} pilot generated {effective!r}; expected {expected!r}")
    if request["pilot_kind"] == "evidence_mystery" and str(
            script.get("_story_format_fallback_reason") or "").strip():
        errors.append("Evidence Mystery pilot fell back to Standard")
    return {"passed": not errors, "expected": expected, "effective": effective,
            "errors": errors}


def artifact_completeness(output_dir: str) -> dict:
    root = Path(output_dir)
    present = {
        str(path.relative_to(root)).replace(os.sep, "/")
        for path in root.rglob("*") if path.is_file() and not path.name.endswith(".tmp")
    }
    missing = sorted(PILOT_REQUIRED_ARTIFACTS - present)
    return {
        "passed": not missing,
        "required": sorted(PILOT_REQUIRED_ARTIFACTS),
        "present_count": len(present),
        "missing": missing,
    }


def final_pilot_outcome(*, rendered_contract: dict, human_review: dict,
                        completeness: dict) -> dict:
    """Combine immutable automated and editorial grades without an override path."""
    score = int(rendered_contract.get("score") or 0)
    hard_failures = sorted(set(rendered_contract.get("hard_failures") or []))
    calibration = validate_threshold_profile(
        rendered_contract.get("threshold_profile") or {}, require_calibrated=True)
    automated_pass = bool(
        rendered_contract.get("automated_pass")
        and score >= RELEASE_SCORE
        and not hard_failures
        and calibration.get("passed")
    )
    checklist = human_review.get("checklist") if isinstance(human_review.get("checklist"), list) else []
    editorial_pass = bool(
        human_review.get("status") == "completed"
        and human_review.get("decision") == "approve"
        and checklist
        and all(item.get("approved") is True for item in checklist)
    )
    artifacts_pass = bool(completeness.get("passed"))
    passed = automated_pass and editorial_pass and artifacts_pass
    reasons = []
    if not automated_pass:
        reasons.append("automated_rendered_contract_failed")
    if not editorial_pass:
        reasons.append("editorial_review_failed")
    if not artifacts_pass:
        reasons.append("required_artifacts_missing")
    return {
        "schema_version": PILOT_SCHEMA_VERSION,
        "status": "pilot_passed" if passed else "pilot_failed",
        "pilot_passed": passed,
        "publishable_full_video": False,
        "automated": {
            "passed": automated_pass,
            "score": score,
            "score_floor": RELEASE_SCORE,
            "hard_failures": hard_failures,
            "threshold_calibration": calibration,
        },
        "editorial": {
            "passed": editorial_pass,
            "decision": human_review.get("decision") or "pending",
            "reviewer": human_review.get("reviewer") or "",
        },
        "artifacts": completeness,
        "failure_reasons": reasons,
        "promotion_rule": "A failed automated or editorial grade cannot be promoted in place.",
    }
