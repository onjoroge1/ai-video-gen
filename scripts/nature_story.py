#!/usr/bin/env python3
"""CLI for the unified Nature Story flow.

Non-spending stages:
  validate       run the shared Nature KPI/contract checks
  storyboard     compile the existing Nature-aware evidence storyboard
  compile-short  write the keyframe renderer spec
  long-request   write arguments for the existing long-form explainer pipeline

Paid stage:
  render-short --authorize-paid
                 run stills, narration, motion clips, regate, and assembly through the existing
                 keyframe Short renderer. The episode hard cap remains authoritative.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import nature_story_flow as ns


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _work_dir(episode: dict) -> Path:
    episode_id = str(episode.get("episode_id") or episode.get("species") or "nature_episode")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in episode_id.lower())
    return ROOT / "renders" / safe


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("episode")
    parser.add_argument("stage", choices=("validate", "storyboard", "compile-short", "long-request", "render-short"))
    parser.add_argument("--authorize-paid", action="store_true")
    args = parser.parse_args()

    episode = _load(args.episode)
    report = ns.validate_episode(episode)
    work = _work_dir(episode)
    _write(work / "nature_story_qa.json", report)

    if args.stage == "validate":
        print(json.dumps(report, indent=2))
        return 0 if report["passed_pre_render"] else 2

    if not report["passed_pre_render"]:
        print(json.dumps(report, indent=2))
        print("Nature Story pre-render hard checks failed; no media stage started.", file=sys.stderr)
        return 2

    if args.stage == "storyboard":
        result = ns.compile_storyboard(episode)
        out = _write(work / "nature_story_storyboard.json", result)
        print(out)
        return 0 if result["validation"].get("passed") else 3

    if args.stage == "compile-short":
        spec = ns.compile_keyframe_spec(episode)
        out = _write(work / "nature_story_keyframe_spec.json", spec)
        print(out)
        return 0

    if args.stage == "long-request":
        out = _write(work / "nature_story_long_request.json", ns.longform_pipeline_kwargs(episode))
        print(out)
        return 0

    if args.stage == "render-short":
        if not args.authorize_paid:
            raise SystemExit("render-short can spend provider funds; re-run with --authorize-paid")
        spec = ns.compile_keyframe_spec(episode)
        spec_path = _write(work / "nature_story_keyframe_spec.json", spec)
        runner = ROOT / "scripts" / "keyframe_short.py"
        for stage in ("stills", "narrate", "clips", "regate", "assemble"):
            subprocess.run([sys.executable, str(runner), str(spec_path), stage], cwd=str(ROOT), check=True)
        final = work / f"{spec['name']}_short.mp4"
        print(final)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
