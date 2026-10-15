"""Opening retry: re-cut a weak 45-second opening on the pictures already bought.

The 45-second Retention Readiness grade (retention_readiness.score_retention_readiness, scored at
the illustrated lane's 45-second gate) was computed, logged and written to disk, and nothing acted
on it. Every D opening recorded so far (ten of them, 2026-09-30 to 2026-10-14) is the same failure:
`semantic_sync`, fewer than 70% of the opening's cuts landing on their narration phrase, which caps
the score at 69. Underneath the cap those openings score 81-94. The cuts are good pictures placed
at the wrong instant -- anchors less than 1.5 s apart, one anchor shared by two states, a last
anchor too close to the scene end -- not bad pictures.

The score is deterministic given the plan and the measured word timings, so a candidate re-cut is
scored in milliseconds before anything is rendered. This module is that planner. It is PURE: no
file is read or written and no provider is called inside it. The pipeline gathers the inputs,
supplies the one optional language-model call (R2) as an injected function, applies the chosen
edits to the shared evidence-state lists, and persists the decision.

What a re-cut can move, and what it cannot. Only the Visual component (20 points) changes under a
plan-only re-cut. Audio is fixed by which story roles fall inside the window; the opening contract,
narrative propulsion and packaging come from whole-script validation. So the best any re-cut can
reach is `round(100 * (raw - visual + 20) / assessed_max)`. Under 80 the shortfall is in the script
(bees_v9: one 49 s setup scene, ceiling 75) and no re-cut is attempted.

The ladder, cheapest first, all on the plan before the render:

  R1  $0, deterministic. (i) drop crowded detail-reframe crops -- crops of a picture already on
      screen; (ii) move a crowded anchor back to the start of its own clause or sentence, verbatim;
      (iii) drop crowded or duplicate distinct states down to the opening-assets floor. Never the
      scene master, the callback source, a state another state crops or reuses, or a state with a
      paid motion clip (dropping motion would inflate motion_sync).
  R2  one language-model call, about $0.01-0.03, only when R1 found nothing and the ceiling allows
      B: new verbatim anchors for the states R1 could not place, validated deterministically.

A candidate is accepted only at grade B or better with no hard failure, at least 75% of cuts
aligned (0.70 escapes the cap and earns none of the four alignment points), and the rendered gate's
deterministic checks met with margin. Among accepted candidates the one that drops the fewest
distinct pictures wins, then the highest score. No threshold, window or scorer constant is touched:
the retry changes the plan, never the measurement.

Not attempted at the motion preflight. Opening images are keyed by POSITION
(scene_NN_eNN.jpg by state index), so dropping a planned state before purchase would hand a later
state an earlier state's cached file on resume; and the preflight's prediction only equals the
gate's plan when no image is rejected. The gate re-check would still be required, so the gate is
the one place this runs.

Not the editorial opening read. `_evaluate_opening` / `_revise_opening_once` is a separate LLM
read of the opening's wording with its own threshold, and the rendered contract has its own B at 85
that rests mostly on a random three-vote blind judge. Neither is retried here; re-rolling a judge
until it says yes is not a retry rule.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Callable

from longform_evidence import _anchor_key, validate_evidence_plan
from longform_rendered_gate import (
    MOTION_HOLD_ALLOWANCE_SECONDS,
    OPENING_AVG_STATE_RANGE,
    PROVISIONAL_THRESHOLD_PROFILE,
)
from longform_shots import (
    MIN_SHOT_SECONDS,
    _find_phrase_span,
    _timed_words,
    compile_scene_shots,
    shot_plan_metrics,
    split_long_holds,
)
from retention_readiness import build_audio_cues, score_retention_readiness


RETRY_VERSION = "opening-retry-v1"
# The grade-B floor of score_retention_readiness. Named here, never lowered here.
TARGET_SCORE = 80
# 0.70 is the cap line and earns 0 of the 4 alignment points, so an opening sitting there scores
# exactly 80 with no other visual point to spare. 0.75 earns 2.
ACCEPT_ALIGNMENT = 0.75
# The rendered gate rejects a still held past 3.5 s. A candidate that lands ON the line (bees_v16b's
# best drop left a 3.50 s hold) passes by rounding, so the retry requires margin.
ACCEPT_MAX_HOLD_SECONDS = 3.4
SPACING_SECONDS = MIN_SHOT_SECONDS
ACCEPTED_STATUSES = {"accepted", "reused_exact"}
GENERATED_STRATEGIES = {"master", "distinct"}

# Why a cut is not on its phrase. The first five are anchor GEOMETRY -- two anchors closer than a
# shot may be long, one anchor used twice, an anchor earlier than its predecessor, or a last anchor
# too close to the scene end -- and those are the ones a re-cut may fix by dropping or moving.
CROWDING_REASONS = ("crowded_prev", "crowded_next", "duplicate_anchor", "out_of_order",
                    "short_tail")
REASONS = CROWDING_REASONS + ("unresolved_anchor", "repaired_by_neighbour", "even_spacing_fallback")

# Greedy drop searches per decision: from the plan as planned and from the best free candidates.
MAX_GREEDY_SEEDS = 4

# Prices recorded from real launches (usage_ledger.jsonl), for the operator's report only. None of
# these is ever bought automatically.
PAID_OPTIONS = (
    {"option": "re-voice the opening", "approx_usd": "0.10-0.50",
     "notes": "TTS for the changed scenes plus the claim-entailment re-checks a re-voice triggers "
              "(aral-v2's re-voice spent $0.112 TTS and $0.244 entailment). Re-voiced durations "
              "change state capacity, and opening images are keyed by position."},
    {"option": "buy new opening images", "approx_usd": "0.75-1.20",
     "notes": "Every master and distinct state of the opening, verified again."},
    {"option": "replan the opening beats", "approx_usd": "needs a new plan approval",
     "notes": "An approved beat sheet is never replanned automatically."},
)

# Components the opening window cannot change, and where they come from.
_WHOLE_SCRIPT = {"Opening contract", "Narrative propulsion", "Packaging/payoff alignment"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split())


class OpeningContext:
    """Everything the gate's opening plan is built from, gathered once by the caller.

    `states` are the evidence-state lists of the opening scenes. In the pipeline they are the SAME
    list objects the evidence plan holds and both renders read, which is why the planner below
    never mutates them: candidates are built on copies, and only the caller applies the chosen
    edits, once.
    """

    def __init__(self, *, scenes: list[dict], durations: list[float], word_times: list,
                 states: list[list[dict]], script: dict, validation: dict | None,
                 evidence_plan: dict | None = None, planned_counts: list[int] | None = None,
                 scene_indexes: list[int] | None = None, has_alternate: list[bool] | None = None,
                 motion_state_ids=frozenset(), i2v_seconds: float = 5.0,
                 purchased_through: int | None = None,
                 source_change_floor: float | None = None):
        if not (len(scenes) == len(durations) == len(word_times) == len(states)):
            raise ValueError("opening scenes, durations, word timings and states differ in length")
        self.scenes = list(scenes)
        self.durations = [float(value) for value in durations]
        self.word_times = list(word_times)
        self.states = states
        self.script = script or {}
        self.validation = validation or {}
        self.evidence_plan = evidence_plan
        self.planned_counts = list(planned_counts) if planned_counts else [len(s) for s in states]
        self.scene_indexes = list(scene_indexes) if scene_indexes else list(range(len(scenes)))
        self.has_alternate = list(has_alternate) if has_alternate else [False] * len(scenes)
        self.motion_state_ids = frozenset(motion_state_ids or ())
        self.i2v_seconds = float(i2v_seconds)
        self.purchased_through = purchased_through
        self.source_change_floor = float(
            source_change_floor if source_change_floor is not None
            else PROVISIONAL_THRESHOLD_PROFILE["source_change_ratio_threshold"])
        # Scored before the render, so the preview is the one the render will produce: whole
        # scenes, decodable. The Technical component is 5/5 for any opening of 40.5 s or more,
        # and the opening runs until the narration passes 45 s.
        self.preview = {"decodable": True, "duration_sec": round(sum(self.durations), 1),
                        "target_sec": 45}


# ── Compile and score: the same functions the gate uses ───────────────────────────────────────


def compile_opening(ctx: OpeningContext, states: list[list[dict]] | None = None, *,
                    split: bool = True) -> list[list[dict]]:
    """The gate's own plan: compile_scene_shots, then split_long_holds, per opening scene."""
    states = ctx.states if states is None else states
    plan = []
    for k, scene in enumerate(ctx.scenes):
        shots = compile_scene_shots(
            scene, ctx.durations[k], k, has_alternate=bool(ctx.has_alternate[k]),
            i2v_seconds=ctx.i2v_seconds, word_times=ctx.word_times[k],
            evidence_states=states[k], motion_state_ids=ctx.motion_state_ids)
        plan.append(split_long_holds(shots) if split else shots)
    return plan


