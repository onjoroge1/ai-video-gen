#!/usr/bin/env python3
"""Do cheaper checker models agree with the Opus verdicts we already paid for?

    python3 scripts/compare_verifier_models.py jobs/bees_v13 jobs/bees_v14 jobs/bees_v15 \
        --models claude-sonnet-5-5,claude-haiku-5-5 --limit 120

Reads each job's saved evidence plan and its accepted images (every image on disk passed the
Opus checker at full resolution), plus any refused images kept as <image>.rejected-<n>.jpg.
Each candidate model judges the same image against the same state at the checker's current
settings (downscaled, colour-is-style rule). No image is generated; the only spend is the
candidate models' judgments, which the usage ledger records under the comparison directory.

Reports, per model: agreement with Opus on accepted images (a false refusal costs a redraw)
and on refused images (a false acceptance puts a wrong picture on screen). Writes
<first job>/verifier_comparison.json.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cases(job: str) -> list[dict]:
    with open(os.path.join(job, "evidence_asset_plan.json"), encoding="utf-8") as handle:
        plan = json.load(handle)
    pack = plan.get("continuity_pack") or {}
    images = os.path.join(job, "images")
    cases = []
    for scene_index, scene in enumerate(plan.get("scenes") or []):
        for state_index, state in enumerate(scene.get("states") or []):
            if state.get("asset_strategy") in ("detail_reframe", "exact_reuse"):
                continue
            suffix = "" if state_index == 0 else f"_e{state_index + 1:02d}"
            path = os.path.join(images, f"scene_{scene_index:02d}{suffix}.jpg")
            if os.path.isfile(path):
                cases.append({"job": job, "path": path, "state": state, "pack": pack,
                              "opus": True})
            for attempt in (1, 2):
                rejected = f"{path}.rejected-{attempt}.jpg"
                if os.path.isfile(rejected):
                    cases.append({"job": job, "path": rejected, "state": state, "pack": pack,
                                  "opus": False})
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("jobs", nargs="+")
    parser.add_argument("--models", default="claude-sonnet-5-5,claude-haiku-5-5")
    parser.add_argument("--limit", type=int, default=120, help="accepted images sampled per run")
    parser.add_argument("--mismatch", type=int, default=40,
                        help="accepted images judged against another scene's state (should be refused)")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    import explainer_pipeline as ep
    import usage_ledger

    cases = [case for job in args.jobs for case in _cases(job)]
    accepted = [c for c in cases if c["opus"]]
    refused = [c for c in cases if not c["opus"]]
    random.Random(args.seed).shuffle(accepted)
    # MISMATCHED PAIRS stand in for refusals while none are on disk (refused images were
    # overwritten by their redraws until 2026-10-08): an accepted image judged against the state
    # of a different scene whose required objects share no word with its own. Every model should
    # refuse these; one that accepts them is rubber-stamping.
    rng = random.Random(args.seed + 1)
    mismatched = []
    pool = accepted[args.limit:] or accepted
    for case in pool:
        if len(mismatched) >= args.mismatch:
            break
        own = {w for item in case["state"].get("required_objects") or [] for w in str(item).lower().split()}
        others = [o for o in accepted if o["job"] == case["job"] and o["path"] != case["path"]
                  and not own & {w for item in o["state"].get("required_objects") or []
                                 for w in str(item).lower().split()}]
        if others:
            other = rng.choice(others)
            mismatched.append({**case, "state": other["state"], "opus": False, "mismatch": True})
    refused = refused + mismatched
    sample = accepted[:args.limit] + refused
    out_dir = os.path.join(args.jobs[0], "verifier_comparison")
    os.makedirs(out_dir, exist_ok=True)
    usage_ledger.set_job_dir(out_dir)

    report = {"accepted_cases": len(accepted[:args.limit]), "refused_cases": len(refused),
              "models": {}}
    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        ep.EVIDENCE_VERIFY_MODEL = model
        agree_accept = agree_refuse = unavailable = 0
        disagreements = []
        for case in sample:
            # Judge a copy so the job's own verdict cache is never touched by a candidate model.
            probe = os.path.join(out_dir, f"probe_{model}_{abs(hash(case['path'])) % 10**10}.jpg")
            with open(case["path"], "rb") as src, open(probe, "wb") as dst:
                dst.write(src.read())
            verdict = ep.verify_evidence_asset(probe, case["state"], case["pack"], cost_sink=[],
                                               identity_by_silhouette=True)
            if verdict.get("verifier_available") is False:
                unavailable += 1
                continue
            passed = bool(verdict.get("passed"))
            if case["opus"] and passed:
                agree_accept += 1
            elif not case["opus"] and not passed:
                agree_refuse += 1
            else:
                disagreements.append({"image": case["path"], "opus_passed": case["opus"],
                                      "model_passed": passed,
                                      "reasons": verdict.get("reasons") or []})
        spend = usage_ledger.summarize(os.path.join(out_dir, usage_ledger.LEDGER_FILENAME))
        report["models"][model] = {
            "agree_on_accepted": agree_accept, "agree_on_refused": agree_refuse,
            "unavailable": unavailable, "disagreements": disagreements,
            "ledger_total_usd_so_far": spend["total_usd"],
        }
        print(f"{model}: accepted {agree_accept}/{report['accepted_cases']} agree, "
              f"refused {agree_refuse}/{report['refused_cases']} agree, "
              f"{unavailable} unavailable, ledger so far ${spend['total_usd']:.3f}")
    with open(os.path.join(args.jobs[0], "verifier_comparison.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
