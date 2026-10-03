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
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    # Providers/model constants read their configuration during import.
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

import cost_ledger
import explainer_pipeline as ep
import illustrated_story as illustrated
from longform_research import validate_research_dossier
from longform_retention import validate_longform_story
from runtime_planner import plan_runtime


COVERAGE = ["production run_explainer_pipeline with stop_after_script", "research and planning",
            "fact-check and bounded repairs", "runtime policy", "storyboard and evidence plan",
            "final editorial grade", "current-script readiness"]
EXCLUDED = ["HTTP approval and dispatch", "durable worker recovery", "TTS and measured audio timing",
            "images", "render", "Blob publication"]


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
    """Observe the production stop boundary, with no independently maintained orchestration."""
    started = time.monotonic()
    costs = cost_ledger.CostLedger()
    report = {"sample": sample_id, "passed": False, "stage": "production", "checks": {},
              "fresh_script": True, "cost_may_be_incomplete": True,
              "cost_basis": "recorded estimates, not provider billing"}
    with tempfile.TemporaryDirectory(prefix="script-check-") as directory:
        def progress(message):
            if message.startswith("stage:"):
                report["stage"] = message[6:]
            log(message)
        try:
            ep.run_explainer_pipeline(args.question, directory, duration_sec=args.duration,
                video_format=args.video_format, story_format=args.format, visual_style=args.visual_style,
                stop_after_script=True, fresh_script=True, text_cost_sink=costs, progress_cb=progress)
            raise RuntimeError("Production script-only path returned without its approval boundary")
        except ep.ScriptApprovalRequired:
            report["stage"] = "complete"
            report["passed"] = True
        except Exception as exc:
            report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        state = Path(directory, "_state.json")
        script = json.loads(state.read_text()).get("script", {}) if state.exists() else {}
        failures = [json.loads(p.read_text()) for p in Path(directory).glob("semantic_failure_*.json")]
        if not report["passed"] and failures:
            latest = max(failures, key=lambda row: str(row.get("failed_at") or ""))
            script = latest.get("script") or script
            report["failure"] = latest.get("report")
            report["stage"] = latest.get("stage") or report["stage"]
        for key in ("_script_readiness", "_final_retention_review", "_final_factcheck_review",
                    "_claim_validation", "_runtime_plan", "_retention_validation"):
            if key in script:
                report["checks"][key] = script[key]
        report["script"] = script
        report["engine"] = script.get("_story_engine")
        report["spine"] = script.get("_spine") or {}
        report["scene_count"] = len(script.get("scenes") or [])
        report["word_count"] = sum(len(str(row.get("narration") or "").split())
                                   for row in script.get("scenes") or [])
        report["clean_script_checks"] = report["passed"] and bool(
            (script.get("_script_readiness") or {}).get("passed"))
        report["spend"] = costs.report()
        report["recorded_cost_usd"] = costs.total()
        report["elapsed_sec"] = round(time.monotonic() - started, 3)
        if args.show_script:
            for i, row in enumerate(script.get("scenes") or [], 1):
                log(f"{i}. {row.get('narration') or ''}")
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
        for stage, usd in sorted((sample.get("spend") or {}).get("by_stage", {}).items(),
                                 key=lambda kv: -kv[1]):
            print(f"    {stage:<22s} ${usd:.4f}")
        if sample.get("error"):
            print(sample["error"]["message"])
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