def cut_alignment(plan: list[list[dict]]) -> tuple[int, int]:
    """(aligned, total) over the cuts shot_plan_metrics counts: within a scene, no hold splits."""
    cuts = [shot for scene in plan for shot in scene[1:]
            if shot.get("asset_strategy") != "hold_split"]
    return sum(1 for shot in cuts if shot.get("semantic_aligned")), len(cuts)


def literal_45_alignment(plan: list[list[dict]], durations: list[float],
                         limit: float = 45.0) -> dict:
    """Alignment over the cuts that start before 45.0 s of narration.

    The graded window is not 45 seconds: whole scenes run until the narration passes 45 s, so
    previews last 46-61 s, and the 1.5 s tail rule pushes unaligned cuts to the END of the last
    opening scene. Both published D openings were D because of seconds 45-55. Reported beside the
    grade, never substituted for it.
    """
    aligned = total = 0
    offset = 0.0
    for scene, duration in zip(plan, durations):
        for shot in scene[1:]:
            if shot.get("asset_strategy") == "hold_split":
                continue
            if offset + float(shot.get("start_sec") or 0.0) < limit:
                total += 1
                aligned += 1 if shot.get("semantic_aligned") else 0
        offset += float(duration)
    return {"aligned": aligned, "cuts": total,
            "ratio": round(aligned / total, 3) if total else 1.0}


def recut_ceiling(report: dict) -> int:
    """The best score any plan-only re-cut can reach: Visual at 20/20, everything else unchanged."""
    visual = next((c for c in report.get("components") or []
                   if _text(c.get("name")).startswith("Visual")), None)
    assessed = int(report.get("assessed_max") or 0)
    if not visual or not assessed:
        return 0
    raw = int(report.get("raw_score") or 0)
    return round(100.0 * (raw - int(visual["score"]) + int(visual["max"])) / assessed)


def uncapped_score(report: dict) -> int:
    """The score before the hard-failure cap. The 69 cap hides progress: 0.059 and 0.667 aligned
    both read 69 D, so the retry tracks this and aligned/total, never the letter."""
    assessed = int(report.get("assessed_max") or 0)
    return round(100.0 * int(report.get("raw_score") or 0) / assessed) if assessed else 0


def rendered_gate_checks(plan: list[list[dict]], source_change_floor: float) -> dict:
    """The rendered gate's deterministic cadence checks, computed on the plan before encoding.

    Same arithmetic as longform_rendered_gate.inspect_rendered_opening over the flattened shots:
    average state length inside OPENING_AVG_STATE_RANGE, no still past the hold limit (here with
    margin, ACCEPT_MAX_HOLD_SECONDS), no motion shot past its clip allowance, and the source-change
    ratio at or above the slideshow line.
    """
    shots = [shot for scene in plan for shot in scene]
    durations = [float(shot.get("duration") or 0.0) for shot in shots]
    stills = [d for shot, d in zip(shots, durations) if shot.get("kind") != "i2v"]
    motion = [d for shot, d in zip(shots, durations) if shot.get("kind") == "i2v"]
    sources = [_text(shot.get("source")) for shot in shots]
    changes = sum(a != b for a, b in zip(sources, sources[1:]))
    average = sum(durations) / len(durations) if durations else 0.0
    max_still = max(stills, default=0.0)
    ratio = changes / max(1, len(shots) - 1)
    low, high = OPENING_AVG_STATE_RANGE
    failures = []
    if not low <= average <= high:
        failures.append(f"average state {average:.2f}s is outside {low}-{high}s")
    if max_still > ACCEPT_MAX_HOLD_SECONDS:
        failures.append(f"a still holds {max_still:.2f}s (limit {ACCEPT_MAX_HOLD_SECONDS}s "
                        "with margin under the 3.5s gate)")
    if any(d > MOTION_HOLD_ALLOWANCE_SECONDS for d in motion):
        failures.append(f"a motion shot holds {max(motion):.2f}s past its clip allowance")
    if ratio < source_change_floor:
        failures.append(f"source-change ratio {ratio:.2f} is under {source_change_floor:.2f}")
    return {"average_state_sec": round(average, 3), "max_still_sec": round(max_still, 3),
            "source_change_ratio": round(ratio, 3), "shot_count": len(shots),
            "passed": not failures, "failures": failures}


def score_opening(ctx: OpeningContext, plan: list[list[dict]]) -> dict:
    """score_retention_readiness with exactly the gate's other inputs."""
    metrics = shot_plan_metrics(plan)
    cues = build_audio_cues(ctx.scenes, ctx.durations)
    opening_script = dict(ctx.script)
    opening_script["scenes"] = list(ctx.scenes)
    report = score_retention_readiness(
        opening_script, ctx.validation, metrics, cues, preview=dict(ctx.preview))
    aligned, cuts = cut_alignment(plan)
    return {"report": report, "metrics": metrics, "score": int(report["score"]),
            "grade": report["grade"], "hard_failures": list(report.get("hard_failures") or []),
            "uncapped": uncapped_score(report), "aligned": aligned, "cuts": cuts,
            "ratio": round(aligned / cuts, 3) if cuts else 1.0,
            "literal_45": literal_45_alignment(plan, ctx.durations)}


# ── Diagnosis ─────────────────────────────────────────────────────────────────────────────────


def _accepted(states: list[dict]) -> list[dict]:
    return [state for state in states if state.get("asset_status") in ACCEPTED_STATUSES]


def _timed(ctx: OpeningContext, k: int) -> list:
    return _timed_words(_text(ctx.scenes[k].get("narration")), ctx.word_times[k],
                        ctx.durations[k])


def _starts(ctx: OpeningContext, k: int, accepted: list[dict], timed=None) -> list[float | None]:
    timed = _timed(ctx, k) if timed is None else timed
    out = []
    for state in accepted:
        span = _find_phrase_span(timed, _text(state.get("anchor_phrase")))
        out.append(float(span[0]) if span else None)
    return out


