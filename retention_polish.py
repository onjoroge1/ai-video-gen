"""Bounded editorial revision of a sourced script after its technical repairs.

Scores are editorial proxies, not measured YouTube retention. Evidence and structure veto
every candidate; a higher model score alone never licenses new facts or a later mechanism.
"""
from copy import deepcopy
import json
from pathlib import Path
import re

import storyboard_repair as repair
import script_cadence
import hook_callback
from script_repair import broken_repair

VERSION = "retention_polish_v1"
FILENAME = VERSION + ".json"
AXES = ("hook", "story", "ending", "repetition", "cadence")
MAX_PASSES = 2
MAX_SCENES = 4


def target_errors(grade, target=78, floor=70):
    if not isinstance(grade, dict) or not isinstance(grade.get("scores"), dict):
        return ["UNSCORED: final narration grader unavailable"]
    scores = grade["scores"]
    values = [grade.get("overall")] + [scores.get(axis) for axis in AXES]
    if any(type(v) not in (int, float) or not 0 <= v <= 100 for v in values):
        return ["UNSCORED: invalid final narration grades"]
    errors = []
    if grade["overall"] < target:
        errors.append(f"overall {grade['overall']} below {target}")
    for axis in AXES:
        minimum = target if axis in ("hook", "story") else floor
        if scores[axis] < minimum:
            errors.append(f"{axis} {scores[axis]} below {minimum}")
    return errors


def apply_edits(script, response):
    """Narration-only, at most four scenes; all source and causal metadata remain immutable."""
    rows = response.get("scenes") if isinstance(response, dict) else None
    if (not isinstance(response, dict) or set(response) != {"scenes"}
            or not isinstance(rows, list) or not 1 <= len(rows) <= MAX_SCENES):
        raise ValueError("Editorial response must contain one to four scene edits")
    candidate = deepcopy(script)
    scenes = candidate.get("scenes") or []
    by_id = {s.get("scene_id"): s for s in scenes}
    if len(by_id) != len(scenes) or not all(by_id):
        raise ValueError("Editorial revision requires unique scene IDs")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"scene_id", "narration"}:
            raise ValueError("Editorial response may change narration only")
        sid, text = row["scene_id"], row["narration"]
        if not isinstance(sid, str) or sid not in by_id or sid in seen or broken_repair(text):
            raise ValueError("Invalid editorial scene or incomplete narration")
        seen.add(sid)
        old = by_id[sid]["narration"]
        if len(text.split()) > len(old.split()) + 8:
            raise ValueError("Editorial revision padded a scene")
        import causal_story as cs
        marker = cs._MARKER.match(old)
        if marker and not text.startswith(marker.group()):
            raise ValueError("Editorial revision changed a spoken chapter marker")
        by_id[sid]["narration"] = text.strip()
    old_total = sum(len(s.get("narration", "").split()) for s in script["scenes"])
    new_total = sum(len(s.get("narration", "").split()) for s in scenes)
    if not .85 * old_total <= new_total <= 1.05 * old_total:
        raise ValueError("Editorial revision exceeded its total word budget")
    if scenes[0]["scene_id"] in seen:
        cold = script.get("_cold_open") or ""
        if cold and cold.casefold().rstrip(".!?") not in scenes[0]["narration"].casefold():
            raise ValueError("Editorial revision changed the sourced cold open")
        if script.get("hook"):
            candidate["hook"] = re.split(r"(?<=[.!?])\s+", scenes[0]["narration"], maxsplit=1)[0]
    return candidate


def prompt(script, grade, target, floor):
    return (
        "Improve this sourced YouTube narration without inventing facts. Use submit_narration_edits "
        "for at most FOUR weak scenes; all others are read-only. Address the grade's named weakness. "
        "Hook: name the subject, make a concrete surprising promise in <=18 words, and create a "
        "question the story earns. Story: each scene adds a distinct consequence or complication, "
        "not another version of the same claim. Remove repetition, preserve uncertainty, vary "
        "sentence lengths naturally, and end with the concrete opening object and its changed meaning. "
        "Do not manufacture mystery by concealing the causal mechanism; keep it early. "
        "Every assertion must stay inside that scene's event. Keep IDs, order, sourced cold open "
        "verbatim, chapter markers, hinge <=10 words, and callback. If editing the first scene, "
        "its FIRST sentence is the new hook. No new scene, fact, date, actor, or statistic. "
        "No scene may grow by more than 8 words; total length must stay within 85%-105%. "
        "Return complete spoken sentences, not clipped fragments or editorial instructions.\n"
        + script_cadence.BRIEF
        + hook_callback.BRIEF + hook_callback.expansion_direction(script)
        + json.dumps({"cadence": script_cadence.measure(script), "grade": grade, "targets": {"overall": target, "hook": target,
            "story": target, "other_axes": floor}, "hook": script.get("hook"),
            "cold_open": script.get("_cold_open"), "contract": script.get("_story_contract"),
            "scenes": [{k: s.get(k) for k in ("scene_id", "narration", "causal_role", "event",
                                               "continues", "claim_refs", "chapter")}
                       for s in script["scenes"]]}, ensure_ascii=False))


