"""The targeted editor: one bounded pass that rewrites only the scenes with a named defect.

The pipeline grew five separate repair prompts (claims, hook, hinge, storyboard, repeats), each
rewriting a scene in isolation. The killer bees film (2026-10-02) showed the failure mode: the
claim repair rewrote both halves of a split beat toward the same supported sentence and the film
said the escape twice. An editor needs the whole script in view, a list of named defects, a
narrow licence (change only those scenes, assert nothing beyond each scene's event), and a
deterministic check afterwards that the defects are gone and no new one appeared.

    python3 script_editor.py jobs/<id>            # report defects, write script.edited.json
    python3 script_editor.py jobs/<id> --apply    # also write the edit back into _state.json

Detectors are free. One rewrite and bounded semantic validation calls may spend.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any

REPEAT = "REPEAT"
COLD_OPEN_RESTATED = "COLD_OPEN_RESTATED"
META_PHRASE = "META_PHRASE"
FILLER = "FILLER"
HOOK_TOO_LONG = "HOOK_TOO_LONG"
HINGE_TOO_LONG = "HINGE_TOO_LONG"
EXCEEDS_EVENT = "EXCEEDS_EVENT"

_META = re.compile(r"explained like you are five|in this video|let'?s dive|welcome back|"
                   r"in this chapter|here'?s the (?:reveal|peak|hook)|stay tuned", re.I)
_FILLER = re.compile(r"\bas we saw\b|\bas mentioned\b|\bremember\b|\brecall\b|\bin other words\b|"
                     r"\bas (?:we|i) said\b|\bto recap\b", re.I)

_SYSTEM = (
    "You are the targeted editor of an already-written, sourced video script. You receive the "
    "whole script and a list of defects, each naming one scene. Rewrite ONLY the listed scenes. "
    "Every other scene is read-only context. For each rewritten scene keep its role, its place "
    "in the order, its tone and its causal meaning; keep its word count inside the words_allowed "
    "range given for it (count them), and assert nothing "
    "beyond its `event` text: no number, date, place, named actor, motive or quantity the event "
    "does not contain. Explicit context_events also support brief causal connections and "
    "callbacks, without adding facts or re-explaining earlier scenes. Rules by defect: REPEAT -- the scene says what an earlier scene already "
    "said; write what that scene did NOT say: the next stretch of time, the particular, the "
    "consequence, the picture. COLD_OPEN_RESTATED -- the scene retells the opening flash-forward; "
    "tell the same moment in full and in sequence with the particulars the flash-forward withheld. "
    "For both, the defect note lists the SHARED WORDS the gate measured: your rewrite may keep at "
    "most HALF of them. Refer back with an article or pronoun ('the queens', 'that apiary', "
    "'the breach') instead of naming the thing again, and spend the words on what the event "
    "holds that the earlier scene left out. A rewrite that keeps the same nouns in a new order "
    "fails the gate and is thrown away. "
    "META_PHRASE / FILLER -- remove the phrase that narrates the video or points backwards; say "
    "the content directly. HOOK_TOO_LONG / HINGE_TOO_LONG -- cut to the budget without losing the "
    "turn. EXCEEDS_EVENT -- cut the listed unsupported details rather than hedging them. "
    "Every repaired sentence must be grammatically complete; rewrite the sentence instead of "
    "deleting a span that leaves a dangling preposition or removes its predicate. "
    "Return ONLY JSON: {\"scenes\": [{\"scene\": <1-based index>, \"narration\": \"...\"}]}"
)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _words(text: str) -> set[str]:
    import explainer_pipeline as ep
    return {w for w in re.findall(r"[a-z]{3,}", _text(text).lower()) if w not in ep._DUP_STOP}


def detect_defects(script: dict, claim_report: dict | None = None) -> list[dict]:
    """Every defect the editor can act on, found without a model."""
    import causal_story as cs
    import explainer_pipeline as ep
    scenes = script.get("scenes") or []
    out: list[dict] = []
    for d in ep.duplicate_narration(scenes):
        if not d.get("continuation"):
            shared = sorted(_words(scenes[d["scene"] - 1].get("narration"))
                            & _words(scenes[d["duplicate_of"] - 1].get("narration")))
            out.append({"scene": d["scene"], "code": REPEAT,
                        "note": f"repeats scene {d['duplicate_of']} ({d['overlap']:.0%} overlap); "
                                f"shared words: {', '.join(shared)}"})
    cold = _text(script.get("_cold_open"))
    if cold:
        cw = _words(cold)
        for i, scene in enumerate(scenes[1:], 2):
            for sentence in re.split(r"(?<=[.!?])\s+", _text(scene.get("narration"))):
                sw = _words(sentence)
                if cw and sw and len(cw & sw) / len(cw | sw) >= 0.6:
                    if not any(x["scene"] == i and x["code"] in (REPEAT, COLD_OPEN_RESTATED) for x in out):
                        out.append({"scene": i, "code": COLD_OPEN_RESTATED,
                                    "note": f"retells the cold open: {sentence[:80]!r}; "
                                            f"shared words: {', '.join(sorted(cw & sw))}"})
                    break
    for i, scene in enumerate(scenes, 1):
        narration = _text(scene.get("narration"))
        m = _META.search(narration)
        if m:
            out.append({"scene": i, "code": META_PHRASE, "note": m.group(0)})
        f = _FILLER.search(narration)
        if f:
            out.append({"scene": i, "code": FILLER, "note": f.group(0)})
        role = _text(scene.get("causal_role") or scene.get("role")).lower()
        if role == cs.HINGE and len(narration.split()) > cs.MAX_HINGE_WORDS:
            out.append({"scene": i, "code": HINGE_TOO_LONG,
                        "note": f"{len(narration.split())} words over {cs.MAX_HINGE_WORDS}"})
    hook = _text(script.get("hook"))
    if hook and len(hook.split()) > cs.MAX_HOOK_WORDS and scenes:
        out.append({"scene": 1, "code": HOOK_TOO_LONG,
                    "note": f"hook is {len(hook.split())} words over {cs.MAX_HOOK_WORDS}"})
    by_beat = {}
    for position, scene in enumerate(scenes, 1):
        for key in ("beat_id", "scene_id"):
            if _text(scene.get(key)):
                by_beat.setdefault(_text(scene.get(key)), position)
    for item in ((claim_report or {}).get("errors") or []):
        if not isinstance(item, dict) or item.get("code") != "NARRATION_EXCEEDS_EVENT":
            continue
        marker = item.get("scene")
        index = int(marker) if isinstance(marker, int) or (isinstance(marker, str) and marker.isdigit()) \
            else by_beat.get(_text(marker), 0)
        if index:
            out.append({"scene": index, "code": EXCEEDS_EVENT,
                        "note": "; ".join(_text(d) for d in (item.get("unsupported_details") or []))})
    out.sort(key=lambda d: (d["scene"], d["code"]))
    return out


def build_payload(script: dict, research_dossier: dict | None, defects: list[dict]) -> dict:
    """The editor's user message, shared by the pipeline and the promptfoo eval."""
    from longform_research import claim_context_for_prompt
    import causal_story as cs
    scenes = script.get("scenes") or []
    targets = {int(d["scene"]) for d in defects if 1 <= int(d["scene"]) <= len(scenes)}
    rows = []
    for i, s in enumerate(scenes):
        row = {"scene": i + 1, "role": _text(s.get("causal_role") or s.get("story_role")),
               "narration": _text(s.get("narration"))}
        if (i + 1) in targets:
            n = len(_text(s.get("narration")).split())
            row["event"] = (s.get("event") or {}).get("text", "")
            from story_fact_model import context_events
            row["context_events"] = context_events(s, scenes)
            row["words_now"] = n
            row["words_allowed"] = f"{max(6, int(n * 0.8))}-{int(n * 1.2) + 1}"
            codes = {d["code"] for d in defects if int(d["scene"]) == i + 1}
            if HINGE_TOO_LONG in codes:
                row["words_allowed"] = f"1-{cs.MAX_HINGE_WORDS}"
            if HOOK_TOO_LONG in codes:
                row["hook_words_allowed"] = f"1-{cs.MAX_HOOK_WORDS}"
        rows.append(row)
    return {
        "hook": _text(script.get("hook")),
        "cold_open": _text(script.get("_cold_open")),
        "scenes": rows,
        "defects": [{"scene": int(d["scene"]), "code": _text(d["code"]), "note": _text(d.get("note"))}
                    for d in defects if int(d["scene"]) in targets],
        "claims": claim_context_for_prompt(research_dossier or {}),
    }