def _classify(index: int, starts: list, keys: list, duration: float,
              timing_source: str, ids: list) -> tuple[str, list[str]]:
    """Why cut `index` missed its phrase, from the anchors themselves rather than the repair."""
    start = starts[index]
    if start is None:
        return "unresolved_anchor", []
    for j in range(index):
        if (keys[j] and keys[j] == keys[index]) or (
                starts[j] is not None and abs(starts[j] - start) < 0.01):
            return "duplicate_anchor", [ids[j]] if j else []
    # The master always starts at 0.0 whatever its own anchor says; it is the floor of the scene.
    previous = next((j for j in range(index - 1, 0, -1) if starts[j] is not None), 0)
    previous_start = 0.0 if previous == 0 else starts[previous]
    if start < previous_start - 1e-9:
        return "out_of_order", [ids[previous]] if previous else []
    if start - previous_start < SPACING_SECONDS - 1e-9:
        return "crowded_prev", [ids[previous]] if previous else []
    if index == len(starts) - 1 and duration - start < SPACING_SECONDS - 1e-9:
        return "short_tail", []
    following = next((j for j in range(index + 1, len(starts)) if starts[j] is not None), None)
    if following is not None and starts[following] - start < SPACING_SECONDS - 1e-9:
        return "crowded_next", [ids[following]]
    if timing_source == "even_fallback":
        return "even_spacing_fallback", []
    return "repaired_by_neighbour", []


def diagnose_opening(ctx: OpeningContext, states: list[list[dict]] | None = None) -> dict:
    """A reason for every unaligned cut, plus the numbers that say whether a re-cut can help.

    Start from the cut, not the grade. The operator's manual anchor fix on aral-v2 ($0.53) repaired
    two duplicate anchors and missed the real failure, three anchors crowded inside 2.5 s, so the
    opening scored 69 again.
    """
    states = ctx.states if states is None else states
    unsplit = compile_opening(ctx, states, split=False)
    plan = [split_long_holds(shots) for shots in unsplit]
    scored = score_opening(ctx, plan)
    cuts = []
    offset = 0.0
    for k, shots in enumerate(unsplit):
        accepted = _accepted(states[k])
        starts = _starts(ctx, k, accepted)
        keys = [_anchor_key(state.get("anchor_phrase")) for state in accepted]
        ids = [_text(state.get("state_id")) for state in accepted]
        for index in range(1, len(accepted)):
            shot = shots[index]
            aligned = bool(shot.get("semantic_aligned"))
            entry = {
                "scene": int(ctx.scene_indexes[k]) + 1,
                "opening_scene": k,
                "state_id": ids[index],
                "asset_strategy": _text(accepted[index].get("asset_strategy")),
                "anchor_phrase": _text(accepted[index].get("anchor_phrase")),
                "anchor_start_sec": None if starts[index] is None else round(starts[index], 3),
                "cut_start_sec": round(float(shot.get("start_sec") or 0.0), 3),
                "global_start_sec": round(offset + float(shot.get("start_sec") or 0.0), 3),
                "timing_source": _text(shot.get("timing_source")),
                "aligned": aligned,
                "reason": None,
                "conflicts_with": [],
            }
            if not aligned:
                entry["reason"], entry["conflicts_with"] = _classify(
                    index, starts, keys, ctx.durations[k], entry["timing_source"], ids)
            cuts.append(entry)
        offset += ctx.durations[k]
    reasons: dict[str, int] = {}
    for entry in cuts:
        if entry["reason"]:
            reasons[entry["reason"]] = reasons.get(entry["reason"], 0) + 1
    return {
        "cuts": cuts,
        "reasons": reasons,
        "aligned": scored["aligned"],
        "total": scored["cuts"],
        "ratio": scored["ratio"],
        "score": scored["score"],
        "grade": scored["grade"],
        "uncapped_score": scored["uncapped"],
        "hard_failures": scored["hard_failures"],
        "literal_45": scored["literal_45"],
        "ceiling": recut_ceiling(scored["report"]),
    }


def implicated_state_ids(diagnosis: dict) -> list[str]:
    """States a crowding fix may touch: the unaligned crowded cut and the anchor crowding it."""
    out: list[str] = []
    for entry in diagnosis.get("cuts") or []:
        if entry.get("reason") not in CROWDING_REASONS:
            continue
        for state_id in [entry["state_id"]] + list(entry.get("conflicts_with") or []):
            if state_id and state_id not in out:
                out.append(state_id)
    return out


# ── Edits ─────────────────────────────────────────────────────────────────────────────────────


def drop_edit(state: dict, reason: str = "") -> dict:
    return {"op": "drop", "state_id": _text(state.get("state_id")),
            "asset_id": _text(state.get("asset_id")),
            "asset_strategy": _text(state.get("asset_strategy")), "reason": reason}


def reanchor_edit(state: dict, new: str, rung: str, how: str = "") -> dict:
    return {"op": "reanchor", "state_id": _text(state.get("state_id")),
            "old": _text(state.get("anchor_phrase")), "new": new, "rung": rung, "how": how}


def apply_edits(states: list[list[dict]], edits: list[dict]) -> list[list[dict]]:
    """Candidate state lists with the edits applied. Copies; the originals are untouched."""
    drops = {e["state_id"] for e in edits if e.get("op") == "drop"}
    anchors = {e["state_id"]: e["new"] for e in edits if e.get("op") == "reanchor"}
    out = []
    for scene_states in states:
        row = []
        for state in scene_states:
            state_id = _text(state.get("state_id"))
            if state_id in drops:
                continue
            row.append(dict(state, anchor_phrase=anchors[state_id])
                       if state_id in anchors else state)
        out.append(row)
    return out


def apply_edits_in_place(states: list[list[dict]], edits: list[dict]) -> list[str]:
    """Apply the chosen edits to the SHARED lists, or nothing at all.

    Returns the problems that stopped it. A replayed checkpoint whose state ids or old anchors no
    longer match the plan is not applied by halves: the caller decides again instead.
    """
    by_id = {_text(state.get("state_id")): state for scene in states for state in scene}
    problems = []
    for edit in edits:
        state = by_id.get(edit.get("state_id"))
        if state is None:
            problems.append(f"{edit.get('state_id')}: not in the opening plan")
        elif edit.get("op") == "reanchor" and _text(state.get("anchor_phrase")) != edit.get("old"):
            problems.append(f"{edit.get('state_id')}: anchor is "
                            f"{_text(state.get('anchor_phrase'))!r}, not {edit.get('old')!r}")
        elif edit.get("op") not in ("drop", "reanchor"):
            problems.append(f"{edit.get('state_id')}: unknown edit {edit.get('op')!r}")
    if problems:
        return problems
    drops = {e["state_id"] for e in edits if e["op"] == "drop"}
    for edit in edits:
        if edit["op"] == "reanchor":
            state = by_id[edit["state_id"]]
            state["anchor_phrase_before_opening_retry"] = edit["old"]
            state["anchor_phrase"] = edit["new"]
            state["opening_retry"] = {"rung": edit.get("rung"), "how": edit.get("how")}
    for scene_states in states:
        scene_states[:] = [state for state in scene_states
                           if _text(state.get("state_id")) not in drops]
    return []


