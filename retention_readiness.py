"""Transparent, provider-free readiness scoring for long-form retention.

This is an editorial quality score, not a forecast of YouTube audience
retention. Actual retention can only be measured after publication.
"""

from __future__ import annotations

import json
import os


ATTENTION_ROLES = {
    "cold_consequence", "prediction_gate", "payoff", "rehook", "reversal",
    "branch", "false_relief", "final_escalation", "final_payoff",
}


def build_audio_cues(scenes: list[dict], durations: list[float]) -> list[dict]:
    """Place restrained editorial cues at story turns, never on every cut."""
    cues, cursor, last_sound = [], 0.0, -99.0
    for scene, duration in zip(scenes, durations):
        role = str(scene.get("story_role") or "").lower()
        cue = None
        if role == "prediction_gate":
            cue = "prediction_tick"
        elif role in {"payoff", "reversal", "final_payoff"}:
            cue = "impact"
        elif role in {"false_relief", "rehook"}:
            cue = "music_drop"
        if cue and (cue == "music_drop" or cursor - last_sound >= 7.0):
            event = {"time_sec": round(cursor + min(0.25, duration * 0.1), 2),
                     "type": cue, "story_role": role}
            cues.append(event)
            if cue != "music_drop":
                last_sound = cursor
        cursor += float(duration)
    return cues


def _component(name: str, score: int, maximum: int, notes: list[str]) -> dict:
    return {"name": name, "score": int(score), "max": maximum, "notes": notes}


