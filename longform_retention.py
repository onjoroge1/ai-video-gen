"""Deterministic story-contract validation for long-form explainer scripts.

The language model plans the story; this module checks the resulting structure without
asking that same model whether it followed its own instructions.  It intentionally has no
provider dependencies so it can run before images, TTS, or video generation spend begins.
"""

from __future__ import annotations

import json
import os
import re
import hashlib
from datetime import datetime, timezone
from typing import Any


WORDS_PER_SECOND = 2.64
ATTENTION_ROLES = {
    "cold_consequence", "prediction_gate", "payoff", "rehook", "reversal", "branch",
    "false_relief", "final_escalation", "final_payoff",
}
ANSWER_ROLES = {"payoff", "reversal", "branch", "final_payoff"}
EXPOSITION_ROLES = {"rules", "mechanism"}


class StoryFormatAcknowledgementRequired(RuntimeError):
    """An operator must accept a Mystery-to-Standard fallback before visual spending."""

_SUBJECT_STOP = {
    "a", "an", "and", "are", "at", "be", "can", "could", "did", "do", "does", "for",
    "from", "had", "has", "have", "how", "if", "in", "is", "it", "of", "on", "or",
    "really", "the", "then", "this", "to", "was", "were", "what", "when", "where", "who",
    "why", "will", "with", "would", "you", "your", "happen", "happens", "explained",
    # Function words that carry no subject. Their absence inflated the requirement: for "Why were
    # doctors wrong about what causes stomach ulcers?", "about" counted as a subject term, so the
    # opening had to hit 3 of 6 rather than 3 of 5 — and one of the six was a preposition no
    # narration would naturally repeat.
    "about", "into", "over", "under", "between", "through", "during", "after", "before",
    "actually", "against", "because", "than", "that", "these", "those", "there",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


_EMPTY_SEMANTIC_VALUES = {"", "none", "no", "n/a", "na", "unchanged", "same", "empty"}


def _meaningful(value: Any) -> bool:
    return _text(value).casefold() not in _EMPTY_SEMANTIC_VALUES


def _bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = _text(value).casefold()
    if normalized in {"false", "0", "no", "off", "absent"}:
        return False
    if normalized in {"true", "1", "yes", "on", "present"}:
        return True
    return default


def story_format_fallback_payload(script: dict) -> dict:
    contract = script.get("_story_contract") if isinstance(script.get("_story_contract"), dict) else {}
    return {
        "requested": _text(contract.get("story_format_requested")
                           or script.get("_story_format_requested")),
        "effective": _text(contract.get("story_format_effective") or script.get("_story_format")),
        "reason": _text(contract.get("story_format_fallback_reason")
                        or script.get("_story_format_fallback_reason")),
        "title": _text(script.get("title")),
    }


def _fallback_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_story_format_review(script: dict, output_path: str) -> dict:
    payload = story_format_fallback_payload(script)
    if payload["requested"] != "evidence_led_mystery" or payload["effective"] != "standard_explainer" \
            or not payload["reason"]:
        raise ValueError("Story-format review requires a concrete Mystery-to-Standard fallback.")
    record = {
        "version": 1, "status": "pending", "decision": "pending", "reviewer": "",
        "reviewed_at": "", "fallback": payload, "fallback_sha256": _fallback_hash(payload),
    }
    temp = output_path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
    os.replace(temp, output_path)
    return record


def apply_story_format_review(record: dict, *, script: dict, reviewer: str,
                              decision: str) -> dict:
    if decision not in {"accept", "reject"}:
        raise ValueError("Story-format decision must be accept or reject.")
    if not _text(reviewer):
        raise ValueError("Story-format acknowledgement requires a reviewer name.")
    payload = story_format_fallback_payload(script)
    if _fallback_hash(payload) != _text(record.get("fallback_sha256")):
        raise ValueError("Story-format fallback changed after it was presented to the operator.")
    return {
        **record, "status": "completed", "decision": decision,
        "reviewer": _text(reviewer), "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }


def validate_story_format_review(record: dict, script: dict) -> bool:
    return bool(
        isinstance(record, dict)
        and record.get("decision") == "accept"
        and _fallback_hash(story_format_fallback_payload(script))
        == _text(record.get("fallback_sha256"))
    )


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
            "human_present": _bool_value(beat.get("human_present"), True),
            "human_intention": _text(beat.get("human_intention")),
            "human_belief": _text(beat.get("human_belief")),
            "viewer_knows": _text(beat.get("viewer_knows")),
            "human_knows": _text(beat.get("human_knows")),
            "expected_outcome": _text(beat.get("expected_outcome")),
            "actual_outcome": _text(beat.get("actual_outcome")),
            "belief_changed": _text(beat.get("belief_changed")),
            "decision_caused": _text(beat.get("decision_caused")),
            "continuity_anchor": _text(beat.get("continuity_anchor")),
            "causal_link": _text(beat.get("causal_link")),
            "bolt_mode": _text(beat.get("bolt_mode")) or "absent",
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
        "version": 2,
        "core_question": _text(plan.get("throughline")) or _text(question),
        "title_promise": _text(plan.get("title")) or _text(question),
        "thumbnail_promise": _text(plan.get("thumbnail_promise")) or _text(plan.get("hook")),
        "false_model": _text(plan.get("false_model")),
        "replacement_model": _text(plan.get("replacement_model")),
        "personal_stake": _text(plan.get("personal_stake")),
        "story_format_requested": _text(plan.get("story_format_requested")) or "standard_explainer",
        "story_format_effective": _text(plan.get("story_format_effective")) or "standard_explainer",
        "story_format_fallback_reason": _text(plan.get("story_format_fallback_reason")),
        "mystery_suitable": _bool_value(plan.get("mystery_suitable")),
        "anomaly": _text(plan.get("anomaly")),
        "human_subject": _text(plan.get("human_subject")),
        "human_role": _text(plan.get("human_role")),
        "recurring_location": _text(plan.get("recurring_location")),
        "subject_goal": _text(plan.get("subject_goal")),
        "antagonistic_force": _text(plan.get("antagonistic_force")),
        "accepted_belief": _text(plan.get("accepted_belief")),
        "contradictory_evidence": _text(plan.get("contradictory_evidence")),
        "viewer_initial_belief": _text(plan.get("viewer_initial_belief")),
        "viewer_belief_after_reveal": _text(plan.get("viewer_belief_after_reveal")),
        "opening_object": _text(plan.get("opening_object")),
        "final_callback_object": _text(plan.get("final_callback_object")),
        "character_budget": plan.get("character_budget") or {},
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

    # Version 2 is the human-led Phase-1 contract. Legacy fixtures remain readable,
    # while every newly generated long-form plan is held to these fail-closed rules.
    if int(contract.get("version") or 1) >= 2:
        required = (
            "anomaly", "human_subject", "human_role", "recurring_location", "subject_goal",
            "antagonistic_force", "accepted_belief", "contradictory_evidence",
            "viewer_initial_belief", "viewer_belief_after_reveal", "opening_object",
            "final_callback_object",
        )
        missing = [key for key in required if not _meaningful(contract.get(key))]
        checks["missing_human_story_fields"] = missing
        if missing:
            errors.append(_issue("incomplete_human_story_contract",
                                 "Missing human-story field(s): " + ", ".join(missing)))

        if (_text(contract.get("opening_object")).casefold()
                != _text(contract.get("final_callback_object")).casefold()):
            errors.append(_issue("broken_opening_object_callback",
                                 "The ending must return to the exact opening object."))

        opening_objective = [i for i, scene in enumerate(scenes)
                             if starts[i] <= 8.0 and scene.get("human_present")
                             and _text(scene.get("human_intention"))]
        checks["human_objective_scenes_by_8s"] = [i + 1 for i in opening_objective]
        if not opening_objective:
            errors.append(_issue("human_goal_not_visible_by_8s",
                                 "The human lead has no legible intention in the opening eight seconds."))

        gaps = [i for i, scene in enumerate(scenes)
                if _meaningful(scene.get("viewer_knows"))
                and _text(scene.get("viewer_knows")).casefold()
                != _text(scene.get("human_knows")).casefold()]
        checks["knowledge_gap_scenes"] = [i + 1 for i in gaps]
        if not gaps:
            errors.append(_issue("no_viewer_human_knowledge_gap",
                                 "At least one beat must let the viewer know evidence Alex does not."))

        changed = [i for i, scene in enumerate(scenes)
                   if _meaningful(scene.get("belief_changed"))
                   and _meaningful(scene.get("decision_caused"))]
        checks["belief_change_decision_scenes"] = [i + 1 for i in changed]
        if not changed:
            errors.append(_issue("evidence_never_forces_decision",
                                 "No visible evidence changes Alex's belief and forces a decision."))

        flat_runs = []
        for i in range(max(0, len(scenes) - 2)):
            window = scenes[i:i + 3]
            def has_turn(scene: dict) -> bool:
                causal = _text(scene.get("causal_link")).casefold()
                linked = any(token in causal for token in (
                    "because", "but", "therefore", "so ", "so,", "yet", "forces", "leads to"))
                semantic_turn = any(_meaningful(scene.get(key)) for key in (
                    "decision_caused", "belief_changed", "question_answered", "new_complication"))
                return linked or semantic_turn

            if all(not has_turn(scene) for scene in window):
                flat_runs.append([i + 1, i + 2, i + 3])
        checks["flat_consequence_runs"] = flat_runs
        if flat_runs:
            errors.append(_issue("consequence_enumeration",
                                 "Three adjacent beats enumerate consequences without a causal turn.",
                                 flat_runs[0][0]))

        first_act_n = max(1, int(len(scenes) * 0.30 + 0.999))
        recurring_terms = {w.lower() for w in _words(_text(contract.get("recurring_location")))
                           if w.lower() not in _SUBJECT_STOP and len(w) > 2}
        continuity_hits = []
        for i, scene in enumerate(scenes[:first_act_n]):
            anchor_terms = {w.lower() for w in _words(_text(scene.get("continuity_anchor")))}
            if scene.get("human_present") or recurring_terms.intersection(anchor_terms):
                continuity_hits.append(i + 1)
        checks["first_act_continuity_hits"] = continuity_hits
        required_hits = max(1, int(first_act_n * 0.70 + 0.999))
        if len(continuity_hits) < required_hits:
            errors.append(_issue("broken_first_act_continuity",
                                 f"Only {len(continuity_hits)}/{first_act_n} first-act beats preserve Alex or the recurring location."))

        bolt_scenes = [i + 1 for i, scene in enumerate(scenes) if scene.get("mascot_present")]
        first_bolt = sum(1 for i in bolt_scenes if i <= first_act_n)
        first_cap = max(1, int(first_act_n * 0.35))
        total_cap = max(1, int(len(scenes) * 0.30))
        checks["bolt_scenes"] = bolt_scenes
        checks["bolt_caps"] = {"first_act": first_cap, "overall": total_cap}
        if not bolt_scenes:
            errors.append(_issue(
                "missing_useful_bolt_scene",
                "At least one scene must give Bolt useful measurement, demonstration, warning, "
                "reaction, or assistance work."))
        if first_bolt > first_cap or len(bolt_scenes) > total_cap:
            errors.append(_issue("bolt_presence_budget_exceeded",
                                 "Bolt exceeds the selective supporting-character presence budget."))
        decorative = [i + 1 for i, scene in enumerate(scenes)
                      if scene.get("mascot_present") and _text(scene.get("bolt_mode"))
                      not in {"measurement", "demonstration", "warning", "reaction", "assistance"}]
        decorative.extend(i + 1 for i, scene in enumerate(scenes)
                          if scene.get("mascot_present") and _text(scene.get("story_role"))
                          in {"rules", "mechanism"} and i + 1 not in decorative)
        checks["decorative_bolt_scenes"] = decorative
        if decorative:
            errors.append(_issue("decorative_bolt", "Bolt appears without a permitted story action.", decorative[0]))

        requested = _text(contract.get("story_format_requested"))
        effective = _text(contract.get("story_format_effective"))
        if requested == "evidence_led_mystery" and not contract.get("mystery_suitable"):
            if effective != "standard_explainer" or not _text(contract.get("story_format_fallback_reason")):
                errors.append(_issue("invalid_mystery_fallback",
                                     "An unsuitable mystery must fall back to Standard with a visible reason."))

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
        issue = _issue("subject_unclear_by_5s", "The exact subject is not clear in the first five seconds.")
        (errors if int(contract.get("version") or 1) >= 2 else warnings).append(issue)

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

    # Editorial judgements expressed as hard arithmetic. Each is a reasonable thing to notice and a
    # bad thing to block on: a peak outside 55-82% of runtime, first-act continuity under 70%, an
    # enumerated consequence, a missing viewer/human knowledge gap, or subject terms not dense
    # enough in the first five seconds. None of them means the video is unusable, and blocking on
    # them meant a good script died at a threshold nobody validated against real outcomes. They
    # stay visible as warnings, and still cost score, so they can be tuned on evidence rather than
    # on a run that never finished.
    # Deliberately NOT including consequence_enumeration or no_viewer_human_knowledge_gap. An audit
    # recommended demoting them too, but tests named test_three_uncausal_consequence_beats_are_
    # rejected and test_fake_knowledge_gap_is_blocking assert they must block — that is a decision
    # someone made on purpose, not an oversight, and it is not mine to reverse quietly. The three
    # below carry no such intent and are pure thresholds.
    _EDITORIAL = {"misplaced_peak", "broken_first_act_continuity", "subject_unclear_by_5s"}
    demoted = [issue for issue in errors if _text(issue.get("code")) in _EDITORIAL]
    if demoted:
        errors = [issue for issue in errors if _text(issue.get("code")) not in _EDITORIAL]
        warnings = warnings + demoted

    score = max(0, 100 - 12 * len(errors) - 3 * len(warnings))
    return {
        "version": 1,
        "passed": not errors,
        "score": score,
        "errors": errors,
        "warnings": warnings,
        "demoted_editorial": [_text(issue.get("code")) for issue in demoted],
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
        f"Story structure: {_text(contract.get('story_format_effective')) or 'standard_explainer'}",
        f"Human lead: {_text(contract.get('human_subject')) or 'not declared'} — goal: {_text(contract.get('subject_goal'))}",
        f"Bolt scenes: {(contract.get('character_budget') or {}).get('bolt_scenes', [])}",
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