def _edit_counts(edits: list[dict]) -> dict:
    drops = [e for e in edits if e.get("op") == "drop"]
    return {
        "distinct_dropped": sum(1 for e in drops
                                if e.get("asset_strategy") in GENERATED_STRATEGIES),
        "reframes_dropped": sum(1 for e in drops if e.get("asset_strategy") == "detail_reframe"),
        "reanchored": sum(1 for e in edits if e.get("op") == "reanchor"),
        "edit_count": len(edits),
    }


def edits_phrase(edits: list[dict]) -> str:
    counts = _edit_counts(edits)
    parts = []
    if counts["reframes_dropped"]:
        parts.append(f"dropped {counts['reframes_dropped']} crop" +
                     ("s" if counts["reframes_dropped"] > 1 else ""))
    if counts["distinct_dropped"]:
        parts.append(f"dropped {counts['distinct_dropped']} picture" +
                     ("s" if counts["distinct_dropped"] > 1 else ""))
    if counts["reanchored"]:
        parts.append(f"re-anchored {counts['reanchored']}")
    return ", ".join(parts) or "no edits"


# ── Guards: what a re-cut may never touch ─────────────────────────────────────────────────────


def protected_state_ids(ctx: OpeningContext, states: list[list[dict]] | None = None) -> dict:
    """state_id -> why it may not be dropped."""
    states = ctx.states if states is None else states
    pack = (ctx.evidence_plan or {}).get("continuity_pack") or {}
    callback_source = {
        _text((pack.get("callback") or {}).get("reuse_source_asset_id")),
        _text((pack.get("opening_object") or {}).get("opening_source_asset_id")),
    } - {""}
    every_state = [state for scene in states for state in scene]
    for scene_plan in (ctx.evidence_plan or {}).get("scenes") or []:
        every_state.extend(scene_plan.get("states") or [])
    sourced = {_text(state.get("source_asset_id")): _text(state.get("state_id"))
               for state in every_state if _text(state.get("source_asset_id"))}
    protected = {}
    for scene in states:
        for index, state in enumerate(scene):
            state_id = _text(state.get("state_id"))
            asset_id = _text(state.get("asset_id"))
            if index == 0:
                protected[state_id] = "scene master"
            elif state_id in ctx.motion_state_ids:
                # Dropping a paid motion clip would also inflate motion_sync to 1.0 (+2).
                protected[state_id] = "carries a paid motion clip"
            elif asset_id in callback_source:
                protected[state_id] = "callback reuse source"
            elif asset_id in sourced and sourced[asset_id] != state_id:
                protected[state_id] = f"source of {sourced[asset_id]}"
            elif _text(state.get("asset_strategy")) == "exact_reuse":
                protected[state_id] = "exact reuse"
    return protected


def opening_floor(planned: int) -> int:
    """_opening_assets_policy's floor: at least 70% of the PLANNED states, never fewer than two.

    Counted against the plan, not against what survived verification, so rejections and retry
    drops together can never take a scene below the rule.
    """
    return max(2, math.ceil(0.7 * int(planned)))


def _scene_of(states: list[list[dict]], state_id: str) -> int:
    for k, scene in enumerate(states):
        if any(_text(state.get("state_id")) == state_id for state in scene):
            return k
    return -1


def _droppable(ctx: OpeningContext, states: list[list[dict]], state_id: str,
               protected: dict) -> bool:
    if state_id in protected:
        return False
    k = _scene_of(states, state_id)
    if k < 0:
        return False
    return len(states[k]) - 1 >= opening_floor(ctx.planned_counts[k])


# ── Candidate evaluation ──────────────────────────────────────────────────────────────────────


def _validation_issues(report: dict | None) -> set:
    return {(_text(item.get("code")), item.get("scene"))
            for item in (report or {}).get("errors") or []}


def _validate(ctx: OpeningContext, states: list[list[dict]]) -> dict | None:
    """The gate's own opening validation (validate_evidence_plan, opening_only) on the candidate."""
    plan = ctx.evidence_plan
    if not isinstance(plan, dict) or not isinstance(plan.get("scenes"), list):
        return None
    by_index = {int(ctx.scene_indexes[k]): states[k] for k in range(len(states))}
    scenes = [dict(scene_plan, states=by_index[int(scene_plan.get("scene_index") or 0)])
              if int(scene_plan.get("scene_index") or 0) in by_index else scene_plan
              for scene_plan in plan["scenes"]]
    return validate_evidence_plan(dict(plan, scenes=scenes), require_verified_assets=True,
                                  opening_only=True, purchased_through=ctx.purchased_through)


def evaluate(ctx: OpeningContext, edits: list[dict], *, label: str = "", rung: str = "",
             baseline: dict | None = None) -> dict:
    """Compile, score and check one candidate. Never raises for a bad candidate; it is rejected."""
    states = apply_edits(ctx.states, edits)
    result = {"label": label, "rung": rung, "edits": list(edits), **_edit_counts(edits),
              "compiled": False, "valid": False, "accepted": False, "rejected_because": []}
    try:
        plan = compile_opening(ctx, states)
    except ValueError as exc:
        result["rejected_because"].append(f"does not compile: {str(exc)[:160]}")
        return result
    scored = score_opening(ctx, plan)
    gate = rendered_gate_checks(plan, ctx.source_change_floor)
    validation = _validate(ctx, states)
    result.update({
        "compiled": True, "plan": plan, "states": states, "report": scored["report"],
        "score": scored["score"], "grade": scored["grade"],
        "hard_failures": scored["hard_failures"], "uncapped": scored["uncapped"],
        "aligned": scored["aligned"], "cuts": scored["cuts"], "ratio": scored["ratio"],
        "literal_45": scored["literal_45"], "gate": gate,
        "validation_errors": sorted(_validation_issues(validation), key=str),
        "bolt_ratio": (validation or {}).get("bolt_visual_state_ratio"),
    })
    reasons = result["rejected_because"]
    if not gate["passed"]:
        reasons.extend(gate["failures"])
    if baseline is not None and validation is not None:
        new = (_validation_issues(validation)
               - set(map(tuple, baseline.get("validation_errors") or [])))
        if new:
            reasons.append("opening validation: " + ", ".join(sorted(str(c) for c, _ in new)))
        before = baseline.get("bolt_ratio")
        after = result["bolt_ratio"]
        if after is not None and after > 0.35 and (before is None or after > before):
            reasons.append(f"Bolt ratio {after:.0%} over 35%")
    result["valid"] = not reasons
    misses = acceptance_misses(result["score"], result["grade"], result["hard_failures"],
                               result["ratio"])
    result["accepted"] = result["valid"] and not misses
    reasons.extend(misses)
    return result


def acceptance_misses(score: int, grade: str, hard_failures: list, ratio: float) -> list[str]:
    """What keeps a valid candidate from being accepted; empty when it is."""
    misses = []
    if int(score) < TARGET_SCORE or grade not in ("A", "B"):
        misses.append(f"score {score} {grade} under B")
    if hard_failures:
        misses.append("hard failure(s): " + ", ".join(hard_failures))
    if float(ratio) < ACCEPT_ALIGNMENT:
        misses.append(f"alignment {float(ratio):.0%} under {ACCEPT_ALIGNMENT:.0%}")
    return misses


def _progress(result: dict) -> tuple:
    return (bool(result.get("valid")), not result.get("hard_failures"),
            int(result.get("score") or 0), float(result.get("ratio") or 0.0),
            int(result.get("uncapped") or 0))


