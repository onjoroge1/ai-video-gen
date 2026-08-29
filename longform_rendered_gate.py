"""Fail-closed animatic and rendered-story gates for long-form explainers.

Planner metadata may decide what to generate, but it cannot award rendered-video
points.  This module extracts chronological pixels from the encoded opening,
measures the edit, cross-checks a blind story reading against deterministic facts,
and applies the frozen 100-point Bolt long-form rubric.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from media_binaries import ffmpeg as _ffmpeg_bin, ffprobe as _ffprobe_bin

import numpy as np
from PIL import Image, ImageDraw, ImageFont


RENDERED_GATE_VERSION = 1
RELEASE_SCORE = 85
OPENING_AVG_STATE_RANGE = (1.8, 3.2)
OPENING_MAX_STATE_SECONDS = 3.5
DIAGNOSTIC_WATERMARK = "REJECTED DIAGNOSTIC — NOT FOR PUBLICATION"
MIN_CALIBRATION_EXAMPLES_PER_CLASS = 20
MIN_CALIBRATION_BALANCED_ACCURACY = 0.70
MIN_CALIBRATION_CLASS_ACCURACY = 0.60
# `slideshow` and `source_change_ratio` are properties of a whole video, not of one cut, so a
# dataset drawn from a single video teaches that threshold nothing. Require the label to be
# supported by more than one real render on each side.
MIN_CALIBRATION_VIDEOS_PER_SLIDESHOW_CLASS = 2
PROVISIONAL_THRESHOLD_PROFILE = {
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


class HumanReviewRequired(RuntimeError):
    """The rendered opening passed automation but must pause before later visual spend."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _issue(code: str, message: str, **fields: Any) -> dict:
    return {"code": code, "message": message, **fields}


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _profile_error(message: str) -> ValueError:
    return ValueError(f"Rendered-gate calibration profile is invalid: {message}")


def validate_threshold_profile(profile: dict, *, require_calibrated: bool = False) -> dict:
    """Validate a labeled calibration profile without awarding calibration by assertion."""
    errors = []
    if not isinstance(profile, dict) or profile.get("schema_version") != 1:
        errors.append("schema_version must equal 1")
        profile = profile if isinstance(profile, dict) else {}
    status = _text(profile.get("status"))
    if status not in {"calibrated", "provisional_uncalibrated"}:
        errors.append("status must be calibrated or provisional_uncalibrated")
    for field in ("pixel_delta_threshold", "source_change_ratio_threshold"):
        try:
            value = float(profile.get(field))
        except (TypeError, ValueError):
            errors.append(f"{field} must be numeric")
            continue
        if not 0 < value < 1:
            errors.append(f"{field} must be between zero and one")
    if status == "calibrated":
        counts = profile.get("sample_counts") if isinstance(profile.get("sample_counts"), dict) else {}
        for label in ("meaningful_change", "not_meaningful_change", "not_slideshow", "slideshow"):
            try:
                count = int(counts.get(label) or 0)
            except (TypeError, ValueError):
                count = 0
            if count < MIN_CALIBRATION_EXAMPLES_PER_CLASS:
                errors.append(
                    f"{label} needs at least {MIN_CALIBRATION_EXAMPLES_PER_CLASS} labeled examples")
        if not _text(profile.get("dataset_sha256")):
            errors.append("calibrated profiles require dataset_sha256")
        if not _text(profile.get("reviewer")):
            errors.append("calibrated profiles require reviewer")
        if not _text(profile.get("created_at")):
            errors.append("calibrated profiles require created_at")
        if _text(profile.get("method")) != "balanced_accuracy_human_labeled_real_video_v1":
            errors.append("calibrated profiles require the supported calibration method")
        metrics = profile.get("metrics") if isinstance(profile.get("metrics"), dict) else {}
        for family in ("pixel_delta", "source_change_ratio"):
            family_metrics = metrics.get(family) if isinstance(metrics.get(family), dict) else {}
            try:
                balanced = float(family_metrics.get("balanced_accuracy"))
                sensitivity = float(family_metrics.get("sensitivity"))
                specificity = float(family_metrics.get("specificity"))
            except (TypeError, ValueError):
                balanced = sensitivity = specificity = 0.0
            if balanced < MIN_CALIBRATION_BALANCED_ACCURACY:
                errors.append(
                    f"{family} balanced accuracy must reach {MIN_CALIBRATION_BALANCED_ACCURACY:.0%}")
            if min(sensitivity, specificity) < MIN_CALIBRATION_CLASS_ACCURACY:
                errors.append(
                    f"{family} sensitivity and specificity must each reach "
                    f"{MIN_CALIBRATION_CLASS_ACCURACY:.0%}")
    if require_calibrated and status != "calibrated":
        errors.append("a calibrated profile is required for a publishable rendered score")
    return {"passed": not errors, "calibrated": status == "calibrated" and not errors,
            "errors": errors}


def load_threshold_profile(path: str | None = None) -> dict:
    """Load a real calibration profile, or return explicitly provisional defaults.

    If an operator configures a profile path, malformed or insufficient evidence fails closed.
    """
    configured = path if path is not None else os.environ.get("LONGFORM_GATE_CALIBRATION_PROFILE", "")
    configured = _text(configured)
    if not configured:
        return dict(PROVISIONAL_THRESHOLD_PROFILE)
    try:
        with open(configured, encoding="utf-8") as handle:
            profile = json.load(handle)
    except (OSError, ValueError, TypeError) as exc:
        raise _profile_error(str(exc)) from exc
    validation = validate_threshold_profile(profile, require_calibrated=True)
    if not validation["passed"]:
        raise _profile_error("; ".join(validation["errors"]))
    return profile


