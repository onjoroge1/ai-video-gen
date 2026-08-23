#!/usr/bin/env python3
"""Build a rendered-gate threshold profile from human-labeled real-video samples."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from longform_rendered_gate import calibrate_threshold_profile  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", help="JSON array or {samples:[...]} of labeled observations")
    parser.add_argument("output", help="Output calibration-profile JSON path")
    parser.add_argument("--reviewer", required=True, help="Editor responsible for the labels")
    parser.add_argument("--dataset-id", default="", help="Human-readable dataset/version identifier")
    args = parser.parse_args()

    payload = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    samples = payload.get("samples") if isinstance(payload, dict) else payload
    profile = calibrate_threshold_profile(
        samples, reviewer=args.reviewer, dataset_id=args.dataset_id)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, target)
    print(f"Wrote calibrated profile {profile['profile_id']} to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