def choose(results: list[dict]) -> dict | None:
    """Fewest distinct pictures dropped, then the highest score, then the fewest edits."""
    accepted = [r for r in results if r.get("accepted")]
    if not accepted:
        return None
    return min(enumerate(accepted), key=lambda item: (
        item[1]["distinct_dropped"], -item[1]["score"], -item[1]["ratio"],
        item[1]["edit_count"], item[0]))[1]


def best_attempt(results: list[dict], baseline: dict) -> dict:
    """When nothing is accepted: the valid candidate with the highest score, or the plan as
    planned. A picture or a crop is dropped only for a higher SCORE -- never to move an alignment
    ratio under an unchanged, capped 69 (killerbees01: two crops for 5/15 -> 5/13, still 69 D)."""
    pool = [r for r in results if r.get("valid")
            and int(r.get("score") or 0) > int(baseline.get("score") or 0)]
    if not pool:
        return baseline
    return min(enumerate(pool), key=lambda item: (
        -int(item[1].get("score") or 0), item[1].get("distinct_dropped", 0),
        -float(item[1].get("ratio") or 0.0), item[1].get("edit_count", 0), item[0]))[1]


# ── R1 ────────────────────────────────────────────────────────────────────────────────────────

# A clause ends at sentence or clause punctuation followed by space, or at a spaced dash.
_CLAUSE_END = re.compile(r"(?:[.!?;:,]+[\"'”’)\]]*\s+|\s*[—–]\s*|\s+-\s+)")
_SENTENCE_END = re.compile(r"[.!?]+[\"'”’)\]]*\s+")


def clause_start_anchors(narration: str, anchor: str) -> list[tuple[str, str]]:
    """The anchor moved back to the start of its own clause, and of its own sentence.

    Both are verbatim narration from the clause start through the end of the old anchor, so the
    cut still sits on its own words -- the aral-v2 case: 'it built the canals' becomes 'Through
    the 1960s it built the canals'. A run longer than twelve words keeps its first eight; the
    start is what places the cut.
    """
    text = _norm(narration)
    phrase = _norm(anchor)
    position = text.casefold().find(phrase.casefold()) if phrase else -1
    if position <= 0:
        return []
    end = position + len(phrase)
    out: list[tuple[str, str]] = []
    for how, pattern in (("clause start", _CLAUSE_END), ("sentence start", _SENTENCE_END)):
        start = max((m.end() for m in pattern.finditer(text[:position])), default=0)
        if start >= position:
            continue
        words = text[start:end].split()
        candidate = " ".join(words if len(words) <= 12 else words[:8])
        if candidate and _anchor_key(candidate) != _anchor_key(phrase) and all(
                _anchor_key(candidate) != _anchor_key(seen) for _, seen in out):
            out.append((how, candidate))
    return out


def anchor_fits(ctx: OpeningContext, k: int, scene_states: list[dict], state_id: str,
                phrase: str, *, others: dict | None = None) -> tuple[float | None, str]:
    """(start, "") when `phrase` can carry this state's cut, else (None, why).

    The rules every new anchor must meet, from R1 or from R2: it resolves in the measured words,
    no other state in the scene uses the same words or the same instant, it falls after its
    predecessor and before its successor, at least 1.5 s from each by measured word times, and a
    last anchor leaves at least 1.5 s before the scene ends.
    """
    accepted = _accepted(scene_states)
    ids = [_text(state.get("state_id")) for state in accepted]
    if state_id not in ids:
        return None, "not an accepted state of this scene"
    index = ids.index(state_id)
    if index == 0:
        return None, "the scene master always opens the scene"
    anchors = [(others or {}).get(sid, _text(state.get("anchor_phrase")))
               for sid, state in zip(ids, accepted)]
    anchors[index] = phrase
    timed = _timed(ctx, k)
    starts = []
    for anchor in anchors:
        span = _find_phrase_span(timed, anchor)
        starts.append(float(span[0]) if span else None)
    start = starts[index]
    if start is None:
        return None, "does not resolve in the measured words"
    key = _anchor_key(phrase)
    for j, other in enumerate(anchors):
        if j == index:
            continue
        if _anchor_key(other) == key:
            return None, f"duplicates the anchor of {ids[j]}"
        if j and starts[j] is not None and abs(starts[j] - start) < 0.01:
            return None, f"lands on the same instant as {ids[j]}"
    previous = 0.0 if index == 1 else starts[index - 1]
    if previous is None:
        return None, f"its predecessor {ids[index - 1]} has no measured anchor"
    if start <= previous:
        return None, "out of order"
    if start - previous < SPACING_SECONDS - 1e-9:
        return None, f"{start - previous:.2f}s after its predecessor"
    if index == len(accepted) - 1:
        if ctx.durations[k] - start < SPACING_SECONDS - 1e-9:
            return None, f"leaves {ctx.durations[k] - start:.2f}s before the scene ends"
    else:
        following = starts[index + 1]
        if following is None:
            return None, f"its successor {ids[index + 1]} has no measured anchor"
        if following - start < SPACING_SECONDS - 1e-9:
            return None, f"{following - start:.2f}s before its successor"
    return start, ""


def _reanchor_options(ctx: OpeningContext, states: list[list[dict]], state_id: str) -> list:
    k = _scene_of(states, state_id)
    if k < 0:
        return []
    state = next(s for s in states[k] if _text(s.get("state_id")) == state_id)
    options = []
    for how, phrase in clause_start_anchors(_text(ctx.scenes[k].get("narration")),
                                            _text(state.get("anchor_phrase"))):
        start, _why = anchor_fits(ctx, k, states[k], state_id, phrase)
        if start is not None:
            options.append(reanchor_edit(state, phrase, "R1", how))
    return options


def _sequential_reanchors(ctx: OpeningContext, base_edits: list[dict],
                          state_ids: list[str]) -> list[dict]:
    """Every re-anchor that still fits once the earlier ones are in, first option each."""
    edits = list(base_edits)
    for state_id in state_ids:
        options = _reanchor_options(ctx, apply_edits(ctx.states, edits), state_id)
        if options:
            edits.append(options[0])
    return edits


def r1_candidates(ctx: OpeningContext, diagnosis: dict) -> list[tuple[str, list[dict]]]:
    """Rungs (i) and (ii) of R1, as (label, edits), cheapest first. Rung (iii) is greedy."""
    implicated = implicated_state_ids(diagnosis)
    protected = protected_state_ids(ctx)
    by_id = {_text(s.get("state_id")): s for scene in ctx.states for s in scene}
    candidates: list[tuple[str, list[dict]]] = []

    reframes = [sid for sid in implicated
                if _text(by_id.get(sid, {}).get("asset_strategy")) == "detail_reframe"
                and _droppable(ctx, ctx.states, sid, protected)]
    reframe_drops: list[dict] = []
    for sid in reframes:
        edits = [drop_edit(by_id[sid], "crowded crop of a picture already on screen")]
        candidates.append((f"drop crop {sid}", edits))
        if _droppable(ctx, apply_edits(ctx.states, reframe_drops), sid, protected):
            reframe_drops.append(edits[0])
    if len(reframe_drops) > 1:
        candidates.append(("drop every crowded crop", list(reframe_drops)))

    movable = [sid for sid in implicated if protected.get(sid) != "scene master"]
    for sid in movable:
        for edit in _reanchor_options(ctx, ctx.states, sid):
            candidates.append((f"re-anchor {sid} to its {edit['how']}", [edit]))
    together = _sequential_reanchors(ctx, [], movable)
    if len(together) > 1:
        candidates.append(("re-anchor every crowded anchor", together))
    if reframe_drops:
        combined = _sequential_reanchors(ctx, reframe_drops, movable)
        if len(combined) > len(reframe_drops):
            candidates.append(("drop crowded crops and re-anchor", combined))
    seen, unique = set(), []
    for label, edits in candidates:
        signature = json.dumps(sorted(json.dumps(e, sort_keys=True) for e in edits))
        if signature not in seen:
            seen.add(signature)
            unique.append((label, edits))
    return unique


