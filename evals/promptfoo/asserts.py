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
    """Apply the editor's scenes to the fixture and re-run the detector."""
    import script_editor as se
    v = context.get("vars") or {}
    script = _fixture(v["script"])
    before = se.detect_defects(script, script.get("_claim_validation"))
    data = _json(output)
    rows = data.get("scenes") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return {"pass": False, "score": 0.0, "reason": "no scenes in the reply"}
    targets = {int(d["scene"]) for d in before}
    done = set()
    for row in rows:
        index = int((row or {}).get("scene") or 0)
        text = ((row or {}).get("narration") or "").strip()
        if index in targets and text:
            script["scenes"][index - 1]["narration"] = text
            done.add(index)
    if done != targets:
        return {"pass": False, "score": 0.0, "reason": f"edited {sorted(done)} of {sorted(targets)}"}
    after = se.detect_defects(script, None)
    keys_before = {(d["scene"], d["code"]) for d in before if d["code"] != se.EXCEEDS_EVENT}
    keys_after = {(d["scene"], d["code"]) for d in after}
    still = keys_before & keys_after
    new = {k for k in keys_after if k[1] in (se.REPEAT, se.COLD_OPEN_RESTATED)} - keys_before
    ok = not still and not new
    return {"pass": ok, "score": 1.0 if ok else max(0.0, 1 - (len(still) + len(new)) / max(1, len(keys_before))),
            "reason": ("resolved all " + str(len(keys_before))) if ok else
                      f"still {sorted(still)}; new {sorted(new)}"}


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
