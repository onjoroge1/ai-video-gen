"""Narration first; evidence-owned paragraphs, then lossless production shots.

The seven sections are editorial jobs, not seven fixed shots or seven independent
prompts. The factual planner still owns what happened. Existing reviewers edit
paragraphs through the scene adapter until the text is frozen for production.
"""
from copy import deepcopy
import json
import re

import script_stages
import story_fact_model as facts
import story_compiler as compiler
from storyboard_repair import response_data
from script_repair import broken_repair

VERSION = "seven_section_v1"
MODE = "seven_section"
ENGINES = {"removed_keystone", "backfiring_solution"}
SECTIONS = (
    ("hook", "Name the subject and a concrete contradiction or consequential question."),
    ("original_problem", "Explain who had a problem and why intervention seemed necessary."),
    ("proposed_fix", "Explain the action and the result people expected; no invented success."),
    ("overlooked_behavior", "Reveal the supported behavior, incentive or constraint behind the turn."),
    ("consequences", "Develop distinct supported effects; distinguish causal chains from parallel effects."),
    ("outcome", "Answer the opening promise, including supported limits and uncertainty."),
    ("callback", "Return to the opening image with changed meaning after answering the question."),
)
ROLE_SECTION = {"setup": "original_problem", "intervention": "proposed_fix",
    "false_resolution": "proposed_fix", "hinge": "overlooked_behavior",
    "mechanism": "overlooked_behavior", "escalation": "consequences",
    "reversal": "outcome", "tool": "callback", "verdict": "callback"}


def brief(plan, beats, dossier, engine):
    """Missing evidence blocks writing. IDs are references, never model-created facts."""
    if engine not in ENGINES:
        raise ValueError("SEVEN_SECTION_UNSUPPORTED_ENGINE: use scene-first for this story engine")
    if not (plan.get("_spine", {}).get("compiled") or {}).get("passed"):
        raise ValueError("SEVEN_SECTION_UNACCEPTED_PLAN: a supported factual plan is required")
    known = {c["claim_id"]: c for c in dossier.get("claims", []) if c.get("claim_id")}
    ids = [b.get("beat_id") for b in beats]
    if not ids or not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("SEVEN_SECTION_INVALID_BEAT_IDS")
    rows = []
    singleton_roles = [b.get("causal_role") or b.get("role") for b in beats
                       if (b.get("causal_role") or b.get("role")) != "escalation"]
    if len(singleton_roles) != len(set(singleton_roles)):
        raise ValueError("SEVEN_SECTION_UNACCEPTED_PLAN: duplicate single-use story role")
    for beat in beats:
        role = beat.get("causal_role") or beat.get("role")
        if role not in ROLE_SECTION or facts.scope_of(beat) != facts.PRIMARY_STORY:
            raise ValueError("SEVEN_SECTION_SCOPE: this template needs one primary intervention story")
        event = facts.event_of(beat)
        contexts = facts.context_events(beat, beats)
        refs = set(event["claim_refs"])
        for context in contexts:
            refs.update(context["event"].get("claim_refs") or [])
        if refs - known.keys() or (event["text"] and not refs):
            raise ValueError("SEVEN_SECTION_EVIDENCE_GAP: " + beat["beat_id"])
        rows.append({"paragraph_id": beat["beat_id"], "section": ROLE_SECTION[role],
            "role": role, "event": event, "context_events": contexts,
            "instruction": beat.get("beat", "") if beat.get("presentation_device") else event["text"],
            "claim_ids": sorted(refs)})
    missing = {s for s, _ in SECTIONS if s != "hook"} - {r["section"] for r in rows}
    if missing:
        raise ValueError("SEVEN_SECTION_EVIDENCE_GAP: missing " + ", ".join(sorted(missing))
                         + "; research or narrow the story rather than inventing a section")
    return {"sections": [{"id": s, "job": job} for s, job in SECTIONS], "paragraphs": rows,
            "claims": [known[c] for c in sorted({c for r in rows for c in r["claim_ids"]})]}


