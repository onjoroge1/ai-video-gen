"""Deterministic story-contract validation for long-form explainer scripts.

The language model plans the story; this module checks the resulting structure without
asking that same model whether it followed its own instructions.  It intentionally has no
provider dependencies so it can run before images, TTS, or video generation spend begins.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any


WORDS_PER_SECOND = 2.64
ATTENTION_ROLES = {
    "cold_consequence", "prediction_gate", "payoff", "rehook", "reversal", "branch",
    "false_relief", "final_escalation", "final_payoff",
}
ANSWER_ROLES = {"payoff", "reversal", "branch", "final_payoff"}
EXPOSITION_ROLES = {"rules", "mechanism"}

_SUBJECT_STOP = {
    "a", "an", "and", "are", "at", "be", "can", "could", "did", "do", "does", "for",
    "from", "had", "has", "have", "how", "if", "in", "is", "it", "of", "on", "or",
    "really", "the", "then", "this", "to", "was", "were", "what", "when", "where", "who",
    "why", "will", "with", "would", "you", "your", "happen", "happens", "explained",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W\d_]+(?:['-][^\W\d_]+)*", text or "", re.UNICODE)


def _duration(text: str) -> float:
    return max(1.0, len(_words(text)) / WORDS_PER_SECOND)


def _timeline(scenes: list[dict]) -> tuple[list[float], list[float], float]:
    starts: list[float] = []
    durations: list[float] = []
    cursor = 0.0
    for scene in scenes:
        starts.append(cursor)
        dur = _duration(_text(scene.get("narration")))
        durations.append(dur)
        cursor += dur
    return starts, durations, cursor


def build_story_contract(
    question: str,
    plan: dict,
    beats: list[dict],
    scenes: list[dict],
    target_duration_sec: int,
) -> dict:
    """Persist the planner's promises in a stable, inspectable contract."""
    starts, _, natural_runtime = _timeline(scenes)
    compact_beats = []
    opened: list[dict] = []
    for index, beat in enumerate(beats):
        n = index + 1
        opens = _text(beat.get("opens_loop"))
        closes = _text(beat.get("closes_loop"))
        item = {
            "n": n,
            "pct": int(beat.get("pct") or round(100 * index / max(1, len(beats) - 1))),
            "role": _text(beat.get("role")) or "beat",
            "beat": _text(beat.get("beat")),
            "question_opened": _text(beat.get("question_opened")),
            "question_answered": _text(beat.get("question_answered")),
            "new_complication": _text(beat.get("new_complication")),
            "visible_consequence": _text(beat.get("visible_consequence")),
            "opens_loop": opens,
            "closes_loop": closes,
        }
        compact_beats.append(item)
        if opens:
            opened.append({
                "id": opens,
                "question": item["question_opened"],
                "open_scene": n,
                "open_sec": round(starts[index], 1) if index < len(starts) else None,
            })

    return {
        "version": 1,
        "core_question": _text(plan.get("throughline")) or _text(question),
        "title_promise": _text(plan.get("title")) or _text(question),
        "thumbnail_promise": _text(plan.get("thumbnail_promise")) or _text(plan.get("hook")),
        "false_model": _text(plan.get("false_model")),
        "replacement_model": _text(plan.get("replacement_model")),
        "personal_stake": _text(plan.get("personal_stake")),
        "stages": [_text(x) for x in (plan.get("stages") or []) if _text(x)],
        "open_loops": opened,
        "target_runtime_sec": int(target_duration_sec),
        "natural_runtime_sec": round(natural_runtime, 1),
        "beat_count": len(beats),
        "scene_count": len(scenes),
        "beats": compact_beats,
    }


def _issue(code: str, message: str, scene: int | None = None, time_sec: float | None = None) -> dict:
    out: dict[str, Any] = {"code": code, "message": message}
    if scene is not None:
        out["scene"] = scene
    if time_sec is not None:
        out["time_sec"] = round(time_sec, 1)
    return out


