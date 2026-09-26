"""Unified Bolt Explains Nature story contract.

This module is intentionally Nature-only. It does not register a new global video format and it
does not change World, History, Quiz, TV Review, Simulation, or generic explainer behavior.

One episode contract can produce two output profiles:
- short: portrait keyframe/motion storytelling
- long: landscape illustrated storytelling through the existing explainer pipeline

Both profiles share the same question, evidence ledger, mechanism, progression rules, subject sheet,
and storyboard semantics. Rendering remains profile-specific.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any

FLOW_ID = "nature_story_v1"
FLOW_NAME = "Nature Story"
CHANNEL = "nature"
SERIES_TERRIBLE_PARENTS = "terrible_parents"
PROFILE_SHORT = "short"
PROFILE_LONG = "long"
PROFILES = {PROFILE_SHORT, PROFILE_LONG}
ALLOWED_ENGINES = {"mistaken_verdict", "strange_behaviour"}
DEVELOPMENTS = {
    "action", "constraint", "mechanism", "consequence", "limitation",
    "reinterpretation", "callback",
}
HARD_CHECKS = {
    "INPUTS_READY", "WORD_CAP", "HOOK_ONCE", "CLAIM_SUPPORT", "PROMISE_CLOSED",
    "MECHANISM_COMPLETE", "PARENT_SUBJECT_MATCH", "NO_CONTRADICTION",
    "VISUAL_PROOF",
}

# Shared writing doctrine. nature_channel imports this exact string for the model-authored long form;
# the Nature Story validator applies the same contract to authored Shorts before any render stage.
NATURE_WRITING_CONTRACT = (
    "Use one authoritative story question. For the Terrible Parents series, open with the direct "
    "question 'Why is this [animal] the worst [mother/father/parent]?' as a question being examined, "
    "not as a scientific ranking. Speak it once. Immediately show the specific parenting behaviour "
    "and make the practical problem understandable.\n"
    "Follow one causal line: behaviour -> constraint/problem -> mechanism -> supported development "
    "or limitation -> outcome -> one evidence-supported interpretation. Do not add a second twist "
    "unless the evidence genuinely earns one.\n"
    "Every beat must add a new action, constraint, mechanism, consequence, limitation, or changed "
    "interpretation. Different wording, another statistic, or another camera angle is not a new beat. "
    "If removing a beat changes neither the explanation nor the unresolved question, merge or cut it.\n"
    "A mechanism must explain the resource or origin, the process/action, and the benefit or effect "
    "for the young. Do not answer 'how' by merely restating the outcome.\n"
    "Keep the parent named by the title central. Do not hide a known caregiver, protected egg, actual "
    "nursing, or other basic context to manufacture neglect. Do not invent a reputation, intention, "
    "emergency, rescue, guaranteed survival, or worst-parent ranking. Preserve source qualifiers such "
    "as 'can', 'about', 'roughly', 'temporary', and conditional wording.\n"
    "Separate narration from visual direction. The storyboard must visibly prove critical actions and "
    "mechanisms; track parent presence, offspring age, chronology, flashbacks, and conditional scenes. "
    "Nature frames contain no people or human equipment unless a separately approved episode contract "
    "explicitly requires them.\n"
    "End once on the episode's supported payoff, remaining dependency, trade-off, or care changeover. "
    "The final action must demonstrate the interpretation. Do not force every species into a feeding "
    "or reunion ending, and do not force a seamless loop when it would reverse age or chronology."
)

_WORD = re.compile(r"\b[\w'-]+\b", re.UNICODE)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value)).casefold()


def _word_count(value: str) -> int:
    return len(_WORD.findall(value or ""))


def canonical_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def episode_sha256(episode: dict) -> str:
    return hashlib.sha256(canonical_json(episode).encode("utf-8")).hexdigest()


def narration_text(episode: dict) -> str:
    return " ".join(_text(beat.get("vo")) for beat in episode.get("beats") or [] if _text(beat.get("vo")))


def _check(check_id: str, status: str, evidence: Any = None, repair: str = "",
           severity: str = "hard") -> dict:
    return {
        "check_id": check_id,
        "status": status,
        "severity": severity,
        "evidence": evidence,
        "repair_instruction": repair,
    }


def validate_episode(episode: dict, *, profile: str | None = None) -> dict:
    """Return a fail-closed, pre-render QA record for one Nature Story episode.

    PASS/FAIL/UNKNOWN are deliberately distinct. Unknown production measurements never become passes.
    """
    profile = _text(profile or episode.get("profile")).lower()
    beats = [b for b in (episode.get("beats") or []) if isinstance(b, dict)]
    narration = narration_text(episode)
    checks: list[dict] = []
    issues: list[str] = []

    required = {
        "flow_id": episode.get("flow_id"),
        "profile": profile,
        "series_id": episode.get("series_id"),
        "species": episode.get("species"),
        "parent_role": episode.get("parent_role"),
        "title": episode.get("title"),
        "central_question": episode.get("central_question"),
        "observed_behavior": episode.get("observed_behavior"),
        "practical_problem": episode.get("practical_problem"),
        "mechanism": episode.get("mechanism"),
        "beats": beats,
        "claims": episode.get("claims"),
    }
    missing = [key for key, value in required.items() if not value]
    structural = []
    if episode.get("flow_id") != FLOW_ID:
        structural.append(f"flow_id must be {FLOW_ID}")
    if profile not in PROFILES:
        structural.append("profile must be short or long")
    if _text(episode.get("channel") or CHANNEL).lower() != CHANNEL:
        structural.append("channel must be nature")
    if _text(episode.get("engine")).lower() not in ALLOWED_ENGINES:
        structural.append("Nature Story engine must be mistaken_verdict or strange_behaviour")
    inputs_ok = not missing and not structural
    checks.append(_check(
        "INPUTS_READY", "PASS" if inputs_ok else "FAIL",
        {"missing": missing, "structural": structural},
        "Supply every required Nature Story field and use a Nature-supported engine."))

    word_count = _word_count(narration)
    try:
        word_cap = int(episode.get("word_cap"))
    except (TypeError, ValueError):
        word_cap = 0
    cap_ok = bool(word_cap) and word_count <= word_cap
    checks.append(_check(
        "WORD_CAP", "PASS" if cap_ok else "FAIL",
        {"words": word_count, "cap": word_cap},
        "Shorten redundant speech without deleting needed evidence qualifiers."))

    question = _text(episode.get("central_question"))
    first_vo = _text(beats[0].get("vo")) if beats else ""
    qnorm = _norm(question)
    narration_norm = _norm(narration)
    hook_count = narration_norm.count(qnorm) if qnorm else 0
    hook_ok = bool(qnorm) and _norm(first_vo).startswith(qnorm) and hook_count == 1
    checks.append(_check(
        "HOOK_ONCE", "PASS" if hook_ok else "FAIL",
        {"count": hook_count, "first_beat": first_vo[:180]},
        "Put the approved direct question at the start of beat 1 and speak it exactly once."))

    claims = {str(c.get("id")): c for c in (episode.get("claims") or []) if isinstance(c, dict) and c.get("id")}
    claim_failures = []
    for beat in beats:
        for cid in beat.get("claim_ids") or []:
            claim = claims.get(str(cid))
            if not claim:
                claim_failures.append({"beat": beat.get("id"), "claim_id": cid, "reason": "missing"})
            elif _text(claim.get("status")).lower() != "verified" or not _text(claim.get("passage")):
                claim_failures.append({"beat": beat.get("id"), "claim_id": cid, "reason": "not passage-verified"})
    checks.append(_check(
        "CLAIM_SUPPORT", "PASS" if claims and not claim_failures else "FAIL",
        claim_failures or {"verified_claims": len(claims)},
        "Map every material narration/visual claim to a passage-verified claim record."))

    beat_ids = {str(b.get("id")) for b in beats if b.get("id")}
    promise_failures = []
    promises = episode.get("promises") or []
    for promise in promises:
        if not isinstance(promise, dict):
            continue
        answer = str(promise.get("answer_beat_id") or "")
        if not answer or answer not in beat_ids:
            promise_failures.append({"promise": promise.get("id"), "answer_beat_id": answer})
    checks.append(_check(
        "PROMISE_CLOSED", "PASS" if promises and not promise_failures else "FAIL",
        promise_failures or {"promises": len(promises)},
        "Give every substantive promise a specific answer beat in this same video."))

    mechanism = episode.get("mechanism") if isinstance(episode.get("mechanism"), dict) else {}
    mech_missing = [k for k in ("resource_or_origin", "process", "offspring_benefit")
                    if not _text(mechanism.get(k))]
    checks.append(_check(
        "MECHANISM_COMPLETE", "PASS" if not mech_missing else "FAIL",
        {"missing": mech_missing},
        "State the resource/origin, process, and offspring benefit; do not merely repeat the outcome."))

    species = _norm(episode.get("species"))
    parent_role = _norm(episode.get("parent_role"))
    combined = _norm(question + " " + _text(episode.get("title")))
    subject_ok = bool(species and parent_role and species in combined and parent_role in combined)
    checks.append(_check(
        "PARENT_SUBJECT_MATCH", "PASS" if subject_ok else "FAIL",
        {"species": episode.get("species"), "parent_role": episode.get("parent_role")},
        "Make the title/question name the same species and parent role whose behavior the story explains."))

    contradictions_reviewed = bool((episode.get("review") or {}).get("contradictions_reviewed"))
    contradiction_notes = (episode.get("review") or {}).get("contradictions") or []
    no_contradiction = contradictions_reviewed and not contradiction_notes
    checks.append(_check(
        "NO_CONTRADICTION", "PASS" if no_contradiction else ("FAIL" if contradiction_notes else "UNKNOWN"),
        contradiction_notes,
        "Review narration and implied imagery for contradictions; record and resolve any conflict."))

    redundant_words = 0
    duplicate_info = []
    seen_info = set()
    for beat in beats:
        dev = _text(beat.get("development")).lower()
        info = _norm(beat.get("new_information"))
        if dev and dev not in DEVELOPMENTS:
            duplicate_info.append({"beat": beat.get("id"), "reason": f"unknown development {dev}"})
        if info and info in seen_info and dev != "callback":
            duplicate_info.append({"beat": beat.get("id"), "reason": "repeated new_information"})
            redundant_words += _word_count(_text(beat.get("vo")))
        seen_info.add(info)
    redundant_ratio = (redundant_words / word_count) if word_count else 0.0
    progression_status = "FAIL" if duplicate_info else "PASS"
    checks.append(_check(
        "PROGRESSION_REVIEW", progression_status,
        {"duplicate_or_invalid": duplicate_info, "redundant_word_ratio": round(redundant_ratio, 3)},
        "Merge repeated propositions. A callback may repeat meaning only when it closes the story.",
        severity="review"))

    critical = [b for b in beats if b.get("critical_visual")]
    visual_fail = []
    for beat in critical:
        visual_beats = [v for v in beat.get("visual_beats") or [] if isinstance(v, dict)]
        if not visual_beats or not any(v.get("visual_proof") for v in visual_beats):
            visual_fail.append(beat.get("id"))
    checks.append(_check(
        "VISUAL_PROOF", "PASS" if critical and not visual_fail else "FAIL",
        {"critical_beats": [b.get("id") for b in critical], "missing": visual_fail},
        "Give every critical explanatory beat at least one storyboard state explicitly marked visual_proof."))

    timing = episode.get("measured_timing") if isinstance(episode.get("measured_timing"), dict) else {}
    measured = timing.get("duration_sec")
    target = episode.get("target_duration_sec")
    tolerance = episode.get("runtime_tolerance_sec", 2.0 if profile == PROFILE_SHORT else 10.0)
    timing_status = "UNKNOWN"
    timing_evidence = {"measured": measured, "target": target, "tolerance": tolerance}
    try:
        if measured is not None and target is not None:
            timing_status = "PASS" if abs(float(measured) - float(target)) <= float(tolerance) else "FAIL"
    except (TypeError, ValueError):
        timing_status = "FAIL"
    checks.append(_check(
        "TIMING_MEASURED", timing_status, timing_evidence,
        "Synthesize and align the exact approved narration; estimates cannot clear timing.",
        severity="production"))

    checks.append(_check(
        "SCHEMA_ACTUAL", "PASS" if episode.get("schema_validated") is True else "UNKNOWN",
        episode.get("schema_validation"),
        "Run the exact production schema validator on the exact payload.",
        severity="production"))

    grade = episode.get("script_grade") if isinstance(episode.get("script_grade"), dict) else {}
    grade_status = "UNKNOWN"
    if grade.get("score") is not None and grade.get("floor") is not None:
        grade_status = "PASS" if float(grade["score"]) >= float(grade["floor"]) else "FAIL"
    checks.append(_check(
        "SCRIPT_GRADE_ACTUAL", grade_status, grade,
        "Run the configured production script grader; do not substitute this QA record for it.",
        severity="production"))

    checks.append(_check(
        "RENDER_GATE_ACTUAL", "UNKNOWN", None,
        "Run and inspect the final rendered asset; script approval does not clear this gate.",
        severity="production"))

    hard_failures = [c["check_id"] for c in checks if c["check_id"] in HARD_CHECKS and c["status"] == "FAIL"]
    for check in checks:
        if check["status"] == "FAIL":
            issues.append(check["check_id"])
    return {
        "flow_id": FLOW_ID,
        "flow_name": FLOW_NAME,
        "profile": profile,
        "episode_sha256": episode_sha256(episode),
        "passed_pre_render": not hard_failures,
        "hard_failures": hard_failures,
        "issues": issues,
        "metrics": {
            "word_count": word_count,
            "word_cap": word_cap,
            "promise_coverage": 1.0 if promises and not promise_failures else 0.0,
            "redundant_word_ratio": round(redundant_ratio, 3),
            "beat_count": len(beats),
        },
        "checks": checks,
    }


def to_storyboard_script(episode: dict) -> dict:
    """Convert the shared Nature episode into the existing long-form evidence storyboard contract."""
    scenes = []
    for index, beat in enumerate(episode.get("beats") or []):
        scenes.append({
            "n": index + 1,
            "narration": _text(beat.get("vo")),
            "story_role": _text(beat.get("role") or beat.get("development") or "beat"),
            "role": _text(beat.get("role") or beat.get("development") or "beat"),
            "visual_beats": deepcopy(beat.get("visual_beats") or []),
            "visible_consequence": _text(beat.get("new_information")),
            "claim_refs": list(beat.get("claim_ids") or []),
            "mascot_present": False,
            "human_present": False,
            "continuity_anchor": _text((episode.get("visual") or {}).get("location")),
        })
    return {
        "title": _text(episode.get("title")),
        "hook": _text(episode.get("central_question")),
        "_topic_channel": CHANNEL,
        "_subject_sheet": _text((episode.get("visual") or {}).get("subject_sheet")),
        "_story_contract": {
            "opening_object": _text((episode.get("visual") or {}).get("opening_object")),
            "final_callback_object": _text((episode.get("visual") or {}).get("final_object")),
            "recurring_location": _text((episode.get("visual") or {}).get("location")),
        },
        "scenes": scenes,
    }


def compile_storyboard(episode: dict) -> dict:
    """Reuse the existing Nature-aware long-form evidence-state planner for either profile."""
    import longform_evidence as evidence

    script = to_storyboard_script(episode)
    seconds = {}
    for i, beat in enumerate(episode.get("beats") or []):
        value = beat.get("duration_sec")
        if value is None:
            # Planning fallback only. Measured timing remains a separate KPI.
            rate = float(episode.get("estimated_words_per_sec") or 2.6)
            value = max(1.0, _word_count(_text(beat.get("vo"))) / max(0.5, rate))
        seconds[i] = float(value)
    plan = evidence.compile_evidence_plan(script, seconds)
    validation = evidence.validate_evidence_plan(plan)
    return {"script": script, "plan": plan, "validation": validation}


def compile_keyframe_spec(episode: dict) -> dict:
    """Compile the shared episode storyboard into the existing keyframe Short renderer format."""
    if _text(episode.get("profile")).lower() != PROFILE_SHORT:
        raise ValueError("compile_keyframe_spec requires profile=short")
    visual = episode.get("visual") or {}
    beats_out = []
    for beat in episode.get("beats") or []:
        shots = []
        for index, state in enumerate(beat.get("visual_beats") or []):
            if not isinstance(state, dict):
                continue
            before = _text(state.get("state_before") or state.get("start"))
            after = _text(state.get("state_after") or state.get("end"))
            if not before or not after:
                raise ValueError(f"{beat.get('id')}: every Short storyboard state needs before and after")
            shot = {
                "id": _text(state.get("id") or f"{beat.get('id')}s{index + 1}"),
                "duration": int(state.get("duration") or 5),
                "start": before,
                "end": after,
                "motion": _text(state.get("motion")) or (
                    "Locked camera. Show only the declared visible change from the start state to "
                    "the end state at natural speed. No cuts, no camera drift, no invented action."),
            }
            if state.get("use") is not None:
                shot["use"] = list(state["use"])
            shots.append(shot)
        if not shots:
            raise ValueError(f"{beat.get('id')}: at least one storyboard state is required")
        beats_out.append({
            "id": _text(beat.get("id")),
            "caption": _text(beat.get("caption")),
            "vo": _text(beat.get("vo")),
            "shots": shots,
        })
    return {
        "name": _text(episode.get("episode_id") or episode.get("species")).lower().replace(" ", "_"),
        "title": _text(episode.get("title")),
        "channel": CHANNEL,
        "flow_id": FLOW_ID,
        "series_id": _text(episode.get("series_id")),
        "engine": _text(episode.get("engine")),
        "voice": _text(episode.get("voice") or "onyx"),
        "music_mood": _text(episode.get("music_mood") or "nostalgic"),
        "model": _text(episode.get("motion_model") or "kling-v3-pro"),
        "hard_cap_usd": float(episode.get("hard_cap_usd") or 12.0),
        "loop": bool(visual.get("continuity_loop_safe", False)),
        "style": _text(visual.get("style")),
        "end_rule": _text(visual.get("end_rule")) or (
            " Keep the exact same camera position, framing, lighting, and subject identity as the "
            "start frame; change only the declared action."),
        "negative": _text(visual.get("negative")),
        "beats": beats_out,
    }


def longform_pipeline_kwargs(episode: dict) -> dict:
    """Arguments for the existing explainer pipeline, scoped only to this Nature episode."""
    if _text(episode.get("profile")).lower() != PROFILE_LONG:
        raise ValueError("longform_pipeline_kwargs requires profile=long")
    mechanism = episode.get("mechanism") or {}
    canonical = {
        "flow": FLOW_ID,
        "series": episode.get("series_id"),
        "episode_id": episode.get("episode_id"),
        "species": episode.get("species"),
        "parent_role": episode.get("parent_role"),
        "question": episode.get("central_question"),
        "behavior": episode.get("observed_behavior"),
        "problem": episode.get("practical_problem"),
        "mechanism": mechanism,
        "limitation": episode.get("supported_limitation"),
        "ending": episode.get("ending"),
        "beat_progression": [
            {"id": b.get("id"), "development": b.get("development"),
             "new_information": b.get("new_information")}
            for b in episode.get("beats") or []
        ],
    }
    return {
        "question": _text(episode.get("central_question")),
        "duration_sec": int(episode.get("target_duration_sec") or 240),
        "voice": _text(episode.get("voice") or "onyx"),
        "style": _text((episode.get("visual") or {}).get("style")) or "illustrated natural history",
        "video_format": "landscape",
        "motion_mode": _text(episode.get("long_motion_mode") or "standard"),
        "series": _text(episode.get("series_id")),
        "short_template": "explainer",
        "operator_direction": (
            "NATURE STORY SHARED EPISODE CONTRACT. Treat the following JSON as authoritative for "
            "story focus, not as optional inspiration. Do not add a second crisis or alternate "
            "ending merely to fill runtime. Preserve every factual qualifier.\n"
            + json.dumps(canonical, ensure_ascii=False)
        ),
        "story_format": "standard_explainer",
        "visual_style": "illustrated_story",
        "topic_channel": CHANNEL,
    }
