"""Canonical JSON contract and fail-closed preflight for operator-directed longform video.

The legacy longform pipeline starts by inventing a script and research plan.  A directed run is
the opposite job: the operator supplies the narration, evidence and shot decisions.  Keeping the
two paths separate prevents a growing collection of bypass flags in the legacy pipeline.

This module is deliberately provider-free.  ``validate_directed_spec`` performs every check that
can be completed without spending money and returns an immutable hash.  The renderer must receive
that exact hash plus explicit paid authorization before it can generate even narration.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator,
)


SCHEMA_VERSION = "directed_longform_v1"
TTS_COST_PER_CHARACTER = 30.0 / 1_000_000
IMAGE_COST_USD = 0.045
IMAGE_EDIT_COST_USD = 0.055
I2V_COST_USD = 0.28
_UNRESOLVED_LICENSES = {"", "unknown", "unresolved", "tbd", "verify"}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DirectedTarget(_StrictModel):
    duration_sec: float = Field(gt=0)
    pilot_end_sec: float = Field(default=45.0, gt=0)
    format: Literal["landscape"] = "landscape"
    voice: str = "echo"
    max_cost_usd: float = Field(default=25.0, gt=0)

    @field_validator("pilot_end_sec")
    @classmethod
    def pilot_inside_runtime(cls, value: float, info):
        duration = (info.data or {}).get("duration_sec")
        if duration is not None and value > duration:
            raise ValueError("pilot_end_sec cannot exceed duration_sec")
        return value


class DirectedAcceptance(_StrictModel):
    runtime_tolerance_sec: float = Field(default=10.0, ge=0)
    pilot_runtime_min_sec: float = Field(default=43.0, gt=0)
    pilot_runtime_max_sec: float = Field(default=47.0, gt=0)
    pilot_min_visual_states: int = Field(default=15, ge=1)
    # Kept at one for schema compatibility with already-archived v1 contracts. New downloadable
    # templates and bundled pilots set an explicit density floor; the immutable old artifacts can
    # still be parsed and diagnosed instead of collapsing into a generic schema error.
    pilot_min_unique_master_assets: int = Field(default=1, ge=1)
    min_shot_sec: float = Field(default=1.25, gt=0)
    max_unchanged_hold_sec: float = Field(default=3.0, gt=0)
    max_consecutive_still_asset_sec: float = Field(default=3.0, gt=0)
    full_motion_duration_sec: float = Field(default=5.0, gt=0)
    full_motion_duration_tolerance_sec: float = Field(default=0.25, ge=0, le=1.0)
    frontloaded_motion_count: int = Field(default=0, ge=0)
    frontloaded_motion_window_sec: float = Field(default=15.0, gt=0)
    max_unique_master_assets: int = Field(default=60, ge=1)
    min_useful_bolt_appearances: int = Field(default=1, ge=0)
    max_bolt_appearances: int = Field(default=3, ge=0)
    planned_bolt_appearances: int | None = Field(default=None, ge=0)
    evidence_coverage_pct: float = Field(default=100.0, ge=0, le=100)
    automatic_grade_min: float = Field(default=90.0, ge=0, le=100)
    editorial_grade_min: float = Field(default=85.0, ge=0, le=100)

    @model_validator(mode="after")
    def coherent_ranges(self):
        if self.pilot_runtime_min_sec > self.pilot_runtime_max_sec:
            raise ValueError("pilot_runtime_min_sec cannot exceed pilot_runtime_max_sec")
        if self.min_useful_bolt_appearances > self.max_bolt_appearances:
            raise ValueError("min_useful_bolt_appearances cannot exceed max_bolt_appearances")
        if self.pilot_min_unique_master_assets > self.max_unique_master_assets:
            raise ValueError(
                "pilot_min_unique_master_assets cannot exceed max_unique_master_assets")
        if (self.planned_bolt_appearances is not None
                and not self.min_useful_bolt_appearances
                <= self.planned_bolt_appearances
                <= self.max_bolt_appearances):
            raise ValueError("planned_bolt_appearances must be inside the accepted Bolt range")
        return self


class DirectedWorld(_StrictModel):
    world_id: str = Field(min_length=1)
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)
    base_prompt: str = Field(min_length=1)
    on_screen_label: str = ""


class DirectedEvidence(_StrictModel):
    claim_id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    qualification: str = Field(min_length=1)
    license: str = "unresolved"


class DirectedReference(_StrictModel):
    reference_id: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    sha256: str = ""
    mime_type: str = Field(min_length=1)
    license: str = "unresolved"
    origin: str = Field(min_length=1)


class DirectedScene(_StrictModel):
    scene_id: str = Field(min_length=1)
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)
    narration: str = Field(min_length=1)
    world_id: str = Field(min_length=1)
    story_role: str = "beat"
    claim_ids: list[str] = Field(default_factory=list)


class DirectedShot(_StrictModel):
    shot_id: str = Field(min_length=1)
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)
    visual: str = Field(min_length=1)
    mode: str = Field(min_length=1)
    world_id: str = Field(min_length=1)
    scene_id: str = ""
    asset_key: str = ""
    # ``asset_prompt`` defines the paid master image. Multiple shots may reuse that master while
    # ``visual`` and ``transformation`` describe the crop/camera treatment seen in each shot.
    asset_prompt: str = ""
    transformation: str = ""
    claim_ids: list[str] = Field(default_factory=list)
    reference_ids: list[str] = Field(default_factory=list)
    overlay_text: str = ""
    labels: list[str] = Field(default_factory=list)


class DirectedLongformSpec(_StrictModel):
    schema_version: Literal[SCHEMA_VERSION]
    project_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    negative_prompt: str = ""
    target: DirectedTarget
    acceptance: DirectedAcceptance = Field(default_factory=DirectedAcceptance)
    worlds: list[DirectedWorld] = Field(min_length=1)
    narration: list[DirectedScene] = Field(min_length=1)
    shots: list[DirectedShot] = Field(min_length=1)
    evidence: list[DirectedEvidence] = Field(default_factory=list)
    references: list[DirectedReference] = Field(default_factory=list)
    prohibited_claims: list[str] = Field(default_factory=list)


class DirectedValidationError(RuntimeError):
    """The canonical spec is invalid or is not authorized for paid processing."""


def _canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def spec_sha256(value: DirectedLongformSpec | dict) -> str:
    if isinstance(value, DirectedLongformSpec):
        value = value.model_dump(mode="json")
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _issue(code: str, message: str, path: str = "", *, severity: str = "error") -> dict:
    return {"severity": severity, "code": code, "path": path, "message": message}


def _ordered_timeline(items, *, target: float, name: str, issues: list[dict]) -> None:
    ordered = sorted(items, key=lambda item: (item.start_sec, item.end_sec))
    if not ordered:
        return
    if abs(ordered[0].start_sec) > 0.05:
        issues.append(_issue(f"{name}_does_not_start_at_zero",
                             f"{name} starts at {ordered[0].start_sec:.2f}s, not 0s", name))
    for item in ordered:
        if item.end_sec <= item.start_sec:
            issues.append(_issue(f"invalid_{name}_duration",
                                 f"{item.end_sec:.2f}s must be after {item.start_sec:.2f}s",
                                 name))
    for earlier, later in zip(ordered, ordered[1:]):
        delta = later.start_sec - earlier.end_sec
        if delta > 0.05:
            issues.append(_issue(f"{name}_timeline_gap",
                                 f"{delta:.2f}s gap after {earlier.end_sec:.2f}s", name))
        elif delta < -0.05:
            issues.append(_issue(f"{name}_timeline_overlap",
                                 f"{-delta:.2f}s overlap at {later.start_sec:.2f}s", name))
    if abs(ordered[-1].end_sec - target) > 0.05:
        issues.append(_issue(f"{name}_runtime_mismatch",
                             f"{name} ends at {ordered[-1].end_sec:.2f}s; target is {target:.2f}s",
                             name))


def _cost_estimate(spec: DirectedLongformSpec, *, start_sec: float = 0.0,
                   end_sec: float | None = None) -> dict:
    scenes = [scene for scene in spec.narration
              if scene.start_sec >= start_sec - 0.001
              and (end_sec is None or scene.start_sec < end_sec)]
    shots = [shot for shot in spec.shots
             if shot.start_sec >= start_sec - 0.001
             and (end_sec is None or shot.start_sec < end_sec)]
    narration_chars = sum(len(scene.narration) for scene in scenes)
    master_keys = {shot.asset_key.strip() or shot.shot_id for shot in shots}
    motion_keys = {
        (shot.asset_key.strip() or shot.shot_id, shot.visual, shot.mode,
         round(shot.end_sec - shot.start_sec, 3))
        for shot in shots
        if shot.mode.strip().casefold() == "full motion"
    }
    tts = narration_chars * TTS_COST_PER_CHARACTER
    referenced_master_keys = {
        shot.asset_key.strip() or shot.shot_id for shot in shots if shot.reference_ids
    }
    images = (
        (len(master_keys) - len(referenced_master_keys)) * IMAGE_COST_USD
        + len(referenced_master_keys) * IMAGE_EDIT_COST_USD
    )
    i2v = len(motion_keys) * I2V_COST_USD
    return {
        "narration_characters": narration_chars,
        "scene_count": len(scenes),
        "shot_count": len(shots),
        "unique_master_assets": len(master_keys),
        "full_motion_assets": len(motion_keys),
        "tts_usd": round(tts, 4),
        "images_usd": round(images, 4),
        "i2v_usd": round(i2v, 4),
        "estimated_total_usd": round(tts + images + i2v, 4),
    }


def window_cost_estimate(payload: DirectedLongformSpec | dict, start_sec: float,
                         end_sec: float) -> dict:
    """Provider-independent estimate for a separately authorized timeline window."""
    spec = payload if isinstance(payload, DirectedLongformSpec) \
        else DirectedLongformSpec.model_validate(payload)
    if start_sec < 0 or end_sec <= start_sec or end_sec > spec.target.duration_sec + 0.05:
        raise DirectedValidationError("Invalid directed cost-estimate window")
    return _cost_estimate(spec, start_sec=float(start_sec), end_sec=float(end_sec))


def pilot_visual_metrics(spec: DirectedLongformSpec) -> dict:
    """Measure source-image cadence separately from superficial shot-state cadence.

    A crop, overlay, or camera preset can create several shot rows while the viewer still sees
    the same underlying composition. The earlier validator counted those rows and therefore
    certified a 1.8-second cadence even when one master image remained onscreen for 5–9 seconds.
    """
    pilot_end = spec.target.pilot_end_sec
    shots = sorted(
        (shot for shot in spec.shots if shot.start_sec < pilot_end),
        key=lambda shot: (shot.start_sec, shot.end_sec),
    )
    unique_assets = {shot.asset_key.strip() or shot.shot_id for shot in shots}
    motion = [shot for shot in shots if shot.mode.strip().casefold() == "full motion"]
    frontloaded = [
        shot for shot in motion
        if shot.start_sec < spec.acceptance.frontloaded_motion_window_sec
    ]

    runs: list[dict] = []
    current: dict | None = None
    for shot in shots:
        key = shot.asset_key.strip() or shot.shot_id
        # The renderer sends every mode except the exact "Full motion" value through the still
        # camera-path encoder. Labels such as "Useful mascot beat" must not evade still cadence.
        is_still = shot.mode.strip().casefold() != "full motion"
        contiguous = bool(
            current and abs(float(shot.start_sec) - float(current["end_sec"])) <= 0.05)
        if is_still and current and contiguous and current["asset_key"] == key:
            current["end_sec"] = shot.end_sec
            current["shot_ids"].append(shot.shot_id)
            continue
        if current:
            runs.append(current)
            current = None
        if is_still:
            current = {
                "asset_key": key,
                "start_sec": shot.start_sec,
                "end_sec": shot.end_sec,
                "shot_ids": [shot.shot_id],
            }
    if current:
        runs.append(current)
    for run in runs:
        run["duration_sec"] = round(float(run["end_sec"]) - float(run["start_sec"]), 3)

    longest = max((float(run["duration_sec"]) for run in runs), default=0.0)
    return {
        "pilot_unique_master_assets": len(unique_assets),
        "pilot_full_motion_assets": len(motion),
        "frontloaded_motion_assets": len(frontloaded),
        "max_consecutive_still_asset_sec": round(longest, 3),
        "consecutive_still_asset_runs": runs,
    }


def validate_directed_spec(payload: dict) -> dict:
    """Validate a directed contract without importing or calling any media provider."""
    try:
        spec = DirectedLongformSpec.model_validate(payload)
    except ValidationError as exc:
        issues = [
            _issue("schema_error", item["msg"], ".".join(str(part) for part in item["loc"]))
            for item in exc.errors()
        ]
        return {
            "schema_version": payload.get("schema_version") if isinstance(payload, dict) else None,
            "valid": False,
            "processing_allowed": False,
            "spec_sha256": "",
            "issues": issues,
            "errors": len(issues),
            "warnings": 0,
        }

    issues: list[dict] = []
    target = spec.target.duration_sec
    _ordered_timeline(spec.worlds, target=target, name="worlds", issues=issues)
    _ordered_timeline(spec.narration, target=target, name="narration", issues=issues)
    _ordered_timeline(spec.shots, target=target, name="shots", issues=issues)

    def duplicate_ids(values: list[str], code: str, path: str):
        seen, duplicates = set(), set()
        for value in values:
            if value in seen:
                duplicates.add(value)
            seen.add(value)
        for value in sorted(duplicates):
            issues.append(_issue(code, f"duplicate id: {value}", path))

    duplicate_ids([scene.scene_id for scene in spec.narration], "duplicate_scene_id", "narration")
    duplicate_ids([shot.shot_id for shot in spec.shots], "duplicate_shot_id", "shots")
    duplicate_ids([item.claim_id for item in spec.evidence], "duplicate_claim_id", "evidence")
    duplicate_ids([item.reference_id for item in spec.references],
                  "duplicate_reference_id", "references")

    worlds = {world.world_id for world in spec.worlds}
    world_prompts: dict[str, tuple[str, str]] = {}
    for world in spec.worlds:
        contract = (world.base_prompt, world.on_screen_label)
        prior = world_prompts.setdefault(world.world_id, contract)
        if prior != contract:
            issues.append(_issue(
                "world_definition_conflict",
                f"{world.world_id} is reused with a different prompt or label",
                f"worlds.{world.world_id}"))
    scenes = {scene.scene_id for scene in spec.narration}
    scene_by_id = {scene.scene_id: scene for scene in spec.narration}
    claims = {item.claim_id for item in spec.evidence}
    references = {item.reference_id for item in spec.references}
    used_claims: set[str] = set()

    def inside_world(world_id: str, start_sec: float, end_sec: float) -> bool:
        return any(
            world.world_id == world_id
            and start_sec + 0.05 >= world.start_sec
            and end_sec <= world.end_sec + 0.05
            for world in spec.worlds
        )

    def starts_inside_world(world_id: str, start_sec: float) -> bool:
        return any(
            world.world_id == world_id
            and world.start_sec - 0.05 <= start_sec < world.end_sec + 0.05
            for world in spec.worlds
        )

    for scene in spec.narration:
        if scene.world_id not in worlds:
            issues.append(_issue("unknown_world", scene.world_id,
                                 f"narration.{scene.scene_id}.world_id"))
        elif not starts_inside_world(scene.world_id, scene.start_sec):
            issues.append(_issue(
                "world_timeline_mismatch",
                f"{scene.world_id} is not active at {scene.start_sec:.2f}s",
                f"narration.{scene.scene_id}.world_id"))
        for claim_id in scene.claim_ids:
            used_claims.add(claim_id)
            if claim_id not in claims:
                issues.append(_issue("unknown_claim", claim_id,
                                     f"narration.{scene.scene_id}.claim_ids"))

    for shot in spec.shots:
        if shot.world_id not in worlds:
            issues.append(_issue("unknown_world", shot.world_id,
                                 f"shots.{shot.shot_id}.world_id"))
        elif not inside_world(shot.world_id, shot.start_sec, shot.end_sec):
            issues.append(_issue(
                "world_timeline_mismatch",
                f"{shot.world_id} does not cover {shot.start_sec:.2f}-{shot.end_sec:.2f}s",
                f"shots.{shot.shot_id}.world_id"))
        if shot.scene_id and shot.scene_id not in scenes:
            issues.append(_issue("unknown_scene", shot.scene_id,
                                 f"shots.{shot.shot_id}.scene_id"))
        elif shot.scene_id:
            scene = scene_by_id[shot.scene_id]
            if not scene.start_sec - 0.05 <= shot.start_sec < scene.end_sec + 0.05:
                issues.append(_issue(
                    "scene_timeline_mismatch",
                    f"{shot.scene_id} does not contain the shot start at {shot.start_sec:.2f}s",
                    f"shots.{shot.shot_id}.scene_id"))
        for claim_id in shot.claim_ids:
            used_claims.add(claim_id)
            if claim_id not in claims:
                issues.append(_issue("unknown_claim", claim_id,
                                     f"shots.{shot.shot_id}.claim_ids"))
        for reference_id in shot.reference_ids:
            if reference_id not in references:
                issues.append(_issue("unknown_reference", reference_id,
                                     f"shots.{shot.shot_id}.reference_ids"))

    asset_contracts: dict[str, tuple] = {}
    asset_members: dict[str, list[DirectedShot]] = {}
    prompt_assets: dict[str, set[str]] = {}
    for shot in spec.shots:
        asset_key = shot.asset_key.strip() or shot.shot_id
        master_prompt = shot.asset_prompt.strip() or shot.visual
        normalized_prompt = re.sub(r"\s+", " ", master_prompt.strip().casefold())
        prompt_assets.setdefault(normalized_prompt, set()).add(asset_key)
        if not shot.asset_key.strip():
            continue
        contract = (master_prompt, shot.world_id, tuple(sorted(shot.reference_ids)))
        prior = asset_contracts.setdefault(shot.asset_key, contract)
        asset_members.setdefault(shot.asset_key, []).append(shot)
        if prior != contract:
            issues.append(_issue(
                "asset_key_conflict",
                f"{shot.asset_key} groups shots with different master prompts/worlds/references",
                f"shots.{shot.shot_id}.asset_key"))
    for asset_key, members in asset_members.items():
        if len(members) > 1:
            missing = [shot.shot_id for shot in members if not shot.transformation.strip()]
            if missing:
                issues.append(_issue(
                    "asset_reuse_transformation_missing",
                    f"{asset_key} is reused but lacks an explicit transformation on: "
                    + ", ".join(missing),
                    f"shots.{missing[0]}.transformation"))
    for asset_keys in prompt_assets.values():
        if len(asset_keys) > 1:
            issues.append(_issue(
                "duplicate_master_composition",
                "Different asset keys reuse the same master-image prompt: "
                + ", ".join(sorted(asset_keys))
                + ". Reuse one key for an intentional callback or author a materially new "
                  "composition.",
                "shots"))

    unresolved_claims = claims - used_claims
    coverage = 100.0 if not claims else 100.0 * (len(claims) - len(unresolved_claims)) / len(claims)
    if coverage + 1e-6 < spec.acceptance.evidence_coverage_pct:
        issues.append(_issue(
            "evidence_coverage",
            f"{coverage:.1f}% of evidence claims are mapped; "
            f"{spec.acceptance.evidence_coverage_pct:.1f}% required",
            "evidence"))
    for claim in spec.evidence:
        if claim.license.strip().casefold() in _UNRESOLVED_LICENSES:
            issues.append(_issue("unresolved_source_license", claim.claim_id,
                                 f"evidence.{claim.claim_id}.license"))
    for reference in spec.references:
        if reference.license.strip().casefold() in _UNRESOLVED_LICENSES:
            issues.append(_issue("unresolved_reference_license", reference.reference_id,
                                 f"references.{reference.reference_id}.license"))
        if not re.match(r"^[\w.+-]+/[\w.+-]+$", reference.mime_type):
            issues.append(_issue("invalid_mime_type", reference.mime_type,
                                 f"references.{reference.reference_id}.mime_type"))
        if not reference.sha256:
            issues.append(_issue("missing_reference_sha256", reference.reference_id,
                                 f"references.{reference.reference_id}.sha256"))
        elif not re.fullmatch(r"[0-9a-fA-F]{64}", reference.sha256):
            issues.append(_issue("invalid_reference_sha256", reference.reference_id,
                                 f"references.{reference.reference_id}.sha256"))

    pilot_shots = [shot for shot in spec.shots if shot.start_sec < spec.target.pilot_end_sec]
    if len(pilot_shots) < spec.acceptance.pilot_min_visual_states:
        issues.append(_issue(
            "pilot_visual_states",
            f"pilot has {len(pilot_shots)} visual states; "
            f"{spec.acceptance.pilot_min_visual_states} required",
            "shots"))
    for shot in pilot_shots:
        hold = shot.end_sec - shot.start_sec
        if hold + 1e-6 < spec.acceptance.min_shot_sec:
            issues.append(_issue("pilot_shot_too_short",
                                 f"{shot.shot_id} holds {hold:.2f}s; "
                                 f"minimum is {spec.acceptance.min_shot_sec:.2f}s",
                                 f"shots.{shot.shot_id}"))
    for shot in spec.shots:
        hold = shot.end_sec - shot.start_sec
        if (shot.mode.strip().casefold() != "full motion"
                and hold > spec.acceptance.max_unchanged_hold_sec):
            issues.append(_issue(
                "unchanged_hold_too_long",
                f"{shot.shot_id} holds a still for {hold:.2f}s; "
                f"maximum is {spec.acceptance.max_unchanged_hold_sec:.2f}s",
                f"shots.{shot.shot_id}"))
        if shot.mode.strip().casefold() == "full motion":
            expected = spec.acceptance.full_motion_duration_sec
            tolerance = spec.acceptance.full_motion_duration_tolerance_sec
            if abs(hold - expected) > tolerance + 1e-6:
                issues.append(_issue(
                    "full_motion_duration_mismatch",
                    f"{shot.shot_id} plans {hold:.2f}s of generated motion; the contract "
                    f"requires {expected:.2f}s ± {tolerance:.2f}s",
                    f"shots.{shot.shot_id}"))

    visual_metrics = pilot_visual_metrics(spec)
    if (visual_metrics["pilot_unique_master_assets"]
            < spec.acceptance.pilot_min_unique_master_assets):
        issues.append(_issue(
            "pilot_unique_master_assets",
            f"pilot has {visual_metrics['pilot_unique_master_assets']} genuinely distinct "
            f"master images; {spec.acceptance.pilot_min_unique_master_assets} required",
            "shots"))
    for run in visual_metrics["consecutive_still_asset_runs"]:
        if (run["duration_sec"]
                > spec.acceptance.max_consecutive_still_asset_sec + 1e-6):
            issues.append(_issue(
                "consecutive_still_asset_too_long",
                f"{run['asset_key']} remains the source composition for "
                f"{run['duration_sec']:.2f}s across {', '.join(run['shot_ids'])}; maximum "
                f"is {spec.acceptance.max_consecutive_still_asset_sec:.2f}s",
                f"shots.{run['shot_ids'][0]}.asset_key"))
    if (visual_metrics["frontloaded_motion_assets"]
            < spec.acceptance.frontloaded_motion_count):
        issues.append(_issue(
            "frontloaded_motion_missing",
            f"pilot has {visual_metrics['frontloaded_motion_assets']} full-motion shots before "
            f"{spec.acceptance.frontloaded_motion_window_sec:.2f}s; "
            f"{spec.acceptance.frontloaded_motion_count} required",
            "shots"))

    cost = _cost_estimate(spec)
    pilot_cost = _cost_estimate(spec, end_sec=spec.target.pilot_end_sec)
    if cost["unique_master_assets"] > spec.acceptance.max_unique_master_assets:
        issues.append(_issue(
            "too_many_unique_master_assets",
            f"{cost['unique_master_assets']} unique masters exceed the cap of "
            f"{spec.acceptance.max_unique_master_assets}; assign shared asset_key values for "
            "intentional reframes/reuse",
            "shots"))
    if cost["estimated_total_usd"] > spec.target.max_cost_usd:
        issues.append(_issue(
            "cost_cap_exceeded",
            f"estimated ${cost['estimated_total_usd']:.2f} exceeds "
            f"${spec.target.max_cost_usd:.2f}",
            "target.max_cost_usd"))

    bolt_count = sum(
        1 for shot in spec.shots
        if "bolt" in shot.mode.casefold() or any("bolt" in label.casefold() for label in shot.labels)
    )
    if bolt_count < spec.acceptance.min_useful_bolt_appearances:
        issues.append(_issue("bolt_appearance_minimum",
                             f"{bolt_count} planned; at least "
                             f"{spec.acceptance.min_useful_bolt_appearances} required", "shots"))
    if bolt_count > spec.acceptance.max_bolt_appearances:
        issues.append(_issue("bolt_appearance_maximum",
                             f"{bolt_count} planned; at most "
                             f"{spec.acceptance.max_bolt_appearances} allowed", "shots"))
    if (spec.acceptance.planned_bolt_appearances is not None
            and bolt_count != spec.acceptance.planned_bolt_appearances):
        issues.append(_issue(
            "bolt_appearance_plan",
            f"{bolt_count} planned; the contract requires exactly "
            f"{spec.acceptance.planned_bolt_appearances}", "shots"))

    normalized = spec.model_dump(mode="json")
    errors = sum(item["severity"] == "error" for item in issues)
    warnings = sum(item["severity"] == "warning" for item in issues)
    return {
        "schema_version": SCHEMA_VERSION,
        "valid": errors == 0,
        "processing_allowed": errors == 0,
        "spec_sha256": spec_sha256(normalized),
        "title": spec.title,
        "duration_sec": target,
        "pilot_end_sec": spec.target.pilot_end_sec,
        "scene_count": len(spec.narration),
        "shot_count": len(spec.shots),
        "pilot_visual_states": len(pilot_shots),
        **visual_metrics,
        "evidence_coverage_pct": round(coverage, 1),
        "planned_bolt_appearances": bolt_count,
        "cost_estimate": cost,
        "pilot_cost_estimate": pilot_cost,
        "issues": issues,
        "errors": errors,
        "warnings": warnings,
        "normalized_spec": normalized,
    }


def authorize_processing(payload: dict, *, expected_sha256: str,
                         authorize_paid: bool) -> tuple[DirectedLongformSpec, dict]:
    """Revalidate at the paid boundary and bind approval to the exact JSON bytes."""
    report = validate_directed_spec(payload)
    if not report.get("valid"):
        raise DirectedValidationError("directed spec failed validation")
    if not expected_sha256 or expected_sha256 != report["spec_sha256"]:
        raise DirectedValidationError(
            "spec hash does not match the validated contract; validate the edited JSON again")
    if authorize_paid is not True:
        raise DirectedValidationError("explicit paid-generation authorization is required")
    return DirectedLongformSpec.model_validate(report["normalized_spec"]), report


def write_validation_artifacts(report: dict, out_dir: str | Path) -> dict:
    """Persist the immutable input and validation decision before processing starts."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    spec_path = out / "directed_spec.json"
    report_path = out / "validation_report.json"
    spec_path.write_text(
        json.dumps(report.get("normalized_spec") or {}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    public_report = {key: value for key, value in report.items() if key != "normalized_spec"}
    report_path.write_text(json.dumps(public_report, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"directed_spec_path": str(spec_path), "validation_report_path": str(report_path)}


def json_schema() -> dict:
    return DirectedLongformSpec.model_json_schema()


def starter_template() -> dict:
    """Return a complete, downloadable contract starter that intentionally cannot spend yet."""
    shots = []
    durations = [5.0, 5.0] + [35.0 / 13.0] * 13
    cursor = 0.0
    for index, duration in enumerate(durations):
        start = cursor
        end = 45.0 if index == len(durations) - 1 else start + duration
        cursor = end
        shots.append({
            "shot_id": f"shot_{index + 1:03d}",
            "start_sec": round(start, 4),
            "end_sec": round(end, 4),
            "visual": f"Replace with the visible composition for pilot shot {index + 1}",
            "mode": "Full motion" if index < 2 else "Still + camera path",
            "world_id": "primary_world",
            "scene_id": "scene_001",
            "asset_key": f"master_{index + 1:03d}",
            "asset_prompt": f"Replace with the generation prompt for master {index + 1}",
            "transformation": "five-second generated action" if index < 2 else "slow push",
            "claim_ids": ["F01"] if index == 5 else [],
            "reference_ids": ["REF01"] if index == 5 else [],
            "overlay_text": "",
            "labels": ["useful_bolt"] if index == 3 else [],
        })
    acceptance = DirectedAcceptance().model_dump(mode="json")
    acceptance.update({
        "pilot_min_visual_states": 15,
        "pilot_min_unique_master_assets": 15,
        "max_unchanged_hold_sec": 3.0,
        "max_consecutive_still_asset_sec": 3.0,
        "full_motion_duration_sec": 5.0,
        "frontloaded_motion_count": 2,
        "frontloaded_motion_window_sec": 15.0,
    })
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": "replace-with-project-id",
        "title": "Replace With Video Title",
        "negative_prompt": "malformed text, logos, watermarks, anatomy errors",
        "target": {
            "duration_sec": 45.0, "pilot_end_sec": 45.0, "format": "landscape",
            "voice": "echo", "max_cost_usd": 5.0,
        },
        "acceptance": acceptance,
        "worlds": [{
            "world_id": "primary_world", "start_sec": 0.0, "end_sec": 45.0,
            "base_prompt": "Replace with the consistent visual-world prompt",
            "on_screen_label": "",
        }],
        "narration": [{
            "scene_id": "scene_001", "start_sec": 0.0, "end_sec": 45.0,
            "narration": "Replace with the exact operator-authored narration for this window.",
            "world_id": "primary_world", "story_role": "hook", "claim_ids": ["F01"],
        }],
        "shots": shots,
        "evidence": [{
            "claim_id": "F01", "claim": "Replace with a factual claim",
            "source_uri": "https://replace-with-source.example",
            "qualification": "Replace with the exact allowed wording",
            "license": "unresolved",
        }],
        "references": [{
            "reference_id": "REF01", "uri": "https://replace-with-reference.example",
            "sha256": "", "mime_type": "image/jpeg", "license": "unresolved",
            "origin": "Replace with the original archive/provider",
        }],
        "prohibited_claims": ["Replace with claims the renderer must never introduce"],
    }