def _best_threshold(values: list[float], labels: list[bool]) -> tuple[float, dict]:
    """Choose the deterministic balanced-accuracy threshold for positive values >= threshold."""
    candidates = sorted(set(values))
    best = None
    positives = sum(labels)
    negatives = len(labels) - positives
    for threshold in candidates:
        tp = sum(label and value >= threshold for value, label in zip(values, labels))
        tn = sum((not label) and value < threshold for value, label in zip(values, labels))
        sensitivity = tp / max(1, positives)
        specificity = tn / max(1, negatives)
        score = (sensitivity + specificity) / 2
        candidate = (score, min(sensitivity, specificity), -threshold, threshold,
                     sensitivity, specificity)
        if best is None or candidate > best:
            best = candidate
    assert best is not None
    return round(best[3], 6), {
        "balanced_accuracy": round(best[0], 4),
        "sensitivity": round(best[4], 4),
        "specificity": round(best[5], 4),
    }


def calibrate_threshold_profile(samples: list[dict], *, reviewer: str,
                                dataset_id: str = "") -> dict:
    """Build a calibrated profile from human-labeled real-video observations.

    Each sample must carry measured pixel/source values and independent editorial labels.
    Small or one-sided datasets are rejected rather than called calibrated.
    """
    if not _text(reviewer):
        raise _profile_error("reviewer is required")
    clean = []
    rejected = []
    for item in samples or []:
        if not isinstance(item, dict):
            rejected.append("sample is not an object")
            continue
        try:
            sample_id = _text(item.get("sample_id"))
            pixel_delta = float(item["pixel_delta"])
            source_change_ratio = float(item["source_change_ratio"])
            meaningful_change = item["meaningful_change"]
            slideshow = item["slideshow"]
        except (KeyError, TypeError, ValueError):
            rejected.append(f"invalid sample {_text(item.get('sample_id')) or '<unnamed>'}")
            continue
        if (not sample_id or not isinstance(meaningful_change, bool)
                or not isinstance(slideshow, bool)
                or not 0 <= pixel_delta <= 1 or not 0 <= source_change_ratio <= 1):
            rejected.append(f"invalid sample {sample_id or '<unnamed>'}")
            continue
        clean.append({
            "sample_id": sample_id,
            "pixel_delta": pixel_delta,
            "meaningful_change": meaningful_change,
            "source_change_ratio": source_change_ratio,
            "slideshow": slideshow,
        })
    duplicate_ids = len({item["sample_id"] for item in clean}) != len(clean)
    if rejected:
        raise _profile_error(
            f"{len(rejected)} sample(s) have missing/invalid typed labels or measurements")
    if duplicate_ids:
        raise _profile_error("sample_id values must be unique")
    counts = {
        "meaningful_change": sum(item["meaningful_change"] for item in clean),
        "not_meaningful_change": sum(not item["meaningful_change"] for item in clean),
        "not_slideshow": sum(not item["slideshow"] for item in clean),
        "slideshow": sum(item["slideshow"] for item in clean),
    }
    for label, count in counts.items():
        if count < MIN_CALIBRATION_EXAMPLES_PER_CLASS:
            raise _profile_error(
                f"{label} needs at least {MIN_CALIBRATION_EXAMPLES_PER_CLASS} labeled examples; got {count}")
    pixel_threshold, pixel_metrics = _best_threshold(
        [item["pixel_delta"] for item in clean],
        [item["meaningful_change"] for item in clean])
    source_threshold, source_metrics = _best_threshold(
        [item["source_change_ratio"] for item in clean],
        [not item["slideshow"] for item in clean])
    for family, metrics in (("pixel_delta", pixel_metrics),
                            ("source_change_ratio", source_metrics)):
        if metrics["balanced_accuracy"] < MIN_CALIBRATION_BALANCED_ACCURACY \
                or min(metrics["sensitivity"], metrics["specificity"]) \
                < MIN_CALIBRATION_CLASS_ACCURACY:
            raise _profile_error(
                f"{family} labels do not support a viable threshold: "
                f"balanced accuracy {metrics['balanced_accuracy']:.0%}, "
                f"sensitivity {metrics['sensitivity']:.0%}, "
                f"specificity {metrics['specificity']:.0%}")
    canonical = json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")
    profile = {
        "schema_version": 1,
        "profile_id": "rendered-gate-" + hashlib.sha256(canonical).hexdigest()[:12],
        "status": "calibrated",
        "dataset_id": _text(dataset_id),
        "dataset_sha256": hashlib.sha256(canonical).hexdigest(),
        "reviewer": _text(reviewer),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "method": "balanced_accuracy_human_labeled_real_video_v1",
        "sample_counts": counts,
        "pixel_delta_threshold": pixel_threshold,
        "source_change_ratio_threshold": source_threshold,
        "metrics": {"pixel_delta": pixel_metrics, "source_change_ratio": source_metrics},
    }
    validation = validate_threshold_profile(profile, require_calibrated=True)
    if not validation["passed"]:
        raise _profile_error("; ".join(validation["errors"]))
    return profile


CALIBRATION_WORKSHEET_VERSION = 1

# The editor answers exactly these two questions per row. Everything else in a worksheet row is
# either a measurement or context for the eye.
CALIBRATION_LABEL_FIELDS = ("meaningful_change", "slideshow")

CALIBRATION_LABEL_QUESTIONS = {
    "meaningful_change": (
        "Looking only at the before/after frames: does the cut show genuinely new visual "
        "information, or is it the same state again?"),
    "slideshow": (
        "Watching the whole video: does it read as a slideshow of stills rather than a shot "
        "sequence that develops? Answer the same way for every row from this video."),
}


