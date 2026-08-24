#!/usr/bin/env python3
"""Harvest rendered-gate calibration samples from real rendered-opening inspections.

The rendered gate refuses to publish under an uncalibrated threshold profile, and
`calibrate_rendered_gate.py` needs a human-labeled dataset that nothing previously produced.
This CLI is the missing first step:

    harvest  inspection.json [...]  worksheet.json    # measurements -> unlabeled worksheet
    status   worksheet.json                           # how far from a viable dataset
    compile  worksheet.json  samples.json             # filled worksheet -> calibration input

Then hand `samples.json` to `calibrate_rendered_gate.py` to emit the hashed profile.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from longform_rendered_gate import (  # noqa: E402
    calibration_readiness,
    harvest_calibration_samples,
    load_labeled_samples,
)


def _read_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str, payload) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, target)


def _print_readiness(readiness: dict) -> None:
    print(f"Rows: {readiness['total_rows']} total, {readiness['labeled_rows']} labeled, "
          f"{readiness['unlabeled_rows']} unlabeled, {readiness['malformed_rows']} malformed")
    minimum = readiness["minimum_per_class"]
    for label, count in sorted(readiness["counts"].items()):
        mark = "ok " if count >= minimum else "-- "
        print(f"  {mark}{label}: {count}/{minimum}")
    for label, count in sorted(readiness["distinct_videos"].items()):
        minimum_videos = readiness["minimum_videos_per_slideshow_class"]
        mark = "ok " if count >= minimum_videos else "-- "
        print(f"  {mark}{label} distinct videos: {count}/{minimum_videos}")
    if readiness["ready"]:
        print("Dataset is ready to calibrate.")
    else:
        print("Not ready:")
        for blocker in readiness["blockers"]:
            print(f"  - {blocker}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    harvest = sub.add_parser("harvest", help="Build an unlabeled worksheet from inspections")
    harvest.add_argument("inspections", nargs="+",
                         help="rendered-opening inspection JSON file(s)")
    harvest.add_argument("output", help="Worksheet JSON path to write")
    harvest.add_argument("--dataset-id", default="", help="Human-readable dataset identifier")

    status = sub.add_parser("status", help="Report labeling progress for a worksheet")
    status.add_argument("worksheet", help="Worksheet JSON path")

    compile_cmd = sub.add_parser("compile", help="Validate labels and emit calibration input")
    compile_cmd.add_argument("worksheet", help="Filled worksheet JSON path")
    compile_cmd.add_argument("output", help="Calibration samples JSON path to write")

    args = parser.parse_args()

    if args.command == "harvest":
        # The output path is positional and last, so a stray inspection argument cannot silently
        # become the destination; argparse assigns it here rather than to the file list.
        worksheet = harvest_calibration_samples(
            [_read_json(path) for path in args.inspections], dataset_id=args.dataset_id)
        _write_json(args.output, worksheet)
        print(f"Wrote {len(worksheet['samples'])} unlabeled row(s) from "
              f"{len(worksheet['videos'])} video(s) to {args.output}")
        _print_readiness(calibration_readiness(worksheet))
        return 0

    if args.command == "status":
        _print_readiness(calibration_readiness(_read_json(args.worksheet)))
        return 0

    samples = load_labeled_samples(_read_json(args.worksheet))
    _write_json(args.output, {"samples": samples})
    print(f"Wrote {len(samples)} labeled sample(s) to {args.output}")
    print("Next: scripts/calibrate_rendered_gate.py "
          f"{args.output} <profile.json> --reviewer '<editor>'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
