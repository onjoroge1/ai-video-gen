"""Dramatron-style planning for the causal long-form lane: candidates, scores, approval.

Dramatron (Mirowski et al., 2022) writes a script top-down -- logline, characters, plot
outline, locations, then dialogue -- generating several candidates at each level, carrying the
whole outline into every lower-level prompt, and letting a person edit between levels. This
lane already has the levels (question, engine, factual beat sheet, storyboard, prose). What it
lacked, measured on the killer bees film (2026-10-02), was everything else: one beat sheet was
asked for once, nothing scored it, and seven escalation beats on three distinct facts went
straight to prose, where the budget splitter doubled them and the film said the escape twice.

This module owns the three missing pieces:

  * `planner_prompt`   the beat-sheet prompt as ONE pure function, so promptfoo and the
                       pipeline render the identical request;
  * `score_plan`       a deterministic score for a returned sheet (compiles, no duplicate
                       roles, a usable cold open, distinct facts per beat, the event count the
                       runtime needs, the pre-incentive budget) -- the gates choose, not a judge;
  * approval files     `plan.json` / `plan_for_approval.md` written when the operator asked to
                       stop after the plan, and `plan.approved.json` read back on the rerun.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

PLAN_CANDIDATES_DEFAULT = 3
DISTINCT_EVENT_JACCARD = 0.5
APPROVED_PLAN_FILE = "plan.approved.json"
PLAN_FILE = "plan.json"
PLAN_MARKDOWN = "plan_for_approval.md"

_STOP = {"the", "and", "that", "with", "from", "into", "were", "was", "had", "has", "have",
         "then", "than", "this", "these", "those", "their", "they", "them", "its", "for",
         "but", "not", "are", "been", "being", "after", "before", "while", "where", "which",
         "about", "could", "would", "also", "more", "most", "some", "each", "both", "when"}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", _text(text).lower()) if w not in _STOP}


def planner_prompt(question: str, duration_sec: int, engine_id: str,
                   research_dossier: dict | None, *, operator_direction: str = "",
                   series: str = "", improve_note: str = "", cast_free: bool = True,
                   n_scenes: int | None = None, cast_rules: str | None = None) -> str:
    """The exact beat-sheet request the pipeline sends for the causal lane."""
    import explainer_pipeline as ep
    import story_compiler
    from longform_research import claim_context_for_prompt
    n_scenes = n_scenes if n_scenes is not None else ep.scene_count_for(duration_sec, "landscape")
    cast_rules = cast_rules if cast_rules is not None else ("" if not cast_free else
                  "\nCAST: this story has NO recurring characters and NO named host. Never "
                  "write Alex, Bolt, or any invented stand-in into the narration. Name the real "
                  "actors the history had -- 'colonial officials', 'the bounty clerks', "
                  "'Delhi residents', 'the breeders' -- or use no name at all. Set "
                  "human_present and mascot_present to false on every scene.\n")
    import script_cadence
    prompt = story_compiler.factual_plan_prompt(question, duration_sec, n_scenes, engine_id, cast_rules)
    prompt += script_cadence.BRIEF
    import hook_callback
    prompt += hook_callback.BRIEF
    claim_context = claim_context_for_prompt(research_dossier or {})
    if claim_context:
        prompt += (
            "\nBINDING RESEARCH CLAIM LEDGER — use only these sourced claims for factual, numeric, "
            "or causal narration. Every such beat must reference one or more claim_id values and a "
            "stable evidence_id. Preserve geographic_scope, timescale, and confidence; speculative "
            "claims must be explicitly hedged. Do not invent a claim or URL:\n"
            + json.dumps(claim_context, ensure_ascii=False))
    if improve_note:
        prompt += ("\nPRIORITY FIX — the previous draft scored weak here; fix this FIRST in the "
                   "beat sheet while keeping everything else: " + improve_note)
    return prompt + ep._series_block(series) + ep._operator_block(operator_direction)


def planner_system_prompt() -> str:
    import explainer_pipeline as ep
    return ep._SCRIPT_SYSTEM


def plan_beats(plan: dict) -> list[dict]:
    """The planner's beats, clamped to rows with text and renumbered (the pipeline's rule)."""
    rows = [b for b in ((plan or {}).get("beats") or [])
            if isinstance(b, dict) and _text(b.get("beat"))]
    for i, row in enumerate(rows):
        row["n"] = i + 1
    return rows


def distinct_events(beats: list[dict]) -> list[bool]:
    """Per beat: does it add a fact? False when its event restates an earlier event's words and
    cites no claim the earlier beats did not already cite."""
    import story_fact_model as sfm
    seen_words: list[set[str]] = []
    seen_refs: set[str] = set()
    out = []
    for beat in beats:
        event = sfm.event_of(beat)
        words = _words(event.get("text"))
        refs = set(event.get("claim_refs") or [])
        restates = any(words and prior and len(words & prior) / len(words | prior) >= DISTINCT_EVENT_JACCARD
                       for prior in seen_words)
        new_refs = bool(refs - seen_refs)
        out.append(not restates or (new_refs and not restates))
        seen_words.append(words)
        seen_refs |= refs
    return out


def score_plan(plan: dict, engine_id: str, research_dossier: dict | None,
               duration_sec: int) -> dict:
    """Deterministic score for one beat sheet; semantic validation and final readiness are separate."""
    import causal_story as cs
    import story_compiler
    import story_engines
    import story_fact_model as sfm
    from longform_research import events_for_runtime
    import explainer_pipeline as ep

    issues: list[str] = []
    beats = [json.loads(json.dumps(b)) for b in plan_beats(plan)]
    score = 100.0
    if not beats:
        return {"score": 0.0, "issues": ["no beats"], "beats": 0}
    compatibility = story_engines.evidence_compatibility(engine_id, research_dossier)
    if not compatibility.get("compatible"):
        score -= 60
        issues.append(
            f"engine mismatch: {engine_id} — {compatibility.get('reason')} "
            f"(use {compatibility.get('replacement')})")
    claims = ep._spine_claims(research_dossier or {})
    roles = story_compiler.compile_roles(beats, engine_id, claims)
    if not roles.get("compiled") or not roles.get("passed"):
        score -= 40
        issues.extend(f"compile: {_text(i.get('code'))}" for i in (roles.get("issues") or [])[:3]
                      if isinstance(i, dict))
        if not issues:
            issues.append("compile: sheet does not compile")
    role_beats = roles.get("beats") or beats
    dups = sfm.duplicate_event_functions(role_beats, engine_id)
    across = [d for d in dups if not d.get("collapsible")]
    within = [d for d in dups if d.get("collapsible")]
    if across:
        score -= 15 * len(across)
        issues.extend(f"duplicate roles: {d.get('beat_id')} restates {d.get('duplicate_of')}" for d in across)
    if within:
        score -= 5 * len(within)
        issues.extend(f"repeated beat: {d.get('beat_id')} restates {d.get('duplicate_of')}" for d in within)

    cold = plan.get("cold_open")
    cold_text = _text(cold.get("text")) if isinstance(cold, dict) else _text(cold)
    cold_refs = [r for r in ((cold.get("claim_refs") or []) if isinstance(cold, dict) else []) if _text(r)]
    cold_issues = cs.check_cold_open(cold_text, _text(plan.get("hook")))
    known = {_text(c.get("claim_id")) for c in ((research_dossier or {}).get("claims") or [])
             if isinstance(c, dict)}
    if cold_text and known and not [r for r in cold_refs if r in known]:
        cold_issues.append({"code": "COLD_OPEN_UNCITED"})
    if cold_issues:
        score -= 15
        issues.extend(f"cold open: {_text(i.get('code'))}" for i in cold_issues)

    hook = _text(plan.get("hook"))
    if not hook:
        score -= 10
        issues.append("hook: missing")
    elif len(hook.split()) > cs.MAX_HOOK_WORDS:
        score -= 5
        issues.append(f"hook: {len(hook.split())} words over {cs.MAX_HOOK_WORDS}")

    flags = distinct_events(beats)
    ratio = sum(flags) / len(flags)
    score -= 25 * (1 - ratio)
    if ratio < 1:
        issues.append(f"distinct facts: {sum(flags)}/{len(flags)} beats add a fact")

    mapping = story_compiler.ef.map_for(engine_id)
    target = max(len(mapping.required), events_for_runtime(duration_sec)) if mapping else events_for_runtime(duration_sec)
    if len(beats) < target:
        shortfall = (target - len(beats)) / max(1, target)
        score -= 10 * min(1.0, shortfall * 2)
        issues.append(f"event count: {len(beats)} of about {target} the runtime needs")

    budget = story_compiler._max_events_before_incentive(duration_sec, engine_id)
    before = 0
    for beat in beats:
        if _text(beat.get("event_function")) == "changes_incentive":
            break
        before += 1
    else:
        before = 0
    if before > budget:
        score -= 10
        issues.append(f"{before} events before the incentive changes; budget is {budget}")

    return {"score": round(max(0.0, score), 1), "issues": issues, "beats": len(beats),
            "distinct_ratio": round(ratio, 2), "compiled": bool(roles.get("passed")),
            "cold_open_ok": not cold_issues, "target_events": target}


def choose_plan(scored: list[dict]) -> int:
    """Index of the best candidate: highest score, earliest on a tie."""
    best, best_score = 0, -1.0
    for index, item in enumerate(scored):
        score = float((item or {}).get("score") or 0.0)
        if score > best_score:
            best, best_score = index, score
    return best


def plan_markdown(plan: dict, report: dict | None = None, candidates: list[dict] | None = None) -> str:
    import story_fact_model as sfm
    lines = [f"# {_text(plan.get('title'))}", "",
             f"Hook: {_text(plan.get('hook'))}",
             f"Cold open: {_text((plan.get('cold_open') or {}).get('text')) if isinstance(plan.get('cold_open'), dict) else _text(plan.get('cold_open'))}",
             f"Throughline: {_text(plan.get('throughline'))}",
             f"Opening object: {_text(plan.get('opening_object'))}", ""]
    if report:
        lines.append(f"Plan score: {report.get('score')}/100"
                     + (" — " + "; ".join(report.get("issues") or []) if report.get("issues") else ""))
        lines.append("")
    import hook_callback
    pair = hook_callback.contract(plan)
    if pair:
        lines += ["Hook/callback writing plan (not evidence):"]
        lines += [f"- {key}: {value}" for key, value in pair.items()]
        lines.append("")
    if candidates:
        lines.append("Candidates: " + ", ".join(f"#{i + 1} {c.get('score')}" for i, c in enumerate(candidates)))
        lines.append("")
    for beat in plan_beats(plan):
        event = sfm.event_of(beat)
        lines.append(f"{beat['n']}. [{_text(beat.get('event_function'))}] {event.get('text')}")
        refs = ", ".join(event.get("claim_refs") or [])
        if refs:
            lines.append(f"   claims: {refs}")
    lines += ["", "To approve: copy plan.json to plan.approved.json (edit it first if you like) and "
                  "rerun the same request without --stop-after plan."]
    return "\n".join(lines) + "\n"


def write_plan_for_approval(output_dir: str, plan: dict, report: dict | None,
                            candidates: list[dict] | None) -> str:
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, PLAN_FILE), "w", encoding="utf-8") as handle:
        json.dump(plan, handle, indent=1, ensure_ascii=False)
    path = os.path.join(output_dir, PLAN_MARKDOWN)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(plan_markdown(plan, report, candidates))
    return path


def approved_plan(output_dir: str) -> dict | None:
    path = os.path.join(output_dir or "", APPROVED_PLAN_FILE)
    if not output_dir or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        plan = json.load(handle)
    return plan if isinstance(plan, dict) and plan.get("beats") else None


def candidate_brief(index):
    """Stable diversity: each candidate is replayable, but sends a different request."""
    approaches = (
        "Open on a concrete, sourced consequence; trace the decision that caused it.",
        "Open on the original intervention and its promise; follow the first sourced sign of failure.",
        "Open on a sourced physical object or animal; show how its meaning changes at the ending.",
    )
    return (f"\nCANDIDATE {index + 1}/3 — {approaches[index]} "
            "Keep the required engine, evidence limits and roles. Do not invent a scene to fit this approach.")