def harvest_calibration_samples(inspections: list[dict], *, dataset_id: str = "") -> dict:
    """Turn real rendered-opening inspections into an unlabeled calibration worksheet.

    `inspect_rendered_opening` measures every cut but nothing previously turned those
    measurements into something an editor could label, so a calibrated profile could not be
    produced and the gate stayed permanently uncalibrated.  This closes that loop.

    Labels are deliberately left null.  Pre-filling them from `declared_new_information` would let
    planner metadata calibrate the threshold that is supposed to audit planner metadata, which is
    exactly the circularity the rendered gate exists to prevent.
    """
    rows: list[dict] = []
    videos: list[dict] = []
    seen_ids: set[str] = set()

    for inspection in inspections or []:
        if not isinstance(inspection, dict):
            raise _profile_error("each inspection must be an object")
        video_sha = _text(inspection.get("video_sha256"))
        if not video_sha:
            raise _profile_error(
                "each inspection needs a video_sha256; a sample must be traceable to real bytes")
        deterministic = inspection.get("deterministic") if isinstance(
            inspection.get("deterministic"), dict) else {}
        try:
            source_change_ratio = float(deterministic["source_change_ratio"])
        except (KeyError, TypeError, ValueError) as exc:
            raise _profile_error(
                f"inspection {video_sha[:12]} has no measured source_change_ratio") from exc
        deltas = inspection.get("boundary_deltas") if isinstance(
            inspection.get("boundary_deltas"), list) else []
        if not deltas:
            raise _profile_error(
                f"inspection {video_sha[:12]} recorded no boundary cuts to label")

        for item in deltas:
            if not isinstance(item, dict):
                continue
            try:
                shot_index = int(item["shot_index"])
                pixel_delta = float(item["pixel_delta"])
            except (KeyError, TypeError, ValueError):
                raise _profile_error(
                    f"inspection {video_sha[:12]} has a boundary cut without a measurement")
            sample_id = f"{video_sha[:12]}-cut{shot_index:03d}"
            if sample_id in seen_ids:
                raise _profile_error(f"duplicate sample_id {sample_id}")
            seen_ids.add(sample_id)
            rows.append({
                "sample_id": sample_id,
                "video_sha256": video_sha,
                "shot_index": shot_index,
                "time_sec": item.get("time_sec"),
                "pixel_delta": pixel_delta,
                "source_change_ratio": source_change_ratio,
                # Context for the editor's eye, never a label.
                "context": {
                    "video_path": _text(inspection.get("video_path")),
                    "declared_new_information": bool(item.get("declared_new_information")),
                    "source_changed": bool(item.get("source_changed")),
                },
                "meaningful_change": None,
                "slideshow": None,
            })
        videos.append({"video_sha256": video_sha, "cut_count": len(deltas),
                       "source_change_ratio": source_change_ratio})

    if not rows:
        raise _profile_error("no boundary observations were harvested")

    return {
        "worksheet_version": CALIBRATION_WORKSHEET_VERSION,
        "dataset_id": _text(dataset_id),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "label_questions": dict(CALIBRATION_LABEL_QUESTIONS),
        "instructions": (
            "Fill meaningful_change and slideshow with true or false on every row. Judge from the "
            "extracted frames and the video itself, not from the context block."),
        "videos": videos,
        "samples": rows,
    }


def calibration_readiness(worksheet: dict) -> dict:
    """Report how far a worksheet is from being a viable calibration dataset."""
    samples = worksheet.get("samples") if isinstance(worksheet, dict) else None
    samples = samples if isinstance(samples, list) else []
    labeled: list[dict] = []
    unlabeled = 0
    malformed = 0
    for item in samples:
        if not isinstance(item, dict):
            malformed += 1
            continue
        values = [item.get(field) for field in CALIBRATION_LABEL_FIELDS]
        if all(value is None for value in values):
            unlabeled += 1
        elif all(isinstance(value, bool) for value in values):
            labeled.append(item)
        else:
            malformed += 1

    counts = {
        "meaningful_change": sum(item["meaningful_change"] for item in labeled),
        "not_meaningful_change": sum(not item["meaningful_change"] for item in labeled),
        "slideshow": sum(item["slideshow"] for item in labeled),
        "not_slideshow": sum(not item["slideshow"] for item in labeled),
    }
    videos_by_class = {
        "slideshow": {_text(item.get("video_sha256")) for item in labeled if item["slideshow"]},
        "not_slideshow": {_text(item.get("video_sha256"))
                          for item in labeled if not item["slideshow"]},
    }
    needed = {
        label: max(0, MIN_CALIBRATION_EXAMPLES_PER_CLASS - count)
        for label, count in counts.items()
    }
    video_shortfall = {
        label: max(0, MIN_CALIBRATION_VIDEOS_PER_SLIDESHOW_CLASS - len(shas - {""}))
        for label, shas in videos_by_class.items()
    }
    blockers: list[str] = []
    if malformed:
        blockers.append(f"{malformed} row(s) have a partial or non-boolean label")
    if unlabeled:
        blockers.append(f"{unlabeled} row(s) are still unlabeled")
    for label, shortfall in sorted(needed.items()):
        if shortfall:
            blockers.append(f"{label} needs {shortfall} more labeled example(s)")
    for label, shortfall in sorted(video_shortfall.items()):
        if shortfall:
            blockers.append(
                f"{label} needs cuts from {shortfall} more distinct real video(s)")

    return {
        "version": CALIBRATION_WORKSHEET_VERSION,
        "ready": not blockers,
        "total_rows": len(samples),
        "labeled_rows": len(labeled),
        "unlabeled_rows": unlabeled,
        "malformed_rows": malformed,
        "counts": counts,
        "minimum_per_class": MIN_CALIBRATION_EXAMPLES_PER_CLASS,
        "distinct_videos": {label: len(shas - {""}) for label, shas in videos_by_class.items()},
        "minimum_videos_per_slideshow_class": MIN_CALIBRATION_VIDEOS_PER_SLIDESHOW_CLASS,
        "blockers": blockers,
    }


