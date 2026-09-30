"""Run one illustrated long-form film on this machine, outside the studio server.

The studio's public route (`/api/explainer/generate`) runs the same pipeline in-process but
always with the module's $25 ceiling. This launcher exists so a laptop run can carry a tighter
ceiling, a stable output directory, and a log file that survives the process.

Usage:
    python scripts/run_illustrated_local.py --question "..." --direction-file direction.txt \
        --out jobs/<slug> --duration 300 --max-cost 12

Resume a stopped run with the same --out and --resume.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", required=True)
    parser.add_argument("--direction-file", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--duration", type=int, default=300)
    parser.add_argument("--voice", default="echo")
    parser.add_argument("--max-cost", type=float, default=12.0)
    parser.add_argument("--topic-channel", default="")
    parser.add_argument("--motion-mode", default="standard")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "run.log"
    direction = Path(args.direction_file).read_text() if args.direction_file else ""

    from provider_readiness import illustrated_provider_readiness
    readiness = illustrated_provider_readiness()
    if not readiness["configured"]:
        print("providers not configured:", readiness["missing_configuration"])
        return 2

    import explainer_pipeline as ep

    def log(msg: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {msg}"
        print(line, flush=True)
        with open(log_path, "a") as handle:
            handle.write(line + "\n")

    log(f"launch question={args.question!r} duration={args.duration} cap=${args.max_cost:.2f} "
        f"resume={args.resume} out={out}")
    started = time.time()
    try:
        result = ep.run_explainer_pipeline(
            question=args.question,
            output_dir=str(out),
            duration_sec=args.duration,
            voice=args.voice,
            style="engaging and scientific",
            fact_check=True,
            video_format="landscape",
            max_cost_usd=args.max_cost,
            resume=args.resume,
            i2v=True,
            motion_mode=args.motion_mode,
            operator_direction=direction,
            story_format="standard_explainer",
            visual_style="illustrated_story",
            topic_channel=args.topic_channel,
            progress_cb=log,
        )
    except Exception as exc:  # the log file is the record; the exception text is the headline
        log(f"FAILED after {time.time() - started:.0f}s: {type(exc).__name__}: {exc}")
        (out / "run_error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
        raise
    summary = {k: result.get(k) for k in (
        "status", "output_path", "title", "hook", "scene_count", "duration_sec", "est_cost",
        "actual_cost", "degraded_reasons", "thumbnail_path", "transcript_path", "srt_path",
        "description_path", "technical_status", "automated_grade_status", "rendered_contract_path",
        "storyboard_path", "generation_manifest_path")}
    (out / "run_result.json").write_text(json.dumps(summary, indent=2, default=str))
    log(f"DONE in {time.time() - started:.0f}s: {json.dumps(summary, default=str)[:600]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
