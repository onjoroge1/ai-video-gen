"""Replay the opening retry (diagnosis + R1) over saved jobs, offline.

Rebuilds each job's 45-second opening from the artifacts the run left behind -- the number of
opening scenes from rendered_contract.json `inspection.frames`, the measured words from
audio/scene_NN.mp3.word_times.json, the states from evidence_asset_plan.json, the paid motion
clips from the frames that rendered as i2v -- and runs opening_retry's diagnosis and R1 on it. R2
is never run: this script makes no provider call of any kind, and passes no rebind function.

Usage:
    python scripts/simulate_opening_retry.py                 # every job under jobs/
    python scripts/simulate_opening_retry.py wolves01 bees_v16b --cuts
    python scripts/simulate_opening_retry.py --json out.json

Columns:
    saved    the score of the plan the run actually rendered (the logged opening score)
    before   the same opening recompiled by the current compiler, before any retry edit
    ceiling  the best any plan-only re-cut can reach (Visual at 20/20)
    after    the R1 outcome's score; `aligned` is aligned/total cuts before -> after
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import opening_retry as retry                                   # noqa: E402
from longform_shots import shot_plan_metrics                    # noqa: E402
from media_binaries import probe_duration                       # noqa: E402
from retention_readiness import build_audio_cues, score_retention_readiness  # noqa: E402

_FRAME_KEYS = ("kind", "source", "duration", "start_sec", "end_sec", "motion", "story_role",
               "purpose", "anchor_phrase", "transition", "semantic_aligned", "new_information",
               "state_id", "asset_strategy", "source_asset_id", "verified_visible_information",
               "timing_source")


def _load(path: Path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_job(job_dir: Path) -> tuple[retry.OpeningContext, list[list[dict]], dict]:
    """(context, the saved rendered plan, extras) or raise ValueError naming what is missing."""
    for name in ("_state.json", "rendered_contract.json", "evidence_asset_plan.json"):
        if not (job_dir / name).is_file():
            raise ValueError(f"no {name}")
    script = _load(job_dir / "_state.json").get("script") or {}
    frames = ((_load(job_dir / "rendered_contract.json").get("inspection") or {})
              .get("frames") or [])
    if not frames:
        raise ValueError("no inspection frames")
    by_scene = collections.defaultdict(list)
    for frame in frames:
        by_scene[int(frame["scene_index"])].append(frame)
    count = max(by_scene) + 1
    saved_plan = [[{k: f.get(k) for k in _FRAME_KEYS if k in f}
                   for f in sorted(by_scene[k], key=lambda f: int(f["shot_index"]))]
                  for k in range(count)]
    evidence_plan = _load(job_dir / "evidence_asset_plan.json")
    scenes = (script.get("scenes") or [])[:count]
    if len(scenes) < count or len(evidence_plan.get("scenes") or []) < count:
        raise ValueError("script or evidence plan shorter than the saved opening")
    durations, word_times = [], []
    for k in range(count):
        audio = job_dir / "audio" / f"scene_{k:02d}.mp3"
        timing = Path(str(audio) + ".word_times.json")
        if not audio.is_file() or not timing.is_file():
            raise ValueError(f"no audio or word timings for scene {k + 1}")
        durations.append(float(probe_duration(str(audio))))
        payload = _load(timing)
        word_times.append(payload.get("word_times") if isinstance(payload, dict) else payload)
    states = [[dict(state) for state in evidence_plan["scenes"][k].get("states") or []]
              for k in range(count)]
    report_path = job_dir / "retention_report.json"
    validation = (_load(report_path).get("validation") if report_path.is_file() else None) \
        or script.get("_retention_validation") or {}
    motion = frozenset(f.get("state_id") for f in frames if f.get("kind") == "i2v")
    ctx = retry.OpeningContext(
        scenes=scenes, durations=durations, word_times=word_times, states=states,
        script=script, validation=validation, evidence_plan=evidence_plan,
        scene_indexes=list(range(count)), motion_state_ids=motion, i2v_seconds=5.0,
        purchased_through=count)
    return ctx, saved_plan, {"validation": validation}


def saved_score(ctx: retry.OpeningContext, saved_plan: list[list[dict]]) -> dict:
    metrics = shot_plan_metrics(saved_plan)
    opening_script = dict(ctx.script)
    opening_script["scenes"] = ctx.scenes
    report = score_retention_readiness(opening_script, ctx.validation, metrics,
                                       build_audio_cues(ctx.scenes, ctx.durations),
                                       preview=dict(ctx.preview))
    aligned, cuts = retry.cut_alignment(saved_plan)
    return {"score": report["score"], "grade": report["grade"], "aligned": aligned, "cuts": cuts}


def simulate(job_dir: Path) -> dict:
    ctx, saved_plan, _extra = load_job(job_dir)
    decision = retry.decide_opening_retry(ctx, rebind=None)
    return {"job": job_dir.name, "saved": saved_score(ctx, saved_plan), "decision": decision}


def _row(result: dict) -> str:
    decision = result["decision"]
    before, after = decision["before"], decision.get("after") or decision["before"]
    saved = result["saved"]
    outcome = decision["outcome"]
    edits = retry.edits_phrase(decision.get("edits") or []) if outcome in (
        "passed", "below_b_after_retry") else ""
    return (f"{result['job']:<30} {saved['score']:>3} {saved['grade']}  "
            f"{before['score']:>3} {before['grade']} (unc {before['uncapped_score']:>3})  "
            f"{decision['ceiling']:>3}  {outcome:<20} {after['score']:>3} {after['grade']}  "
            f"{before['aligned']:>2}/{before['cuts']:<2} -> "
            f"{after['aligned']:>2}/{after['cuts']:<2}  "
            f"{(after.get('literal_45') or {}).get('aligned')}/"
            f"{(after.get('literal_45') or {}).get('cuts')}  {edits}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("jobs", nargs="*", help="job directory names under jobs/ (default: all)")
    parser.add_argument("--jobs-dir", default=str(ROOT / "jobs"))
    parser.add_argument("--cuts", action="store_true", help="print the per-cut diagnosis")
    parser.add_argument("--json", default="", help="write every decision to this file")
    args = parser.parse_args()
    root = Path(args.jobs_dir)
    names = args.jobs or sorted(p.name for p in root.iterdir() if p.is_dir())
    print(f"{'job':<30} {'saved':<6} {'before':<14} {'ceil':<4} {'outcome':<20} "
          f"{'after':<6} {'aligned':<15} {'<45s':<5} edits")
    results, skipped = [], []
    for name in names:
        try:
            result = simulate(root / name)
        except (ValueError, KeyError, IndexError, TypeError, OSError) as exc:
            skipped.append((name, f"{type(exc).__name__}: {exc}"))
            continue
        results.append(result)
        print(_row(result))
        if args.cuts:
            for entry in result["decision"]["diagnosis"]["cuts"]:
                if not entry["aligned"]:
                    print(f"      s{entry['scene']} {entry['state_id']:<20} "
                          f"{entry['asset_strategy']:<15} @{entry['global_start_sec']:>6.2f}s "
                          f"{entry['reason']:<22} {entry['anchor_phrase'][:44]!r}"
                          + (f" vs {','.join(entry['conflicts_with'])}"
                             if entry["conflicts_with"] else ""))
            for edit in result["decision"].get("edits") or []:
                print(f"      edit: {edit['op']} {edit['state_id']}"
                      + (f" {edit['old']!r} -> {edit['new']!r}" if edit["op"] == "reanchor" else
                         f" ({edit.get('asset_strategy')})"))
    if skipped:
        print("\nskipped:")
        for name, why in skipped:
            print(f"  {name}: {why}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump([{"job": r["job"], "saved": r["saved"], "decision": r["decision"]}
                       for r in results], handle, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