def draft_prompt(evidence, question, duration, word_target, direction):
    import script_cadence
    return (
        "Write ONE continuous, factual YouTube narration. The seven section jobs below organize "
        "the story; they are not independent fill-in prompts or production scenes. Choose the "
        "supported final answer first, then THREE different hook candidates: a specific "
        "contradiction, a consequential question, and a concrete human moment (only if supported). "
        "Select the strongest earned promise, not the most sensational claim. Do not manufacture "
        "urgency, timelines, motives, an initial success, eyewitness details or failed rescues. "
        "Keep uncertainty. A question can itself make an unsupported factual assertion. "
        "An outcome is not proof of historical intent. Explain the mechanism early, within the "
        "first fifth of the spoken text, then sustain interest with distinct evidence and effects. "
        "Do not turn parallel effects into an invented causal chain. Give every paragraph a new "
        "contribution; brief connections and the final callback may refer to earlier facts. "
        "Write natural transitions and varied sentences for reading aloud. No spoken section "
        "labels, Step numbers, scene directions, host, stock teaser or guru advice. Answer the "
        "opening before reflecting; the callback may transform the question rather than repeat it. "
        "The hook is one complete sentence, <=18 words. The hinge paragraph is one complete "
        "statement, <=10 words. These are the only line-length caps; do not write every sentence "
        "short. Start the FIRST paragraph with the selected hook verbatim, followed by the "
        "original problem; do not add a second cold open or restate the hook. The hook may draw "
        "on the accepted intervention and outcome; every other paragraph stays inside its event "
        "and explicit context_events. Produce every assigned paragraph_id exactly once IN ORDER; "
        "these are logical evidence units, not shots. Read the whole story before writing. "
        "If evidence is inadequate, return evidence_gaps rather than invented filler.\n"
        + script_cadence.BRIEF
        + f"\nTopic: {question}\nRequested seconds: {duration}; total target words: {word_target}.\n"
        + "Opening hook + problem + fix + hinge together should use at most 17% of the total words. "
        "Spend the remaining space explaining the mechanism and distinct sourced consequences, "
        "not repeating the premise. Evidence limits override filling runtime.\n"
        + "Operator direction: " + direction + "\nEVIDENCE BRIEF:\n" + json.dumps(evidence, ensure_ascii=False)
        + '\nReturn ONLY JSON: {"hook_candidates":["...","...","..."],"selected_hook":0,'
          '"supported_answer":"...","callback_image":"...","closing_question":"...",'
          '"outline":[{"section":"hook","new_contribution":"...","claim_ids":["..."]},'
          '... seven sections in the supplied order ...],"paragraphs":[{"paragraph_id":"...",'
          '"narration":"..."}],"evidence_gaps":[],"editorial_weaknesses":[]}. '
          'The outline is not spoken. The paragraphs, read together, ARE the complete narration.'
    )