def r1_drop_greedy(ctx: OpeningContext, seed: dict, baseline: dict,
                   rung: str = "R1") -> list[dict]:
    """Rung (iii): drop crowded or duplicate states one at a time, best first, to the floor.

    Each step tries every eligible single drop on top of the current plan and keeps the one that
    scores best; it stops at an accepted plan, when no drop improves anything, or at the floor.
    Bounded by the floor: a scene can lose at most 30% of its planned states, so a defect like
    bees_c's (one anchor copied across a whole scene, 12 of 23 states to drop) is left to R2
    instead of being hollowed out.
    """
    tried: list[dict] = []
    current = seed
    while True:
        states = apply_edits(ctx.states, current["edits"])
        protected = protected_state_ids(ctx, states)
        by_id = {_text(s.get("state_id")): s for scene in states for s in scene}
        diagnosis = diagnose_opening(ctx, states)
        eligible = [sid for sid in implicated_state_ids(diagnosis)
                    if _text(by_id.get(sid, {}).get("asset_strategy"))
                    in {"distinct", "detail_reframe"}
                    and _droppable(ctx, states, sid, protected)]
        if not eligible:
            return tried
        step = [evaluate(ctx, current["edits"] + [drop_edit(by_id[sid], "crowded anchor")],
                         label=f"{current.get('label') or 'base'} + drop {sid}", rung=rung,
                         baseline=baseline)
                for sid in eligible]
        tried.extend(step)
        best = max(step, key=_progress)
        if best.get("accepted") or _progress(best) <= _progress(current):
            return tried
        current = best


# ── R2 ────────────────────────────────────────────────────────────────────────────────────────

REBIND_SYSTEM = (
    "You place picture cuts on spoken narration. Each picture must appear exactly when the words "
    "that describe it are spoken. You may only choose WHERE a picture starts; you never change "
    "the narration, the pictures or their order. Return ONLY JSON.")


def rebind_request(ctx: OpeningContext, states: list[list[dict]], targets: list[str]) -> dict:
    """The one R2 request: the scenes that hold an unplaced state, with measured word times."""
    scenes = []
    for k, scene_states in enumerate(states):
        accepted = _accepted(scene_states)
        if not any(_text(s.get("state_id")) in targets for s in accepted):
            continue
        timed = _timed(ctx, k)
        starts = _starts(ctx, k, accepted, timed)
        scenes.append({
            "scene": int(ctx.scene_indexes[k]) + 1,
            "duration_sec": round(ctx.durations[k], 2),
            "narration": _norm(ctx.scenes[k].get("narration")),
            "words": [[str(word), round(float(start), 2)] for word, start, _end in timed],
            "pictures_in_order": [
                {"state_id": _text(s.get("state_id")),
                 "shows": _text(s.get("state_after") or s.get("visual"))[:160],
                 "purpose": _text(s.get("purpose")),
                 "anchor_phrase": _text(s.get("anchor_phrase")),
                 "anchor_start_sec": None if start is None else round(start, 2),
                 "rebind": _text(s.get("state_id")) in targets}
                for s, start in zip(accepted, starts)],
        })
    rules = (
        "For every picture marked rebind:true, choose a new anchor_phrase: the words during which "
        "that picture should appear. Rules, all checked by machine and any failure is discarded: "
        "(1) copy the words EXACTLY from that scene's narration, same spelling and case; "
        "(2) no two pictures in a scene may share an anchor or start on the same word; "
        "(3) anchors keep the pictures' order; "
        "(4) using the measured word start times, every anchor starts at least 1.5 seconds after "
        "the previous picture's anchor (the first picture starts at 0.0) and at least 1.5 seconds "
        "before the next picture's anchor; "
        "(5) the last picture's anchor starts at least 1.5 seconds before the scene ends. "
        "Prefer the words that name what the picture shows. Leave out any picture you cannot "
        "place.")
    user = (rules + "\n\n" + json.dumps({"scenes": scenes}, ensure_ascii=False)
            + '\n\nReturn ONLY JSON: {"anchors":[{"state_id":"...","anchor_phrase":"..."}]}')
    return {"system": REBIND_SYSTEM, "user": user, "targets": list(targets),
            "scene_count": len(scenes)}


def validate_rebind(ctx: OpeningContext, states: list[list[dict]], targets: list[str],
                    response: Any) -> tuple[list[dict], list[dict]]:
    """(re-anchor edits, rejections) for an R2 answer. Nothing unchecked is ever applied.

    Each proposal must be a verbatim substring of its scene's narration and meet anchor_fits
    against the scene as proposed. A failing proposal is removed and the rest re-checked, so one
    bad anchor cannot validate or invalidate a neighbour by its own position.
    """
    rejections: list[dict] = []
    if not isinstance(response, dict) or not isinstance(response.get("anchors"), list):
        return [], [{"state_id": "", "reason": "malformed output"}]
    proposals: dict[str, str] = {}
    for item in response["anchors"]:
        if not isinstance(item, dict):
            rejections.append({"state_id": "", "reason": "malformed item"})
            continue
        state_id = _text(item.get("state_id"))
        phrase = _norm(item.get("anchor_phrase"))
        if state_id not in targets:
            rejections.append({"state_id": state_id, "reason": "not a state R1 could not place"})
        elif state_id in proposals:
            rejections.append({"state_id": state_id, "reason": "proposed twice"})
        elif not phrase:
            rejections.append({"state_id": state_id, "reason": "empty anchor"})
        else:
            proposals[state_id] = phrase
    edits: list[dict] = []
    for k, scene_states in enumerate(states):
        narration = _norm(ctx.scenes[k].get("narration"))
        ids = [_text(s.get("state_id")) for s in _accepted(scene_states)]
        mine = {sid: phrase for sid, phrase in proposals.items() if sid in ids}
        for sid in list(mine):
            if mine[sid] not in narration:
                rejections.append({"state_id": sid, "anchor_phrase": mine.pop(sid),
                                   "reason": "not a verbatim substring of the narration"})
        while mine:
            failed = {}
            for sid, phrase in mine.items():
                start, why = anchor_fits(ctx, k, scene_states, sid, phrase, others=mine)
                if start is None:
                    failed[sid] = why
            if not failed:
                break
            for sid, why in failed.items():
                rejections.append({"state_id": sid, "anchor_phrase": mine.pop(sid), "reason": why})
        by_id = {_text(s.get("state_id")): s for s in scene_states}
        for sid in ids:
            if sid in mine:
                edits.append(reanchor_edit(by_id[sid], mine[sid], "R2", "language-model re-bind"))
    return edits, rejections


def _merge_reanchors(edits: list[dict], extra: list[dict]) -> list[dict]:
    replaced = {e["state_id"] for e in extra}
    return [e for e in edits if not (e.get("op") == "reanchor" and e["state_id"] in replaced)] \
        + list(extra)


# ── The decision ──────────────────────────────────────────────────────────────────────────────