def load_labeled_samples(worksheet: dict) -> list[dict]:
    """Validate a filled worksheet and return `calibrate_threshold_profile`-ready samples."""
    readiness = calibration_readiness(worksheet)
    if not readiness["ready"]:
        raise _profile_error("; ".join(readiness["blockers"]))
    return [
        {
            "sample_id": _text(item.get("sample_id")),
            "pixel_delta": float(item["pixel_delta"]),
            "source_change_ratio": float(item["source_change_ratio"]),
            "meaningful_change": bool(item["meaningful_change"]),
            "slideshow": bool(item["slideshow"]),
        }
        for item in worksheet["samples"]
    ]


def _flatten(plan: list[list[dict]]) -> list[dict]:
    flattened, cursor = [], 0.0
    for scene_index, scene in enumerate(plan):
        for shot_index, shot in enumerate(scene):
            duration = max(0.0, float(shot.get("duration") or 0.0))
            item = dict(shot)
            item.update({
                "scene_index": scene_index,
                "shot_index": shot_index,
                "global_start_sec": round(cursor, 3),
                "global_end_sec": round(cursor + duration, 3),
                "midpoint_sec": round(cursor + duration / 2, 3),
            })
            flattened.append(item)
            cursor += duration
    return flattened


def build_animatic_gate(script: dict, evidence_plan: dict, audio_timing: dict) -> dict:
    """Validate the final-narration storyboard before any paid visual generation.

    This is intentionally a contract gate, not a rendered-video score.  It confirms
    that a cheap animatic exposes the six story facts a human reviewer must recover.
    """
    contract = script.get("_story_contract") if isinstance(script.get("_story_contract"), dict) else {}
    scenes = script.get("scenes") if isinstance(script.get("scenes"), list) else []
    evidence_scenes = evidence_plan.get("scenes") if isinstance(evidence_plan, dict) else []
    audio_scenes = audio_timing.get("scenes") if isinstance(audio_timing, dict) else []
    errors = []
    recoverable = {
        "subject": bool(_text(contract.get("human_subject"))),
        "objective": bool(_text(contract.get("subject_goal"))),
        "anomaly": bool(_text(contract.get("anomaly"))),
        "evidence_sequence": sum(len(scene.get("states") or []) for scene in evidence_scenes or []) >= 2,
        "belief_change": any(_text(scene.get("belief_changed")) for scene in scenes),
        "forward_question": any(_text(scene.get("question_opened") or scene.get("opens_loop"))
                                for scene in scenes),
    }
    for field, present in recoverable.items():
        if not present:
            errors.append(_issue(f"animatic_missing_{field}",
                                 f"The low-cost animatic cannot expose the {field.replace('_', ' ')}."))
    if len(audio_scenes or []) != len(scenes):
        errors.append(_issue("animatic_audio_scene_mismatch",
                             "Final-speed narration timings do not cover every storyboard scene."))
    cards = []
    for scene_index, (scene, evidence_scene) in enumerate(zip(scenes, evidence_scenes or [])):
        for state in evidence_scene.get("states") or []:
            cards.append({
                "scene_index": scene_index,
                "state_id": _text(state.get("state_id")),
                "narration_anchor": _text(state.get("anchor_phrase")),
                "visible_state": _text(state.get("state_after") or state.get("visual")),
                "human_intention": _text(scene.get("human_intention")),
                "belief_change": _text(scene.get("belief_changed")),
                "forward_question": _text(scene.get("question_opened") or scene.get("opens_loop")),
            })
    return {
        "version": RENDERED_GATE_VERSION,
        "name": "Low-cost animatic gate",
        "passed": not errors,
        "recoverable_story_facts": recoverable,
        "card_count": len(cards),
        "cards": cards,
        "errors": errors,
    }


