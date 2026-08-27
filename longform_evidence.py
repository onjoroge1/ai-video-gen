"""Fail-closed evidence-state and continuity contracts for long-form explainers."""

from __future__ import annotations

import hashlib
import math
import re
import shutil
from pathlib import Path
from typing import Any


PURE_EVIDENCE_PURPOSES = {"evidence", "mechanism", "scale", "location", "record", "diagram"}
USEFUL_BOLT_PURPOSES = {
    "action", "assistance", "decision", "demonstration", "measurement", "reaction", "test",
    "warning",
}
ASSET_STRATEGIES = {"master", "distinct", "detail_reframe", "exact_reuse"}
ACCEPTED_ASSET_STATUSES = {"accepted", "reused_exact"}
MIN_EVIDENCE_STATE_SECONDS = 1.5


def _text(value: Any) -> str:
    return str(value or "").strip()


def _slug(value: str, fallback: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", _text(value).casefold()).strip("-")
    return (clean[:48] or fallback).strip("-")


def _stable_id(prefix: str, value: str, fallback: str) -> str:
    slug = _slug(value, fallback)
    digest = hashlib.sha1(_text(value).casefold().encode("utf-8")).hexdigest()[:8]
    return f"{prefix}:{slug}:{digest}"


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    if _text(value):
        return [_text(value)]
    return []


def _issue(code: str, message: str, *, scene: int | None = None,
           state_id: str = "") -> dict:
    result = {"code": code, "message": message}
    if scene is not None:
        result["scene"] = scene
    if state_id:
        result["state_id"] = state_id
    return result


def _story_contract(script: dict) -> dict:
    return script.get("_story_contract") if isinstance(script.get("_story_contract"), dict) else {}


def _opening_scene_count(scenes: list[dict]) -> int:
    if not scenes:
        return 0
    explicit = []
    for index, scene in enumerate(scenes):
        try:
            percent = float(scene.get("story_pct"))
        except (TypeError, ValueError):
            continue
        if percent <= 30:
            explicit.append(index)
    if explicit:
        return max(explicit) + 1
    return max(1, min(len(scenes), round(len(scenes) * 0.30)))


def build_continuity_pack(script: dict) -> dict:
    """Create stable IDs for the identities, clothing, first-act location, and callback object."""
    scenes = script.get("scenes") or []
    contract = _story_contract(script)
    opening_object = _text(contract.get("opening_object"))
    callback_object = _text(contract.get("final_callback_object"))
    first_anchor = next((_text(scene.get("continuity_anchor")) for scene in scenes
                         if _text(scene.get("continuity_anchor"))), "")
    location_label = _text(contract.get("recurring_location")) or first_anchor
    callback_scene = next((index for index, scene in reversed(list(enumerate(scenes)))
                           if _text(scene.get("story_role")).casefold() in
                           {"final_payoff", "resonant_end"}), max(0, len(scenes) - 1))
    opening_asset_id = "asset:s001:e01"
    return {
        "version": 1,
        "human": {
            "identity_id": "character:alex:v1",
            "name": "Alex",
            "reference_asset_id": "reference:alex:human-model:v1",
            "clothing_id": "clothing:alex:navy-overshirt-gray-shirt:v1",
            "required_traits": [
                "same adult male face and apparent age", "short brown hair", "light stubble",
                "navy overshirt", "light gray T-shirt", "dark jeans", "dark sneakers",
            ],
        },
        "bolt": {
            "identity_id": "character:bolt:v1",
            "reference_asset_id": "reference:bolt:mascot:v1",
        },
        "first_act_location": {
            "location_id": _stable_id("location", location_label, "recurring-first-act"),
            "label": location_label,
        },
        "opening_object": {
            "object_id": _stable_id("object", opening_object, "opening-object"),
            "label": opening_object,
            "opening_source_asset_id": opening_asset_id,
        },
        "callback": {
            "label": callback_object,
            "scene_index": callback_scene,
            "reuse_source_asset_id": opening_asset_id,
        },
        "opening_scene_count": _opening_scene_count(scenes),
    }


def _visual_beats(scene: dict) -> list[dict]:
    """Beats as objects, coercing a bare string rather than discarding it.

    The planner returns visual_beats as an array of objects, but a prompt edit once shifted it to
    an array of plain phrases -- and this dropped every one of them, silently, because they were
    not dicts. The scene then compiled to ZERO states, the opening gate rejected it, and the error
    said "every opening beat requires two to six evidence states" about a scene whose beats were
    all present and readable. A shape wobble should cost the extra fields, not the whole beat.
    """
    out: list[dict] = []
    for beat in scene.get("visual_beats") or []:
        if isinstance(beat, str) and _text(beat):
            out.append({"anchor_phrase": _text(beat)})
        elif isinstance(beat, dict) and _text(beat.get("anchor_phrase")):
            out.append(dict(beat))
    return out


def _derive_bolt_action(beat: dict, scene: dict, subject: str) -> str:
    """A concrete Bolt action, never a bare category word.

    The old fallback was `beat.bolt_action or scene.bolt_mode`, and that could not work:
    validate_longform_story forces bolt_mode into {measurement, demonstration, warning, reaction,
    assistance}, every one of which is a member of USEFUL_BOLT_PURPOSES — the exact set
    `action_is_specific` rejects. So whenever the model omitted bolt_action, the code substituted a
    value guaranteed to fail its own validator, and the run died on bolt_without_useful_action
    before any spend.

    Naming what the action is performed ON turns the category back into a specific action, which is
    what the check is actually asking for.
    """
    action = _text(beat.get("bolt_action"))
    if action and action.casefold() not in USEFUL_BOLT_PURPOSES:
        return action
    mode = _text(scene.get("bolt_mode")) or _text(beat.get("purpose")) or "demonstration"
    target = _text(subject) or _text(beat.get("visual"))
    if not target:
        return action or ""
    verb = {"measurement": "measures", "demonstration": "demonstrates", "warning": "warns about",
            "reaction": "reacts to", "assistance": "helps with", "test": "tests",
            "decision": "decides on", "action": "acts on"}.get(mode.casefold(), "demonstrates")
    return f"{verb} {target}"


def _state_from_beat(scene: dict, beat: dict, scene_index: int, state_index: int,
                     pack: dict, *, opening: bool) -> dict:
    purpose = _text(beat.get("purpose")).casefold() or ("setup" if state_index == 0 else "evidence")
    source = _text(beat.get("source")).casefold()
    strategy = _text(beat.get("asset_strategy")).casefold()
    if strategy not in ASSET_STRATEGIES:
        strategy = ("detail_reframe" if source in {"detail", "reframe", "crop"}
                    else ("distinct" if state_index or source in {"broll", "alternate", "distinct"}
                          else "master"))
    pure_evidence = bool(beat.get("pure_evidence", purpose in PURE_EVIDENCE_PURPOSES))
    # Scene-level mascot presence is permission, not a command to paste Bolt into every view.
    include_bolt = (bool(scene.get("mascot_present")) and not pure_evidence
                    and bool(beat.get("bolt_visible", purpose == "action")))
    include_human = bool(scene.get("human_present")) and bool(
        beat.get("human_visible", not pure_evidence or purpose in {"measurement", "test"}))
    before = _text(beat.get("state_before"))
    after = _text(beat.get("state_after")) or _text(beat.get("visual"))
    required = _list(beat.get("required_objects"))
    if not required and after:
        required = [after]
    opening_label = _text(pack.get("opening_object", {}).get("label"))
    # The opening object's exact initial state belongs only to the establishing frame. Later
    # states must be free to transform that same object (lit candle -> extinguished candle).
    if scene_index == 0 and state_index == 0 and opening_label and opening_label not in required:
        required.append(opening_label)
    forbidden = _list(beat.get("forbidden_objects"))
    if pure_evidence and "Bolt" not in forbidden:
        forbidden.append("Bolt")
    asset_id = f"asset:s{scene_index + 1:03d}:e{state_index + 1:02d}"
    source_asset_id = ""
    if strategy == "detail_reframe":
        # Reframe the state that immediately introduced the evidence, not always the master.
        source_index = max(1, state_index)
        source_asset_id = f"asset:s{scene_index + 1:03d}:e{source_index:02d}"
    references = []
    if include_human:
        references.extend([
            pack["human"]["reference_asset_id"], pack["human"]["clothing_id"]])
    if include_bolt:
        references.append(pack["bolt"]["reference_asset_id"])
    return {
        "state_id": f"state:s{scene_index + 1:03d}:e{state_index + 1:02d}",
        "asset_id": asset_id,
        "scene_index": scene_index,
        "opening": opening,
        "anchor_phrase": _text(beat.get("anchor_phrase")),
        "purpose": purpose,
        "visual": _text(beat.get("visual")) or after,
        "state_before": before,
        "state_after": after,
        "required_objects": required,
        "forbidden_objects": forbidden,
        "asset_strategy": strategy,
        "source_asset_id": source_asset_id,
        "detail_target": _text(beat.get("detail_target")),
        "pure_evidence": pure_evidence,
        "include_human": include_human,
        "include_bolt": include_bolt,
        # `after` already falls back to beat["visual"] where it exists; referencing a bare `visual`
        # here was a NameError waiting for the first Bolt beat with no state_after — it would crash
        # instead of producing the incomplete_object_state_spec error this validator is built to
        # report.
        "bolt_action": _derive_bolt_action(beat, scene, after) if include_bolt else "",
        "reference_ids": references,
        "human_identity_id": pack["human"]["identity_id"] if include_human else "",
        "clothing_id": pack["human"]["clothing_id"] if include_human else "",
        "location_id": pack["first_act_location"]["location_id"] if opening else "",
        "opening_object_id": pack["opening_object"]["object_id"] if scene_index == 0 else "",
        # Planning metadata never awards a retention event. The asset verifier owns this field.
        "new_information": False,
        "verified_visible_information": False,
        "asset_status": "planned",
        "rejection_reasons": [],
    }


def compile_evidence_plan(script: dict) -> dict:
    """Compile narration beats into explicit visual states without pretending crops are evidence."""
    scenes = script.get("scenes") or []
    pack = build_continuity_pack(script)
    opening_count = int(pack["opening_scene_count"])
    scene_plans = []
    for scene_index, scene in enumerate(scenes):
        opening = scene_index < opening_count
        beats = _visual_beats(scene)
        states = [
            _state_from_beat(scene, beat, scene_index, state_index, pack, opening=opening)
            for state_index, beat in enumerate(beats[:4])
        ]
        scene_plans.append({
            "scene_index": scene_index,
            "story_role": _text(scene.get("story_role")),
            "evidence_id": _text(scene.get("evidence_id")),
            "opening": opening,
            "states": states,
        })

    callback_index = int(pack["callback"]["scene_index"])
    if scene_plans and 0 <= callback_index < len(scene_plans):
        callback_states = scene_plans[callback_index]["states"]
        callback_scene = scenes[callback_index]
        callback_anchor = _text(callback_scene.get("motion_anchor_phrase"))
        if not callback_anchor and callback_states:
            callback_anchor = _text(callback_states[-1].get("anchor_phrase"))
        callback_states.append({
            "state_id": f"state:s{callback_index + 1:03d}:callback",
            "asset_id": f"asset:s{callback_index + 1:03d}:callback",
            "scene_index": callback_index,
            "opening": False,
            "anchor_phrase": callback_anchor,
            "purpose": "callback",
            "visual": f"Return to the exact opening object: {pack['opening_object']['label']}",
            "state_before": "the object carried the opening anomaly",
            "state_after": "the same object is reinterpreted by the final answer",
            "required_objects": [pack["opening_object"]["label"]],
            "forbidden_objects": [],
            "asset_strategy": "exact_reuse",
            "source_asset_id": pack["callback"]["reuse_source_asset_id"],
            "detail_target": "",
            "pure_evidence": False,
            "include_human": False,
            "include_bolt": False,
            "reference_ids": [],
            "human_identity_id": "",
            "clothing_id": "",
            "location_id": "",
            "opening_object_id": pack["opening_object"]["object_id"],
            "new_information": False,
            "verified_visible_information": False,
            "asset_status": "planned",
            "rejection_reasons": [],
        })
    plan = {"version": 1, "continuity_pack": pack, "scenes": scene_plans}
    plan["validation"] = validate_evidence_plan(plan)
    return plan


MAX_VISUAL_STATE_SECONDS = 3.5


def validate_evidence_plan(plan: dict, *, require_verified_assets: bool = False,
                           opening_only: bool = False) -> dict:
    errors: list[dict] = []
    pack = plan.get("continuity_pack") if isinstance(plan, dict) else None
    scenes = plan.get("scenes") if isinstance(plan, dict) else None
    if not isinstance(pack, dict):
        errors.append(_issue("missing_continuity_pack", "The evidence plan has no continuity pack."))
        pack = {}
    if not isinstance(scenes, list) or not scenes:
        errors.append(_issue("missing_evidence_scenes", "The evidence plan contains no scenes."))
        scenes = []

    opening_cuts = []
    compiled_states = []
    useful_bolt_states = []
    seen_state_ids: set[str] = set()
    seen_asset_ids: set[str] = set()
    for scene_plan in scenes:
        scene_index = int(scene_plan.get("scene_index") or 0)
        states = scene_plan.get("states") if isinstance(scene_plan.get("states"), list) else []
        opening = bool(scene_plan.get("opening"))
        # Upper bound raised from 4 to 6. The hold ceiling is physics -- a state held longer
        # than MAX_VISUAL_STATE_SECONDS is rejected downstream -- and a 45-word opening scene
        # needs 5 states to satisfy it. Capping at 4 made such a scene unsatisfiable: two rules,
        # each defensible, that cannot both hold. The floor of 2 stays, because an opening beat
        # with one state is a still frame.
        if opening and not 2 <= len(states) <= 6:
            errors.append(_issue(
                "opening_state_count", "Every opening beat requires two to six evidence states.",
                scene=scene_index + 1))
        accepted_distinct = set()
        verified_detail = False
        for state_index, state in enumerate(states):
            if _text(state.get("purpose")) != "callback":
                compiled_states.append(state)
            state_id = _text(state.get("state_id"))
            asset_id = _text(state.get("asset_id"))
            if not state_id or state_id in seen_state_ids:
                errors.append(_issue("invalid_state_id", "Evidence state IDs must be present and unique.",
                                     scene=scene_index + 1, state_id=state_id))
            if not asset_id or asset_id in seen_asset_ids:
                errors.append(_issue("invalid_asset_id", "Evidence asset IDs must be present and unique.",
                                     scene=scene_index + 1, state_id=state_id))
            seen_state_ids.add(state_id)
            seen_asset_ids.add(asset_id)
            for field in ("state_before", "state_after", "required_objects", "forbidden_objects"):
                value = state.get(field)
                if (field.endswith("objects") and not isinstance(value, list)) or (
                        not field.endswith("objects") and not _text(value)):
                    errors.append(_issue(
                        "incomplete_object_state_spec",
                        f"Evidence state is missing {field}.", scene=scene_index + 1,
                        state_id=state_id))
            if not state.get("required_objects"):
                errors.append(_issue(
                    "missing_required_objects", "Every evidence state must name visible proof.",
                    scene=scene_index + 1, state_id=state_id))
            if (_text(state.get("state_before")).casefold()
                    == _text(state.get("state_after")).casefold()):
                errors.append(_issue(
                    "unchanged_evidence_state", "State before and after are not visibly different.",
                    scene=scene_index + 1, state_id=state_id))
            strategy = _text(state.get("asset_strategy"))
            if strategy not in ASSET_STRATEGIES:
                errors.append(_issue("invalid_asset_strategy", "Unknown evidence asset strategy.",
                                     scene=scene_index + 1, state_id=state_id))
            if strategy == "detail_reframe" and state.get("new_information") is True \
                    and not state.get("detail_verification_passed"):
                errors.append(_issue(
                    "unverified_reframe_information",
                    "A reframe cannot claim new information before detail verification passes.",
                    scene=scene_index + 1, state_id=state_id))
            if state.get("pure_evidence") and state.get("include_bolt"):
                errors.append(_issue(
                    "bolt_in_pure_evidence", "Pure evidence assets must omit Bolt.",
                    scene=scene_index + 1, state_id=state_id))
            if state.get("pure_evidence") and "bolt" not in {
                    _text(item).casefold() for item in state.get("forbidden_objects") or []}:
                errors.append(_issue(
                    "bolt_not_forbidden_in_evidence",
                    "Pure evidence must explicitly forbid Bolt in the generated pixels.",
                    scene=scene_index + 1, state_id=state_id))
            if state.get("include_bolt"):
                purpose = _text(state.get("purpose")).casefold()
                action = _text(state.get("bolt_action"))
                action_is_specific = bool(action) and action.casefold() not in USEFUL_BOLT_PURPOSES
                if purpose not in USEFUL_BOLT_PURPOSES or not action_is_specific:
                    errors.append(_issue(
                        "bolt_without_useful_action",
                        "Every compiled Bolt state must declare a concrete useful action, not merely "
                        "repeat its measurement, test, reaction, warning, assistance, or decision category.",
                        scene=scene_index + 1, state_id=state_id))
                else:
                    useful_bolt_states.append(state)
            refs = state.get("reference_ids") if isinstance(state.get("reference_ids"), list) else []
            if bool(state.get("include_human")) != (pack.get("human", {}).get("reference_asset_id") in refs):
                errors.append(_issue(
                    "human_reference_mismatch", "Human reference inclusion is not deterministic.",
                    scene=scene_index + 1, state_id=state_id))
            expected_bolt_ref = bool(state.get("include_bolt")) and not state.get("pure_evidence")
            if expected_bolt_ref != (pack.get("bolt", {}).get("reference_asset_id") in refs):
                errors.append(_issue(
                    "bolt_reference_mismatch", "Bolt reference inclusion is not deterministic.",
                    scene=scene_index + 1, state_id=state_id))
            if strategy in {"detail_reframe", "exact_reuse"} and not _text(state.get("source_asset_id")):
                errors.append(_issue(
                    "missing_source_asset", "Reframe/reuse state has no declared source asset.",
                    scene=scene_index + 1, state_id=state_id))
            verify_state = require_verified_assets and (not opening_only or opening)
            if verify_state:
                if _text(state.get("asset_status")) not in ACCEPTED_ASSET_STATUSES:
                    errors.append(_issue(
                        "rejected_or_missing_asset", "Evidence asset was not explicitly accepted.",
                        scene=scene_index + 1, state_id=state_id))
                if strategy in {"master", "distinct", "exact_reuse"} and \
                        _text(state.get("asset_status")) in ACCEPTED_ASSET_STATUSES:
                    accepted_distinct.add(_text(state.get("asset_id")))
                if strategy == "detail_reframe" and state.get("detail_verification_passed"):
                    verified_detail = True
            else:
                if strategy in {"master", "distinct"}:
                    accepted_distinct.add(_text(state.get("asset_id")))
                if strategy == "detail_reframe" and state.get("detail_verification_passed"):
                    verified_detail = True
            if opening and state_index > 0:
                opening_cuts.append(state)
        if opening and len(accepted_distinct) < 2 and not verified_detail:
            errors.append(_issue(
                "insufficient_distinct_evidence_assets",
                "Opening beats need two distinct source/state assets unless a detail reframe is verified.",
                scene=scene_index + 1))

    opening_object = pack.get("opening_object") if isinstance(pack, dict) else {}
    callback = pack.get("callback") if isinstance(pack, dict) else {}
    if not _text(opening_object.get("object_id")) or not _text(opening_object.get("label")):
        errors.append(_issue("missing_opening_object_identity", "Opening object identity is incomplete."))
    if _text(callback.get("reuse_source_asset_id")) != _text(opening_object.get("opening_source_asset_id")):
        errors.append(_issue("callback_asset_mismatch", "Ending does not reuse the exact opening source asset."))
    if _text(callback.get("label")).casefold() != _text(opening_object.get("label")).casefold():
        errors.append(_issue("callback_object_mismatch", "Ending callback object differs from the opening object."))
    human = pack.get("human") if isinstance(pack, dict) else {}
    location = pack.get("first_act_location") if isinstance(pack, dict) else {}
    if not _text(human.get("identity_id")) or not _text(human.get("clothing_id")):
        errors.append(_issue("incomplete_human_continuity", "Human identity or clothing lock is missing."))
    if not _text(location.get("location_id")) or not _text(location.get("label")):
        errors.append(_issue("incomplete_location_continuity", "First-act location lock is missing."))

    bolt_count = len(useful_bolt_states)
    bolt_ratio = bolt_count / max(1, len(compiled_states))
    if compiled_states and bolt_count == 0:
        errors.append(_issue(
            "missing_useful_bolt_state",
            "Long-form requires at least one compiled visual state where Bolt performs useful story work."))
    if bolt_ratio > 0.35:
        errors.append(_issue(
            "bolt_state_budget_exceeded",
            f"Bolt occupies {bolt_ratio:.0%} of compiled visual states; no more than 35% is allowed."))

    verified_cuts = sum(1 for state in opening_cuts if state.get("verified_visible_information"))
    ratio = verified_cuts / len(opening_cuts) if opening_cuts else 0.0
    if require_verified_assets and ratio < 0.70:
        errors.append(_issue(
            "opening_visible_information_ratio",
            f"Only {ratio:.0%} of opening cuts add verified visible information; 70% required."))
    return {
        "version": 1,
        "passed": not errors,
        "opening_cut_count": len(opening_cuts),
        "verified_information_cut_count": verified_cuts,
        "verified_information_ratio": round(ratio, 3),
        "compiled_visual_state_count": len(compiled_states),
        "useful_bolt_state_count": bolt_count,
        "bolt_visual_state_ratio": round(bolt_ratio, 3),
        "rejected_asset_count": sum(
            1 for scene in scenes for state in scene.get("states") or []
            if _text(state.get("asset_status")) == "rejected"),
        "errors": errors,
    }


def record_asset_verification(state: dict, *, asset_path: str,
                              verification: dict | None, generation_error: str = "") -> dict:
    """Record acceptance/rejection explicitly; never convert failure into a disguised reframe."""
    reasons = []
    if generation_error:
        reasons.append(generation_error)
    if not asset_path or not Path(asset_path).is_file():
        reasons.append("asset file is missing")
    if not isinstance(verification, dict):
        reasons.append("asset verifier unavailable or invalid")
    elif not verification.get("passed"):
        reasons.extend(_list(verification.get("reasons")) or ["asset verification failed"])
    state["asset_path"] = asset_path
    state["verification"] = verification or {}
    state["rejection_reasons"] = reasons
    if reasons:
        state["asset_status"] = "rejected"
        state["verified_visible_information"] = False
        state["new_information"] = False
        return state
    state["asset_status"] = ("reused_exact" if state.get("asset_strategy") == "exact_reuse"
                             else "accepted")
    visible = bool(verification.get("visible_information"))
    if state.get("asset_strategy") == "detail_reframe":
        state["detail_verification_passed"] = visible
    state["verified_visible_information"] = visible
    state["new_information"] = visible
    return state


def reuse_exact_asset(source_path: str, output_path: str) -> dict:
    """Copy a callback asset byte-for-byte and return a fail-closed verification result."""
    source = Path(source_path)
    output = Path(output_path)
    if not source.is_file():
        raise FileNotFoundError("exact opening-object source asset is unavailable")
    shutil.copyfile(source, output)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    matched = source_hash == output_hash
    return {
        "passed": matched,
        "visible_information": False,
        "source_sha256": source_hash,
        "exact_reuse_sha256": output_hash,
        "reasons": [] if matched else ["callback bytes differ"],
    }


def evidence_asset_counts(plan: dict) -> dict:
    states = [state for scene in plan.get("scenes") or [] for state in scene.get("states") or []]
    generated = [state for state in states if state.get("asset_strategy") in {"master", "distinct"}]
    reframes = [state for state in states if state.get("asset_strategy") == "detail_reframe"]
    reused = [state for state in states if state.get("asset_strategy") == "exact_reuse"]
    return {
        "planned_state_count": len(states),
        "distinct_source_count": len(generated),
        "reframe_count": len(reframes),
        "exact_reuse_count": len(reused),
        "accepted_count": sum(1 for state in states if state.get("asset_status") in ACCEPTED_ASSET_STATUSES),
        "rejected_count": sum(1 for state in states if state.get("asset_status") == "rejected"),
    }


def validate_evidence_timing(plan: dict, audio_timing: dict) -> dict:
    """Reject state density that would force flash frames before buying any images."""
    errors = []
    scene_timings = audio_timing.get("scenes") if isinstance(audio_timing, dict) else []
    scenes = plan.get("scenes") if isinstance(plan, dict) else []
    if len(scene_timings or []) != len(scenes or []):
        errors.append(_issue(
            "evidence_timing_count_mismatch", "Evidence scenes and measured audio scenes differ."))
        return {"version": 1, "passed": False, "errors": errors}
    intervals = []
    for scene_plan, timing in zip(scenes, scene_timings):
        count = len(scene_plan.get("states") or [])
        duration = float(timing.get("duration_sec") or 0.0)
        interval = duration / count if count else 0.0
        intervals.append(round(interval, 3))
        if count and interval < MIN_EVIDENCE_STATE_SECONDS:
            errors.append(_issue(
                "evidence_states_too_dense",
                f"{count} states in {duration:.2f}s would force {interval:.2f}s flash frames.",
                scene=int(scene_plan.get("scene_index") or 0) + 1))
        # The other side of the same interval. This guarded only the dense end, while the
        # rendered gate hard-fails the sparse end at MAX_VISUAL_STATE_SECONDS -- so a plan
        # could be approved here and be rejectable on arithmetic already known, with the
        # rejection arriving after every image and every second of narration was paid for.
        # A 2-state opening beat is explicitly permitted by opening_state_count and only
        # clears the ceiling if its scene runs under 7s; long-form scenes run about 13s.
        if count and interval > MAX_VISUAL_STATE_SECONDS:
            needed = math.ceil(duration / MAX_VISUAL_STATE_SECONDS)
            errors.append(_issue(
                "evidence_states_too_sparse",
                f"{count} state(s) across {duration:.2f}s holds each for {interval:.2f}s; the "
                f"rendered gate rejects any hold over {MAX_VISUAL_STATE_SECONDS}s. "
                f"Plan at least {needed} states.",
                scene=int(scene_plan.get("scene_index") or 0) + 1))
    return {
        "version": 1, "passed": not errors,
        "minimum_state_seconds": MIN_EVIDENCE_STATE_SECONDS,
        "maximum_state_seconds": MAX_VISUAL_STATE_SECONDS,
        "scene_average_state_seconds": intervals,
        "errors": errors,
    }
