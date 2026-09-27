"""Deterministic high-retention storyboard gate for Nature Shorts.

The shared Nature evidence storyboard answers whether a claim has a visible state.  This module
answers the separate editorial question the octopus pilot exposed: does the *sequence* keep
changing, paying off curiosity, and resisting a swipe?  It is provider-free and runs before any
image or motion purchase.

The contract deliberately mirrors the high-retention toolkit rather than trusting file count as
visual diversity.  Every authored row names its composition, visual language, location, action,
state change, consequence and reference scope.  The renderer consumes the same rows, so this is
not a decorative report that can drift away from production.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any


VERSION = "nature_retention_storyboard_v1"
MINIMUM_SCORE = 82

_WORD = re.compile(r"\b[\w'-]+\b", re.UNICODE)
_STATIC_ACTIONS = {
    "shown", "shows", "seen", "sits", "rests", "remains", "is", "are", "appears",
    "portrait", "view", "close-up", "closeup",
}


def _dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    return dump(mode="json") if callable(dump) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value)).casefold()


def _words(value: Any) -> list[str]:
    return _WORD.findall(_text(value))


def _run_max(values: list[str]) -> int:
    longest = current = 0
    previous = None
    for value in values:
        current = current + 1 if value == previous else 1
        longest = max(longest, current)
        previous = value
    return longest


def _category(name: str, weight: int, earned: float, evidence: dict) -> dict:
    return {
        "name": name,
        "weight": weight,
        "earned": round(max(0.0, min(float(weight), float(earned))), 1),
        "evidence": evidence,
    }


def _issue(issues: list[dict], code: str, message: str, *, domain: str,
           repair: str, automatic_reject: bool = False) -> None:
    issues.append({
        "code": code,
        "domain": domain,
        "message": message,
        "repair": repair,
        "automatic_reject": automatic_reject,
    })


def score_plan(*, narration: str, scenes: list[dict], shots: list[dict],
               storyboard: dict) -> dict:
    """Score one exact script + shot plan against the toolkit's 100-point animatic rubric."""
    board = _dict(storyboard)
    beat_rows = [_dict(item) for item in _list(board.get("beats"))]
    shot_rows = [_dict(item) for item in _list(board.get("shots"))]
    hooks = [_dict(item) for item in _list(board.get("hook_variants"))]
    scene_ids = [_text(item.get("scene_id") or item.get("id")) for item in scenes]
    shot_ids = [_text(item.get("shot_id") or item.get("id")) for item in shots]
    board_scene_ids = [_text(item.get("scene_id")) for item in beat_rows]
    board_shot_ids = [_text(item.get("shot_id")) for item in shot_rows]
    issues: list[dict] = []

    if board.get("version") != VERSION:
        _issue(issues, "storyboard_version", f"Storyboard version must be {VERSION}.",
               domain="contract", repair="Compile a current toolkit storyboard.",
               automatic_reject=True)
    if scene_ids != board_scene_ids:
        _issue(issues, "scene_coverage", "Storyboard beat order does not exactly match narration.",
               domain="contract", repair="Author one ordered storyboard beat for every narration scene.",
               automatic_reject=True)
    if shot_ids != board_shot_ids:
        _issue(issues, "shot_coverage", "Storyboard shot order does not exactly match the render plan.",
               domain="contract", repair="Author one ordered storyboard row for every render shot.",
               automatic_reject=True)

    word_count = len(_words(narration))
    word_min = int(board.get("script_word_min") or 0)
    word_max = int(board.get("script_word_max") or 0)
    word_range_ok = bool(word_min and word_max and word_min <= word_count <= word_max)
    if not word_range_ok:
        _issue(
            issues, "script_word_range",
            f"Narration has {word_count} words; the measured-voice plan requires {word_min}-{word_max}.",
            domain="script",
            repair="Cut repetition or add only story-bearing words, then remeasure the selected voice.",
            automatic_reject=True,
        )

    first_scene = _dict(scenes[0]) if scenes else {}
    first_shot = _dict(shots[0]) if shots else {}
    first_row = shot_rows[0] if shot_rows else {}
    first_motion = _norm(first_shot.get("mode")) == "full motion"
    first_action = len(_words(first_row.get("dominant_action"))) >= 2
    first_change = bool(_text(first_row.get("state_change")))
    selected_hook = _text(board.get("selected_hook"))
    first_narration = _text(first_scene.get("narration") or first_scene.get("vo"))
    selected_aligned = bool(selected_hook and _norm(selected_hook) in _norm(first_narration))
    frame_one_checks = [first_motion, first_action, first_change, selected_aligned]
    if not all(frame_one_checks):
        _issue(issues, "first_frame_action",
               "The selected spoken hook and an active, changing first frame are not locked together.",
               domain="script", repair="Open on motion that visibly proves the selected hook.",
               automatic_reject=True)
    first_frame = _category("first_frame_stopping_power", 15,
                            15 * sum(frame_one_checks) / len(frame_one_checks), {
        "full_motion": first_motion, "dominant_action": first_action,
        "state_change": first_change, "selected_hook_matches_scene_1": selected_aligned,
    })

    strategies = {_norm(item.get("strategy")) for item in hooks if _text(item.get("strategy"))}
    unique_hook_lines = {_norm(item.get("line")) for item in hooks if _text(item.get("line"))}
    hook_options_ok = len(hooks) >= 3 and len(strategies) >= 3 and len(unique_hook_lines) >= 3
    second_loop = _text(board.get("second_open_loop"))
    promise_checks = [hook_options_ok, bool(second_loop), selected_aligned]
    if not hook_options_ok:
        _issue(issues, "hook_variants",
               "The plan does not compare three genuinely different hook strategies.",
               domain="script",
               repair="Write and compare catastrophe, mystery/comparison, and reversal hooks.")
    if not second_loop:
        _issue(issues, "second_open_loop", "The hook has no second curiosity gap.",
               domain="script", repair="Open a new concrete question immediately after the first answer.")
    promise_stack = _category("promise_stack_range", 10,
                              10 * sum(promise_checks) / len(promise_checks), {
        "hook_variants": len(hooks), "strategies": sorted(strategies),
        "second_open_loop": second_loop,
    })

    row_by_shot = {row.get("shot_id"): row for row in shot_rows}
    proof_rows = 0
    for shot in shots:
        row = row_by_shot.get(_text(shot.get("shot_id") or shot.get("id"))) or {}
        if (_text(row.get("dominant_action")) and _text(row.get("state_change"))
                and _text(row.get("mini_payoff"))):
            proof_rows += 1
    proof_ratio = proof_rows / max(1, len(shots))
    if proof_ratio < 1:
        _issue(issues, "visual_proof_rows",
               f"Only {proof_rows}/{len(shots)} shots declare action, change and payoff.",
               domain="visual",
               repair="Replace descriptive poses with visible verbs and before-to-after proof.")
    audio_visual = _category("audio_visual_proof", 15, 15 * proof_ratio, {
        "complete_rows": proof_rows, "shot_count": len(shots),
    })

    payoffs = [bool(_text(row.get("mini_payoff"))) for row in beat_rows]
    loops = [bool(_text(row.get("opens_loop"))) for row in beat_rows[:-1]]
    payoff_ratio = sum(payoffs) / max(1, len(payoffs))
    loop_ratio = sum(loops) / max(1, len(loops))
    mini_earned = 15 * (0.65 * payoff_ratio + 0.35 * loop_ratio)
    if payoff_ratio < 1 or loop_ratio < 1:
        _issue(issues, "mini_payoff_density",
               "Every beat does not both reward attention and hand off curiosity to the next beat.",
               domain="script",
               repair="Give each beat a concrete reveal; give every non-final beat a new open loop.")
    mini_payoffs = _category("mini_payoff_density", 15, mini_earned, {
        "beats_with_payoff": sum(payoffs), "beat_count": len(beat_rows),
        "nonfinal_beats_with_open_loop": sum(loops),
    })

    consequences = [_norm(row.get("consequence_category")) for row in shot_rows]
    consequence_types = {value for value in consequences if value}
    repeated_consequence_pairs = [
        [shot_rows[index - 1].get("shot_id"), shot_rows[index].get("shot_id")]
        for index in range(1, len(consequences))
        if consequences[index] and consequences[index] == consequences[index - 1]
    ]
    consequence_checks = [len(consequence_types) >= 4, not repeated_consequence_pairs]
    if not all(consequence_checks):
        _issue(issues, "consequence_variety",
               "The sequence repeats an adjacent consequence or uses fewer than four consequence types.",
               domain="visual",
               repair="Alternate behavior, mechanism, development, pressure, scale and payoff evidence.",
               automatic_reject=bool(repeated_consequence_pairs))
    consequence_variety = _category("consequence_variety", 10,
                                    10 * sum(consequence_checks) / len(consequence_checks), {
        "types": sorted(consequence_types), "repeated_adjacent": repeated_consequence_pairs,
    })

    modes = [_norm(row.get("visual_mode")) for row in shot_rows]
    scales = [_norm(row.get("shot_scale")) for row in shot_rows]
    locations = [_norm(row.get("location_id")) for row in shot_rows]
    compositions = [_norm(row.get("composition_id")) for row in shot_rows]
    adjacent_composition_repeats = [
        [shot_rows[index - 1].get("shot_id"), shot_rows[index].get("shot_id")]
        for index in range(1, len(compositions))
        if compositions[index] and compositions[index] == compositions[index - 1]
    ]
    reset_checks = [
        len({value for value in modes if value}) >= 4,
        len({value for value in scales if value}) >= 3,
        len({value for value in locations if value}) >= 2,
        not adjacent_composition_repeats,
        _run_max(modes) <= 2,
    ]
    if not all(reset_checks):
        _issue(issues, "visual_resets",
               "The board lacks the required visual-language, scale, location or composition resets.",
               domain="visual",
               repair="Use at least four visual modes, three shot scales, two spatial contexts, and no repeated adjacent composition.",
               automatic_reject=True)
    visual_resets = _category("visual_premise_resets", 10,
                              10 * sum(reset_checks) / len(reset_checks), {
        "visual_modes": sorted({value for value in modes if value}),
        "shot_scales": sorted({value for value in scales if value}),
        "locations": sorted({value for value in locations if value}),
        "max_same_mode_run": _run_max(modes),
        "adjacent_composition_repeats": adjacent_composition_repeats,
    })

    active_rows = 0
    for row in shot_rows:
        words = {_norm(word) for word in _words(row.get("dominant_action"))}
        if words and not words.issubset(_STATIC_ACTIONS):
            active_rows += 1
    action_ratio = active_rows / max(1, len(shot_rows))
    if action_ratio < 0.8:
        _issue(issues, "dominant_action_density",
               f"Only {active_rows}/{len(shot_rows)} shots contain a meaningful visible action.",
               domain="visual", repair="Give the animal, eggs, water or environment a readable verb in at least 80% of shots.")
    action_score = _category("subject_action_and_interaction", 10, 10 * min(1, action_ratio / 0.8), {
        "active_rows": active_rows, "shot_count": len(shot_rows),
    })

    functions = [_norm(row.get("retention_function")) for row in beat_rows]
    predictability_checks = [
        bool(second_loop),
        len({value for value in functions if value}) >= 4,
        any(value in {"reversal", "reinterpretation", "verdict"} for value in functions),
    ]
    if not all(predictability_checks):
        _issue(issues, "predictability_control",
               "The remaining story can be predicted too early because it lacks a reset or reversal.",
               domain="script", repair="Add a supported hinge and a later reinterpretation, not another synonym for the setup.")
    predictability = _category("predictability_control", 5,
                               5 * sum(predictability_checks) / len(predictability_checks), {
        "retention_functions": functions, "second_open_loop": second_loop,
    })

    mute_story = [_text(item) for item in _list(board.get("mute_story")) if _text(item)]
    mute_checks = [len(mute_story) >= 4, proof_ratio >= 0.8]
    if not all(mute_checks):
        _issue(issues, "silent_comprehension",
               "The board cannot state at least four ordered story facts without narration.",
               domain="visual", repair="Rewrite the visual sequence until setup, mechanism, escalation and payoff read muted.")
    silent = _category("silent_comprehension", 5,
                       5 * sum(mute_checks) / len(mute_checks), {
        "mute_story_steps": len(mute_story), "visual_proof_ratio": round(proof_ratio, 3),
    })

    climax = _text(board.get("climax"))
    final_beat = beat_rows[-1] if beat_rows else {}
    final_row = shot_rows[-1] if shot_rows else {}
    final_checks = [
        bool(climax), bool(_text(final_beat.get("mini_payoff"))),
        _norm(final_row.get("reveal_level")) == "full_payoff",
        bool(_text(final_row.get("dominant_action"))),
    ]
    if not all(final_checks):
        _issue(issues, "final_payoff",
               "The final storyboard row is not the strongest, fully revealed action payoff.",
               domain="script", repair="End on the decisive visible result, not a summary card or repeated narration.",
               automatic_reject=True)
    final_payoff = _category("final_payoff", 5,
                             5 * sum(final_checks) / len(final_checks), {
        "climax": climax, "final_reveal": final_row.get("reveal_level"),
    })

    reference_scopes = [_norm(row.get("reference_scope")) for row in shot_rows]
    allowed_scopes = {"none", "continuity_group", "explicit_subject"}
    invalid_scopes = [scope for scope in reference_scopes if scope not in allowed_scopes]
    groups = [_norm(row.get("continuity_group")) for row in shot_rows
              if _norm(row.get("reference_scope")) == "continuity_group"]
    missing_groups = [row.get("shot_id") for row in shot_rows
                      if _norm(row.get("reference_scope")) == "continuity_group"
                      and not _text(row.get("continuity_group"))]
    overused_groups = {key: count for key, count in Counter(groups).items() if key and count > 2}
    if invalid_scopes or missing_groups or overused_groups:
        _issue(issues, "reference_scope",
               "Continuity references are invalid or broad enough to freeze composition across the story.",
               domain="visual",
               repair="Use no reference for new compositions; reuse a group reference only for an intentional two-shot before/after.",
               automatic_reject=True)

    categories = [
        first_frame, promise_stack, audio_visual, mini_payoffs, consequence_variety,
        visual_resets, action_score, predictability, silent, final_payoff,
    ]
    score = round(sum(item["earned"] for item in categories))
    automatic_rejections = [item["code"] for item in issues if item["automatic_reject"]]
    script_issues = [item for item in issues if item["domain"] in {"script", "contract"}]
    visual_issues = [item for item in issues if item["domain"] in {"visual", "contract"}]
    passed = score >= MINIMUM_SCORE and not automatic_rejections
    if score < MINIMUM_SCORE:
        _issue(issues, "minimum_score",
               f"Storyboard scored {score}/100; {MINIMUM_SCORE} is required before visual spending.",
               domain="contract", repair="Apply the category-specific repairs and rescore the same immutable plan.")
    return {
        "version": VERSION,
        "name": "Nature storyboard structural compliance",
        "assessment_type": "structural_compliance_not_editorial_quality",
        "semantic_review": "separate_review_required",
        "passed": passed,
        "score": score,
        "minimum_score": MINIMUM_SCORE,
        "script_passed": word_range_ok and not script_issues,
        "visual_passed": not visual_issues,
        "automatic_rejections": automatic_rejections,
        "categories": categories,
        "metrics": {
            "word_count": word_count,
            "script_word_range": [word_min, word_max],
            "beat_count": len(beat_rows),
            "shot_count": len(shot_rows),
            "visual_mode_count": len({value for value in modes if value}),
            "shot_scale_count": len({value for value in scales if value}),
            "location_count": len({value for value in locations if value}),
            "consequence_type_count": len(consequence_types),
            "global_first_frame_reference": any(scope == "global" for scope in reference_scopes),
        },
        "issues": issues,
    }


