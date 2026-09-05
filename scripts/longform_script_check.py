#!/usr/bin/env python3
"""Sample the production long-form script path, stopping before evidence assets, TTS and images.

This command makes PAID research/script/fact-check calls. Each sample is a fresh draft using
production's existing bounded replan policy. Research may reuse the normal verified cache.
A pass covers only the stages listed in the report, never request dispatch or a finished video.

    python scripts/longform_script_check.py --visual-style illustrated_story --duration 220 \
        --samples 5 --output script-check.json "Why did the plan backfire?"
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    # Providers/model constants read their configuration during import.
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

import explainer_pipeline as ep
import illustrated_story as illustrated
from longform_research import validate_claim_joins, validate_research_dossier
from longform_retention import validate_longform_story
from runtime_planner import plan_runtime


COVERAGE = ["research", "fresh graded script with production replans", "fact-check",
            "narration bindings", "claim joins", "configured runtime policy",
            "illustrated hook and storyboard when selected"]
EXCLUDED = ["HTTP approval and dispatch", "durable worker recovery", "evidence asset plan",
            "TTS and measured audio timing", "images", "render", "Blob publication"]


def _positive(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--duration", type=_positive, default=90)
    parser.add_argument("--format", choices=("standard_explainer", "evidence_led_mystery"),
                        default=None)
    parser.add_argument("--video-format", choices=("landscape", "social", "portrait"),
                        default="landscape")
    parser.add_argument("--visual-style", choices=("cinematic", "illustrated_story"),
                        default="cinematic")
    parser.add_argument("--samples", type=_positive, default=1,
                        help="fresh independent drafts; each may incur paid production replans")
    parser.add_argument("--output", type=Path, help="write a JSON report after every sample")
    parser.add_argument("--show-script", action="store_true")
    args = parser.parse_args(argv)
    args.format = args.format or (
        "standard_explainer" if args.visual_style == "illustrated_story"
        else "evidence_led_mystery")
    if not args.question.strip():
        parser.error("question must not be empty")
    # A social request follows generate_graded_short in production. This harness has always
    # called the long-form generator, so accepting social would claim parity it does not have.
    if args.video_format != "landscape":
        parser.error("this script-only long-form harness currently supports landscape only")
    try:
        illustrated.validate_request(
            visual_style=args.visual_style, video_format=args.video_format,
            story_format=args.format, controlled_pilot=False)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def run_sample(args, sample_id: int, log=print) -> dict:
    started = time.monotonic()
    costs: list[float] = []
    script: dict = {}
    dossier: dict = {}
    is_illustrated = args.visual_style == "illustrated_story"
    stable = ep._stable_standard_longform(args.video_format, args.format, False)
    sourcing_advisory = stable and not is_illustrated
    research_mode = ep._ordinary_research_mode(stable, is_illustrated)
    report = {
        "sample": sample_id, "passed": False, "stage": "research", "checks": {},
        "fresh_script": True, "research_mode": research_mode,
        "runtime_hard": ep._runtime_is_enforced(),
        "configured_replans": ep._LONGFORM_CONTRACT_RETRIES,
        "script_provider": ep.script_provider.active_provider(),
        "script_model": (ep.script_provider.openai_script_model()
                         if ep.script_provider.active_provider() == ep.script_provider.OPENAI
                         else ep.ANTHROPIC_MODEL),
        "research_model": ep.ANTHROPIC_MODEL,
        "claim_ledger_hard": ep._claim_ledger_hard(),
        "illustrated_storyboard_hard": ep._illustrated_storyboard_hard(),
        "recorded_cost_usd": 0.0,
        "cost_basis": "pipeline usage estimates; not a provider billing ledger",
        "cost_may_be_incomplete": True,
    }
    try:
        if research_mode != "off":
            try:
                dossier = ep.generate_research_dossier(args.question, cost_sink=costs, log=log)
            except Exception as exc:
                if research_mode == "required":
                    raise
                report["research_warning"] = f"{type(exc).__name__}: {exc}"
        report["checks"]["research"] = validate_research_dossier(dossier)
        report["stage"] = "script"
        direction = illustrated.story_direction(args.question) if is_illustrated else ""
        # Call the generator directly. SCRIPT_CACHE must not turn independent samples into
        # repeated measurements of one cached draft. Its own production replan policy remains.
        script = ep.generate_graded_script(
            args.question, args.duration, "engaging and scientific", "", args.video_format, "",
            cost_sink=costs, log=log, operator_direction=direction,
            story_format=args.format, research_dossier=dossier, causal_lane=is_illustrated)
        report["stage"] = "factcheck"
        if script.get("scenes"):
            script, notes, cost = ep.factcheck_script(script, args.question, dossier)
            script["_script_cost_usd"] = float(script.get("_script_cost_usd") or 0) + cost
            report["factcheck_notes"] = notes
        ep.rederive_narration_bindings(script, log)
        script["_story_structure_review"] = ep._review_story_structure(
            script, args.format, args.video_format, log)
        report["checks"]["structure_review"] = script["_story_structure_review"]
        report["stage"] = "claims_after_factcheck"
        joins = validate_claim_joins(script, dossier)
        report["checks"][report["stage"]] = joins
        if not joins.get("passed") and ep._claim_ledger_hard() and not sourcing_advisory:
            raise ValueError("Claim ledger failed after fact-check: " + json.dumps(joins.get("errors")))

        report["stage"] = "runtime"
        if ep._runtime_is_enforced():
            script = ep._enforce_requested_runtime(
                script, args.duration, cost_sink=costs, log=log)
        else:
            script["_runtime_plan"] = plan_runtime(script.get("scenes") or [], args.duration)
        report["checks"]["runtime"] = script["_runtime_plan"]
        ep.rederive_narration_bindings(script, log)
        report["stage"] = "claims_after_runtime"
        joins = validate_claim_joins(script, dossier)
        report["checks"][report["stage"]] = joins
        if not joins.get("passed") and ep._claim_ledger_hard() and not sourcing_advisory:
            raise ValueError("Claim ledger failed after runtime: " + json.dumps(joins.get("errors")))

        if is_illustrated:
            report["stage"] = "illustrated_storyboard"
            script, _ = ep._ensure_hook_fits_budget(script, costs)
            board = illustrated.build_storyboard(script, args.question)
            report["checks"]["illustrated_storyboard"] = board["validation"]
            report["causal_clock"] = {
                "estimated_runtime_sec": board.get("estimated_runtime_sec"),
                "chain": board.get("chain"), "chapter_count": board.get("chapter_count"),
            }
            if not board["validation"].get("passed") and ep._illustrated_storyboard_hard():
                raise ValueError("Illustrated storyboard failed: " + "; ".join(board["validation"]["errors"]))
        # Retention and prose structure are reported at this boundary, not invented extra gates.
        report["checks"]["retention_review"] = validate_longform_story(script, args.question)
        report["stage"] = "complete"
        report["passed"] = True
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        # Generation and fact-check costs live on the script; research/grade/refit costs use
        # cost_sink. The old harness printed only the latter, omitting most script spend.
        report["recorded_cost_usd"] = round(
            sum(float(c or 0) for c in costs) + float(script.get("_script_cost_usd") or 0), 6)
        # Some production helpers swallow provider/parsing errors before recording their cost.
        # Never present a zero/partial estimate, especially after an exception, as actual billing.
        report["cost_may_be_incomplete"] = True
        report["elapsed_sec"] = round(time.monotonic() - started, 3)
        report["engine"] = script.get("_story_engine")
        scenes = script.get("scenes") or []
        report["scene_count"] = len(scenes)
        report["word_count"] = sum(len(str(s.get("narration") or "").split()) for s in scenes)
        report["script"] = script
        if args.show_script:
            for index, scene in enumerate(scenes, 1):
                log(f"{index}. [{scene.get('causal_role') or scene.get('story_role') or '?'}] "
                    f"{scene.get('narration') or ''}")
    # Failures waived by diagnostic flags must not look like clean candidate passes.
    quality_checks = ("research", "claims_after_factcheck", "claims_after_runtime",
                      "illustrated_storyboard") if is_illustrated else (
                          "claims_after_factcheck", "claims_after_runtime")
    report["clean_script_checks"] = report["passed"] and all(
        report["checks"].get(key, {}).get("passed", False) for key in quality_checks)
    return report


def main(argv=None) -> int:
    args = parse_args(argv)
    result = {
        "schema_version": 1, "question": args.question, "duration_sec": args.duration,
        "story_format": args.format, "visual_style": args.visual_style,
        "video_format": args.video_format, "coverage": COVERAGE, "excluded": EXCLUDED,
        "samples_requested": args.samples, "samples": [], "passed": False,
    }
    print("PAID script sampling; no media generation. Cost figures are recorded estimates.")
    for index in range(1, args.samples + 1):
        sample = run_sample(args, index)
        result["samples"].append(sample)
        result["passed"] = (len(result["samples"]) == args.samples and all(
            item["passed"] and item["clean_script_checks"] for item in result["samples"]))
        result["recorded_cost_usd"] = round(sum(
            item["recorded_cost_usd"] for item in result["samples"]), 6)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_name(args.output.name + ".tmp")
            temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
            temporary.replace(args.output)
        print(f"Sample {index}/{args.samples}: "
              f"{'PASS' if sample['passed'] and sample['clean_script_checks'] else 'FAIL'} "
              f"at {sample['stage']}; engine={sample['engine']}; "
              f"recorded cost=${sample['recorded_cost_usd']:.4f}")
        if sample.get("error"):
            print(sample["error"]["message"])
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
