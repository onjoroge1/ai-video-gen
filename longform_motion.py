"""Deterministic story-role motion planning for verified long-form evidence states."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


MOTION_MODES = {"stills", "standard", "full_motion"}
STATIC_PURPOSES = {"diagram", "record"}
STANDARD_MOTION_FRACTION = 0.35

# Higher scores purchase motion first. These are story functions, not scene positions.
ROLE_PRIORITY = {
    "cold_consequence": 100,
    "hook": 100,
    "opening_anomaly": 100,
    "prediction_test": 90,
    "prediction_gate": 90,
    "test": 90,
    "experiment": 90,
    "reversal": 80,
    "twist": 80,
    "reveal": 75,
    "peak_reveal": 75,
    "final_payoff": 70,
    "payoff": 65,
    "callback": 70,
}
PRIORITY_CLASSES = ("hook", "test", "reversal", "reveal", "callback")


def normalize_motion_mode(value: str | None, *, legacy_i2v: bool | None = None) -> str:
    """Resolve the new three-mode contract while preserving old API callers."""
    normalized = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {"still": "stills", "full": "full_motion", "standard_motion": "standard"}
    normalized = aliases.get(normalized, normalized)
    if normalized in MOTION_MODES:
        return normalized
    if legacy_i2v is False:
        return "stills"
    return "standard"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _contains_exact_phrase(narration: str, phrase: str) -> bool:
    return bool(phrase) and phrase.casefold() in narration.casefold()


def _candidate(scene: dict, scene_plan: dict, state: dict) -> dict:
    role = _text(scene_plan.get("story_role") or scene.get("story_role")).casefold()
    purpose = _text(state.get("purpose")).casefold()
    anchor = _text(state.get("anchor_phrase"))
    narration = _text(scene.get("narration"))
    eligible = (
        _text(state.get("asset_status")) in {"planned", "accepted", "reused_exact"}
        and bool(_text(state.get("asset_id")))
        and bool(_text(state.get("state_before")))
        and bool(_text(state.get("state_after")))
        and purpose not in STATIC_PURPOSES
        and _contains_exact_phrase(narration, anchor)
    )
    reason = ""
    if purpose in STATIC_PURPOSES:
        reason = f"static {purpose} state"
    elif not anchor:
        reason = "missing narration anchor"
    elif not _contains_exact_phrase(narration, anchor):
        reason = "anchor is not an exact final-narration phrase"
    elif _text(state.get("asset_status")) not in {"planned", "accepted", "reused_exact"}:
        reason = "evidence asset is not available"
    priority = ROLE_PRIORITY.get(role, 40)
    if purpose == "callback":
        priority = max(priority, 85)
    if purpose in {"action", "consequence"}:
        priority += 5
    if purpose == "callback":
        priority_class = "callback"
    elif role in {"cold_consequence", "hook", "opening_anomaly"}:
        priority_class = "hook"
    elif role in {"prediction_test", "prediction_gate", "test", "experiment"}:
        priority_class = "test"
    elif role in {"reversal", "twist"}:
        priority_class = "reversal"
    elif role in {"reveal", "peak_reveal", "payoff", "final_payoff"}:
        priority_class = "reveal"
    else:
        priority_class = "support"
    return {
        "motion_id": f"motion:{_text(state.get('state_id'))}",
        "scene_index": int(scene_plan.get("scene_index") or 0),
        "state_id": _text(state.get("state_id")),
        "asset_id": _text(state.get("asset_id")),
        "story_role": role,
        "purpose": purpose,
        "anchor_phrase": anchor,
        "state_before": _text(state.get("state_before")),
        "state_after": _text(state.get("state_after")),
        "pure_evidence": bool(state.get("pure_evidence")),
        "eligible": eligible,
        "ineligible_reason": reason,
        "role_priority": priority,
        "priority_class": priority_class,
        "semantic_aligned": _contains_exact_phrase(narration, anchor),
        "selected": False,
        "generation_status": "not_requested",
        "provider": "",
        "clip_path": "",
        "cost_usd": 0.0,
        "fallback_reason": "",
    }


def _standard_selection(eligible: list[dict], limit: int) -> list[dict]:
    ranked = sorted(
        eligible,
        key=lambda item: (-int(item["role_priority"]), int(item["scene_index"]), item["state_id"]),
    )
    reserved = []
    for priority_class in PRIORITY_CLASSES:
        match = next((item for item in ranked if item.get("priority_class") == priority_class), None)
        if match:
            reserved.append(match)
    target = min(limit, max(1, round(len(eligible) * STANDARD_MOTION_FRACTION), len(reserved)))
    selected = reserved[:target]
    selected_ids = {item["motion_id"] for item in selected}
    selected.extend(item for item in ranked if item["motion_id"] not in selected_ids)
    return selected[:target]


def _full_selection(eligible: list[dict], limit: int) -> list[dict]:
    if limit <= 0:
        return []
    if len(eligible) <= limit:
        return list(eligible)
    if limit == 1:
        return [eligible[0]]
    positions = [round(index * (len(eligible) - 1) / (limit - 1)) for index in range(limit)]
    return [eligible[position] for position in positions]


def compile_motion_plan(script: dict, evidence_plan: dict, *, mode: str,
                        max_requests: int) -> dict:
    """Select motion by story role for Standard and by evidence-state order for Full."""
    resolved = normalize_motion_mode(mode)
    scenes = script.get("scenes") or []
    candidates = []
    for scene_plan in evidence_plan.get("scenes") or []:
        index = int(scene_plan.get("scene_index") or 0)
        scene = scenes[index] if index < len(scenes) else {}
        candidates.extend(_candidate(scene, scene_plan, state)
                          for state in scene_plan.get("states") or [])
    eligible = [candidate for candidate in candidates if candidate["eligible"]]
    limit = max(0, int(max_requests))
    selected: list[dict] = []
    if resolved == "standard" and limit:
        selected = _standard_selection(eligible, limit) if eligible else []
    elif resolved == "full_motion" and limit:
        selected = _full_selection(eligible, limit)
    selected_ids = {item["motion_id"] for item in selected}
    for candidate in candidates:
        if candidate["motion_id"] in selected_ids:
            candidate["selected"] = True
            candidate["generation_status"] = "pending"
    plan = {
        "version": 1,
        "mode": resolved,
        "max_requests": limit,
        "eligible_count": len(eligible),
        "selected_count": len(selected),
        "capped_out_count": max(0, len(eligible) - len(selected)) if resolved == "full_motion" else 0,
        "candidates": candidates,
    }
    plan["validation"] = validate_motion_plan(plan)
    return plan


def validate_motion_plan(plan: dict, *, require_generation: bool = False) -> dict:
    errors = []
    mode = _text(plan.get("mode"))
    candidates = plan.get("candidates") if isinstance(plan.get("candidates"), list) else []
    selected = [item for item in candidates if item.get("selected")]
    eligible = [item for item in candidates if item.get("eligible")]
    limit = max(0, int(plan.get("max_requests") or 0))
    if mode not in MOTION_MODES:
        errors.append({"code": "invalid_motion_mode", "message": "Unknown motion mode."})
    if mode == "stills" and selected:
        errors.append({"code": "stills_requested_motion", "message": "Stills mode purchased motion."})
    if len(selected) > limit:
        errors.append({"code": "motion_cap_exceeded", "message": "Selected motion exceeds its cap."})
    if mode == "standard" and selected:
        expected = _standard_selection(eligible, len(selected))
        if {item["motion_id"] for item in selected} != {item["motion_id"] for item in expected}:
            errors.append({"code": "standard_role_priority_broken",
                           "message": "Standard motion did not select the highest story roles first."})
    if mode == "full_motion":
        expected = _full_selection(eligible, limit)
        if [item["motion_id"] for item in selected] != [item["motion_id"] for item in expected]:
            errors.append({"code": "full_motion_coverage_broken",
                           "message": "Full Motion did not request every eligible state within the cap."})
    aligned = sum(1 for item in selected if item.get("semantic_aligned"))
    ratio = aligned / len(selected) if selected else 1.0
    if selected and ratio < 0.90:
        errors.append({"code": "motion_semantic_alignment",
                       "message": f"Motion semantic alignment is {ratio:.0%}; 90% required."})
    if require_generation:
        invalid = [item for item in selected
                   if item.get("generation_status") not in {"animated", "fallback"}]
        if invalid:
            errors.append({"code": "motion_generation_unresolved",
                           "message": "Selected motion contains unresolved generation states."})
    return {
        "version": 1,
        "passed": not errors,
        "selected_count": len(selected),
        "animated_count": sum(1 for item in selected if item.get("generation_status") == "animated"),
        "fallback_count": sum(1 for item in selected if item.get("generation_status") == "fallback"),
        "semantic_alignment_ratio": round(ratio, 3),
        "actual_cost_usd": round(sum(float(item.get("cost_usd") or 0) for item in selected), 4),
        "errors": errors,
    }


def motion_prompt(candidate: dict) -> str:
    cast_rule = ("Do not introduce Bolt or any character; animate only the physical evidence. "
                 if candidate.get("pure_evidence") else "Preserve every character and object identity. ")
    return (
        f"Animate only this narration-aligned evidence change: '{candidate.get('anchor_phrase')}'. "
        f"Begin from: {candidate.get('state_before')}. End with: {candidate.get('state_after')}. "
        f"Story function: {candidate.get('story_role')}; evidence purpose: {candidate.get('purpose')}. "
        + cast_rule
        + "One continuous physical action, stable geography, no cuts, no text, no new objects, "
          "no generic idle motion, and no camera move presented as evidence."
    )


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def freeze_opening_manifest(scene_segments: dict[int, str], motion_clips: dict[str, str],
                            output_path: str) -> dict:
    """Freeze exact approved segment/clip hashes so the final edit cannot silently diverge."""
    manifest = {
        "version": 1,
        "scene_segments": {str(index): {"path": path, "sha256": sha256_file(path)}
                           for index, path in sorted(scene_segments.items())},
        "motion_clips": {state_id: {"path": path, "sha256": sha256_file(path)}
                         for state_id, path in sorted(motion_clips.items())},
    }
    Path(output_path).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def validate_frozen_opening(manifest: dict) -> dict:
    errors = []
    checked = 0
    for group in ("scene_segments", "motion_clips"):
        for identity, item in (manifest.get(group) or {}).items():
            path = _text(item.get("path"))
            if not path or not Path(path).is_file():
                errors.append({"code": "frozen_opening_missing",
                               "message": f"Frozen {group} asset {identity} is missing."})
                continue
            checked += 1
            if sha256_file(path) != _text(item.get("sha256")):
                errors.append({"code": "frozen_opening_changed",
                               "message": f"Frozen {group} asset {identity} changed after approval."})
    return {"version": 1, "passed": not errors, "checked_asset_count": checked, "errors": errors}