def render_low_cost_animatic(script: dict, evidence_plan: dict, prepared_audio: dict[int, dict],
                             output_path: str, *, width: int = 960, height: int = 540) -> str:
    """Render final TTS over local storyboard cards without purchasing visual assets."""
    root = Path(output_path).parent / "animatic_cards"
    root.mkdir(parents=True, exist_ok=True)
    segments = []
    scenes = script.get("scenes") or []
    plans = evidence_plan.get("scenes") or []
    for index, (scene, scene_plan) in enumerate(zip(scenes, plans)):
        audio = _text((prepared_audio.get(index) or {}).get("aud"))
        if not audio or not Path(audio).is_file():
            raise ValueError(f"Final TTS is missing for animatic scene {index + 1}.")
        image_path = root / f"card_{index:03d}.jpg"
        segment_path = root / f"card_{index:03d}.mp4"
        image = Image.new("RGB", (width, height), "#111827")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        draw.text((42, 34), f"STORYBOARD {index + 1:02d} · {_text(scene.get('story_role')).upper()}",
                  fill="#67e8f9", font=font)
        lines = [
            f"ACTION: {_text(scene.get('human_intention')) or '—'}",
            f"BELIEF CHANGE: {_text(scene.get('belief_changed')) or '—'}",
            f"QUESTION: {_text(scene.get('question_opened') or scene.get('opens_loop')) or '—'}",
        ]
        lines.extend(
            f"EVIDENCE {state_index + 1}: {_text(state.get('state_after') or state.get('visual'))}"
            for state_index, state in enumerate(scene_plan.get("states") or []))
        y = 92
        for line in lines:
            words, row = line.split(), ""
            for word in words:
                candidate = (row + " " + word).strip()
                if len(candidate) > 105:
                    draw.text((42, y), row, fill="white", font=font)
                    y += 25
                    row = word
                else:
                    row = candidate
            if row:
                draw.text((42, y), row, fill="white", font=font)
                y += 31
        image.save(image_path, "JPEG", quality=88)
        subprocess.run([
            _ffmpeg_bin(), "-nostdin", "-y", "-loglevel", "error", "-loop", "1", "-i", str(image_path),
            "-i", audio, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-tune", "stillimage",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(segment_path),
        ], check=True, capture_output=True, timeout=120)
        segments.append(segment_path)
    if not segments:
        raise ValueError("The animatic has no renderable storyboard scenes.")
    concat_path = root / "segments.txt"
    concat_path.write_text("".join(f"file '{path.as_posix()}'\n" for path in segments), encoding="utf-8")
    subprocess.run([
        _ffmpeg_bin(), "-nostdin", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", str(concat_path), "-c", "copy", output_path,
    ], check=True, capture_output=True, timeout=180)
    return output_path


def _extract_frame(video_path: str, timestamp: float, output_path: str) -> None:
    subprocess.run([
        _ffmpeg_bin(), "-nostdin", "-y", "-loglevel", "error", "-ss", f"{max(0.0, timestamp):.3f}",
        "-i", video_path, "-frames:v", "1", "-vf", "scale=640:-2", output_path,
    ], check=True, capture_output=True, timeout=60)


def _visual_vector(path: str) -> np.ndarray:
    image = Image.open(path).convert("RGB").resize((64, 36))
    # Exclude headline/subtitle bands so caption animation cannot masquerade as a visual-state change.
    array = np.asarray(image, dtype=np.float32)[7:29, :, :]
    return array / 255.0


def _pixel_delta(left: str, right: str) -> float:
    a, b = _visual_vector(left), _visual_vector(right)
    return float(np.mean(np.abs(a - b)))


def inspect_rendered_opening(video_path: str, shot_plan: list[list[dict]], output_dir: str,
                             evidence_plan: dict, threshold_profile: dict | None = None) -> dict:
    """Extract each cut midpoint plus boundary samples and measure encoded story states."""
    profile = threshold_profile or load_threshold_profile()
    profile_validation = validate_threshold_profile(profile)
    if not profile_validation["passed"]:
        raise _profile_error("; ".join(profile_validation["errors"]))
    pixel_threshold = float(profile["pixel_delta_threshold"])
    source_threshold = float(profile["source_change_ratio_threshold"])
    frame_dir = Path(output_dir) / "rendered_gate_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    shots = _flatten(shot_plan)
    state_by_id = {
        _text(state.get("state_id")): state
        for scene in evidence_plan.get("scenes") or [] for state in scene.get("states") or []
    }
    frames, errors = [], []
    for index, shot in enumerate(shots):
        frame_path = frame_dir / f"shot_{index:03d}_mid.jpg"
        try:
            _extract_frame(video_path, float(shot["midpoint_sec"]), str(frame_path))
            state = state_by_id.get(_text(shot.get("state_id"))) or {}
            verification = state.get("verification") if isinstance(state.get("verification"), dict) else {}
            frames.append({
                **shot,
                "frame_path": str(frame_path),
                "frame_sha256": _sha256(str(frame_path)),
                "required_objects": state.get("required_objects") or [],
                "state_before": _text(state.get("state_before")),
                "state_after": _text(state.get("state_after")),
                "asset_verification_passed": verification.get("passed") is True,
                "asset_verification_reasons": verification.get("reasons") or [],
            })
        except Exception as exc:
            errors.append(_issue("midpoint_extraction_failed", str(exc)[:180], shot=index))

    boundary_deltas = []
    for index, shot in enumerate(shots[1:], 1):
        before = frame_dir / f"cut_{index:03d}_before.jpg"
        after = frame_dir / f"cut_{index:03d}_after.jpg"
        cut = float(shot["global_start_sec"])
        try:
            _extract_frame(video_path, max(0.0, cut - 0.12), str(before))
            _extract_frame(video_path, cut + 0.12, str(after))
            boundary_deltas.append({
                "shot_index": index,
                "time_sec": round(cut, 3),
                "pixel_delta": round(_pixel_delta(str(before), str(after)), 4),
                "declared_new_information": bool(shot.get("verified_visible_information")),
                "source_changed": _text(shot.get("source")) != _text(shots[index - 1].get("source")),
            })
        except Exception as exc:
            errors.append(_issue("boundary_extraction_failed", str(exc)[:180], shot=index))

    durations = [float(shot.get("duration") or 0) for shot in shots]
    sources = [_text(shot.get("source")) for shot in shots]
    source_changes = sum(a != b for a, b in zip(sources, sources[1:]))
    verified = sum(bool(shot.get("verified_visible_information")) for shot in shots)
    expected_bolt = 0
    pure_bolt_violations = 0
    continuity_failures = []
    for shot in shots:
        state = state_by_id.get(_text(shot.get("state_id"))) or {}
        verification = state.get("verification") if isinstance(state.get("verification"), dict) else {}
        if state.get("include_bolt") or verification.get("bolt_present") is True:
            expected_bolt += 1
        if state.get("pure_evidence") and verification.get("bolt_present") is True:
            pure_bolt_violations += 1
        for field in ("human_identity_matches", "clothing_matches", "location_matches",
                      "opening_object_matches"):
            if verification.get(field) is False:
                continuity_failures.append({"state_id": state.get("state_id"), "field": field})
    avg_state = sum(durations) / len(durations) if durations else 999.0
    max_state = max(durations, default=999.0)
    pixel_changes = sum(item["pixel_delta"] >= pixel_threshold for item in boundary_deltas)
    source_change_ratio = source_changes / max(1, len(shots) - 1)
    deterministic = {
        "decodable": bool(frames) and not errors,
        "shot_count": len(shots),
        "extracted_midpoint_count": len(frames),
        "distinct_source_count": len(set(filter(None, sources))),
        "source_change_ratio": round(source_change_ratio, 3),
        "pixel_boundary_change_ratio": round(pixel_changes / max(1, len(boundary_deltas)), 3),
        "verified_information_ratio": round(verified / max(1, len(shots)), 3),
        "per_cut_verification_ratio": round(
            sum(frame.get("asset_verification_passed") for frame in frames) / max(1, len(frames)), 3),
        "unverified_cut_count": sum(not frame.get("asset_verification_passed") for frame in frames),
        "average_visual_state_sec": round(avg_state, 3),
        "max_visual_state_sec": round(max_state, 3),
        "long_hold_count": sum(duration > OPENING_MAX_STATE_SECONDS for duration in durations),
        "bolt_shot_count": expected_bolt,
        "bolt_shot_ratio": round(expected_bolt / max(1, len(shots)), 3),
        "pure_evidence_bolt_violations": pure_bolt_violations,
        "continuity_failures": continuity_failures,
        "slideshow": (len(set(filter(None, sources))) <= max(1, math.ceil(len(shots) * 0.35))
                      or source_change_ratio < source_threshold),
        "threshold_profile": profile,
    }
    return {
        "version": RENDERED_GATE_VERSION,
        "video_path": video_path,
        "video_sha256": _sha256(video_path) if Path(video_path).is_file() else "",
        "frames": frames,
        "boundary_deltas": boundary_deltas,
        "deterministic": deterministic,
        "errors": errors,
    }


