#!/usr/bin/env python3
"""Verify an operator spec (research + narration) and, on approval, render it through the pipeline.

    python3 scripts/import_spec.py topics/specs/<slug>.md --out jobs/<slug>
        -> jobs/<slug>/verification_report.md (no provider calls, no spend)
    python3 scripts/import_spec.py topics/specs/<slug>.md --out jobs/<slug> \
        --approve <narration sha256 from the report> --max-cost 6
        -> research_dossier.json + _state.json, then run_illustrated_local --resume
           (add --build-only to stop before the resume)

See docs/SPEC_IMPORT.md and topics/specs/TEMPLATE.md. Exit codes: 0 ready (or built), 1 report
written but not ready, 2 the spec or the approval was refused.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import spec_import as si  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec")
    parser.add_argument("--out", required=True, help="job directory, e.g. jobs/<slug>")
    parser.add_argument("--approve", default="", metavar="SHA256",
                        help="the narration sha256 printed in verification_report.md")
    parser.add_argument("--max-cost", type=float, default=0.0, help="hard ceiling for the render (required with --approve)")
    parser.add_argument("--build-only", action="store_true", help="with --approve: write the state, do not resume")
    parser.add_argument("--offline", action="store_true", help="read cited pages from <out>/pages only; never fetch")
    parser.add_argument("--force", action="store_true", help="with --approve: replace an existing _state.json")
    args = parser.parse_args(argv)
    out = os.path.abspath(args.out)

    try:
        if not args.approve:
            run = si.run_verification(args.spec, out, offline=args.offline)
            s = run["summary"]
            print(f"{os.path.join(out, si.REPORT_NAME)}")
            print(f"lines {s['lines']}  consequence {'PASS' if run['consequence']['passed'] else 'FAIL'}  "
                  f"ready {s['ready_to_approve']}")
            print(f"narration sha256 {si.narration_sha256(run['spec'])}")
            return 0 if s["ready_to_approve"] else 1
        built = si.approve(args.spec, out, args.approve, max_cost=args.max_cost, offline=args.offline,
                           force=args.force)
    except si.SpecError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(f"built {built['state_path']}: {built['scenes']} scenes, {built['claims']} claims")
    print("resume: " + " ".join(built["command"]))
    if args.build_only:
        return 0
    return subprocess.call(built["command"], cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