def _summary(result: dict) -> dict:
    report = result.get("report") or {}
    return {
        "score": result.get("score"), "grade": result.get("grade"),
        "uncapped_score": result.get("uncapped"),
        "raw_score": report.get("raw_score"), "assessed_max": report.get("assessed_max"),
        "hard_failures": result.get("hard_failures"),
        "aligned": result.get("aligned"), "cuts": result.get("cuts"), "ratio": result.get("ratio"),
        "literal_45": result.get("literal_45"), "gate": result.get("gate"),
        "components": [{"name": c["name"], "score": c["score"],
                        "assessed_max": c["assessed_max"], "notes": c.get("notes") or []}
                       for c in report.get("components") or []],
    }


def _candidate_row(result: dict) -> dict:
    return {"label": result.get("label"), "rung": result.get("rung"),
            "edits": [{k: e.get(k) for k in ("op", "state_id", "new") if e.get(k)}
                      for e in result.get("edits") or []],
            "score": result.get("score"), "grade": result.get("grade"),
            "aligned": result.get("aligned"), "cuts": result.get("cuts"),
            "ratio": result.get("ratio"), "distinct_dropped": result.get("distinct_dropped"),
            "accepted": bool(result.get("accepted")),
            "rejected_because": result.get("rejected_because") or []}


def below_b_axes(report: dict) -> list[dict]:
    """Where the points a re-cut cannot reach were lost, per component."""
    rows = []
    for component in report.get("components") or []:
        name = _text(component.get("name"))
        if name.startswith("Visual") or name == "Technical delivery":
            continue
        lost = int(component.get("assessed_max") or 0) - int(component.get("score") or 0)
        if lost <= 0:
            continue
        rows.append({
            "component": name, "score": component.get("score"),
            "assessed_max": component.get("assessed_max"), "points_lost": lost,
            "measured_over": ("the whole script" if name in _WHOLE_SCRIPT
                              else "the story roles inside the opening window"),
            "notes": component.get("notes") or [],
        })
    return rows


def decide_opening_retry(ctx: OpeningContext, *,
                         rebind: Callable[[dict], tuple[Any, float]] | None = None) -> dict:
    """Diagnose, then climb the ladder. Returns the decision; applies nothing.

    `rebind` is R2's language-model call: request dict in, (parsed JSON or None, USD) out. It is
    called at most once, and only when R1 found no passing candidate and B is within the re-cut
    ceiling.
    """
    decision = _decide(ctx, rebind)
    edits = decision.get("edits") or []
    # The edits restated for a reader of opening_retry.json; `edits` is what a replay applies.
    decision["dropped_state_ids"] = [e["state_id"] for e in edits if e.get("op") == "drop"]
    decision["reanchored"] = [{k: e.get(k) for k in ("state_id", "old", "new", "rung", "how")}
                              for e in edits if e.get("op") == "reanchor"]
    return decision


