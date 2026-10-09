#!/usr/bin/env python3
"""Replay a saved illustrated script through every deterministic gate up to the first spend.

No provider calls, no money. Takes a script the pipeline already wrote -- a job's `_state.json`
checkpoint, a Finished Videos `.script` sidecar, or a script-cache entry -- and runs it through
the same functions run_explainer_pipeline calls between "Script ready" and "Preparing narration":

    presentation repairs (offline: the writer is absent, so only the deterministic fallbacks run)
    illustrated storyboard and causal contract        illustrated_story.build_storyboard
    long-form retention contract                       longform_retention.validate_longform_story
    runtime contract                                   runtime_planner.plan_runtime
    evidence-state plan                                longform_evidence.compile/validate
    motion plan (stills)                               longform_motion.compile/validate
    music spec                                         illustrated_score.score_spec
    pre-spend cost estimate                            explainer_pipeline.estimate_cost

It reports each gate's verdict and whether the pipeline would BLOCK on it, so a run can be
checked to the spend line without buying research, a script, or a single image. It does not
run the fact-check or the claim ledger (both are paid judge calls), TTS, images, or the render.

    python scripts/illustrated_dry_run.py /path/to/_state.json --duration 300
    python scripts/illustrated_dry_run.py finished_videos/kudzu26-*.script --json report.json
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Offline by construction: no key means every provider client construction fails loudly, and
# the repairs below are written to fall back rather than raise when the writer is absent.
for _key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
    os.environ.pop(_key, None)
os.environ.setdefault("RESEARCH_CACHE", "0")
os.environ.setdefault("SCRIPT_CACHE", "0")

import explainer_pipeline as ep                      # noqa: E402
import illustrated_story as illustrated              # noqa: E402
import illustrated_score                             # noqa: E402
from longform_evidence import compile_evidence_plan, validate_evidence_plan   # noqa: E402
from longform_motion import compile_motion_plan, validate_motion_plan          # noqa: E402
from longform_retention import validate_longform_story                         # noqa: E402
from runtime_planner import plan_runtime                                       # noqa: E402


def load_script(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict) and "script" in data and isinstance(data["script"], dict):
        data = data["script"]                       # _state.json / .script sidecar shape
    if not isinstance(data, dict) or not data.get("scenes"):
        raise SystemExit(f"{path}: no scenes found in this file")
    return data


def _offline_writer():
    """A model client that is not there. The repairs must survive its absence."""
    class _Down:
        @property
        def messages(self):
            raise RuntimeError("offline dry run: no writer")
    return _Down()


def dry_run(script: dict, *, question: str, duration_sec: int, motion_mode: str = "stills",
            max_cost_usd: float = 10.0, log=print) -> dict:
    script = copy.deepcopy(script)
    report = {"gates": [], "blocking": [], "advisory": [], "script": {
        "scenes": len(script.get("scenes") or []),
        "engine": script.get("_story_engine"),
        "compiled": bool(script.get("_compiled_story")),
        "claim_ledger_passed": bool((script.get("_claim_validation") or {}).get("passed")),
        "gates_passed_when_stored": list(script.get("_gates_passed") or []),
    }}

    def gate(name: str, passed: bool, blocks: bool, detail: str = "", **extra):
        row = {"gate": name, "passed": bool(passed), "blocks_when_failing": blocks,
               "detail": detail, **extra}
        report["gates"].append(row)
        if not passed:
            (report["blocking"] if blocks else report["advisory"]).append(name)
        mark = "PASS" if passed else ("BLOCK" if blocks else "warn")
        log(f"  [{mark:5s}] {name}" + (f" — {detail}" if detail else ""))
        return row

    # 0. Presentation repairs, offline. The hook/hinge/mechanism repairs need the writer and
    #    return the script unchanged without it; the callback repair has a deterministic line.
    ep._claude = _offline_writer
    costs: list = []
    before = ep._mechanism_position(script.get("scenes") or [], script.get("_story_engine"),
                                    bool(script.get("_compiled_story")))
    if ep._align_callback_object(script, log=lambda m: None):
        log("  callback object label aligned to the opening object")
    script, _ = ep._ensure_close_returns_to_object(script, costs, log=lambda m: None)
    script, _ = ep._ensure_mechanism_meets_deadline(script, costs, log=lambda m: None)
    log(f"  mechanism at {before['before'] / max(1, before['total']):.1%} of words "
        f"against a {before['pct']:.0%} line" + (" (LATE)" if before["late"] else ""))

    # 1. Storyboard + causal contract (blocks unless ILLUSTRATED_STORYBOARD_HARD=0)
    try:
        board = illustrated.build_storyboard(script, question)
        validation = board.get("validation") or {}
        gate("illustrated storyboard / causal contract", validation.get("passed"),
             ep._illustrated_storyboard_hard(),
             "; ".join(validation.get("errors") or [])[:400],
             beats=len(board.get("beats") or []),
             locations=len((board.get("visual_bible") or {}).get("locations") or []))
    except Exception as exc:
        gate("illustrated storyboard / causal contract", False, True,
             f"{type(exc).__name__}: {exc}"[:400])
        board = {}

    # 2. Long-form retention contract (advisory on this lane)
    retention = validate_longform_story(script, question)
    gate("long-form retention contract", retention.get("passed"), False,
         f"score {retention.get('score')}/100; "
         + "; ".join(_s(e) for e in (retention.get("errors") or [])[:3])[:300])

    # 3. Runtime contract (advisory unless RUNTIME_HARD=1)
    runtime = plan_runtime(script.get("scenes") or [], float(duration_sec))
    gate("runtime contract", runtime.get("passed"), ep._runtime_is_enforced(),
         f"{runtime.get('estimated_seconds', 0):.1f}s estimated for {duration_sec}s "
         f"({runtime.get('word_count')} words, allowed "
         f"{runtime.get('min_words')}-{runtime.get('max_words')})")

    # 4. Evidence-state plan (blocks)
    try:
        ep.rederive_narration_bindings(script, lambda m: None, script.get("_research_dossier"))
    except Exception:
        pass
    plan = compile_evidence_plan(script)
    ev = plan.get("validation") or {}
    states = [state for scene in plan.get("scenes") or [] for state in scene.get("states") or []]
    generated = [s for s in states if s.get("asset_strategy") in {"master", "distinct"}]
    gate("evidence-state plan", ev.get("passed"), True,
         "; ".join(_s(e.get("message")) for e in (ev.get("errors") or [])[:4])[:400],
         states=len(states), generated_images=len(generated))

    # 5. Motion plan (blocks)
    motion = compile_motion_plan(script, plan, mode=motion_mode, max_requests=0)
    mv = motion.get("validation") or {}
    gate("motion plan", mv.get("passed"), True,
         "; ".join(_s(e.get("message")) for e in (mv.get("errors") or [])[:4])[:300],
         selected=motion.get("selected_count"))

    # 6. Music spec (never blocks; failure means narration-only)
    try:
        spec = illustrated_score.score_spec(question, _s(script.get("_story_engine")),
                                            float(duration_sec))
        gate("music spec", True, False, f"{spec.get('mood')} {spec.get('mode')} "
             f"{spec.get('tempo_bpm')} bpm, theme {spec.get('theme_id')}")
    except Exception as exc:
        gate("music spec", False, False, f"{type(exc).__name__}: {exc}"[:200])

    # 7. Pre-spend estimate against the cap (blocks)
    narration_chars = sum(len(_s(s.get("narration"))) for s in script.get("scenes") or [])
    est = round(ep.estimate_cost(len(generated), 0, narration_chars) + len(states) * 0.02, 2)
    gate("pre-spend cost estimate", est <= max_cost_usd, True,
         f"${est:.2f} estimated against a ${max_cost_usd:.2f} cap", estimate_usd=est)

    report["would_reach_spend"] = not report["blocking"]
    return report


def _s(value) -> str:
    return str(value or "").strip()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("script", help="_state.json, a .script sidecar, or a script-cache file")
    parser.add_argument("--question", default="")
    parser.add_argument("--duration", type=int, default=300)
    parser.add_argument("--motion-mode", default="stills")
    parser.add_argument("--max-cost", type=float, default=10.0)
    parser.add_argument("--json", default="", help="write the report here")
    parser.add_argument("--store", action="store_true",
                        help="if the replay reaches the spend line, store the script in the "
                             "pipeline's script cache under the key the next launch of this "
                             "question will compute, so the render starts from this beat sheet")
    parser.add_argument("--operator-direction", default="",
                        help="the request's creative direction, if any (part of the cache key)")
    args = parser.parse_args(argv)
    script = load_script(args.script)
    question = args.question or _s(script.get("title")) or "dry run"
    print(f"Dry run: {args.script}")
    report = dry_run(script, question=question, duration_sec=args.duration,
                     motion_mode=args.motion_mode, max_cost_usd=args.max_cost)
    verdict = ("would reach the spend line" if report["would_reach_spend"]
               else "BLOCKED at: " + ", ".join(report["blocking"]))
    print(f"Result: {verdict}"
          + (f"; advisory: {', '.join(report['advisory'])}" if report["advisory"] else ""))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
    if args.store:
        if not report["would_reach_spend"]:
            print("Not stored: a script the gates would refuse must not be served to a render.")
            return 1
        print(store_for_reuse(script, question=question, duration_sec=args.duration,
                              operator_direction=args.operator_direction))
    return 0 if report["would_reach_spend"] else 1


def store_for_reuse(script: dict, *, question: str, duration_sec: int,
                    operator_direction: str = "") -> str:
    """Write the script where run_explainer_pipeline's cache read will find it.

    Same key the pipeline derives: model, question, duration, format, lane, the request's
    creative direction as illustrated_story.story_direction shapes it, the claim ids of the
    research dossier, and the prompt source. The dossier is the one carried on the script; a
    launch whose research cache holds a different claim set will miss and write fresh, which is
    the right outcome. Requires the script to have passed the claim ledger, because the pipeline
    skips the fact-check on a cached script and the ledger is what proved the text.
    """
    os.environ["SCRIPT_CACHE"] = "1"      # the harness disabled it above for the replay
    if not (script.get("_claim_validation") or {}).get("passed"):
        return "Not stored: this script never passed the claim ledger."
    direction = illustrated.story_direction(question, operator_direction)
    fingerprint = ep._script_fingerprint(
        duration_sec=duration_sec, video_format="landscape", story_format="standard_explainer",
        causal_lane=True, operator_direction=direction,
        research_dossier=script.get("_research_dossier") or {})
    stored = copy.deepcopy(script)
    stored["_fact_checked"] = True
    gates = [g for g in (stored.get("_gates_passed") or []) if g not in ("claim ledger", "replay")]
    stored["_gates_passed"] = gates + ["claim ledger", "replay"]
    ep._store_graded_script(question, fingerprint, stored, causal_lane=True)
    path = ep._script_cache_path(question, fingerprint)
    return (f"Stored for reuse at {path}\n  the next 300s launch of this question starts from "
            f"this beat sheet (SCRIPT_CACHE=0 to override)") if os.path.exists(path) \
        else "Not stored: the cache write failed."


if __name__ == "__main__":
    raise SystemExit(main())
