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

import numpy as np
from PIL import Image, ImageDraw, ImageFont


RENDERED_GATE_VERSION = 1
RELEASE_SCORE = 85
OPENING_AVG_STATE_RANGE = (1.8, 3.2)
OPENING_MAX_STATE_SECONDS = 3.5
DIAGNOSTIC_WATERMARK = "REJECTED DIAGNOSTIC — NOT FOR PUBLICATION"


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
            "ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-loop", "1", "-i", str(image_path),
            "-i", audio, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-tune", "stillimage",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(segment_path),
        ], check=True, capture_output=True, timeout=120)
        segments.append(segment_path)
    if not segments:
        raise ValueError("The animatic has no renderable storyboard scenes.")
    concat_path = root / "segments.txt"
    concat_path.write_text("".join(f"file '{path.as_posix()}'\n" for path in segments), encoding="utf-8")
    subprocess.run([
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", str(concat_path), "-c", "copy", output_path,
    ], check=True, capture_output=True, timeout=180)
    return output_path


def _extract_frame(video_path: str, timestamp: float, output_path: str) -> None:
    subprocess.run([
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-ss", f"{max(0.0, timestamp):.3f}",
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
                             evidence_plan: dict) -> dict:
    """Extract each cut midpoint plus boundary samples and measure encoded story states."""
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
    pixel_changes = sum(item["pixel_delta"] >= 0.035 for item in boundary_deltas)
    deterministic = {
        "decodable": bool(frames) and not errors,
        "shot_count": len(shots),
        "extracted_midpoint_count": len(frames),
        "distinct_source_count": len(set(filter(None, sources))),
        "source_change_ratio": round(source_changes / max(1, len(shots) - 1), 3),
        "pixel_boundary_change_ratio": round(pixel_changes / max(1, len(boundary_deltas)), 3),
        "verified_information_ratio": round(verified / max(1, len(shots)), 3),
        "per_cut_verification_ratio": round(
            sum(frame.get("asset_verification_passed") for frame in frames) / max(1, len(frames)), 3),
        "unverified_cut_count": sum(not frame.get("asset_verification_passed") for frame in frames),
        "average_visual_state_sec": round(avg_state, 3),
        "max_visual_state_sec": round(max_state, 3),
        "long_hold_count": sum(duration > OPENING_MAX_STATE_SECONDS for duration in durations),
        "bolt_shot_ratio": round(expected_bolt / max(1, len(shots)), 3),
        "pure_evidence_bolt_violations": pure_bolt_violations,
        "continuity_failures": continuity_failures,
        "slideshow": (len(set(filter(None, sources))) <= max(1, math.ceil(len(shots) * 0.35))
                      or source_changes / max(1, len(shots) - 1) < 0.45),
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
    add("Genuine multi-shot visual storytelling", _fraction_score(15, [
        blind.get("multi_shot_storytelling"), not blind.get("slideshow"),
        not deterministic.get("slideshow"), deterministic.get("source_change_ratio", 0) >= 0.45,
        deterministic.get("pixel_boundary_change_ratio", 0) >= 0.45]), 15)
    add("Bolt discipline and usefulness", _fraction_score(10, [
        deterministic.get("bolt_shot_ratio", 0) <= 0.35,
        deterministic.get("pure_evidence_bolt_violations", 0) == 0,
        blind.get("bolt_useful") or deterministic.get("bolt_shot_ratio", 0) == 0]), 10)
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
    if hard_failures:
        total = min(total, 69)
    automated_pass = total >= RELEASE_SCORE and not hard_failures and blind.get("valid", True)
    review = human_review or {"status": "pending", "decision": "pending"}
    human_approved = review.get("decision") == "approve"
    return {
        "version": RENDERED_GATE_VERSION,
        "name": "Bolt Long-Form Rendered Contract",
        "score": int(total),
        "percent": int(total),
        "grade": "A" if total >= 90 else "B" if total >= 85 else "C" if total >= 70 else "D" if total >= 60 else "F",
        "status": ("PASS" if automated_pass and human_approved else
                   "AUTOMATED_PASS_AWAITING_HUMAN" if automated_pass else "REJECT"),
        "passed": bool(automated_pass and human_approved),
        "automated_pass": automated_pass,
        "publishable": bool(automated_pass and human_approved),
        "hard_failures": sorted(set(hard_failures)),
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
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", video_path,
        "-vf", ("drawbox=x=0:y=ih*0.42:w=iw:h=ih*0.16:color=black@0.78:t=fill,"
                f"drawtext=text='{escaped}':fontcolor=red:fontsize=h/22:"
                "x=(w-text_w)/2:y=(h-text_h)/2"),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy", output_path,
    ], check=True, capture_output=True, timeout=180)
    return output_path
