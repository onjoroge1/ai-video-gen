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


def _text(value) -> str:
    return str(value or "").strip()


def _measured(checks: dict, key: str) -> float | None:
    """A numeric check, or None when it was never computed.

    `float(checks.get(key) or default)` cannot tell absent from zero, and both readings were
    wrong in opposite directions: an absent attention gap became 999 seconds on a 75-second video,
    while an absent exposition length became a flawless 0s. Absent is its own answer.
    """
    if key not in checks:
        return None
    value = checks.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _component(name: str, score: int, maximum: int, notes: list[str],
               unmeasured_points: int = 0) -> dict:
    # `assessed_max` is what this component could actually be scored out of. An axis nobody
    # measured is subtracted from the denominator rather than counted as a loss, so an unwired
    # validator cannot look like a bad video.
    return {"name": name, "score": int(score), "max": maximum,
            "assessed_max": max(0, maximum - unmeasured_points), "notes": notes}


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

    # Metrics the validator for this lane never produced. They must not be scored: the old code
    # read them with `or` defaults, so an absent attention gap became a 999-second reading (-8) and
    # an absent exposition length became a perfect 0s (+5). Three defaults penalised and two
    # rewarded, for a total of -18/+10 awarded to things nobody measured. An unmeasured axis earns
    # nothing, costs nothing, and is named in the report.
    unmeasured: list[str] = []

    opening = 0
    opening_notes = []
    if script.get("_story_contract"):
        opening += 5
    else:
        opening_notes.append("missing packaging/story contract")
    # The causal lane speaks a different grammar. Its engines all open on `setup` by contract and
    # `cold_consequence` is not one of its roles at all, so this test could never pass there -- a
    # permanent -5 on every illustrated video, awarded for obeying a different contract. Two
    # contracts disagree about what an opening is; scoring one against the other is not a
    # measurement. Which opening a causal story should have is an editorial question, so it is
    # left unassessed rather than silently decided here.
    causal_lane = _text(checks.get("retention_role_vocabulary")) == "causal"
    if causal_lane:
        unmeasured.append("opening_is_cold_consequence")
        opening_notes.append(
            "opening-beat shape not assessed: this lane opens on `setup` by engine contract")
    elif scenes and scenes[0].get("story_role") == "cold_consequence":
        opening += 5
    else:
        opening_notes.append("first beat is not a visible consequence")
    if "subject_unclear_by_5s" not in warnings:
        opening += 5
    else:
        opening_notes.append("subject may be unclear by five seconds")
    if "prediction_scenes" not in checks:
        unmeasured.append("prediction_scenes")
        opening_notes.append("prediction gate was not measured on this lane")
    elif "late_first_prediction" not in errors and checks.get("prediction_scenes"):
        opening += 5
    else:
        opening_notes.append("prediction gate is missing or late")
    if "answer_scenes" not in checks:
        unmeasured.append("answer_scenes")
        opening_notes.append("first payoff was not measured on this lane")
    elif "late_first_payoff" not in errors and checks.get("answer_scenes"):
        opening += 5
    else:
        opening_notes.append("first useful payoff is missing or late")
    components.append(_component("Opening contract", opening, 25, opening_notes,
                                 unmeasured_points=5 * sum(
                                     1 for key in ("opening_is_cold_consequence",
                                                   "prediction_scenes", "answer_scenes")
                                     if key in unmeasured)))

    narrative = 0
    narrative_notes = []
    gap = _measured(checks, "max_attention_gap_sec")
    if gap is None:
        unmeasured.append("max_attention_gap_sec")
        narrative_notes.append("attention gap was not measured on this lane")
    else:
        narrative += 8 if gap <= 45 else (4 if gap <= 55 else 0)
        if gap > 45:
            narrative_notes.append(f"longest attention gap is {gap:.1f}s")
    expo = _measured(checks, "max_exposition_block_sec")
    if expo is None:
        unmeasured.append("max_exposition_block_sec")
        narrative_notes.append("exposition block length was not measured on this lane")
    else:
        narrative += 5 if expo <= 15 else (3 if expo <= 18 else 0)
        if expo > 15:
            narrative_notes.append(f"longest exposition block is {expo:.1f}s")
    if "unresolved_loops" not in checks:
        unmeasured.append("unresolved_loops")
        narrative_notes.append("open-loop resolution was not measured on this lane")
    elif not checks.get("unresolved_loops"):
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
    components.append(_component(
        "Narrative propulsion", narrative, 25, narrative_notes,
        unmeasured_points=(8 if "max_attention_gap_sec" in unmeasured else 0)
        + (5 if "max_exposition_block_sec" in unmeasured else 0)
        + (5 if "unresolved_loops" in unmeasured else 0)))

    visual = 0
    visual_notes = []
    avg_still = float(shot_metrics.get("avg_still_seconds") or 0)
    min_shot = float(shot_metrics.get("min_shot_seconds") or 0)
    sub_min = int(shot_metrics.get("sub_min_shot_count") or 0)
    semantic_sync = float(shot_metrics.get("semantic_sync_ratio", 0))
    meaningful_cuts = float(shot_metrics.get("meaningful_cut_ratio", 0))
    motion_sync = float(shot_metrics.get("motion_sync_ratio", 0))
    same_source_hard = int(shot_metrics.get("same_source_hard_cut_count") or 0)
    # A calm continuous camera path may legitimately run longer than the old 3.2s
    # timer. Reward an intentional range without rewarding frantic over-cutting.
    if 1.5 <= avg_still <= 7.5:
        visual += 4
    else:
        visual_notes.append(
            f"average continuous still is {avg_still:.2f}s; target is 1.5–7.5s")
    if min_shot >= 1.5 and sub_min == 0:
        visual += 4
    else:
        visual_notes.append(
            f"{sub_min} shot(s) are under 1.5s; minimum is {min_shot:.2f}s")
    if semantic_sync >= 0.9:
        visual += 4
    elif semantic_sync >= 0.75:
        visual += 2
        visual_notes.append(
            f"only {semantic_sync:.0%} of cuts align to narration phrases")
    else:
        visual_notes.append(
            f"semantic cut alignment is only {semantic_sync:.0%}")
    if meaningful_cuts >= 0.9 and same_source_hard == 0:
        visual += 4
    elif meaningful_cuts >= 0.75 and same_source_hard == 0:
        visual += 2
        visual_notes.append(
            f"only {meaningful_cuts:.0%} of cuts add new information")
    else:
        visual_notes.append(
            f"meaningful-cut ratio is {meaningful_cuts:.0%}; "
            f"{same_source_hard} same-source hard cut(s)")
    if int(shot_metrics.get("broll_clause_count") or 0) > 0:
        visual += 2
    else:
        visual_notes.append("no clause-specific B-roll appears in this cut")
    if motion_sync >= 0.9:
        visual += 2
    else:
        visual_notes.append(
            f"generated motion aligns to the spoken action only {motion_sync:.0%} of the time")
    components.append(_component("Visual continuity & semantic sync", visual, 20, visual_notes))

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
    # Grade on what could actually be assessed. Keeping a 100-point denominator while an axis was
    # never measured is the same error as the 999-second sentinel, one step later: it turns a
    # missing validator into a low grade for the video. `score` stays the raw sum so nothing is
    # inflated; the grade is taken from the percentage of the assessed maximum.
    assessed_max = sum(c["assessed_max"] for c in components)
    nominal_max = sum(c["max"] for c in components)
    graded = round(100.0 * total / assessed_max) if assessed_max else 0
    hard_failures = []
    if sub_min:
        hard_failures.append("sub_minimum_shots")
    if semantic_sync < 0.70:
        hard_failures.append("semantic_sync")
    if same_source_hard:
        hard_failures.append("same_source_jump_cuts")
    if hard_failures:
        graded = min(graded, 69)
    if graded >= 90:
        grade, label = "A", "Exceptional readiness"
    elif graded >= 80:
        grade, label = "B", "Strong readiness"
    elif graded >= 70:
        grade, label = "C", "Shippable; improve weak axes"
    elif graded >= 60:
        grade, label = "D", "Weak; revise before full render"
    else:
        grade, label = "F", "Reject before full render"
    if unmeasured:
        label += f" (graded on {assessed_max}/{nominal_max} points; "
        label += f"unmeasured: {', '.join(sorted(set(unmeasured)))})"
    return {
        "version": 2,
        "name": "Retention Readiness Score",
        "disclaimer": "Editorial readiness score, not a prediction of actual YouTube retention.",
        "score": graded,
        "raw_score": total,
        "assessed_max": assessed_max,
        "nominal_max": nominal_max,
        "unmeasured": sorted(set(unmeasured)),
        "grade": grade,
        "label": label,
        "passed": graded >= 70 and not hard_failures,
        "hard_failures": hard_failures,
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


def grade_observed_retention(
    duration_sec: float,
    average_percentage_viewed: float,
    *,
    retention_30s: float | None = None,
    views: int | None = None,
) -> dict:
    """Grade real YouTube outcomes with runtime-aware APV bands.

    Unlike RRS, this consumes post-publish analytics. The bands are an internal
    comparison scale to calibrate against this channel—not a universal YouTube
    benchmark or an algorithm guarantee.
    """
    duration = float(duration_sec)
    apv = float(average_percentage_viewed)
    if duration < 300:
        bands = ((55, "A"), (45, "B"), (35, "C"), (25, "D"))
    elif duration <= 600:
        bands = ((50, "A"), (40, "B"), (30, "C"), (20, "D"))
    else:
        bands = ((45, "A"), (35, "B"), (25, "C"), (18, "D"))
    grade = next((letter for threshold, letter in bands if apv >= threshold), "F")
    order = "ABCDF"
    if retention_30s is not None:
        hold = float(retention_30s)
        cap = "F" if hold < 40 else ("D" if hold < 50 else ("C" if hold < 60 else "A"))
        grade = order[max(order.index(grade), order.index(cap))]
    labels = {"A": "Exceptional", "B": "Strong", "C": "Competitive",
              "D": "Weak", "F": "Critical collapse"}
    return {
        "name": "Observed Retention Grade",
        "grade": grade,
        "label": labels[grade],
        "duration_sec": round(duration, 1),
        "average_percentage_viewed": round(apv, 1),
        "retention_30s": None if retention_30s is None else round(float(retention_30s), 1),
        "confidence": "low" if views is not None and views < 100 else "directional",
        "note": ("Internal runtime-aware outcome scale; calibrate bands as the channel accumulates videos."
                 + (" Fewer than 100 views: treat this grade as low-confidence." if views is not None and views < 100 else "")),
    }