def _keys(defects: list[dict]) -> set[tuple[int, str]]:
    return {(int(d["scene"]), _text(d["code"])) for d in defects}


def edit(script: dict, research_dossier: dict | None, defects: list[dict],
         cost_sink: list | None = None, log=lambda message: None) -> tuple[dict, float, list[dict]]:
    """One editor pass. Returns (script, cost, remaining defects).

    The edit is accepted only when every listed defect is gone from its scene and no new REPEAT
    or COLD_OPEN_RESTATED appeared anywhere; otherwise the original script is returned with the
    defects still listed, so the caller's gate can refuse the render honestly.
    """
    import explainer_pipeline as ep
    scenes = script.get("scenes") or []
    targets = sorted({int(d["scene"]) for d in defects if 1 <= int(d["scene"]) <= len(scenes)})
    if not targets:
        return script, 0.0, []
    payload = build_payload(script, research_dossier, defects)
    cost = 0.0
    try:
        response = ep._claude().messages.create(
            model=ep.ANTHROPIC_MODEL, max_tokens=4000, system=_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
        cost = ep._msg_cost(response.usage)
        if cost_sink is not None:
            cost_sink.append(cost)
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw[raw.find("{"):raw.rfind("}") + 1]
        data = json.loads(raw)  # malformed edits stop; never buy an unbounded JSON rewrite
    except __import__("durable_execution").DurableExecutionError:
        raise
    except Exception as exc:
        log(f"  editor unavailable: {type(exc).__name__}: {str(exc)[:120]}")
        return script, round(cost, 4), defects
    candidate, remaining = apply_response(script, defects, data, log=log)
    if candidate is script:
        return script, round(cost, 4), defects
    semantic_costs = []
    if not semantic_accepts(candidate, research_dossier or {}, cost_sink=semantic_costs):
        log("  editor: semantic validation failed; keeping the original")
        candidate, remaining = script, defects
    if cost_sink is not None:
        for amount in semantic_costs:
            cost_sink.append(amount)
    return candidate, round(cost + sum(semantic_costs), 4), remaining


def semantic_accepts(candidate, dossier, *, cost_sink=None):
    """Shared by the production editor and Promptfoo; a detector pass is insufficient."""
    import explainer_pipeline as ep
    report = ep._validate_claims(candidate, dossier, cost_sink)
    return bool(report.get("passed")) and not report.get("retryable")


def apply_response(script, defects, data, *, log=lambda message: None):
    """Pure edit transaction. Reject missing, duplicate, foreign or malformed scene edits."""
    scenes = script.get("scenes") or []
    targets = sorted({int(d["scene"]) for d in defects if 1 <= int(d["scene"]) <= len(scenes)})
    rows = data.get("scenes") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return script, defects
    candidate = json.loads(json.dumps(script))
    done = set()
    for row in rows:
        if not isinstance(row, dict) or type(row.get("scene")) is not int:
            return script, defects
        index = row["scene"]
        text = _text((row or {}).get("narration"))
        from script_repair import broken_repair
        if broken_repair(text):
            log("  editor: incomplete narration repair; keeping the original")
            return script, defects
        if index not in targets or index in done or not text:
            return script, defects
        if index in targets and text:
            candidate["scenes"][index - 1]["narration"] = text
            done.add(index)
    if done != set(targets):
        log("  editor: did not return every listed scene; keeping the original")
        return script, defects
    if any(d["code"] == HOOK_TOO_LONG for d in defects):
        first = re.split(r"(?<=[.!?])\s+", _text(candidate["scenes"][0].get("narration")), maxsplit=1)[0]
        if first:
            candidate["hook"] = first
    for index in targets:
        was = len(_text(scenes[index - 1].get("narration")).split())
        now = len(_text(candidate["scenes"][index - 1].get("narration")).split())
        budget_edit = any(int(d["scene"]) == index and d["code"] in
                          (HOOK_TOO_LONG, HINGE_TOO_LONG) for d in defects)
        if not budget_edit and was >= 8 and abs(now - was) / was > 0.35:
            log(f"  editor: scene {index} went {was}->{now} words; keeping the original")
            return script, defects
    after = detect_defects(candidate, None)
    wanted = {k for k in _keys(defects) if k[1] != EXCEEDS_EVENT}
    still = wanted & _keys(after)
    new_repeats = {k for k in _keys(after) if k[1] in (REPEAT, COLD_OPEN_RESTATED)} - _keys(defects)
    if still or new_repeats:
        log("  editor: " + (f"{len(still)} defect(s) remain" if still else "")
            + (f"; {len(new_repeats)} new repeat(s)" if new_repeats else "") + "; keeping the original")
        return script, defects
    for index in targets:
        log(f"  ✎ scene {index} edited: " + ", ".join(_text(d["code"]) for d in defects if int(d["scene"]) == index))
    remaining = [d for d in after if d["code"] in {k[1] for k in _keys(defects)}]
    return candidate, remaining


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    root = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, root)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(root, ".env"))
    state_path = os.path.join(args.job, "_state.json")
    state = json.load(open(state_path, encoding="utf-8"))
    script = state["script"]
    dossier = script.get("_research_dossier") or {}
    defects = detect_defects(script, script.get("_claim_validation"))
    print(f"{len(defects)} defect(s):")
    for d in defects:
        print(f"  scene {d['scene']:2d} {d['code']:20} {d['note'][:100]}")
    if not defects:
        return 0
    costs: list[float] = []
    edited, cost, remaining = edit(script, dossier, defects, costs, print)
    print(f"editor cost ${cost:.3f}; remaining {len(remaining)}")
    out = os.path.join(args.job, "script.edited.json")
    json.dump(edited, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("wrote", out)
    if args.apply and edited is not script:
        backup = state_path + ".bak"
        os.replace(state_path, backup)
        state["script"] = edited
        json.dump(state, open(state_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print(f"applied to {state_path} (backup {backup})")
    return 0 if not remaining else 1


if __name__ == "__main__":
    sys.exit(main())