def score_directed_spec(payload: dict | Any) -> dict:
    """Score the retention contract embedded in a normalized directed Nature Short spec."""
    data = _dict(payload)
    nature = _dict(data.get("nature_short"))
    return score_plan(
        narration=" ".join(_text(_dict(scene).get("narration"))
                           for scene in _list(data.get("narration"))),
        scenes=[_dict(scene) for scene in _list(data.get("narration"))],
        shots=[_dict(shot) for shot in _list(data.get("shots"))],
        storyboard=_dict(nature.get("retention_storyboard")),
    )


def score_episode(episode: dict) -> dict:
    """Score the authoring episode before it is converted to a paid directed contract."""
    beats = [_dict(beat) for beat in _list(episode.get("beats"))]
    shots = []
    for beat in beats:
        for state in _list(beat.get("visual_beats")):
            state = _dict(state)
            shots.append({
                "shot_id": _text(state.get("id")),
                "mode": _text(state.get("render_mode") or "Still"),
            })
    return score_plan(
        narration=" ".join(_text(beat.get("vo")) for beat in beats),
        scenes=[{"scene_id": _text(beat.get("id")), "narration": _text(beat.get("vo"))}
                for beat in beats],
        shots=shots,
        storyboard=_dict(episode.get("retention_storyboard")),
    )
