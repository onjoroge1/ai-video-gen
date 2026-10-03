"""promptfoo Python assertions: the pipeline's deterministic gates judge the model's output.

Each function receives (output, context) and returns {"pass", "score", "reason"}. No model is
asked anything here; a score is what the gates would do with this output in a real run.
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _json(output: str):
    raw = output if isinstance(output, str) else json.dumps(output)
    if "```" in raw:
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
    try:
        return json.loads(raw)
    except ValueError:
        start, end = raw.find("{"), raw.rfind("}")
        return json.loads(raw[start:end + 1]) if start >= 0 < end else None


def _fixture(name: str) -> dict:
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as handle:
        return json.load(handle)


def plan_has_hook_pair(output, context) -> dict:
    import hook_callback
    try:
        plan = _json(output)
        pair = hook_callback.contract(plan) if isinstance(plan, dict) else {}
        missing = [key for key in ("viewer_question", "supported_answer", "callback_image")
                   if not pair.get(key)]
        return {"pass": not missing, "score": int(not missing),
                "reason": "Missing hook-pair fields: " + ", ".join(missing) if missing else
                          "Hook/answer/callback present; semantic quality is separately judged"}
    except (ValueError, TypeError):
        return {"pass": False, "score": 0, "reason": "Invalid hook-pair response"}


def integrity_findings(output, context) -> dict:
    import script_integrity as si
    case = _fixture("script_integrity.json")[context["vars"]["case"]]
    try:
        report = si._normalise(_json(output), si._inputs({"scenes": case["scenes"]}, {"claims": []}))
        actual = {e["code"] for e in report["errors"]}
        expected = set(case["expected"])
        passed = actual == expected
        return {"pass": passed, "score": int(passed),
                "reason": f"Expected {sorted(expected)}; observed {sorted(actual)}"}
    except (ValueError, TypeError, KeyError):
        return {"pass": False, "score": 0, "reason": "Malformed or unaddressable integrity report"}


def plan_score(output, context) -> dict:
    """score_plan over the returned beat sheet; pass at 75 or more."""
    import story_planner as sp
    v = context.get("vars") or {}
    plan = _json(output)
    if not isinstance(plan, dict):
        return {"pass": False, "score": 0.0, "reason": "not a JSON object"}
    report = sp.score_plan(plan, v.get("engine") or "removed_keystone",
                           _fixture(v["dossier"]), int(v.get("duration") or 300))
    return {"pass": report["score"] >= 75, "score": report["score"] / 100.0,
            "reason": f"{report['score']}/100; " + ("; ".join(report["issues"]) or "clean")}


def plan_has_cold_open(output, context) -> dict:
    import causal_story as cs
    plan = _json(output) or {}
    cold = plan.get("cold_open")
    text = (cold.get("text") if isinstance(cold, dict) else cold) or ""
    issues = cs.check_cold_open(text, plan.get("hook") or "")
    return {"pass": not issues, "score": 0.0 if issues else 1.0,
            "reason": "; ".join(i["code"] for i in issues) or f"cold open: {text[:80]}"}


def plan_event_count(output, context) -> dict:
    from longform_research import events_for_runtime
    import story_planner as sp
    v = context.get("vars") or {}
    plan = _json(output) or {}
    n = len(sp.plan_beats(plan))
    target = events_for_runtime(int(v.get("duration") or 300))
    return {"pass": n >= 0.8 * target, "score": min(1.0, n / max(1, target)),
            "reason": f"{n} events for a target of about {target}"}


def edit_resolves_defects(output, context) -> dict:
    """The same structural transaction as production, not a claim of factual quality."""
    import script_editor as se
    try:
        script = _fixture(context["vars"]["script"])
        before = se.detect_defects(script, script.get("_claim_validation"))
        candidate, remaining = se.apply_response(script, before, _json(output))
        passed = candidate is not script and not remaining
        return {"pass": passed, "score": int(passed),
                "reason": "Structural edit contract only; grounding is checked separately"}
    except (ValueError, KeyError, TypeError):
        return {"pass": False, "score": 0, "reason": "Invalid edit transaction"}


def edit_is_grounded(output, context) -> dict:
    import script_editor as se
    if os.environ.get("REELFORGE_PAID_EVAL") != "1":
        return {"pass": False, "score": 0, "reason": "Semantic review unverified; paid eval disabled"}
    costs = []
    try:
        script = _fixture(context["vars"]["script"])
        defects = se.detect_defects(script, script.get("_claim_validation"))
        candidate, remaining = se.apply_response(script, defects, _json(output))
        passed = (candidate is not script and not remaining
                  and se.semantic_accepts(candidate, script.get("_research_dossier") or {}, cost_sink=costs))
        return {"pass": passed, "score": int(passed),
                "reason": f"Production semantic acceptance: {passed}; review estimate ${sum(costs):.4f}"}
    except (ValueError, KeyError, TypeError):
        return {"pass": False, "score": 0, "reason": "Invalid or ungrounded edit"}


def edit_keeps_length(output, context) -> dict:
    """Every rewritten scene stays within 35% of its original word count."""
    v = context.get("vars") or {}
    script = _fixture(v["script"])
    data = _json(output) or {}
    bad = []
    for row in data.get("scenes") or []:
        index = int((row or {}).get("scene") or 0)
        if not 1 <= index <= len(script["scenes"]):
            continue
        was = len((script["scenes"][index - 1].get("narration") or "").split())
        now = len(((row or {}).get("narration") or "").split())
        if was and abs(now - was) / was > 0.35:
            bad.append(f"scene {index}: {was}->{now} words")
    return {"pass": not bad, "score": 0.0 if bad else 1.0, "reason": "; ".join(bad) or "lengths held"}


def no_meta_phrases(output, context) -> dict:
    data = _json(output) or {}
    texts = [((row or {}).get("narration") or "") for row in data.get("scenes") or []]
    hits = [t[:60] for t in texts if re.search(r"explained like|in this video|let'?s dive|welcome back", t, re.I)]
    return {"pass": not hits, "score": 0.0 if hits else 1.0, "reason": "; ".join(hits) or "none"}