def validate_longform_story(script: dict, question: str = "") -> dict:
    """Validate structural retention requirements using only persisted script metadata.

    ``errors`` are objective failures that can block paid rendering. ``warnings`` are useful
    editorial signals but never block a render by themselves.
    """
    scenes = [s for s in (script.get("scenes") or []) if isinstance(s, dict)]
    contract = script.get("_story_contract") if isinstance(script.get("_story_contract"), dict) else {}
    errors: list[dict] = []
    warnings: list[dict] = []
    checks: dict[str, Any] = {}

    if not contract:
        errors.append(_issue("missing_story_contract", "The long-form story contract is missing."))
    if len(scenes) < 4:
        errors.append(_issue("too_few_scenes", "Long-form requires at least four planned scenes."))
        return {"version": 1, "passed": False, "score": 0, "errors": errors,
                "warnings": warnings, "checks": checks}

    starts, durations, runtime = _timeline(scenes)
    roles = [_text(s.get("story_role")) for s in scenes]
    checks["estimated_runtime_sec"] = round(runtime, 1)
    checks["scene_count"] = len(scenes)
    checks["contract_scene_count"] = int(contract.get("scene_count") or 0)
    checks["contract_beat_count"] = int(contract.get("beat_count") or 0)
    if contract and int(contract.get("scene_count") or 0) != len(scenes):
        errors.append(_issue("contract_scene_mismatch", "Contract and generated scene counts differ."))
    if contract and int(contract.get("beat_count") or 0) != len(scenes):
        errors.append(_issue("beat_expansion_mismatch", "One or more planned beats did not expand into a scene."))

    if roles[0] != "cold_consequence":
        errors.append(_issue("opening_not_consequence", "Scene 1 must be a cold, visible consequence.", 1, 0))

    title = _text(question) or _text(contract.get("title_promise")) or _text(script.get("title"))
    subject_terms = [w.lower() for w in _words(title)
                     if w.lower() not in _SUBJECT_STOP and len(w) > 2]
    opening_text = ""
    for i, scene in enumerate(scenes):
        if starts[i] > 5.0:
            break
        opening_text += " " + _text(scene.get("narration")).lower()
    hits = [term for term in subject_terms if term in opening_text]
    subject_ratio = len(hits) / max(1, len(set(subject_terms)))
    checks["subject_terms_in_first_5s"] = hits
    if subject_terms and subject_ratio < 0.4:
        warnings.append(_issue("subject_unclear_by_5s", "The exact subject may not be clear in the first five seconds."))

    predictions = [i for i, role in enumerate(roles) if role == "prediction_gate"]
    needed_predictions = 2 if runtime >= 120 else 1
    checks["prediction_scenes"] = [i + 1 for i in predictions]
    if len(predictions) < needed_predictions:
        errors.append(_issue("too_few_predictions", f"Expected at least {needed_predictions} viewer prediction gate(s)."))
    elif starts[predictions[0]] > 30.0:
        errors.append(_issue("late_first_prediction", "The first prediction gate arrives after 30 seconds.",
                             predictions[0] + 1, starts[predictions[0]]))

    answer_markers = [i for i, scene in enumerate(scenes)
                      if roles[i] in ANSWER_ROLES or _text(scene.get("question_answered"))]
    checks["answer_scenes"] = [i + 1 for i in answer_markers]
    if not answer_markers:
        errors.append(_issue("no_payoff", "No evidence-backed answer/payoff is identified."))
    elif starts[answer_markers[0]] > 25.0:
        errors.append(_issue("late_first_payoff", "The first useful answer arrives after 25 seconds.",
                             answer_markers[0] + 1, starts[answer_markers[0]]))

    attention = [i for i, role in enumerate(roles) if role in ATTENTION_ROLES]
    attention_times = [0.0] + [starts[i] for i in attention] + [runtime]
    max_gap = max((b - a for a, b in zip(attention_times, attention_times[1:])), default=runtime)
    checks["max_attention_gap_sec"] = round(max_gap, 1)
    if max_gap > 55.0:
        errors.append(_issue("attention_gap", f"A {max_gap:.1f}-second stretch has no prediction, payoff, rehook, or reversal."))

    longest_exposition = 0.0
    block_start: int | None = None
    for i, role in enumerate(roles + ["__end__"]):
        if role in EXPOSITION_ROLES and block_start is None:
            block_start = i
        elif role not in EXPOSITION_ROLES and block_start is not None:
            block = sum(durations[block_start:i])
            longest_exposition = max(longest_exposition, block)
            block_start = None
    checks["max_exposition_block_sec"] = round(longest_exposition, 1)
    if longest_exposition > 18.0:
        errors.append(_issue("exposition_block", f"A mechanism/rules block runs {longest_exposition:.1f} seconds without a story turn."))

    peak_scene = int(script.get("_peak_scene") or 0)
    peak_ratio = peak_scene / max(1, len(scenes))
    checks["peak_scene"] = peak_scene
    if not peak_scene or not 0.55 <= peak_ratio <= 0.82:
        errors.append(_issue("misplaced_peak", "The strongest reveal must land between 55% and 82% of the story."))

    final_payoffs = [i for i, role in enumerate(roles) if role == "final_payoff"]
    if not final_payoffs:
        errors.append(_issue("missing_final_payoff", "The title needs an explicit final-payoff beat."))
    elif final_payoffs[-1] < int(len(scenes) * 0.85):
        errors.append(_issue("early_final_payoff", "The final title payoff lands before the final 15% of the story.",
                             final_payoffs[-1] + 1, starts[final_payoffs[-1]]))
    if "resonant_end" not in roles[-2:]:
        warnings.append(_issue("missing_resonant_end", "The last two scenes should contain a specific resonant ending."))

    opened: dict[str, int] = {}
    closed: set[str] = set()
    for i, scene in enumerate(scenes):
        opens = _text(scene.get("opens_loop"))
        closes = _text(scene.get("closes_loop"))
        if opens:
            opened.setdefault(opens, i)
        if closes:
            closed.add(closes)
            if closes not in opened:
                warnings.append(_issue("loop_closed_without_open", f"Loop '{closes}' closes without a recorded opening.", i + 1, starts[i]))
    unresolved = sorted(set(opened) - closed)
    checks["opened_loops"] = sorted(opened)
    checks["closed_loops"] = sorted(closed)
    checks["unresolved_loops"] = unresolved
    if unresolved:
        errors.append(_issue("unresolved_loops", "Unresolved narrative loop(s): " + ", ".join(unresolved)))
    if not opened:
        errors.append(_issue("no_tracked_loops", "The beat sheet does not track any open narrative question."))

    missing_visible = [i + 1 for i, scene in enumerate(scenes)
                       if not _text(scene.get("visible_consequence"))]
    if missing_visible:
        warnings.append(_issue("missing_visible_consequence",
                               f"{len(missing_visible)} scene(s) do not declare a visible consequence."))
    checks["missing_visible_consequence_scenes"] = missing_visible

    score = max(0, 100 - 12 * len(errors) - 3 * len(warnings))
    return {
        "version": 1,
        "passed": not errors,
        "score": score,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }


