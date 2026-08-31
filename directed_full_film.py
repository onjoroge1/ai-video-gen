"""Hash-bound promotion of an accepted directed pilot into its remaining film.

The pilot action pays only for the opening.  A promotion envelope binds a second approval to the
full directed spec, the exact parent action/job, and the SHA-256 of the already-rendered opening.
The renderer then buys only the later window and stream-concatenates the frozen MP4 in front.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import directed_longform as dl
import explainer_pipeline as ep
import spec_pilot


OPERATION = "directed_full_film"
SCOPE = "remaining-45-to-300"


class DirectedFullFilmError(RuntimeError):
    pass


def _canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def authorization_sha256(envelope: dict) -> str:
    return hashlib.sha256(_canonical(envelope).encode("utf-8")).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _opening_rows(spec: dict, key: str, pilot_end: float) -> list[dict]:
    return [item for item in spec.get(key) or []
            if float(item.get("start_sec") or 0) < pilot_end]


def validate_opening_identity(parent_spec: dict, full_spec: dict) -> None:
    """Require narration and shot contracts before 0:45 to be byte-equivalent.

    Project title, total runtime, later worlds/evidence, and the target cost cap necessarily differ
    between pilot and full-film specs.  The creative bytes that made the accepted opening do not.
    """
    parent = dl.DirectedLongformSpec.model_validate(parent_spec).model_dump(mode="json")
    full = dl.DirectedLongformSpec.model_validate(full_spec).model_dump(mode="json")
    pilot_end = float(parent["target"]["pilot_end_sec"])
    if abs(float(full["target"]["pilot_end_sec"]) - pilot_end) > 0.001:
        raise DirectedFullFilmError("Full spec changes the accepted pilot boundary")
    for key in ("narration", "shots"):
        if _opening_rows(parent, key, pilot_end) != _opening_rows(full, key, pilot_end):
            raise DirectedFullFilmError(f"Full spec changes accepted opening {key}")
    parent_worlds = [item for item in parent.get("worlds") or []
                     if float(item.get("start_sec") or 0) < pilot_end]
    full_worlds = [item for item in full.get("worlds") or []
                   if float(item.get("start_sec") or 0) < pilot_end]
    if parent_worlds != full_worlds:
        raise DirectedFullFilmError("Full spec changes the accepted opening visual world")


def build_envelope(*, full_spec: dict, parent_spec: dict, parent_action_id: str,
                   parent_job_id: str, parent_video_sha256: str) -> tuple[dict, dict]:
    report = dl.validate_directed_spec(full_spec)
    if not report.get("valid"):
        raise DirectedFullFilmError("Full directed spec failed validation")
    validate_opening_identity(parent_spec, report["normalized_spec"])
    parent_report = dl.validate_directed_spec(parent_spec)
    if not parent_report.get("valid"):
        raise DirectedFullFilmError("Parent pilot spec is no longer valid")
    pilot_end = float(report["pilot_end_sec"])
    duration = float(report["duration_sec"])
    if abs(pilot_end - 45.0) > 0.05 or abs(duration - 300.0) > 0.05:
        raise DirectedFullFilmError("This promotion is scoped to the accepted 0:45–5:00 film")
    remaining = dl.window_cost_estimate(report["normalized_spec"], pilot_end, duration)
    promotion = {
        "schema_version": 1,
        "operation": OPERATION,
        "scope": SCOPE,
        "parent_action_id": str(parent_action_id),
        "parent_job_id": str(parent_job_id),
        "parent_pilot_spec_sha256": parent_report["spec_sha256"],
        "parent_video_sha256": str(parent_video_sha256),
        "content_spec_sha256": report["spec_sha256"],
        "start_sec": pilot_end,
        "end_sec": duration,
        "pilot_reuse_required": True,
        "remaining_cost_estimate": remaining,
    }
    envelope = {"spec": report["normalized_spec"], "promotion": promotion}
    return envelope, {**report, "remaining_cost_estimate": remaining,
                      "authorization_sha256": authorization_sha256(envelope)}


def validate_envelope(envelope: dict, *, expected_sha256: str) -> tuple[dict, dict]:
    if not isinstance(envelope, dict) or set(envelope) != {"spec", "promotion"}:
        raise DirectedFullFilmError("Full-film action payload is malformed")
    if authorization_sha256(envelope) != expected_sha256:
        raise DirectedFullFilmError("Full-film authorization hash changed")
    promotion = envelope.get("promotion") if isinstance(envelope.get("promotion"), dict) else {}
    if (promotion.get("operation") != OPERATION or promotion.get("scope") != SCOPE
            or promotion.get("pilot_reuse_required") is not True):
        raise DirectedFullFilmError("Full-film promotion boundary is invalid")
    report = dl.validate_directed_spec(envelope.get("spec") or {})
    if not report.get("valid") or report.get("spec_sha256") != promotion.get("content_spec_sha256"):
        raise DirectedFullFilmError("Full-film content spec failed hash-bound validation")
    if abs(float(promotion.get("start_sec") or 0) - 45.0) > 0.05:
        raise DirectedFullFilmError("Promotion would re-render the accepted pilot")
    if abs(float(promotion.get("end_sec") or 0) - 300.0) > 0.05:
        raise DirectedFullFilmError("Promotion end does not match the five-minute contract")
    return report, promotion


def _write_text_artifacts(spec: dl.DirectedLongformSpec, out: Path) -> tuple[str, str]:
    transcript = out / "transcript.txt"
    transcript.write_text(
        " ".join(scene.narration.strip() for scene in spec.narration) + "\n",
        encoding="utf-8")
    cues = []
    for index, scene in enumerate(spec.narration, 1):
        def stamp(value: float) -> str:
            millis = int(round(value * 1000))
            hours, millis = divmod(millis, 3_600_000)
            minutes, millis = divmod(millis, 60_000)
            seconds, millis = divmod(millis, 1000)
            return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
        cues.append(
            f"{index}\n{stamp(scene.start_sec)} --> {stamp(scene.end_sec)}\n"
            f"{scene.narration.strip()}\n")
    captions = out / "captions.srt"
    captions.write_text("\n".join(cues), encoding="utf-8")
    return str(transcript), str(captions)


def render_remaining(*, envelope: dict, authorization_hash: str, parent_video_path: str,
                     out_dir: str, voice: str = "echo", authorize_paid: bool = False,
                     restore_parent_video=None, log=print) -> dict:
    """Render only 45–300 seconds and prepend the immutable accepted opening."""
    if authorize_paid is not True:
        raise DirectedFullFilmError("Explicit remaining-film authorization is required")
    report, promotion = validate_envelope(envelope, expected_sha256=authorization_hash)
    parent_path = Path(parent_video_path)
    if not parent_path.is_file():
        raise DirectedFullFilmError("Accepted pilot video is unavailable")
    if file_sha256(parent_path) != promotion["parent_video_sha256"]:
        raise DirectedFullFilmError("Accepted pilot video SHA-256 changed")
    # The accepted pilot is already immutable in Blob and is not needed while the remaining
    # 255 seconds are rendered. Keeping that large MP4 beside restored images and shot batches
    # consumed a material fraction of Vercel's /tmp and repeatedly stranded otherwise durable
    # work. Verify it first, release the local copy, and restore only for final concatenation.
    if restore_parent_video is not None:
        parent_path.unlink(missing_ok=True)
        log("Released local accepted pilot during remaining-film render")
    spec = dl.DirectedLongformSpec.model_validate(report["normalized_spec"])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    log("stage:Reusing accepted 0:00–0:45 pilot")
    log(f"Accepted pilot SHA-256 verified: {promotion['parent_video_sha256']}")
    segment = spec_pilot.render_pilot(
        report["normalized_spec"], str(out), voice=voice,
        window=(promotion["start_sec"], promotion["end_sec"]), use_i2v=True,
        validated_sha256=report["spec_sha256"], authorize_paid=True,
        require_validation=True, log=log)
    log("stage:Assembling accepted pilot + remaining film")
    if restore_parent_video is not None:
        restore_parent_video(str(parent_path))
        if file_sha256(parent_path) != promotion["parent_video_sha256"]:
            raise DirectedFullFilmError("Restored accepted pilot video SHA-256 changed")
    concat = out / "full_film_concat.txt"
    concat.write_text(
        f"file '{parent_path.resolve()}'\nfile '{Path(segment['preview_path']).resolve()}'\n",
        encoding="utf-8")
    output = out / "directed_full_film.mp4"
    ep._run_ffmpeg([
        ep._ffmpeg_bin(), "-nostdin", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat), "-map", "0:v", "-map", "0:a", "-c", "copy",
        "-movflags", "+faststart", str(output),
    ], timeout=600.0)
    measured = ep._audio_dur(str(output))
    if abs(measured - spec.target.duration_sec) > spec.acceptance.runtime_tolerance_sec:
        raise DirectedFullFilmError(
            f"assembled film runtime {measured:.2f}s is outside the five-minute tolerance")
    transcript_path, srt_path = _write_text_artifacts(spec, out)
    delivery = {
        "schema_version": 1,
        "status": "COMPLETED_AWAITING_EDITORIAL",
        "scope": SCOPE,
        "authorization_sha256": authorization_hash,
        "content_spec_sha256": report["spec_sha256"],
        "parent_action_id": promotion["parent_action_id"],
        "parent_job_id": promotion["parent_job_id"],
        "parent_video_sha256": promotion["parent_video_sha256"],
        "pilot_reused": True,
        "remaining_window": {"start_sec": promotion["start_sec"],
                             "end_sec": promotion["end_sec"]},
        "remaining_cost_usd": segment["total_cost_usd"],
        "measured_duration_sec": round(measured, 3),
        "video_sha256": file_sha256(output),
        "remaining_shots": segment["shots"],
        "remaining_animated_shots": segment["animated_shots"],
    }
    delivery_path = out / "full_delivery_report.json"
    delivery_path.write_text(json.dumps(delivery, indent=2), encoding="utf-8")
    log(f"Full five-minute film assembled at {measured:.2f}s; awaiting editorial review")
    return {
        "output_path": str(output),
        "title": spec.title,
        "script": report["normalized_spec"],
        "hook": spec.narration[0].narration,
        "scene_count": len(spec.narration),
        "shot_count": len(spec.shots),
        "remaining_shot_count": segment["shots"],
        "duration_sec": round(measured, 2),
        "video_format": "landscape",
        "actual_cost": segment["total_cost_usd"],
        "est_cost": promotion["remaining_cost_estimate"]["estimated_total_usd"],
        "status": "ok",
        "technical_status": "completed",
        "automated_grade_status": "NOT_RUN_FULL_FILM",
        "editorial_status": "pending",
        "promotion_status": "full_film_completed",
        "degraded_reasons": [],
        "directed_full_film": True,
        "pilot_reused": True,
        "parent_job_id": promotion["parent_job_id"],
        "parent_video_sha256": promotion["parent_video_sha256"],
        "transcript_path": transcript_path,
        "srt_path": srt_path,
        "generation_manifest_path": segment["generation_manifest_path"],
        "directed_spec_path": segment["directed_spec_path"],
        "validation_report_path": segment["validation_report_path"],
        "full_delivery_report_path": str(delivery_path),
    }
