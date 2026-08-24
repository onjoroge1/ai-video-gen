"""Controlled PR8 90-second production pilot contract.

PR7 graded two rendered *openings* and deliberately stopped before buying a full video.  PR8 buys
exactly one complete 90-second video, and only from the structure that already won a completed PR7
batch.  Every gate here is stricter than the ordinary release path:

* the structure is selected from recorded PR7 scores, not chosen by hand;
* the approved PR7 opening is carried forward by hash and must be reused byte-for-byte;
* runtime is measured from the encoded MP4 *and* from natural-speed narration, never post-stretched;
* the rendered-contract floor is 90, not the ordinary 85;
* dropped narration, filler frames, unresolved narrative loops, and unprovenanced media are hard
  failures rather than degradations;
* the deliverable MP4 must be fast-start, and the durable job must prove cross-worker recovery.

Like PR7 this is an immutable evaluation run: nothing in this module offers a route that turns a
recorded failure into a pass.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
from pathlib import Path
from typing import Any

from longform_motion import sha256_file, validate_frozen_opening
from longform_rendered_gate import validate_threshold_profile


PRODUCTION_SCHEMA_VERSION = 1
PRODUCTION_DURATION_SEC = 90

# The roadmap's 87.3–92.7s window is exactly the pipeline's ±3% measured-narration tolerance at a
# 90-second target.  Deriving it keeps the two definitions from drifting apart silently.
PRODUCTION_RUNTIME_TOLERANCE_RATIO = 0.03
PRODUCTION_RUNTIME_TOLERANCE_SEC = round(PRODUCTION_DURATION_SEC * PRODUCTION_RUNTIME_TOLERANCE_RATIO, 3)
PRODUCTION_RUNTIME_MIN = round(PRODUCTION_DURATION_SEC - PRODUCTION_RUNTIME_TOLERANCE_SEC, 3)
PRODUCTION_RUNTIME_MAX = round(PRODUCTION_DURATION_SEC + PRODUCTION_RUNTIME_TOLERANCE_SEC, 3)
assert (PRODUCTION_RUNTIME_MIN, PRODUCTION_RUNTIME_MAX) == (87.3, 92.7)

# PR8 requires an A grade, not the ordinary 85-point release floor.
PRODUCTION_RELEASE_SCORE = 90

PRODUCTION_MOTION_MODE = "standard"
PRODUCTION_STORY_FORMATS = {
    "standard": "standard_explainer",
    "evidence_mystery": "evidence_led_mystery",
}

PRODUCTION_REQUIRED_ARTIFACTS = {
    "production_control.json",
    "production_selection.json",
    "production_script.json",
    "research_dossier.json",
    "claim_ledger_report.json",
    "audio_timing_report.json",
    "evidence_asset_plan.json",
    "evidence_validation.json",
    "retention_validation.json",
    "opening_freeze.json",
    "generation_manifest.json",
    "production_cost_report.json",
    "rendered_contract.json",
    "rendered_contact_sheet.jpg",
    "human_review.json",
    "production_storage_proof.json",
    "publish_recommendation.json",
}

# Channel-padding phrases that occupy narration time without carrying story information.  The list
# is intentionally narrow: each entry is filler in *any* scripted explainer, so a match is a defect
# rather than a style disagreement.
FILLER_PHRASES = (
    "and that's not all",
    "as we all know",
    "at the end of the day",
    "before we get started",
    "but first",
    "don't forget to subscribe",
    "hit that like button",
    "in today's video",
    "in this video",
    "let that sink in",
    "let's dive right in",
    "like and subscribe",
    "more on that later",
    "needless to say",
    "stay tuned",
    "the rest of the story",
    "we'll get to that",
    "without further ado",
    "you won't believe",
)

# A scene earns its runtime by doing at least one of these jobs.  A scene that does none of them is
# structural filler even when every individual word is clean.
_STORY_WORK_FIELDS = (
    "claim_refs",
    "closes_loop",
    "opens_loop",
    "question_answered",
    "question_opened",
    "visible_consequence",
)


class ControlledProductionError(ValueError):
    """A PR8 production request or outcome violates the frozen production contract."""


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _issue(code: str, message: str, **fields: Any) -> dict:
    return {"code": code, "message": message, **fields}


def production_policy() -> dict:
    """Return the frozen validation/spend policy embedded in every production request."""
    policy = {
        "schema_version": PRODUCTION_SCHEMA_VERSION,
        "duration_sec": PRODUCTION_DURATION_SEC,
        "runtime_min_sec": PRODUCTION_RUNTIME_MIN,
        "runtime_max_sec": PRODUCTION_RUNTIME_MAX,
        "rendered_score_floor": PRODUCTION_RELEASE_SCORE,
        "hard_failures_allowed": 0,
        "dropped_scenes_allowed": 0,
        "filler_frames_allowed": 0,
        "unresolved_loops_allowed": 0,
        "motion_mode": PRODUCTION_MOTION_MODE,
        "natural_speed_required": True,
        "post_stretched_narration_allowed": False,
        "frozen_opening_reuse_required": True,
        "opening_object_exact_reuse_required": True,
        "fast_start_mp4_required": True,
        "cross_worker_recovery_proof_required": True,
        "manual_checkpoint_editing_allowed": False,
        "manual_asset_replacement_allowed": False,
        "per_run_threshold_override_allowed": False,
        "failed_result_may_be_promoted": False,
        "structure_may_be_hand_picked": False,
    }
    return {**policy, "policy_sha256": _canonical_hash(policy)}


# --------------------------------------------------------------------------------------------
# Structure selection
# --------------------------------------------------------------------------------------------

def select_production_structure(pilot_outcomes: list[dict], *,
                                tie_break: dict | None = None) -> dict:
    """Choose the stronger PR7 structure from recorded pilot outcomes.

    Both pilots must have passed PR7 before any 90-second spend: PR8 is a production run of a
    proven structure, not a second chance for a structure that already failed.  The winner is the
    higher recorded score.  An exact tie is the only case a human may decide, and that decision is
    recorded with the reviewer's identity and reason so it stays auditable; a human may never
    override a real score difference.
    """
    if not isinstance(pilot_outcomes, list) or len(pilot_outcomes) != 2:
        raise ControlledProductionError(
            "Structure selection requires exactly the two graded PR7 pilot outcomes")

    by_kind: dict[str, dict] = {}
    for outcome in pilot_outcomes:
        if not isinstance(outcome, dict):
            raise ControlledProductionError("A PR7 pilot outcome is not an object")
        kind = _text(outcome.get("pilot_kind"))
        if kind not in PRODUCTION_STORY_FORMATS:
            raise ControlledProductionError(f"Unknown PR7 pilot kind: {kind!r}")
        if kind in by_kind:
            raise ControlledProductionError(f"Duplicate PR7 pilot kind: {kind!r}")
        by_kind[kind] = outcome
    if set(by_kind) != set(PRODUCTION_STORY_FORMATS):
        raise ControlledProductionError(
            "Structure selection requires one Standard and one Evidence Mystery outcome")

    scores: dict[str, int] = {}
    for kind, outcome in by_kind.items():
        if not outcome.get("pilot_passed"):
            raise ControlledProductionError(
                f"The {kind} PR7 pilot did not pass; a 90-second production run cannot start")
        automated = outcome.get("automated") if isinstance(outcome.get("automated"), dict) else {}
        try:
            score = int(automated.get("score"))
        except (TypeError, ValueError) as exc:
            raise ControlledProductionError(
                f"The {kind} PR7 outcome has no recorded automated score") from exc
        if automated.get("hard_failures"):
            raise ControlledProductionError(
                f"The {kind} PR7 outcome recorded hard failures and cannot be promoted")
        scores[kind] = score

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    tie = ordered[0][1] == ordered[1][1]
    tie_break_record: dict | None = None
    if tie:
        if not isinstance(tie_break, dict):
            raise ControlledProductionError(
                "The PR7 pilots scored identically; an identified reviewer must record a tie-break")
        reviewer = _text(tie_break.get("reviewer"))
        reason = _text(tie_break.get("reason"))
        chosen = _text(tie_break.get("pilot_kind"))
        if not reviewer or not reason:
            raise ControlledProductionError(
                "A structure tie-break requires both a reviewer identity and a written reason")
        if chosen not in scores:
            raise ControlledProductionError(
                "A structure tie-break must name one of the two graded PR7 pilot kinds")
        winner = chosen
        tie_break_record = {"reviewer": reviewer, "reason": reason, "pilot_kind": chosen}
    else:
        winner = ordered[0][0]
        if isinstance(tie_break, dict) and _text(tie_break.get("pilot_kind")) not in ("", winner):
            raise ControlledProductionError(
                "A reviewer cannot override the stronger PR7 structure; scores differ")

    selection = {
        "schema_version": PRODUCTION_SCHEMA_VERSION,
        "winning_pilot_kind": winner,
        "story_format": PRODUCTION_STORY_FORMATS[winner],
        "scores": dict(sorted(scores.items())),
        "score_margin": abs(ordered[0][1] - ordered[1][1]),
        "tie_break": tie_break_record,
        "source_job_ids": {
            kind: _text(outcome.get("job_id")) for kind, outcome in sorted(by_kind.items())
        },
        "selection_rule": "The higher PR7 rendered-contract score wins; only an exact tie is decided by a named reviewer.",
    }
    return {**selection, "selection_sha256": _canonical_hash(selection)}


# --------------------------------------------------------------------------------------------
# Request contract
# --------------------------------------------------------------------------------------------

def build_production_request(*, production_id: str, selection: dict, question: str,
                             frozen_opening: dict, voice: str = "echo",
                             operator_direction: str = "") -> dict:
    """Build the single fixed 90-second request.  Runtime and thresholds are not caller-supplied."""
    production_id = _text(production_id)
    question = _text(question)
    if not production_id:
        raise ControlledProductionError("production_id is required")
    if not question:
        raise ControlledProductionError("production question is required")
    if not isinstance(selection, dict) or not _text(selection.get("selection_sha256")):
        raise ControlledProductionError("A hashed PR7 structure selection is required")
    if _canonical_hash({k: v for k, v in selection.items() if k != "selection_sha256"}) \
            != selection["selection_sha256"]:
        raise ControlledProductionError("The structure selection hash does not match its contents")
    if not isinstance(frozen_opening, dict) or not (frozen_opening.get("scene_segments")
                                                    or frozen_opening.get("motion_clips")):
        raise ControlledProductionError(
            "The approved PR7 opening freeze manifest is required before production spend")

    request = {
        "question": question,
        "duration_sec": PRODUCTION_DURATION_SEC,
        "voice": _text(voice) or "echo",
        "style": "evidence-led human story with scientific clarity",
        "image_guidance": "",
        "fact_check": True,
        "video_format": "landscape",
        "speech_bubble": False,
        "i2v": None,
        "motion_mode": PRODUCTION_MOTION_MODE,
        "series": "PR8 Controlled Production",
        "short_template": "auto",
        "n_items": 3,
        "operator_direction": _text(operator_direction),
        "story_format": selection["story_format"],
        "controlled_production": True,
        "production_id": production_id,
        "pilot_kind": selection["winning_pilot_kind"],
        "selection_sha256": selection["selection_sha256"],
        "frozen_opening_sha256": _canonical_hash(frozen_opening),
        "production_policy": production_policy(),
    }
    validate_production_request(request)
    return request


def validate_production_request(request: dict) -> dict:
    """Reject a mutated production request before any provider or visual spend."""
    errors: list[str] = []
    kind = _text(request.get("pilot_kind"))
    if kind not in PRODUCTION_STORY_FORMATS:
        errors.append("pilot_kind must be standard or evidence_mystery")
    expected = {
        "controlled_production": True,
        "duration_sec": PRODUCTION_DURATION_SEC,
        "video_format": "landscape",
        "motion_mode": PRODUCTION_MOTION_MODE,
        "fact_check": True,
        "story_format": PRODUCTION_STORY_FORMATS.get(kind),
    }
    for field, value in expected.items():
        if request.get(field) != value:
            errors.append(f"{field} must equal {value!r}")
    policy = request.get("production_policy") if isinstance(
        request.get("production_policy"), dict) else {}
    frozen = production_policy()
    if policy != frozen:
        errors.append("production_policy does not match the frozen PR8 policy")
    forbidden = {
        "threshold_profile", "threshold_overrides", "validation_overrides",
        "replacement_images", "manual_assets", "checkpoint_path", "resume",
        "runtime_override", "score_floor_override",
    }
    present = sorted(field for field in forbidden if field in request)
    if present:
        errors.append("forbidden production override fields: " + ", ".join(present))
    for field in ("production_id", "question", "selection_sha256", "frozen_opening_sha256"):
        if not _text(request.get(field)):
            errors.append(f"{field} is required")
    if errors:
        raise ControlledProductionError("; ".join(errors))
    return {"passed": True, "pilot_kind": kind, "policy_sha256": frozen["policy_sha256"]}


def validate_effective_story_format(script: dict, request: dict) -> dict:
    """A production run that drifts off the selected structure is a failure, not a substitution."""
    validate_production_request(request)
    expected = PRODUCTION_STORY_FORMATS[request["pilot_kind"]]
    effective = _text(script.get("_story_format")) or expected
    errors = []
    if effective != expected:
        errors.append(
            f"production run generated {effective!r}; expected the selected {expected!r}")
    if _text(script.get("_story_format_fallback_reason")):
        errors.append("The production run fell back to a different story format")
    return {"passed": not errors, "expected": expected, "effective": effective, "errors": errors}


# --------------------------------------------------------------------------------------------
# Runtime, narration, and story integrity
# --------------------------------------------------------------------------------------------

def validate_production_runtime(audio_timing: dict, *, encoded_duration_sec: float) -> dict:
    """Runtime must land in 87.3–92.7s in the encoded MP4 *and* in natural-speed narration."""
    errors: list[dict] = []
    timing = audio_timing if isinstance(audio_timing, dict) else {}

    if not timing.get("passed"):
        errors.append(_issue("audio_timing_failed",
                             "The measured audio timing report did not pass."))
    if not timing.get("natural_speed"):
        errors.append(_issue("narration_not_natural_speed",
                             "Runtime must be achieved at natural TTS speed."))
    if timing.get("post_stretched"):
        errors.append(_issue("narration_post_stretched",
                             "Narration was time-stretched; the runtime window is not genuine."))

    try:
        measured = float(timing.get("measured_seconds"))
    except (TypeError, ValueError):
        measured = -1.0
        errors.append(_issue("measured_narration_missing",
                             "The audio timing report has no measured narration runtime."))
    if measured >= 0 and not PRODUCTION_RUNTIME_MIN <= measured <= PRODUCTION_RUNTIME_MAX:
        errors.append(_issue(
            "narration_runtime_outside_window",
            f"Measured narration is {measured:.2f}s; the window is "
            f"{PRODUCTION_RUNTIME_MIN}–{PRODUCTION_RUNTIME_MAX}s."))

    try:
        encoded = float(encoded_duration_sec)
    except (TypeError, ValueError):
        encoded = -1.0
    if encoded <= 0:
        errors.append(_issue("encoded_duration_missing",
                             "The encoded MP4 duration could not be measured."))
    elif not PRODUCTION_RUNTIME_MIN <= encoded <= PRODUCTION_RUNTIME_MAX:
        errors.append(_issue(
            "encoded_runtime_outside_window",
            f"The encoded video is {encoded:.2f}s; the window is "
            f"{PRODUCTION_RUNTIME_MIN}–{PRODUCTION_RUNTIME_MAX}s."))

    # A video that is materially longer than its own narration is padded; one that is materially
    # shorter has lost narration in the edit.  Either way the runtime window means nothing.
    if measured > 0 and encoded > 0 and abs(encoded - measured) > PRODUCTION_RUNTIME_TOLERANCE_SEC:
        errors.append(_issue(
            "encoded_narration_mismatch",
            f"The encoded video ({encoded:.2f}s) and measured narration ({measured:.2f}s) differ "
            f"by more than {PRODUCTION_RUNTIME_TOLERANCE_SEC}s."))

    return {
        "version": PRODUCTION_SCHEMA_VERSION,
        "passed": not errors,
        "window_sec": [PRODUCTION_RUNTIME_MIN, PRODUCTION_RUNTIME_MAX],
        "measured_narration_sec": round(measured, 3) if measured >= 0 else None,
        "encoded_duration_sec": round(encoded, 3) if encoded > 0 else None,
        "natural_speed": bool(timing.get("natural_speed")),
        "post_stretched": bool(timing.get("post_stretched")),
        "errors": errors,
    }


def find_filler_phrases(script: dict) -> list[dict]:
    """Return every frozen filler phrase occurrence with its scene index."""
    found: list[dict] = []
    for index, scene in enumerate(script.get("scenes") or [], 1):
        if not isinstance(scene, dict):
            continue
        narration = _text(scene.get("narration")).casefold()
        if not narration:
            continue
        for phrase in FILLER_PHRASES:
            if re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", narration):
                found.append({"scene": index, "phrase": phrase})
    return found


def validate_narration_integrity(script: dict, audio_timing: dict, *,
                                 dropped_scene_count: int, filler_frame_count: int) -> dict:
    """No dropped narration, no filler frames, no scene that does no story work."""
    errors: list[dict] = []
    script = script if isinstance(script, dict) else {}
    audio_timing = audio_timing if isinstance(audio_timing, dict) else {}
    scenes = script.get("scenes") if isinstance(script.get("scenes"), list) else []
    timing_scenes = audio_timing.get("scenes") if isinstance(
        audio_timing.get("scenes"), list) else []

    try:
        dropped = int(dropped_scene_count)
    except (TypeError, ValueError):
        dropped = -1
    try:
        filler_frames = int(filler_frame_count)
    except (TypeError, ValueError):
        filler_frames = -1
    if dropped != 0:
        errors.append(_issue("dropped_narration",
                             f"{dropped} scene(s) were dropped for missing narration audio.",
                             dropped=dropped))
    if filler_frames != 0:
        errors.append(_issue("filler_frames",
                             f"{filler_frames} scene(s) rendered a placeholder filler frame.",
                             filler_frames=filler_frames))

    if not scenes:
        errors.append(_issue("empty_script", "The production script contains no scenes."))
    if len(timing_scenes) != len(scenes):
        errors.append(_issue(
            "narration_scene_count_mismatch",
            f"The script has {len(scenes)} scene(s) but the timing report covers "
            f"{len(timing_scenes)}."))
    for report in timing_scenes:
        if not isinstance(report, dict):
            continue
        if int(report.get("timed_words") or 0) <= 0:
            errors.append(_issue("scene_narration_missing",
                                 "A scene produced no measured spoken words.",
                                 scene=report.get("scene")))

    for item in find_filler_phrases(script):
        errors.append(_issue("filler_phrase",
                             f"Scene {item['scene']} narration contains filler: {item['phrase']!r}",
                             **item))

    for index, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            continue
        if not any(scene.get(field) for field in _STORY_WORK_FIELDS):
            errors.append(_issue(
                "scene_does_no_story_work",
                f"Scene {index} opens no question, closes none, binds no claim, and shows no "
                f"visible consequence.", scene=index))

    return {
        "version": PRODUCTION_SCHEMA_VERSION,
        "passed": not errors,
        "scene_count": len(scenes),
        "dropped_scene_count": dropped,
        "filler_frame_count": filler_frames,
        "errors": errors,
    }


def validate_resolved_questions(retention_validation: dict) -> dict:
    """Every narrative loop opened by the 90-second story must close inside it."""
    errors: list[dict] = []
    report = retention_validation if isinstance(retention_validation, dict) else {}
    if not isinstance(report.get("checks"), dict):
        errors.append(_issue("retention_validation_missing",
                             "No retention validation report was supplied."))
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    opened = [item for item in (checks.get("opened_loops") or []) if _text(item)]
    unresolved = [item for item in (checks.get("unresolved_loops") or []) if _text(item)]
    if not opened:
        errors.append(_issue("no_tracked_questions",
                             "The production story tracks no open narrative question."))
    if unresolved:
        errors.append(_issue(
            "unresolved_questions",
            "Unresolved narrative question(s): " + ", ".join(sorted(unresolved)),
            unresolved=sorted(unresolved)))

    return {
        "version": PRODUCTION_SCHEMA_VERSION,
        "passed": not errors,
        "opened_loops": sorted(opened),
        "closed_loops": sorted(item for item in (checks.get("closed_loops") or []) if _text(item)),
        "unresolved_loops": sorted(unresolved),
        "errors": errors,
    }


def validate_claim_visual_reconciliation(*, script: dict, claim_validation: dict,
                                         evidence_plan: dict) -> dict:
    """Every claimed scene must have a compiled, verified visual state, and vice versa."""
    errors: list[dict] = []
    if not claim_validation.get("passed"):
        errors.append(_issue("claim_ledger_failed",
                             "The claim ledger did not reconcile with the narration."))

    plan_scenes = evidence_plan.get("scenes") if isinstance(
        evidence_plan.get("scenes"), list) else []
    states_by_scene: dict[int, list[dict]] = {}
    for scene_plan in plan_scenes:
        if not isinstance(scene_plan, dict):
            continue
        index = int(scene_plan.get("scene_index") or 0)
        states_by_scene[index] = [
            state for state in (scene_plan.get("states") or []) if isinstance(state, dict)]

    scenes = script.get("scenes") if isinstance(script.get("scenes"), list) else []
    claimed_scene_count = 0
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        refs = scene.get("claim_refs") if isinstance(scene.get("claim_refs"), list) else []
        states = states_by_scene.get(index) or []
        if refs:
            claimed_scene_count += 1
            if not states:
                errors.append(_issue(
                    "claim_without_visual_state",
                    f"Scene {index + 1} binds a claim but compiled no visual state.",
                    scene=index + 1))
            elif not any(state.get("verified_visible_information") for state in states):
                errors.append(_issue(
                    "claim_without_verified_visual",
                    f"Scene {index + 1} binds a claim but no compiled state shows verified visible "
                    f"information.", scene=index + 1))
        if states and not refs and not _text(scene.get("visible_consequence")):
            errors.append(_issue(
                "visual_without_story_join",
                f"Scene {index + 1} spends visual states without a claim or visible consequence.",
                scene=index + 1))

    if not claimed_scene_count:
        errors.append(_issue("no_claimed_scenes",
                             "A 90-second explainer must bind at least one sourced claim."))

    return {
        "version": PRODUCTION_SCHEMA_VERSION,
        "passed": not errors,
        "claimed_scene_count": claimed_scene_count,
        "planned_scene_count": len(plan_scenes),
        "errors": errors,
    }


# --------------------------------------------------------------------------------------------
# Opening reuse
# --------------------------------------------------------------------------------------------

def validate_opening_object_return(*, opening_freeze: dict, callback_asset_path: str,
                                   opening_asset_path: str) -> dict:
    """The callback must return the *same bytes* as the approved opening object asset.

    The evidence compiler plans ``asset_strategy: exact_reuse`` for the callback state.  PR8 proves
    it in the produced files: a regenerated look-alike has a different hash and fails here.
    """
    errors: list[dict] = []
    freeze = validate_frozen_opening(opening_freeze if isinstance(opening_freeze, dict) else {})
    if not freeze.get("passed"):
        errors.append(_issue("frozen_opening_invalid",
                             "The approved opening freeze manifest no longer validates.",
                             freeze_errors=freeze.get("errors") or []))

    opening_sha = callback_sha = ""
    if not opening_asset_path or not Path(opening_asset_path).is_file():
        errors.append(_issue("opening_asset_missing",
                             "The approved opening object asset is missing."))
    else:
        opening_sha = sha256_file(opening_asset_path)
    if not callback_asset_path or not Path(callback_asset_path).is_file():
        errors.append(_issue("callback_asset_missing",
                             "The callback object asset is missing."))
    else:
        callback_sha = sha256_file(callback_asset_path)

    if opening_sha and callback_sha and opening_sha != callback_sha:
        errors.append(_issue(
            "opening_object_regenerated",
            "The callback object was regenerated instead of reusing the exact opening asset.",
            opening_sha256=opening_sha, callback_sha256=callback_sha))

    frozen_hashes = {
        _text(item.get("sha256"))
        for group in ("scene_segments", "motion_clips")
        for item in (opening_freeze.get(group) or {}).values()
        if isinstance(item, dict)
    }
    if opening_sha and frozen_hashes and opening_sha not in frozen_hashes:
        errors.append(_issue(
            "opening_asset_not_frozen",
            "The opening object asset is not one of the hashes frozen at PR7 approval.",
            opening_sha256=opening_sha))

    return {
        "version": PRODUCTION_SCHEMA_VERSION,
        "passed": not errors,
        "opening_sha256": opening_sha,
        "callback_sha256": callback_sha,
        "frozen_asset_count": freeze.get("checked_asset_count", 0),
        "errors": errors,
    }


# --------------------------------------------------------------------------------------------
# Delivery: provenance, fast-start, durability
# --------------------------------------------------------------------------------------------

_MEDIA_SUFFIXES = {".mp4", ".mov", ".webm", ".m4a", ".mp3", ".wav", ".png", ".jpg", ".jpeg"}


def validate_artifact_provenance(output_dir: str, generation_manifest: dict) -> dict:
    """Every produced media file must be explained by the generation manifest.

    An "unexplained artifact" is a rendered media file nothing in the run claims to have created.
    Provenance is matched by recorded SHA-256 so renaming a file cannot launder it.
    """
    errors: list[dict] = []
    root = Path(output_dir)
    if not root.is_dir():
        return {"version": PRODUCTION_SCHEMA_VERSION, "passed": False, "media_count": 0,
                "errors": [_issue("output_dir_missing", "The production output directory is missing.")]}

    declared: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("sha256") and isinstance(item, str) and item.strip():
                    declared.add(item.strip().casefold())
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(generation_manifest if isinstance(generation_manifest, dict) else {})

    media = sorted(
        path for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
        and path.suffix.casefold() in _MEDIA_SUFFIXES
        and not path.name.endswith(".tmp"))
    unexplained = []
    for path in media:
        if sha256_file(str(path)) not in declared:
            unexplained.append(path.relative_to(root).as_posix())
    for relative in unexplained:
        errors.append(_issue("unexplained_media_artifact",
                             f"No recorded provenance for produced media file: {relative}",
                             relative_path=relative))

    return {
        "version": PRODUCTION_SCHEMA_VERSION,
        "passed": not errors,
        "media_count": len(media),
        "declared_hash_count": len(declared),
        "unexplained": unexplained,
        "errors": errors,
    }


def inspect_fast_start(video_path: str) -> dict:
    """Parse the real MP4 box order and require ``moov`` ahead of ``mdat``.

    A progressive download cannot start playing until it has the ``moov`` atom, so a deliverable
    whose index sits at the end of the file is not genuinely downloadable-and-playable.
    """
    errors: list[dict] = []
    path = Path(video_path)
    if not path.is_file():
        return {"version": PRODUCTION_SCHEMA_VERSION, "passed": False, "fast_start": False,
                "boxes": [],
                "errors": [_issue("video_missing", "The production MP4 is missing.")]}

    boxes: list[str] = []
    size_total = path.stat().st_size
    with path.open("rb") as handle:
        offset = 0
        while offset < size_total:
            handle.seek(offset)
            header = handle.read(8)
            if len(header) < 8:
                break
            size = struct.unpack(">I", header[:4])[0]
            box_type = header[4:8].decode("latin-1")
            header_size = 8
            if size == 1:
                extended = handle.read(8)
                if len(extended) < 8:
                    errors.append(_issue("truncated_box",
                                         f"Truncated 64-bit size on box {box_type!r}."))
                    break
                size = struct.unpack(">Q", extended)[0]
                header_size = 16
            elif size == 0:
                size = size_total - offset
            if size < header_size:
                errors.append(_issue("invalid_box_size",
                                     f"Box {box_type!r} declares an impossible size {size}."))
                break
            if offset + size > size_total:
                # A declared box that runs past EOF means the deliverable is truncated, even when
                # the boxes read so far are in fast-start order.
                errors.append(_issue(
                    "truncated_file",
                    f"Box {box_type!r} declares {size} bytes but only "
                    f"{size_total - offset} remain."))
                break
            boxes.append(box_type)
            offset += size

    if not boxes:
        errors.append(_issue("no_mp4_boxes", "No readable MP4 boxes were found."))
    if "ftyp" not in boxes:
        errors.append(_issue("missing_ftyp", "The MP4 has no ftyp box."))
    fast_start = False
    if "moov" not in boxes:
        errors.append(_issue("missing_moov", "The MP4 has no moov index box."))
    elif "mdat" not in boxes:
        errors.append(_issue("missing_mdat", "The MP4 has no mdat media box."))
    else:
        fast_start = boxes.index("moov") < boxes.index("mdat")
        if not fast_start:
            errors.append(_issue(
                "not_fast_start",
                "The moov index follows the media data; the download is not fast-start."))

    return {
        "version": PRODUCTION_SCHEMA_VERSION,
        "passed": not errors,
        "fast_start": fast_start,
        "boxes": boxes,
        "size_bytes": size_total,
        "errors": errors,
    }


def validate_cross_worker_recovery(events: list[dict], *, job_id: str) -> dict:
    """Prove the complete job survived being picked up by a different worker.

    A durable engine that has never actually changed hands is untested, so PR8 requires observed
    evidence: at least two distinct workers, a recorded resume, and reuse of already-paid work
    rather than a silent re-run.
    """
    errors: list[dict] = []
    rows = [item for item in (events or []) if isinstance(item, dict)]
    workers: list[str] = []
    resumed = False
    reused_artifacts = 0
    terminal = ""

    for row in rows:
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        worker = _text(row.get("worker_id")) or _text(data.get("worker_id"))
        if worker and worker not in workers:
            workers.append(worker)
        event_type = _text(row.get("type"))
        if event_type in ("resumed", "recovered", "lease_recovered"):
            resumed = True
        if event_type in ("done", "error", "degraded", "production_passed", "production_failed"):
            terminal = event_type
        try:
            reused_artifacts += int(data.get("reused_artifact_count") or 0)
        except (TypeError, ValueError):
            pass

    if len(workers) < 2:
        errors.append(_issue(
            "no_worker_handover",
            f"Job {job_id} was only ever leased by {len(workers)} worker(s); cross-worker recovery "
            f"is unproven.", workers=workers))
    if not resumed:
        errors.append(_issue("no_recorded_resume",
                             f"Job {job_id} records no resume or recovery event."))
    if reused_artifacts <= 0:
        errors.append(_issue(
            "no_reused_work",
            "The recovered run reused no already-persisted artifact, so recovery cannot be "
            "distinguished from a full re-run."))
    if terminal != "done":
        errors.append(_issue("job_not_completed",
                             f"Job {job_id} did not reach a successful terminal state.",
                             terminal=terminal or "none"))

    return {
        "version": PRODUCTION_SCHEMA_VERSION,
        "passed": not errors,
        "job_id": job_id,
        "distinct_workers": workers,
        "resumed": resumed,
        "reused_artifact_count": reused_artifacts,
        "terminal_state": terminal,
        "errors": errors,
    }


def artifact_completeness(output_dir: str) -> dict:
    root = Path(output_dir)
    present = {
        str(path.relative_to(root)).replace(os.sep, "/")
        for path in root.rglob("*") if path.is_file() and not path.name.endswith(".tmp")
    }
    missing = sorted(PRODUCTION_REQUIRED_ARTIFACTS - present)
    return {
        "passed": not missing,
        "required": sorted(PRODUCTION_REQUIRED_ARTIFACTS),
        "present_count": len(present),
        "missing": missing,
    }


# --------------------------------------------------------------------------------------------
# Final outcome
# --------------------------------------------------------------------------------------------

_GATE_ORDER = (
    ("runtime", "runtime_window_failed"),
    ("narration", "narration_integrity_failed"),
    ("questions", "unresolved_questions"),
    ("claims", "claim_visual_reconciliation_failed"),
    ("opening_reuse", "opening_object_not_reused"),
    ("provenance", "unexplained_artifacts"),
    ("fast_start", "mp4_not_fast_start"),
    ("recovery", "cross_worker_recovery_unproven"),
)


def final_production_outcome(*, rendered_contract: dict, human_review: dict,
                             completeness: dict, gates: dict) -> dict:
    """Combine every immutable gate into one publish / do-not-publish recommendation."""
    score = int(rendered_contract.get("score") or 0)
    hard_failures = sorted(set(rendered_contract.get("hard_failures") or []))
    calibration = validate_threshold_profile(
        rendered_contract.get("threshold_profile") or {}, require_calibrated=True)
    automated_pass = bool(
        rendered_contract.get("automated_pass")
        and score >= PRODUCTION_RELEASE_SCORE
        and not hard_failures
        and calibration.get("passed")
    )

    checklist = human_review.get("checklist") if isinstance(
        human_review.get("checklist"), list) else []
    editorial_pass = bool(
        human_review.get("status") == "completed"
        and human_review.get("decision") == "approve"
        and checklist
        and all(item.get("approved") is True for item in checklist)
    )
    artifacts_pass = bool(completeness.get("passed"))

    gate_results = {}
    failure_reasons: list[str] = []
    for name, reason in _GATE_ORDER:
        report = gates.get(name) if isinstance(gates.get(name), dict) else {}
        passed = bool(report.get("passed"))
        gate_results[name] = {"passed": passed, "errors": report.get("errors") or []}
        if not passed:
            failure_reasons.append(reason)

    if not automated_pass:
        failure_reasons.insert(0, "rendered_contract_below_production_floor")
    if not editorial_pass:
        failure_reasons.append("editorial_review_failed")
    if not artifacts_pass:
        failure_reasons.append("required_artifacts_missing")

    gates_pass = all(item["passed"] for item in gate_results.values())
    passed = automated_pass and editorial_pass and artifacts_pass and gates_pass

    return {
        "schema_version": PRODUCTION_SCHEMA_VERSION,
        "status": "production_passed" if passed else "production_failed",
        "production_passed": passed,
        "publish_recommendation": "publish" if passed else "do_not_publish",
        "automated": {
            "passed": automated_pass,
            "score": score,
            "score_floor": PRODUCTION_RELEASE_SCORE,
            "hard_failures": hard_failures,
            "threshold_calibration": calibration,
        },
        "editorial": {
            "passed": editorial_pass,
            "decision": human_review.get("decision") or "pending",
            "reviewer": human_review.get("reviewer") or "",
        },
        "gates": gate_results,
        "artifacts": completeness,
        "failure_reasons": failure_reasons,
        "promotion_rule": "A failed gate, automated grade, or editorial grade cannot be promoted in place.",
    }