def score_retention_readiness(
    script: dict,
    validation: dict,
    shot_metrics: dict,
    audio_cues: list[dict],
    *,
    preview: dict | None = None,
) -> dict:
    """Return a 0-100 Retention Readiness Score (RRS) and an auditable rubric."""
    scenes = script.get("scenes") or []
    checks = validation.get("checks") or {}
    errors = {x.get("code") for x in validation.get("errors") or []}
    warnings = {x.get("code") for x in validation.get("warnings") or []}
    components = []

    opening = 0
    opening_notes = []
    if script.get("_story_contract"):
        opening += 5
    else:
        opening_notes.append("missing packaging/story contract")
    if scenes and scenes[0].get("story_role") == "cold_consequence":
        opening += 5
    else:
        opening_notes.append("first beat is not a visible consequence")
    if "subject_unclear_by_5s" not in warnings:
        opening += 5
    else:
        opening_notes.append("subject may be unclear by five seconds")
    if "late_first_prediction" not in errors and checks.get("prediction_scenes"):
        opening += 5
    else:
        opening_notes.append("prediction gate is missing or late")
    if "late_first_payoff" not in errors and checks.get("answer_scenes"):
        opening += 5
    else:
        opening_notes.append("first useful payoff is missing or late")
    components.append(_component("Opening contract", opening, 25, opening_notes))

    narrative = 0
    narrative_notes = []
    gap = float(checks.get("max_attention_gap_sec") or 999)
    narrative += 8 if gap <= 45 else (4 if gap <= 55 else 0)
    if gap > 45:
        narrative_notes.append(f"longest attention gap is {gap:.1f}s")
    expo = float(checks.get("max_exposition_block_sec") or 0)
    narrative += 5 if expo <= 15 else (3 if expo <= 18 else 0)
    if expo > 15:
        narrative_notes.append(f"longest exposition block is {expo:.1f}s")
    if not checks.get("unresolved_loops"):
        narrative += 5
    else:
        narrative_notes.append("one or more promised questions remain open")
    if "misplaced_peak" not in errors:
        narrative += 3
    else:
        narrative_notes.append("peak is outside the 55–82% window")
    if "missing_final_payoff" not in errors and "early_final_payoff" not in errors:
        narrative += 4
    else:
        narrative_notes.append("final title payoff is missing or early")
    components.append(_component("Narrative propulsion", narrative, 25, narrative_notes))

    visual = 0
    visual_notes = []
    avg_still = float(shot_metrics.get("avg_still_seconds") or 0)
    max_still = float(shot_metrics.get("max_still_seconds") or 0)
    visual += 8 if 0 < avg_still <= 3.2 else (5 if avg_still <= 3.8 else (2 if avg_still <= 4.5 else 0))
    if not avg_still or avg_still > 3.2:
        visual_notes.append(f"average still is {avg_still:.2f}s; target is ≤3.2s")
    if 0 < max_still <= 4.5:
        visual += 4
    else:
        visual_notes.append(f"maximum still is {max_still:.2f}s; ceiling is 4.5s")
    scene_count = max(1, len(scenes))
    shots_per_scene = float(shot_metrics.get("shot_count") or 0) / scene_count
    visual += 4 if shots_per_scene >= 1.5 else (2 if shots_per_scene >= 1.2 else 0)
    if shots_per_scene < 1.5:
        visual_notes.append(f"only {shots_per_scene:.2f} shots per narrative scene")
    if int(shot_metrics.get("alternate_shot_count") or 0) > 0:
        visual += 4
    else:
        visual_notes.append("no alternate source angle appears in this cut")
    components.append(_component("Visual pacing", visual, 20, visual_notes))

    cue_types = {c.get("type") for c in audio_cues}
    turns = sum(1 for s in scenes if s.get("story_role") in ATTENTION_ROLES)
    cue_coverage = len(audio_cues) / max(1, turns)
    audio = (8 if cue_coverage >= 0.35 else (4 if cue_coverage >= 0.2 else 0))
    audio += 4 if len(cue_types) >= 2 else (2 if cue_types else 0)
    times = [float(c.get("time_sec") or 0) for c in audio_cues if c.get("type") != "music_drop"]
    uncluttered = all(b - a >= 6 for a, b in zip(times, times[1:]))
    audio += 3 if uncluttered else 0
    audio_notes = []
    if cue_coverage < 0.35:
        audio_notes.append(f"audio cues cover {cue_coverage:.0%} of attention turns")
    if len(cue_types) < 2:
        audio_notes.append("audio cue palette lacks contrast")
    if not uncluttered:
        audio_notes.append("sound cues are clustered too closely")
    components.append(_component("Audio rhythm", audio, 15, audio_notes))

    contract = script.get("_story_contract") or {}
    packaging = 0
    packaging_notes = []
    if script.get("title") and script.get("hook"):
        packaging += 4
    else:
        packaging_notes.append("title or spoken hook is missing")
    if contract.get("visual_promise") or contract.get("thumbnail_promise"):
        packaging += 3
    else:
        packaging_notes.append("thumbnail/visual promise is missing")
    if "missing_final_payoff" not in errors:
        packaging += 3
    else:
        packaging_notes.append("ending does not explicitly repay the title")
    components.append(_component("Packaging/payoff alignment", packaging, 10, packaging_notes))

    preview = preview or {}
    technical = 0
    technical_notes = []
    if preview.get("decodable"):
        technical += 3
    else:
        technical_notes.append("rendered first-minute preview was not verified")
    preview_duration = float(preview.get("duration_sec") or 0)
    if preview_duration >= min(55.0, float(preview.get("target_sec") or 60.0) * 0.9):
        technical += 2
    else:
        technical_notes.append(f"opening preview is only {preview_duration:.1f}s")
    components.append(_component("Technical delivery", technical, 5, technical_notes))

    total = sum(c["score"] for c in components)
    if total >= 90:
        grade, label = "A", "Exceptional readiness"
    elif total >= 80:
        grade, label = "B", "Strong readiness"
    elif total >= 70:
        grade, label = "C", "Shippable; improve weak axes"
    elif total >= 60:
        grade, label = "D", "Weak; revise before full render"
    else:
        grade, label = "F", "Reject before full render"
    return {
        "version": 1,
        "name": "Retention Readiness Score",
        "disclaimer": "Editorial readiness score, not a prediction of actual YouTube retention.",
        "score": total,
        "grade": grade,
        "label": label,
        "passed": total >= 70,
        "components": components,
        "shot_metrics": shot_metrics,
        "audio_cues": audio_cues,
        "preview": preview,
    }


def write_readiness_report(report: dict, out_dir: str) -> tuple[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    text_path = os.path.join(out_dir, "retention_readiness.txt")
    json_path = os.path.join(out_dir, "retention_readiness.json")
    lines = [
        f"RETENTION READINESS SCORE — {report['score']}/100 ({report['grade']})",
        report["label"], report["disclaimer"], "",
    ]
    for item in report.get("components") or []:
        lines.append(f"{item['name']}: {item['score']}/{item['max']}")
        lines.extend(f"- {note}" for note in item.get("notes") or ["Pass"])
        lines.append("")
    with open(text_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    return text_path, json_path