def run(script, question, dossier, output_dir, cost_sink, log):
    import explainer_pipeline as ep
    import illustrated_story as lane
    from durable_execution import current

    path = Path(output_dir) / FILENAME
    saved = json.loads(path.read_text()) if path.exists() else None
    context_hash = repair.digest({"question": question, "dossier": dossier, "version": VERSION,
                                  "target": ep._SCRIPT_GATE_PASS, "floor": ep._SCRIPT_GATE_FLOOR,
                                  "cadence_policy": script_cadence.VERSION,
                                  "hook_policy": hook_callback.VERSION})
    if saved:
        if saved.get("context_hash") != context_hash:
            raise ValueError("Saved editorial pass belongs to different evidence or targets")
        identities = {repair.story_identity(saved["input_script"]),
                      repair.story_identity(saved["script"])}
        if repair.story_identity(script) not in identities:
            raise ValueError("Saved editorial pass belongs to different narration")
        if saved["status"] == "complete":
            return saved["script"], saved["report"]
    record = saved or {"context_hash": context_hash, "version": VERSION, "status": "started", "input_script": deepcopy(script),
                       "script": deepcopy(script), "attempts": []}

    def persist():
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        temp.replace(path)
        runtime = current()
        if runtime is not None:
            runtime.checkpoint("retention-polish-" + record["status"])

    if not saved:
        persist()  # checkpoint before the first paid grade
    best = record["script"]
    if "grade" not in record:
        record["grade"] = ep.grade_script(best, cost_sink=cost_sink)
        persist()
    grade = record["grade"]
    target, floor = ep._SCRIPT_GATE_PASS, ep._SCRIPT_GATE_FLOOR
    for attempt in range(len(record["attempts"]), MAX_PASSES):
        if repair.has_media(output_dir):
            break  # never invalidate already-purchased narration or images
        if record["attempts"] and not record["attempts"][-1]["accepted"]:
            break  # a worker yielded after persisting a rejection; do not buy a second try
        issues = target_errors(grade, target, floor)
        if not issues or any(e.startswith("UNSCORED:") for e in issues):
            break
        ids = [s.get("scene_id") for s in best.get("scenes") or []]
        if not ids or not all(ids) or len(ids) != len(set(ids)):
            break
        log(f"Editorial pass {attempt + 1}/{MAX_PASSES}: improving {grade.get('weakest', 'story')}")
        response = ep._claude().messages.create(
            model=ep.ANTHROPIC_MODEL, max_tokens=4000,
            system="You are an evidence-bound YouTube story editor. Submit narration edits only.",
            tools=[repair.response_tool(ids, max_edits=min(MAX_SCENES, len(ids)))],
            tool_choice={"type": "tool", "name": repair.EDIT_TOOL},
            messages=[{"role": "user", "content": prompt(best, grade, target, floor)}])
        cost_sink.append(ep._msg_cost(response.usage))
        audit = {"before_grade": grade, "accepted": False}
        try:
            data = repair.response_data(response)
            audit["response"] = data
            candidate = apply_edits(best, data)
            ep.rederive_narration_bindings(candidate, log, dossier)
            board = lane.build_storyboard(deepcopy(candidate), question)
            structure = ep.validate_longform_story(candidate, question)
            if (not board["validation"].get("passed") or not structure.get("passed")
                    or ep.duplicate_narration(candidate["scenes"])):
                raise ValueError("Editorial revision failed structure, timing, callback or repetition checks")
            runtime_target = (best.get("_runtime_plan") or {}).get("target_seconds")
            if runtime_target:
                from runtime_planner import plan_runtime
                runtime_report = plan_runtime(candidate["scenes"], runtime_target)
                if not runtime_report["passed"] and ((best.get("_runtime_plan") or {}).get("passed") or ep._runtime_is_enforced()):
                    raise ValueError("Editorial revision failed the runtime budget")
                candidate["_runtime_plan"] = runtime_report
            claims = ep._validate_claims(candidate, dossier, cost_sink)
            audit["claim_validation"] = claims
            if not claims.get("passed"):
                raise ValueError("Editorial revision exceeded its evidence")
            updated = ep.grade_script(candidate, cost_sink=cost_sink)
            audit["after_grade"] = updated
            if (any(e.startswith("UNSCORED:") for e in target_errors(updated, target, floor))
                    or updated["overall"] <= grade["overall"]
                    or any(updated["scores"][axis] < grade["scores"][axis] for axis in AXES)):
                raise ValueError("Editorial revision did not improve without weakening another axis")
            candidate["_claim_validation"] = claims
            candidate["_grade"] = updated
            best, grade = candidate, updated
            audit["accepted"] = True
        except (ValueError, TypeError, KeyError) as exc:
            audit["reason"] = str(exc)
            log("Editorial revision rejected: " + str(exc))
        record["attempts"].append(audit)
        record.update(script=best, grade=grade)
        persist()
        if not audit["accepted"]:
            break  # no improvement: stop spending instead of re-rolling
    errors = target_errors(grade, target, floor)
    # Baselines face the same structural checks as edited candidates. A high score
    # must not turn an unchecked baseline into a ready script.
    if not ep.validate_longform_story(best, question).get("passed"):
        errors.append("STRUCTURE: final narration violates the long-form contract")
    if not lane.build_storyboard(deepcopy(best), question)["validation"].get("passed"):
        errors.append("STORYBOARD: final narration violates the illustrated contract")
    if ep.duplicate_narration(best.get("scenes") or []):
        errors.append("DUPLICATES: final narration repeats a scene")
    report = {"version": VERSION, "passed": not errors, "errors": errors, "grade": grade,
              "narration_sha256": repair.story_identity(best), "attempts": len(record["attempts"])}
    best["_cadence_review"] = script_cadence.measure(best)
    best["_grade"] = grade or {"status": "UNSCORED"}
    best["_final_retention_review"] = report
    record.update(status="complete", script=best, report=report)
    persist()
    log("Final narration engagement: " + ("PASS" if not errors else "; ".join(errors)))
    return best, report
