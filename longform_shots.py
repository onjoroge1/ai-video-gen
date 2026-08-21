"""Deterministic shot planning for long-form explainers.

The script's scenes are narrative beats, not editing cuts.  This module expands
each narrated beat into short visual shots without changing narration timing or
making provider calls.  That separation lets the renderer cut stills quickly
while preserving a full five seconds for paid image-to-video clips.
"""

from __future__ import annotations

import math


RETENTION_ROLES = {
    "cold_consequence", "payoff", "prediction_gate", "rehook", "reversal",
    "false_relief", "final_escalation", "final_payoff", "resonant_end",
}
EVIDENCE_ROLES = {"mechanism", "evidence", "proof", "explanation"}
MOTIONS = ("kenburns_in", "pan_right", "zoom_tl", "pan_left", "zoom_br", "kenburns_out")


def select_alternate_image_indices(scenes: list[dict], max_images: int = 18) -> frozenset[int]:
    """Choose a bounded set of high-value beats for a genuinely new camera view.

    Most extra cuts are inexpensive reframes of the master image.  Retention
    turns earn an alternate generated image so visual cadence is not merely a
    sequence of crops from the same source.
    """
    if max_images <= 0:
        return frozenset()
    ranked = []
    for i, scene in enumerate(scenes):
        role = str(scene.get("story_role") or "").lower()
        words = len(str(scene.get("narration") or "").split())
        priority = 0 if role in RETENTION_ROLES else (1 if words >= 18 else 2)
        ranked.append((priority, i))
    # Keep the alternate-image budget proportional on short videos and bounded
    # on 20-minute videos. The opener is always eligible.
    target = min(max_images, max(1, round(len(scenes) * 0.18))) if scenes else 0
    return frozenset(i for _, i in sorted(ranked)[:target])


def _target_still_seconds(role: str) -> float:
    if role in RETENTION_ROLES:
        return 2.35
    if role in EVIDENCE_ROLES:
        return 3.5
    return 3.0


def compile_scene_shots(
    scene: dict,
    duration: float,
    scene_index: int,
    *,
    has_i2v: bool = False,
    has_alternate: bool = False,
    i2v_seconds: float = 5.0,
) -> list[dict]:
    """Expand one narrated scene into timed visual shots.

    Invariants:
    - shot durations sum exactly to the narration duration;
    - an available i2v clip receives five seconds when the scene is long enough;
    - ordinary stills target 2.35-3.5 seconds and never exceed 4.5 seconds;
    - adjacent shots use different motion presets.
    """
    duration = max(0.05, float(duration))
    role = str(scene.get("story_role") or "").lower()
    shots: list[dict] = []
    remaining = duration

    if has_i2v:
        motion_dur = min(float(i2v_seconds), remaining)
        shots.append({
            "kind": "i2v", "source": "master", "duration": round(motion_dur, 3),
            "motion": "generated_motion", "story_role": role,
        })
        remaining -= motion_dur

    if remaining > 0.025:
        target = _target_still_seconds(role)
        count = max(1, math.ceil(remaining / target))
        # Splitting into equal lengths prevents a weak sub-second orphan shot.
        each = remaining / count
        for j in range(count):
            source = "alternate" if has_alternate and (j + len(shots)) % 2 else "master"
            motion = MOTIONS[(scene_index * 2 + j + len(shots)) % len(MOTIONS)]
            shots.append({
                "kind": "still", "source": source, "duration": round(each, 3),
                "motion": motion, "story_role": role,
            })

    # Absorb rounding error in the final shot. This makes ffmpeg timelines exact.
    drift = duration - sum(float(s["duration"]) for s in shots)
    shots[-1]["duration"] = round(float(shots[-1]["duration"]) + drift, 3)
    return shots


def compile_shot_plan(
    scenes: list[dict],
    durations: list[float],
    *,
    i2v_indices: set[int] | frozenset[int] = frozenset(),
    alternate_indices: set[int] | frozenset[int] = frozenset(),
    i2v_seconds: float = 5.0,
) -> list[list[dict]]:
    if len(scenes) != len(durations):
        raise ValueError("scenes and durations must have the same length")
    return [
        compile_scene_shots(
            scene, durations[i], i, has_i2v=i in i2v_indices,
            has_alternate=i in alternate_indices, i2v_seconds=i2v_seconds,
        )
        for i, scene in enumerate(scenes)
    ]


def shot_plan_metrics(plan: list[list[dict]]) -> dict:
    shots = [shot for scene in plan for shot in scene]
    stills = [float(s["duration"]) for s in shots if s["kind"] == "still"]
    motion = [float(s["duration"]) for s in shots if s["kind"] == "i2v"]
    alternates = sum(1 for s in shots if s.get("source") == "alternate")
    return {
        "shot_count": len(shots),
        "still_shot_count": len(stills),
        "i2v_shot_count": len(motion),
        "alternate_shot_count": alternates,
        "avg_still_seconds": round(sum(stills) / len(stills), 2) if stills else 0.0,
        "max_still_seconds": round(max(stills), 2) if stills else 0.0,
        "i2v_seconds": round(sum(motion), 2),
    }
