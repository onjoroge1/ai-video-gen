#!/usr/bin/env python3
"""Script-only long-form check: generate a script and grade it, with no image/TTS/render spend.

A full long-form run costs several dollars and many minutes, and most of that is spent proving
things about the *script* that can be decided long before an image is bought. This harness stops
after the script stage and reports the acceptance criteria directly, so a structural change can be
evaluated in one call.

The research dossier is served from cache when available (RESEARCH_CACHE=1, the default), so
repeat runs cost nothing in metered web search.

    python scripts/longform_script_check.py "Why were doctors wrong about stomach ulcers?"
    python scripts/longform_script_check.py --duration 90 --format evidence_led_mystery "..."

Exit code is 0 only when every criterion passes.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import explainer_pipeline as ep
from longform_research import validate_claim_joins, validate_research_dossier
from longform_retention import validate_longform_story
from runtime_planner import plan_runtime

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def _mark(ok: bool) -> str:
    return f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--duration", type=int, default=90)
    parser.add_argument("--format", default="evidence_led_mystery",
                        help="standard_explainer | evidence_led_mystery")
    parser.add_argument("--video-format", default="landscape")
    parser.add_argument("--show-script", action="store_true", help="print the narration")
    args = parser.parse_args()

    log = lambda message: print(f"{DIM}  {message}{RESET}")
    costs: list = []

    print(f"\n=== RESEARCH ===")
    dossier = ep.generate_research_dossier(args.question, cost_sink=costs, log=log)
    claims = dossier.get("claims") or []

    print(f"\n=== SCRIPT ===")
    script = ep.generate_graded_script(
        args.question, args.duration, "engaging and scientific", "",
        args.video_format, "", cost_sink=costs, log=log,
        story_format=args.format, research_dossier=dossier)

    # The repairs that normally run inside the pipeline, so the checks below see what it would.
    ep._repair_claim_phrases(script, log)
    ep._repair_anchor_phrases(script, log)

    # The refit too. This claimed to run what the pipeline runs while omitting the single
    # largest rewriter of narration, so it graded a draft that is never what gets rendered --
    # and it therefore could not see the pipeline's most persistent defect, that compressing
    # to the word budget destroys the sentence cadence the generator was asked for. Anything
    # measured before this point is a statement about draft one, not about the video.
    ep._enforce_requested_runtime(script, args.duration, cost_sink=costs, log=log)

    scenes = script.get("scenes") or []
    if args.show_script:
        print(f"\n=== NARRATION ===")
        for index, scene in enumerate(scenes, 1):
            role = scene.get("story_role", "?")
            mystery = scene.get("_role", "")
            tag = f"{role}/{mystery}" if mystery and mystery != role else role
            print(f"  [{index}] {tag}\n      {(scene.get('narration') or '').strip()}")

    print(f"\n=== ACCEPTANCE CRITERIA ===")
    results = []

    # 1. word count as the renderer would see it, after the refit
    runtime = plan_runtime(scenes, args.duration)
    # Same bounds the pipeline enforces: derived from this draft's punctuation, not
    # from an assumed one-sentence-per-scene. Grading against the assumed window let
    # the harness pass a script the pipeline would reject on seconds.
    target = int(runtime.get("target_words") or 0)
    low = int(runtime.get("min_words") or 0)
    high = int(runtime.get("max_words") or 0)
    words = int(runtime.get("word_count") or 0)
    ok_words = low <= words <= high
    results.append(ok_words)
    print(f"  {_mark(ok_words)}  narration words: {words} (allowed {low}-{high}, "
          f"{runtime.get('estimated_seconds', 0):.1f}s vs {args.duration}s target, "
          f"{len(scenes)} scenes)")

    # 2. evidence coverage
    joins = validate_claim_joins(script, dossier)
    unbound = [e for e in joins.get("errors", []) if e.get("code") == "unbound_factual_scene"]
    ok_claims = bool(joins.get("passed"))
    results.append(ok_claims)
    print(f"  {_mark(ok_claims)}  evidence coverage: {len(claims)} verified claims, "
          f"{len(joins.get('errors', []))} join error(s)"
          + (f", {len(unbound)} unbound factual scene(s)" if unbound else ""))
    for issue in joins.get("errors", [])[:4]:
        print(f"          {DIM}{issue.get('code')}: scene {issue.get('scene')}{RESET}")

    # 3. cadence, via the story-format gates
    engine = ep._review_story_structure(script, args.format, args.video_format, lambda m: None)
    cadence = [c for c in (engine.get("failure_codes") or []) if str(c).startswith("cadence")]
    ok_cadence = not cadence
    results.append(ok_cadence)
    measured = engine.get("measurements") or {}
    print(f"  {_mark(ok_cadence)}  cadence: long {measured.get('long_frac', 0):.0%} (need 25%), "
          f"short {measured.get('short_frac', 0):.0%} (max 55%), "
          f"median {measured.get('median_sentence_words', 0)} words"
          + (f" — {', '.join(cadence)}" if cadence else ""))

    # 4. the opening contract, plus the rest of the retention contract for context
    story = validate_longform_story(script, args.question)
    opening_codes = {"opening_not_consequence", "subject_unclear_by_5s"}
    opening = [e for e in story.get("errors", []) if e.get("code") in opening_codes]
    ok_opening = not opening
    results.append(ok_opening)
    print(f"  {_mark(ok_opening)}  opening contract: "
          + ("clean" if ok_opening else ", ".join(e.get("code") for e in opening)))
    print(f"  {DIM}      retention contract overall: {story.get('score', '?')}/100, "
          f"{len(story.get('errors', []))} blocking{RESET}")
    for issue in story.get("errors", [])[:6]:
        print(f"          {DIM}{issue.get('code')}{RESET}")

    other = [c for c in (engine.get("failure_codes") or []) if not str(c).startswith("cadence")]
    if other:
        print(f"  {DIM}      story-engine (review only): {', '.join(other)}{RESET}")

    print(f"\n  cost: ${sum(float(c or 0) for c in costs):.3f} (script only — no image, TTS or render)")
    passed = all(results)
    print(f"  {_mark(passed)}  {sum(results)}/4 criteria\n")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
