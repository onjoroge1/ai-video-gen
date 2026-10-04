"""Bounded, identity-addressed expansion of an accepted factual storyboard.

Keep completed rows when a writer omits a scene. Provider replay and semantic
checkpoints have different jobs: the former accounts for calls; the latter freezes
the accepted subset and the remaining attempt budget across worker continuation.
These are structural results, never evidence or editorial passes.
"""
from copy import deepcopy
import json
import re

import script_stages
from storyboard_repair import response_data

VERSION = "scene_expansion_v1"
TOOL = "submit_expanded_scenes"
MAX_ATTEMPTS = 2


def response_tool(ids):
    return {"name": TOOL, "description": "Write the requested scenes, preserving their IDs.",
            "input_schema": {"type": "object", "additionalProperties": False,
                "required": ["scenes"], "properties": {"scenes": {
                    "type": "array", "minItems": 1, "maxItems": len(ids), "items": {
                        "type": "object", "required": ["scene_id", "narration"],
                        "properties": {"scene_id": {"type": "string", "enum": ids},
                                       "narration": {"type": "string", "minLength": 1}},
                        "additionalProperties": True}}}}}


def reconcile(value, ids, frozen=None):
    """Never infer a missing ID from position, or choose between duplicate IDs."""
    rows = value.get("scenes") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        return {}, ["Missing scenes array"]
    accepted, errors, seen = {}, [], set()
    for row in rows:
        ident = row.get("scene_id") if isinstance(row, dict) else None
        if not isinstance(ident, str) or ident not in ids:
            errors.append("Unknown or missing scene ID")
            continue
        if ident in seen:
            accepted.pop(ident, None)
            errors.append(f"Duplicate scene ID: {ident}")
            continue
        seen.add(ident)
        narration = row.get("narration")
        if not isinstance(narration, str) or not narration.strip():
            errors.append(f"Empty narration: {ident}")
            continue
        if frozen is not None and narration != frozen[ident]:
            errors.append(f"Rewritten frozen narration: {ident}")
            continue
        accepted[ident] = deepcopy(row)
    return accepted, errors


def expand(rows, prompt, request, *, preserve_narration=False):
    """request(prompt, tool) -> (provider response, accounted cost).

    Initial batches are small. A second attempt addresses one missing/invalid row
    at a time. No JSON-repair purchase, no whole-batch rewrite, no reset on resume.
    Durable/provider interruptions propagate without spending an extra attempt.
    """
    ids = [row["scene_id"] for row in rows]
    if not ids or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Expansion requires unique assigned scene IDs")
    inputs = {"version": VERSION, "rows": rows, "prompt": prompt}
    frozen = {r["scene_id"]: r["narration"] for r in rows} if preserve_narration else None
    if preserve_narration:
        inputs["preserve_narration"] = True
    state = script_stages.load("scene-expansion", inputs) or {
        "accepted": {}, "attempts": {i: 0 for i in ids}, "cost": 0.0,
        "status": "running", "errors": []}
    while state["status"] == "running":
        missing = [i for i in ids if i not in state["accepted"]]
        if not missing:
            state["status"] = "complete"
            script_stages.save("scene-expansion", inputs, state)
            break
        exhausted = [i for i in missing if state["attempts"][i] >= MAX_ATTEMPTS]
        if exhausted:
            state["status"] = "failed"
            script_stages.save("scene-expansion", inputs, state)
            break
        selected = missing if all(state["attempts"][i] == 0 for i in missing) else missing[:1]
        instruction = {
            "requested_scene_ids": selected,
            "assigned_rows": [r for r in rows if r["scene_id"] in selected],
            "read_only_completed_scenes": [state["accepted"][i] for i in ids
                                            if i in state["accepted"]],
            "attempts": {i: state["attempts"][i] + 1 for i in selected}}
        assigned = instruction["assigned_rows"]
        attempt_prompt = re.sub(r"<ASSIGNED_SCENES>.*?</ASSIGNED_SCENES>",
            lambda _: "<ASSIGNED_SCENES>\n" + "\n".join(json.dumps(r, ensure_ascii=False)
                for r in assigned) + "\n</ASSIGNED_SCENES>", prompt, flags=re.S)
        if all(type(r.get("n")) is int for r in assigned):
            attempt_prompt = re.sub(r"NOW WRITE scenes \d+-\d+ ONLY",
                f"NOW WRITE scenes {assigned[0]['n']}-{assigned[-1]['n']} ONLY", attempt_prompt)
        response, cost = request(attempt_prompt + "\n\nEXPANSION RESPONSE CONTRACT: Return via " + TOOL
            + " only requested_scene_ids below, exactly once each. Other scene rows are read-only "
            "context. Never combine rows, omit a closing device, or rewrite completed scenes. "
            "Keep scene_id verbatim; position is not identity.\n" + json.dumps(instruction,
                ensure_ascii=False), response_tool(selected))
        state["cost"] += cost
        for ident in selected:
            state["attempts"][ident] += 1
        try:
            accepted, errors = reconcile(response_data(response, tool_name=TOOL), selected, frozen)
        except (ValueError, TypeError, AttributeError):
            accepted, errors = {}, ["Incomplete or malformed scene response"]
        state["accepted"].update(accepted)
        state["errors"].append({"requested": selected, "errors": errors,
                                "missing": [i for i in selected if i not in accepted]})
        script_stages.save("scene-expansion", inputs, state)
    if state["status"] == "failed":
        missing = [i for i in ids if i not in state["accepted"]]
        raise ValueError("Scene expansion exhausted its two-attempt budget for: " + ", ".join(missing))
    return [deepcopy(state["accepted"][i]) for i in ids], state["cost"]