def _decide(ctx: OpeningContext, rebind) -> dict:
    baseline = evaluate(ctx, [], label="as planned", rung="")
    baseline_for_compare = {"validation_errors": baseline.get("validation_errors") or [],
                            "bolt_ratio": baseline.get("bolt_ratio")}
    diagnosis = diagnose_opening(ctx)
    ceiling = diagnosis["ceiling"]
    decision: dict = {
        "version": RETRY_VERSION,
        "decided": True,
        "before": _summary(baseline),
        "ceiling": ceiling,
        "diagnosis": diagnosis,
        "rung": None,
        "edits": [],
        "candidates": [],
        "cost_usd": 0.0,
        "llm_calls": 0,
        "r2": None,
    }
    triggered = baseline["score"] < TARGET_SCORE or bool(baseline["hard_failures"])
    decision["triggered"] = triggered
    if not triggered:
        decision.update(outcome="not_needed", after=decision["before"])
        return decision
    if ceiling < TARGET_SCORE:
        # The shortfall is in the script. Nothing on the plan can reach B, so nothing is tried.
        decision.update(outcome="script_shortfall", after=decision["before"],
                        below_b_axes=below_b_axes(baseline["report"]))
        return decision

    results: list[dict] = []
    for label, edits in r1_candidates(ctx, diagnosis):
        results.append(evaluate(ctx, edits, label=label, rung="R1", baseline=baseline_for_compare))
    free = sorted((r for r in results if r.get("valid") and r["distinct_dropped"] == 0),
                  key=_progress, reverse=True)
    seed = free[0] if free and _progress(free[0]) > _progress(baseline) else baseline
    if not choose(results):
        # A greedy search is local, so it starts from more than one place. wolves01: dropping the
        # crowded crop first is the best free move, and it leaves that scene at its floor, so the
        # duplicate anchor beside it can no longer go (8/11 aligned); from the plan as planned,
        # one drop in another scene reaches 9/12. `choose` compares where each search ended.
        for start in [baseline] + free[:MAX_GREEDY_SEEDS - 1]:
            results.extend(r1_drop_greedy(ctx, start, baseline_for_compare, rung="R1"))
    chosen = choose(results)

    if chosen is None and rebind is not None:
        seed_states = apply_edits(ctx.states, seed["edits"])
        seed_diagnosis = diagnose_opening(ctx, seed_states)
        targets = [entry["state_id"] for entry in seed_diagnosis["cuts"] if not entry["aligned"]]
        r2 = {"targets": targets, "edits": [], "rejections": [], "cost_usd": 0.0, "error": ""}
        if targets:
            request = rebind_request(ctx, seed_states, targets)
            try:
                response, cost = rebind(request)
            except Exception as exc:          # noqa: BLE001 - an unavailable model is no edit
                response, cost = None, 0.0
                r2["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            decision["llm_calls"] = 1
            r2["cost_usd"] = round(float(cost or 0.0), 6)
            decision["cost_usd"] = r2["cost_usd"]
            if response is not None:
                r2_edits, rejections = validate_rebind(ctx, seed_states, targets, response)
                r2["edits"], r2["rejections"] = r2_edits, rejections
                if r2_edits:
                    merged = _merge_reanchors(seed["edits"], r2_edits)
                    first = evaluate(ctx, merged, label="R2 re-bind", rung="R2",
                                     baseline=baseline_for_compare)
                    results.append(first)
                    if not first.get("accepted") and first.get("compiled"):
                        results.extend(r1_drop_greedy(ctx, first, baseline_for_compare,
                                                      rung="R2"))
        decision["r2"] = r2
        chosen = choose(results)

    decision["candidates"] = [_candidate_row(r) for r in results]
    if chosen is not None:
        decision.update(outcome="passed", rung=chosen["rung"], edits=chosen["edits"],
                        after=_summary(chosen), label=chosen.get("label"))
        return decision
    best = best_attempt(results, baseline)
    # The best attempt can clear B by grade and still miss the acceptance margin (wolves01: 91 A
    # at 8/11 = 73% aligned, under 75%). It is applied either way, as the best attempt; only an
    # opening that is still under B, or still capped, is reported as one.
    clears = (int(best.get("score") or 0) >= TARGET_SCORE and best.get("grade") in ("A", "B")
              and not best.get("hard_failures"))
    decision.update(outcome="passed_without_margin" if clears else "below_b_after_retry",
                    rung=best.get("rung") or None, edits=best.get("edits") or [],
                    after=_summary(best), label=best.get("label"))
    if not clears:
        decision["below_b_axes"] = below_b_axes(baseline["report"])
    return decision


# ── Persistence, replay and reporting ─────────────────────────────────────────────────────────

_KEY_FIELDS = ("state_id", "asset_id", "anchor_phrase", "asset_strategy", "asset_status",
               "source_asset_id", "purpose")


def retry_key(*, audio_sha256: list[str], word_times: list, states: list[list[dict]],
              motion_state_ids=frozenset()) -> str:
    """What the decision was made FROM: the opening's audio, its measured words and its states.

    A resume recompiles the evidence plan from the script on every launch, so an edit that lived
    only in memory is quietly reverted; the decision is replayed when this key matches and made
    again when it does not. Word timings are bought again on every local launch, so a resume whose
    transcription moved decides again rather than replaying edits measured on other timings.
    """
    opening_ids = {_text(s.get("state_id")) for scene in states for s in scene}
    payload = {
        "version": RETRY_VERSION,
        "audio": list(audio_sha256),
        "word_times": [[[str(item[0]), round(float(item[1]), 4), round(float(item[2]), 4)]
                        for item in (scene or [])] for scene in word_times],
        "states": [[{field: state.get(field) for field in _KEY_FIELDS} for state in scene]
                   for scene in states],
        "motion": sorted(set(motion_state_ids or ()) & opening_ids),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def replayable(record: Any, key: str) -> bool:
    return (isinstance(record, dict) and record.get("decided") is True
            and record.get("key") == key and record.get("version") == RETRY_VERSION
            and isinstance(record.get("edits"), list))


def summary_line(decision: dict) -> str:
    before = decision.get("before") or {}
    after = decision.get("after") or before
    outcome = decision.get("outcome")
    aligned = f"aligned {after.get('aligned')}/{after.get('cuts')}"
    if outcome == "not_needed":
        return (f"Opening retry: not needed — {before.get('score')} {before.get('grade')}, "
                f"{aligned}")
    if outcome == "script_shortfall":
        return (f"Opening retry: {before.get('score')} {before.get('grade')} and the re-cut "
                f"ceiling is {decision.get('ceiling')} — a script shortfall, no re-cut can reach B")
    if not decision.get("edits"):
        return (f"Opening retry: still below B — {before.get('score')} {before.get('grade')}, "
                f"no candidate raised the score; the opening renders as planned ({aligned}, "
                f"re-cut ceiling {decision.get('ceiling')})")
    change = (f"{before.get('score')} {before.get('grade')} -> {after.get('score')} "
              f"{after.get('grade')} ({decision.get('rung')}: "
              f"{edits_phrase(decision.get('edits') or [])}; {aligned})")
    if outcome == "passed":
        return "Opening retry: " + change
    if outcome == "passed_without_margin":
        return (f"Opening retry: {change} — B by grade, under the {ACCEPT_ALIGNMENT:.0%} "
                "alignment margin; best attempt kept")
    return "Opening retry: still below B — " + change


def below_b_report(decision: dict) -> tuple[dict, str]:
    """The operator's report for an opening under B: the cuts, the arithmetic, the options."""
    before = decision.get("before") or {}
    after = decision.get("after") or before
    diagnosis = decision.get("diagnosis") or {}
    shortfall = decision.get("outcome") == "script_shortfall"
    axes = decision.get("below_b_axes") or []
    report = {
        "version": RETRY_VERSION,
        "outcome": decision.get("outcome"),
        "stopped": bool(decision.get("stopped")),
        "best_score": after.get("score"), "best_grade": after.get("grade"),
        "best_attempt": decision.get("label"),
        "before_score": before.get("score"), "before_grade": before.get("grade"),
        "uncapped_score": before.get("uncapped_score"),
        "recut_ceiling": decision.get("ceiling"),
        "aligned": after.get("aligned"), "cuts": after.get("cuts"),
        "literal_45": after.get("literal_45"),
        "diagnosis": diagnosis.get("cuts") or [],
        "why_no_recut_reaches_b": (
            f"Only the Visual component (20 points) moves under a re-cut; with it at 20/20 the "
            f"opening reaches {decision.get('ceiling')}, under {TARGET_SCORE}. The points are "
            "lost here:" if shortfall else
            "No re-cut candidate met every acceptance rule (B, no hard failure, 75% of cuts "
            "aligned, the rendered gate's cadence and source-change checks)."),
        "points_lost_outside_visual": axes,
        "candidates_tried": len(decision.get("candidates") or []),
        "r2": decision.get("r2"),
        "paid_options": [dict(option) for option in PAID_OPTIONS],
        "override": "OPENING_RETRY_ALLOW_BELOW_B=1 continues anyway (operator only; logged).",
    }
    lines = [
        f"OPENING BELOW B — {decision.get('outcome')}",
        f"45-second readiness: {before.get('score')} {before.get('grade')} as planned "
        f"(uncapped {before.get('uncapped_score')}); best attempt {after.get('score')} "
        f"{after.get('grade')}; re-cut ceiling {decision.get('ceiling')}.",
        f"Cuts aligned: {after.get('aligned')}/{after.get('cuts')}; before 45.0 s only: "
        f"{(after.get('literal_45') or {}).get('aligned')}/"
        f"{(after.get('literal_45') or {}).get('cuts')}.",
        "",
        report["why_no_recut_reaches_b"],
    ]
    for row in axes:
        lines.append(f"- {row['component']}: {row['score']}/{row['assessed_max']} "
                     f"(-{row['points_lost']}, measured over {row['measured_over']})"
                     + (f": {'; '.join(row['notes'])}" if row["notes"] else ""))
    lines += ["", "Unaligned cuts:"]
    for entry in diagnosis.get("cuts") or []:
        if entry.get("aligned"):
            continue
        lines.append(f"- scene {entry['scene']} {entry['state_id']} ({entry['asset_strategy']}) "
                     f"at {entry['global_start_sec']:.2f}s: {entry['reason']} — "
                     f"{entry['anchor_phrase']!r}"
                     + (f" vs {', '.join(entry['conflicts_with'])}"
                        if entry.get("conflicts_with") else ""))
    lines += ["", "Paid options (none is bought automatically):"]
    for option in PAID_OPTIONS:
        lines.append(f"- {option['option']}: ~${option['approx_usd']}. {option['notes']}"
                     if option["approx_usd"][0].isdigit()
                     else f"- {option['option']}: {option['approx_usd']}. {option['notes']}")
    lines += ["", report["override"]]
    return report, "\n".join(lines).rstrip() + "\n"


def degraded_reason(decision: dict, readiness: dict | None, plan: list[list[dict]] | None) -> str:
    """The degraded reason for an opening that stayed under B after the retry, or ''."""
    if not isinstance(decision, dict) or decision.get("outcome") not in (
            "below_b_after_retry", "script_shortfall"):
        return ""
    readiness = readiness or {}
    score = readiness.get("score", (decision.get("after") or {}).get("score"))
    if readiness and int(score or 0) >= TARGET_SCORE and not readiness.get("hard_failures"):
        return ""
    if plan:
        aligned, cuts = cut_alignment(plan)
    else:
        aligned = (decision.get("after") or {}).get("aligned")
        cuts = (decision.get("after") or {}).get("cuts")
    if decision.get("outcome") == "script_shortfall":
        return (f"opening45 below B: script shortfall (re-cut ceiling {decision.get('ceiling')}, "
                f"score {score}); continued under OPENING_RETRY_ALLOW_BELOW_B")
    return f"opening45 below B after retry ({aligned}/{cuts} cuts aligned, score {score})"