def build_contact_sheet(inspection: dict, output_path: str) -> str:
    frames = inspection.get("frames") or []
    if not frames:
        raise ValueError("No chronological frames are available for the contact sheet.")
    thumb_w, thumb_h, label_h, columns = 320, 180, 42, 3
    rows = math.ceil(len(frames) / columns)
    sheet = Image.new("RGB", (columns * thumb_w, rows * (thumb_h + label_h)), "#101216")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, frame in enumerate(frames):
        x, y = (index % columns) * thumb_w, (index // columns) * (thumb_h + label_h)
        image = Image.open(frame["frame_path"]).convert("RGB").resize((thumb_w, thumb_h))
        sheet.paste(image, (x, y))
        label = f"{index + 1:02d}  {float(frame.get('midpoint_sec') or 0):05.1f}s"
        draw.text((x + 8, y + thumb_h + 8), label, fill="white", font=font)
    sheet.save(output_path, "JPEG", quality=90)
    return output_path


def blind_story_prompt(transcript_cues: list[dict]) -> str:
    """The judge receives chronology and narration only—never planner fields or expected answers."""
    return (
        "Watch the numbered frames left-to-right, top-to-bottom as one opening. Read the timestamped "
        "spoken narration below. You have no title, thumbnail, prompt, plan, expected objects, or scoring "
        "metadata. Report only what an ordinary viewer can recover. Return ONLY JSON with booleans and "
        "short evidence: {\"subject_readable\":bool,\"objective_readable\":bool,"
        "\"anomaly_readable\":bool,\"investigation_develops\":bool,\"evidence_accumulates\":bool,"
        "\"causal_story\":bool,\"belief_change_earned\":bool,\"forward_question_readable\":bool,"
        "\"multi_shot_storytelling\":bool,\"slideshow\":bool,\"bolt_useful\":bool,"
        "\"captions_obscure_evidence\":bool,\"comprehensible_audio_story\":bool,"
        "\"observed_subject\":\"\",\"observed_objective\":\"\",\"observed_anomaly\":\"\","
        "\"observed_evidence_sequence\":[\"\"],\"observed_belief_change\":\"\","
        "\"reason_to_continue\":\"\",\"failures\":[\"\"]}.\n\nNARRATION CUES:\n"
        + json.dumps(transcript_cues, ensure_ascii=False)
    )


def cross_check_blind_observations(blind: dict, deterministic: dict) -> dict:
    """Remove model-awarded credit whenever encoded facts contradict the observation."""
    checked = dict(blind or {})
    contradictions = []
    if checked.get("multi_shot_storytelling") and deterministic.get("slideshow"):
        checked["multi_shot_storytelling"] = False
        contradictions.append("judge called a deterministic slideshow multi-shot storytelling")
    if checked.get("evidence_accumulates") and deterministic.get("verified_information_ratio", 0) < 0.70:
        checked["evidence_accumulates"] = False
        contradictions.append("judge claimed evidence accumulation below the verified-information floor")
    if checked.get("slideshow") is False and deterministic.get("slideshow"):
        checked["slideshow"] = True
        contradictions.append("judge missed deterministic source-reuse slideshow behavior")
    if checked.get("bolt_useful") and deterministic.get("bolt_shot_ratio", 0) >= 0.70:
        checked["bolt_useful"] = False
        contradictions.append("judge credited Bolt despite Bolt-everywhere frequency")
    checked["cross_check_contradictions"] = contradictions
    checked["valid"] = all(key in checked for key in (
        "subject_readable", "objective_readable", "anomaly_readable", "evidence_accumulates",
        "causal_story", "multi_shot_storytelling", "slideshow", "comprehensible_audio_story"))
    return checked


def _fraction_score(maximum: int, values: list[bool]) -> int:
    return round(maximum * sum(bool(value) for value in values) / max(1, len(values)))


def score_rendered_contract(*, deterministic: dict, blind: dict, story_validation: dict,
                            claim_validation: dict, callback_exact: bool,
                            human_review: dict | None = None) -> dict:
    """Apply the frozen 100-point rendered contract. No planner field awards visual credit."""
    components = []
    add = lambda name, score, maximum, notes=None: components.append({
        "name": name, "score": int(score), "max": maximum, "notes": notes or []})
    add("Opening promise and anomaly", _fraction_score(15, [
        blind.get("subject_readable"), blind.get("anomaly_readable"),
        bool(_text(blind.get("reason_to_continue")))]), 15)
    add("Human objective and developing investigation", _fraction_score(15, [
        blind.get("subject_readable"), blind.get("objective_readable"),
        blind.get("investigation_develops"), blind.get("belief_change_earned"),
        bool(_text(blind.get("observed_objective")))]), 15)
    add("Evidence accumulation and causal storytelling", _fraction_score(20, [
        blind.get("evidence_accumulates"), blind.get("causal_story"),
        deterministic.get("verified_information_ratio", 0) >= 0.70,
        blind.get("forward_question_readable"),
        len(blind.get("observed_evidence_sequence") or []) >= 2]), 20)
    threshold_profile = deterministic.get("threshold_profile") or PROVISIONAL_THRESHOLD_PROFILE
    source_threshold = float(threshold_profile.get("source_change_ratio_threshold") or 0.45)
    add("Genuine multi-shot visual storytelling", _fraction_score(15, [
        blind.get("multi_shot_storytelling"), not blind.get("slideshow"),
        not deterministic.get("slideshow"),
        deterministic.get("source_change_ratio", 0) >= source_threshold,
        deterministic.get("pixel_boundary_change_ratio", 0) >= 0.45]), 15)
    add("Bolt discipline and usefulness", _fraction_score(10, [
        deterministic.get("bolt_shot_ratio", 0) <= 0.35,
        deterministic.get("pure_evidence_bolt_violations", 0) == 0,
        blind.get("bolt_useful") and deterministic.get("bolt_shot_ratio", 0) > 0]), 10)
    checks = story_validation.get("checks") if isinstance(story_validation, dict) else {}
    add("First-act continuity and exact callback", _fraction_score(10, [
        not deterministic.get("continuity_failures"),
        bool(checks.get("first_act_continuity_hits")), callback_exact]), 10)
    lo, hi = OPENING_AVG_STATE_RANGE
    add("Visual pacing measured from the MP4", _fraction_score(5, [
        lo <= float(deterministic.get("average_visual_state_sec") or 999) <= hi,
        float(deterministic.get("max_visual_state_sec") or 999) <= OPENING_MAX_STATE_SECONDS]), 5)
    add("Scientific accuracy and claim support", 5 if claim_validation.get("passed") else 0, 5)
    add("Audio, captions, and comprehension", _fraction_score(3, [
        blind.get("comprehensible_audio_story"), not blind.get("captions_obscure_evidence")]), 3)
    add("Runtime and technical delivery", _fraction_score(2, [
        deterministic.get("decodable"), deterministic.get("shot_count", 0) > 0]), 2)

    total = sum(item["score"] for item in components)
    hard_failures = []
    story_codes = {item.get("code") for item in story_validation.get("errors") or []}
    if not deterministic.get("decodable"):
        hard_failures.append("rendered_opening_unavailable")
    if deterministic.get("slideshow") or blind.get("slideshow"):
        hard_failures.append("slideshow_behavior")
        total = min(total, 49)
    if deterministic.get("bolt_shot_ratio", 0) >= 0.70:
        hard_failures.append("bolt_everywhere")
    if int(deterministic.get("bolt_shot_count") or 0) <= 0:
        hard_failures.append("bolt_absent")
    if deterministic.get("long_hold_count", 0):
        hard_failures.append("long_visual_hold")
    average_state = float(deterministic.get("average_visual_state_sec") or 999)
    if not OPENING_AVG_STATE_RANGE[0] <= average_state <= OPENING_AVG_STATE_RANGE[1]:
        hard_failures.append("visual_state_cadence")
    if deterministic.get("continuity_failures"):
        hard_failures.append("broken_continuity")
    if deterministic.get("unverified_cut_count", 0):
        hard_failures.append("unverified_rendered_cut")
    if "evidence_never_forces_decision" in story_codes:
        hard_failures.append("false_belief_without_evidence")
    if "consequence_enumeration" in story_codes:
        hard_failures.append("consequence_list")
    if not claim_validation.get("passed"):
        hard_failures.append("unsupported_major_claim")
        total = min(total, 59)
    # Everything above is a judgement about the VIDEO: it is a slideshow, continuity is broken, a
    # major claim is unsupported. Calibration is a statement about the INSTRUMENT — we have not
    # established what the pixel thresholds should be. Conflating the two made "we cannot measure
    # this yet" indistinguishable from "this video is bad", and since no calibrated profile has
    # ever existed, every long-form run capped at 69 against an 85 bar and aborted before buying
    # its remaining scenes. A gate nothing can pass is a policy defect, not a quality standard.
    #
    # So the instrument failure no longer suppresses the score or blocks the render. It still
    # blocks PUBLICATION: an uncalibrated run can finish and be reviewed, but it cannot be called
    # publishable, because the thresholds behind its measurements are unaudited.
    calibration = validate_threshold_profile(threshold_profile, require_calibrated=True)
    calibrated = bool(calibration["passed"])
    if hard_failures:
        total = min(total, 69)
    automated_pass = total >= RELEASE_SCORE and not hard_failures and blind.get("valid", True)
    review = human_review or {"status": "pending", "decision": "pending"}
    human_approved = review.get("decision") == "approve"
    certified = bool(automated_pass and human_approved and calibrated)
    return {
        "version": RENDERED_GATE_VERSION,
        "name": "Bolt Long-Form Rendered Contract",
        "score": int(total),
        "percent": int(total),
        "grade": "A" if total >= 90 else "B" if total >= 85 else "C" if total >= 70 else "D" if total >= 60 else "F",
        "status": ("PASS" if certified else
                   "PASS_UNCERTIFIED" if automated_pass and human_approved else
                   "AUTOMATED_PASS_AWAITING_HUMAN" if automated_pass else "REJECT"),
        # `passed` keeps meaning "this run may proceed"; `publishable` keeps meaning "this may be
        # released", and only that second one requires a calibrated instrument.
        "passed": bool(automated_pass and human_approved),
        "automated_pass": automated_pass,
        "publishable": certified,
        "calibrated": calibrated,
        "uncertified_reason": ("" if calibrated else "uncalibrated_rendered_thresholds"),
        "hard_failures": sorted(set(hard_failures)),
        "threshold_profile": threshold_profile,
        "threshold_calibration": calibration,
        "components": components,
        "human_review": review,
        "disclaimer": "Contract compliance score; it does not predict audience retention.",
    }


HUMAN_REVIEW_CHECKLIST = [
    "The title/thumbnail promise is visible in the opening.",
    "The human subject, objective, and anomaly are immediately readable.",
    "Each cut adds evidence or advances the investigation.",
    "Bolt appears only when performing useful story work.",
    "Captions do not obscure evidence.",
    "The opening creates a concrete reason to continue.",
]


def create_human_review_record(report_path: str, preview_path: str, output_path: str) -> dict:
    record = {
        "version": RENDERED_GATE_VERSION,
        "status": "pending",
        "decision": "pending",
        "reviewer": "",
        "reviewed_at": "",
        "rendered_report_sha256": _sha256(report_path),
        "preview_sha256": _sha256(preview_path),
        "checklist": [{"item": item, "approved": None, "note": ""}
                      for item in HUMAN_REVIEW_CHECKLIST],
    }
    Path(output_path).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def apply_human_review(record: dict, *, reviewer: str, decision: str,
                       checklist: list[dict], report_path: str,
                       preview_path: str) -> dict:
    """Bind a human decision to the exact report and preview bytes that were reviewed."""
    if decision not in {"approve", "reject"}:
        raise ValueError("Human review decision must be approve or reject.")
    if not _text(reviewer):
        raise ValueError("Human review requires a reviewer name.")
    expected = record.get("checklist") or []
    if len(checklist or []) != len(expected):
        raise ValueError("Every human review checklist item must be returned.")
    normalized = []
    for original, submitted in zip(expected, checklist):
        if _text(submitted.get("item")) != _text(original.get("item")):
            raise ValueError("Human review checklist text changed.")
        normalized.append({
            "item": _text(original.get("item")),
            "approved": submitted.get("approved") is True,
            "note": _text(submitted.get("note")),
        })
    if decision == "approve" and not all(item["approved"] for item in normalized):
        raise ValueError("Approval requires every checklist item to be explicitly approved.")
    if _sha256(report_path) != _text(record.get("rendered_report_sha256")):
        raise ValueError("Rendered-contract report changed after the review record was created.")
    if _sha256(preview_path) != _text(record.get("preview_sha256")):
        raise ValueError("Opening preview changed after the review record was created.")
    return {
        **record,
        "status": "completed",
        "decision": decision,
        "reviewer": _text(reviewer),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "checklist": normalized,
    }


def diagnostic_mode_allowed(environment: dict[str, str] | None = None) -> bool:
    env = environment or os.environ
    return (env.get("LONGFORM_DIAGNOSTIC_MODE") == "1"
            and env.get("VERCEL_ENV", "development") != "production"
            and env.get("APP_ENV", "development") != "production")


def diagnostic_disposition(report: dict, *, allowed: bool) -> dict:
    """A bypass can expose a rejected preview, never a PASS or publishable artifact."""
    result = dict(report)
    result.update({
        "status": "REJECTED_DIAGNOSTIC" if allowed else "REJECT",
        "passed": False,
        "publishable": False,
        "diagnostic_mode": bool(allowed),
        "watermark": DIAGNOSTIC_WATERMARK if allowed else "",
    })
    return result


def watermark_rejected_preview(video_path: str, output_path: str) -> str:
    """Create a visibly rejected diagnostic copy; never mutate the approved source."""
    escaped = DIAGNOSTIC_WATERMARK.replace("—", "-").replace("'", "\\'").replace(":", "\\:")
    subprocess.run([
        _ffmpeg_bin(), "-nostdin", "-y", "-loglevel", "error", "-i", video_path,
        "-vf", ("drawbox=x=0:y=ih*0.42:w=iw:h=ih*0.16:color=black@0.78:t=fill,"
                f"drawtext=text='{escaped}':fontcolor=red:fontsize=h/22:"
                "x=(w-text_w)/2:y=(h-text_h)/2"),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy", output_path,
    ], check=True, capture_output=True, timeout=180)
    return output_path
