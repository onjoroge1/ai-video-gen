#!/usr/bin/env python3
"""Where a job's money went, from its usage ledger, across every launch.

    python3 scripts/job_spend.py jobs/bees_v15

Reads <job>/usage_ledger.jsonl (written by usage_ledger.py from 2026-10-08 on). Jobs older than
that have no ledger; this says so instead of guessing.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import usage_ledger  # noqa: E402


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip())
        return 2
    job = argv[0]
    path = os.path.join(job, usage_ledger.LEDGER_FILENAME)
    if not os.path.exists(path):
        print(f"no usage ledger at {path}: every launch of this job ran before per-call recording was "
              "added (commit 5cde2fc). The next launch or resume starts the ledger.")
        return 1
    s = usage_ledger.summarize(path)
    if "--json" in argv:
        print(json.dumps(s, indent=1))
        return 0
    print(f"total ${s['total_usd']:.2f} over {s['calls']} calls; "
          f"cache read {s['cache_read_tokens']:,} tok, cache write {s['cache_write_tokens']:,} tok")
    for title, key in (("by provider", "by_provider"), ("by kind", "by_kind"),
                       ("by model", "by_model"), ("by launch", "by_launch")):
        print(f"\n{title}:")
        for name, cost in s[key].items():
            print(f"  {cost:>8.3f}  {name or '-'}")
    print("\nby caller (top 15):")
    for name, cost in list(s["by_caller"].items())[:15]:
        print(f"  {cost:>8.3f}  {s['calls_by_caller'].get(name, 0):>4} calls  {name or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