def validate_draft(value, evidence):
    if not isinstance(value, dict) or value.get("evidence_gaps") != []:
        raise ValueError("SEVEN_SECTION_EVIDENCE_GAP: writer could not support the complete story")
    rows = value.get("paragraphs")
    expected = [r["paragraph_id"] for r in evidence["paragraphs"]]
    if (not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows)
            or [r.get("paragraph_id") for r in rows] != expected):
        raise ValueError("SEVEN_SECTION_COVERAGE: missing, duplicated, reordered or unknown paragraph")
    if any(broken_repair(r.get("narration")) for r in rows):
        raise ValueError("SEVEN_SECTION_BROKEN_NARRATION")
    candidates, selected = value.get("hook_candidates"), value.get("selected_hook")
    if (not isinstance(candidates, list) or len(candidates) != 3 or type(selected) is not int
            or not 0 <= selected < 3 or any(not isinstance(h, str) for h in candidates)):
        raise ValueError("SEVEN_SECTION_HOOK_CHOICES")
    hook = candidates[selected].strip()
    if (broken_repair(hook) or len(hook.split()) > 18
            or len(re.split(r"[.!?]+\s*", hook.rstrip(".!?"))) != 1
            or not rows[0]["narration"].startswith(hook)):
        raise ValueError("SEVEN_SECTION_HOOK: selected promise must open the narration verbatim")
    outline = value.get("outline")
    known = {c["claim_id"] for c in evidence["claims"]}
    if (not isinstance(outline, list) or any(not isinstance(r, dict) for r in outline)
            or [r.get("section") for r in outline] != [s for s, _ in SECTIONS]
            or any(not isinstance(r.get("new_contribution"), str) or not r["new_contribution"].strip()
                   or not isinstance(r.get("claim_ids"), list) or not r["claim_ids"]
                   or any(not isinstance(c, str) or c not in known for c in r["claim_ids"])
                   for r in outline)):
        raise ValueError("SEVEN_SECTION_OUTLINE: every section needs a distinct contribution and known evidence")
    for field in ("supported_answer", "callback_image", "closing_question"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError("SEVEN_SECTION_PROMISE: missing " + field)
    return hook


@script_stages.cached("seven-section-draft", context=lambda: {"version": VERSION,
    **__import__("script_contracts").acceptance_policy()})
def generate(plan, beats, dossier, engine, question, duration, word_target,
             direction="", cost_sink=None):
    import explainer_pipeline as ep
    evidence = brief(plan, beats, dossier, engine)
    prompt = draft_prompt(evidence, question, duration, word_target, direction)
    # One coherent drafting call. Provider replay owns interruptions; malformed or
    # incomplete prose is a saved terminal result, not permission for endless retries.
    response = ep._claude().messages.create(model=ep.ANTHROPIC_MODEL, max_tokens=12000,
        system="You are a factual documentary writer. Return the requested JSON only.",
        messages=[{"role": "user", "content": prompt}])
    cost = ep._charge(cost_sink, ep._ledger.EXPANSION, ep._msg_cost(response.usage), "continuous narration")
    value = response_data(response)
    hook = validate_draft(value, evidence)
    scenes = []
    source_ids = {b["beat_id"]: f"scene_{i:03d}" for i, b in enumerate(beats, 1)}
    for i, (beat, paragraph) in enumerate(zip(beats, value["paragraphs"]), 1):
        row = deepcopy(beat)
        role = beat.get("causal_role") or beat.get("role")
        row.update(id=i, scene_id=source_ids[beat["beat_id"]], narration=paragraph["narration"].strip(),
            paragraph_id=beat["beat_id"], narrative_section=ROLE_SECTION[role], story_role=role,
            story_beat_n=i, continues="", human_present=False, mascot_present=False,
            caused_by=source_ids.get(beat.get("caused_by"), ""))
        # A hook asks about the supported outcome, not only the original problem.
        if i == 1:
            row["context_refs"] = list(dict.fromkeys((row.get("context_refs") or []) +
                [b["beat_id"] for b in beats if b.get("role") in {"intervention", "reversal", "mechanism"}]))
        row["evidence_id"] = f"e{i:02d}"
        claim_ids = set(evidence["paragraphs"][i - 1]["claim_ids"])
        for context in facts.context_events(row, beats):
            claim_ids.update(context["event"]["claim_refs"])
        row["claim_refs"] = [{"claim_id": c, "evidence_id": row["evidence_id"],
            "narration_phrase": row["narration"]} for c in sorted(claim_ids)]
        scenes.append(row)
    selected_plan = deepcopy(plan)
    selected_plan.update(hook=hook, opening_object=value["callback_image"],
        final_callback_object=value["callback_image"],
        accepted_belief=facts.event_of(beats[0])["text"])
    compiler.refresh_story_positions(scenes)
    contract = ep.build_story_contract(question, selected_plan, beats, scenes, duration)
    for compact, beat in zip(contract["beats"], beats):
        compact["beat_id"] = beat["beat_id"]
    return {"title": plan.get("title") or question, "hook": hook, "style_mode": "educational",
        "scenes": scenes, "_narrative_mode": MODE, "_production_status": "unplanned",
        "_narrative_outline": value["outline"], "_narrative_draft": value,
        "_hook_contract": {"viewer_question": hook, "supported_answer": value["supported_answer"],
            "contrast": (plan.get("hook_contract") or {}).get("contrast", ""),
            "callback_image": value["callback_image"], "closing_question": value["closing_question"]},
        "_spine": deepcopy(plan["_spine"]), "_entailment_cache": deepcopy(plan.get("_entailment_cache") or {}),
        "_compiled_story": True, "_story_engine": engine, "_planned_story_engine": engine,
        "_parallel_cases": [], "_beats": len(beats), "_story_format": "standard_explainer",
        "_story_contract": contract,
        "_research_dossier": deepcopy(dossier), "_script_cost_usd": cost}


def from_saved(script, question, duration, direction="", cost_sink=None):
    """Use the parent's accepted factual plan, never its rejected narration as evidence."""
    import explainer_pipeline as ep
    plan = {**deepcopy(script.get("_story_contract") or {}), "title": script.get("title"),
            "_spine": deepcopy(script.get("_spine") or {}),
            "_entailment_cache": deepcopy(script.get("_entailment_cache") or {})}
    engine = script.get("_story_engine")
    if engine not in ENGINES:
        raise ValueError("SEVEN_SECTION_UNSUPPORTED_ENGINE")
    try:
        beats = compiler.presentation_beats(plan["_spine"].get("beats") or [], engine)
        brief(plan, beats, script.get("_research_dossier") or {}, engine)
    except (ValueError, StopIteration, KeyError):
        # Old checkpoints may contain duplicate roles that the current compiler
        # rejects. Reuse their research, not that obsolete structural acceptance.
        token = ep._NARRATIVE_MODE.set(MODE)
        try:
            return ep.generate_graded_script(question, duration, "engaging and scientific", "",
                "landscape", "", cost_sink=cost_sink, operator_direction=direction,
                research_dossier=script.get("_research_dossier") or {}, causal_lane=True)
        finally:
            ep._NARRATIVE_MODE.reset(token)
    return generate(plan, beats, script.get("_research_dossier") or {}, engine, question, duration,
                    ep.runtime_word_bounds(duration, len(beats))[0], direction, cost_sink)


def freeze(script):
    """Freeze only the reviewed text. Subsequent calls may verify but never silently reseal edits."""
    if script.get("_narrative_document"):
        verify_projection(script)
        return
    expected = [p["paragraph_id"] for p in script.get("_narrative_draft", {}).get("paragraphs", [])]
    if expected and [s.get("paragraph_id") for s in script["scenes"]] != expected:
        raise ValueError("SEVEN_SECTION_COVERAGE: review dropped or duplicated a logical paragraph")
    paragraphs = [{"id": s["paragraph_id"], "section": s["narrative_section"],
                   "text": s["narration"]} for s in script["scenes"]]
    text = "\n\n".join(p["text"] for p in paragraphs)
    script["_narrative_document"] = {"version": VERSION, "paragraphs": paragraphs,
                                     "text": text, "sha256": script_stages.digest(text)}


def verify_projection(script):
    document = script.get("_narrative_document") or {}
    text = document.get("text")
    if not isinstance(text, str) or script_stages.digest(text) != document.get("sha256"):
        raise ValueError("NARRATION_PROJECTION_CHANGED: invalid source document")
    paragraphs = document.get("paragraphs") or []
    if (not paragraphs or "\n\n".join(p["text"] for p in paragraphs) != text
            or len({p["id"] for p in paragraphs}) != len(paragraphs)):
        raise ValueError("NARRATION_PROJECTION_CHANGED: invalid source paragraphs")
    rows = script.get("scenes") or []
    if script.get("_production_status") != "planned":
        if [{"id": s.get("paragraph_id"), "section": s.get("narrative_section"),
             "text": s.get("narration")} for s in rows] != paragraphs:
            raise ValueError("NARRATION_PROJECTION_CHANGED: paragraph edit after approval")
        return
    cursor, assembled = 0, ""
    by_id, paragraph_start = {}, 0
    for paragraph in paragraphs:
        by_id[paragraph["id"]] = (paragraph_start, paragraph_start + len(paragraph["text"]), paragraph["section"])
        paragraph_start += len(paragraph["text"]) + 2
    for scene in rows:
        span = scene.get("narration_span") or {}
        start, end = span.get("start"), span.get("end")
        separator = span.get("separator", "")
        bounds = by_id.get(scene.get("paragraph_id"))
        if (type(start) is not int or type(end) is not int or not isinstance(separator, str)
                or start != cursor + len(separator) or not cursor <= start < end <= len(text)
                or text[cursor:start] != separator or separator.strip()
                or text[start:end] != scene.get("narration")
                or bounds is None or not bounds[0] <= start < end <= bounds[1]
                or scene.get("narrative_section") != bounds[2]):
            raise ValueError("NARRATION_PROJECTION_CHANGED: gap, overlap, reorder or rewritten shot")
        assembled += separator + scene["narration"]
        cursor = end
    if cursor != len(text) or assembled != text:
        raise ValueError("NARRATION_PROJECTION_CHANGED: incomplete narration")


def split_for_production(script, max_words=45):
    """Complete sentence boundaries only, with character spans preserving all whitespace."""
    freeze(script)
    output, offset = [], 0
    for paragraph in script["scenes"]:
        text = paragraph["narration"]
        sentences = list(re.finditer(r"\S[\s\S]*?(?:[.!?](?=\s|$)|$)", text))
        spans, start, end = [], 0, 0
        for sentence in sentences:
            if end and len(text[start:sentence.end()].split()) > max_words:
                spans.append((start, end))
                start = sentence.start()
            end = sentence.end()
        spans.append((start, len(text)))
        previous = None
        for part, (start, end) in enumerate(spans):
            row = deepcopy(paragraph)
            row.update(id=len(output) + 1,
                scene_id=compiler.part_identity(paragraph["scene_id"], part),
                beat_id=compiler.part_identity(paragraph["beat_id"], part),
                continues=previous["beat_id"] if previous else "", beat_part=part + 1,
                beat_part_count=len(spans), narration=text[start:end])
            if previous:
                row["caused_by"] = previous["scene_id"]
            absolute = offset + start
            previous_end = output[-1]["narration_span"]["end"] if output else 0
            row["narration_span"] = {"start": absolute, "end": offset + end,
                "separator": script["_narrative_document"]["text"][previous_end:absolute]}
            row["evidence_id"] = f"e{row['id']:02d}"
            row["claim_refs"] = [{**r, "evidence_id": row["evidence_id"],
                                  "narration_phrase": row["narration"]} for r in row.get("claim_refs", [])]
            output.append(row)
            previous = row
        offset += len(text) + 2
    candidate = deepcopy(script)
    candidate["scenes"] = output
    candidate["_story_contract"]["scene_count"] = len(output)
    candidate["_production_status"] = "planned"
    verify_projection(candidate)
    return candidate


def verify_child_projection(script, parent):
    """A render continuation may repartition an approved parent, never replace it."""
    verify_projection(script)
    verify_projection(parent)
    if (script.get("_narrative_document") != parent.get("_narrative_document")
            or script.get("_research_dossier") != parent.get("_research_dossier")
            or script.get("title") != parent.get("title") or script.get("hook") != parent.get("hook")):
        raise ValueError("NARRATION_PROJECTION_CHANGED: continuation changed its approved parent")
    expected = split_for_production(deepcopy(parent))["scenes"]
    fields = ("scene_id", "beat_id", "paragraph_id", "narration", "narration_span", "event", "scope",
              "context_refs", "caused_by", "causal_role", "derivation", "chapter", "continues")
    if [{k: s.get(k) for k in fields} for s in script["scenes"]] != [
            {k: s.get(k) for k in fields} for s in expected]:
        raise ValueError("NARRATION_PROJECTION_CHANGED: continuation altered evidence or shot identities")


@script_stages.cached("narrative-production", context=lambda: {"version": VERSION,
    **__import__("script_contracts").acceptance_policy()})
def realize(script, cost_sink=None):
    """Separate visual planning consumes frozen text; it has no authority to rewrite it."""
    import explainer_pipeline as ep
    import scene_expansion
    import storyboard_repair
    review = script.get("_final_retention_review") or {}
    if not review.get("passed") or review.get("narration_sha256") != storyboard_repair.story_identity(script):
        raise ValueError("NARRATION_REVIEW_STALE: review the paragraphs before planning shots")
    candidate = split_for_production(script)
    # A direct full-video request also needs its paragraph approval on a worker
    # continuation. Keep only approval-bound text/meaning fields, not duplicated
    # research, provider caches or arbitrary history. The evidence hash stays on
    # the source readiness report and is checked against the current ledger.
    source_keys = ("title", "hook", "_story_engine", "_story_contract", "_cold_open",
        "_cold_open_claim_refs", "_narrative_mode", "_narrative_document", "_production_status",
        "scenes", "_script_readiness")
    candidate["_projection_source"] = {k: deepcopy(script[k]) for k in source_keys if k in script}
    cost = 0.0
    visual_keys = {"image_prompt", "visual_beats", "environment_type", "text_overlay",
                   "scene_type", "shot_type", "text_sub", "text", "framing", "camera_motion",
                   "visual_style", "evidence_type"}
    for index in range(0, len(candidate["scenes"]), 4):
        batch = candidate["scenes"][index:index + 4]
        prompt = ("Plan visuals for these exact spoken spans. Return narration VERBATIM. "
            "No writing, merging, shortening or extending narration. Only depict the supported "
            "event and context. Use anonymous period-appropriate figures, no recurring host. "
            "Keep at most four recurring locations across the whole film.\n"
            + ep._SCENE_FIELDS_RULES + "\n" + ep._DESIGN_SYSTEM_TEXT
            + "\nWhole narration:\n" + script["_narrative_document"]["text"])
        def request(prompt, tool):
            response = ep._claude().messages.create(model=ep.ANTHROPIC_MODEL, max_tokens=16000,
                system=ep._SCRIPT_SYSTEM, messages=[{"role": "user", "content": prompt}],
                tools=[tool], tool_choice={"type": "tool", "name": tool["name"]})
            return response, ep._charge(cost_sink, ep._ledger.EXPANSION, ep._msg_cost(response.usage),
                                        "frozen narration visuals")
        rows, paid = scene_expansion.expand(batch, prompt, request, preserve_narration=True)
        cost += paid
        for scene, visual in zip(batch, rows):
            scene.update({k: deepcopy(v) for k, v in visual.items() if k in visual_keys})
    verify_projection(candidate)
    # The editor reviewed exactly this continuous text. Preserve the proof of that
    # review across the deterministic repartition, without claiming a new model grade.
    review = candidate.get("_final_retention_review") or {}
    review["source_narration_sha256"] = review["narration_sha256"]
    review["projection_sha256"] = script["_narrative_document"]["sha256"]
    review["narration_sha256"] = storyboard_repair.story_identity(candidate)
    candidate["_script_cost_usd"] = round(candidate.get("_script_cost_usd", 0) + cost, 6)
    return candidate