def validation_rank(report: dict) -> tuple[int, int, int]:
    """Lower tuple is better; useful when retaining the best automatic retry."""
    return (len(report.get("errors") or []), len(report.get("warnings") or []),
            -int(report.get("score") or 0))


def write_retention_report(report: dict, contract: dict, out_dir: str) -> str:
    """Write human-readable and JSON reports; return the downloadable text path."""
    os.makedirs(out_dir, exist_ok=True)
    text_path = os.path.join(out_dir, "retention_report.txt")
    json_path = os.path.join(out_dir, "retention_report.json")
    lines = [
        f"LONG-FORM RETENTION CONTRACT — {'PASS' if report.get('passed') else 'FAIL'}",
        f"Score: {report.get('score', 0)}/100",
        f"Core question: {_text(contract.get('core_question'))}",
        f"Natural runtime estimate: {contract.get('natural_runtime_sec', '?')}s",
        "",
        "DETERMINISTIC CHECKS",
    ]
    for key, value in (report.get("checks") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "BLOCKING ERRORS"])
    errors = report.get("errors") or []
    lines.extend(f"- [{x.get('code')}] {x.get('message')}" for x in errors)
    if not errors:
        lines.append("- None")
    lines.extend(["", "EDITORIAL WARNINGS"])
    warnings = report.get("warnings") or []
    lines.extend(f"- [{x.get('code')}] {x.get('message')}" for x in warnings)
    if not warnings:
        lines.append("- None")
    with open(text_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump({"contract": contract, "validation": report}, handle, indent=2, ensure_ascii=False)
    return text_path
