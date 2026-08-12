"""Run the story gates over real renders. Read-only, free, no API calls.

Usage:
    python3 tools/story_check.py                       # every renders/_ui_jobs/*/_state.json
    python3 tools/story_check.py <path/_state.json>    # one job
    python3 tools/story_check.py --format evidence_led_mystery

Why: thresholds calibrated against a single reference are thresholds fitted to n=1. This prints the
whole corpus distribution so a proposed cut-off can be checked for real separation before it is
allowed to block anything. It is also the cheapest way to see whether a prompt change moved the
narration at all -- run it before and after.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import story_engine as SE                                                   # noqa: E402


def main(argv):
    fmt_name = "evidence_led_mystery"
    if "--format" in argv:
        fmt_name = argv[argv.index("--format") + 1]
    fmt = SE.get(fmt_name)
    paths = [a for a in argv[1:] if a.endswith(".json")]
    if not paths:
        paths = sorted(glob.glob("renders/_ui_jobs/*/_state.json"))
    print(f"format: {fmt.name}   (structural gates need persisted beat roles; cadence/agenda always run)\n")
    print(f"{'job':14s} {'fmt':5s} {'words':>5} {'long%':>6} {'short%':>7} {'dyn':>5} "
          f"{'agnd':>5} {'2p':>5}  failures")
    print("-" * 96)
    rows = []
    for p in paths:
        try:
            d = json.load(open(p))
        except Exception:
            continue
        sc = (d.get("script") or {}).get("scenes") or []
        if not sc:
            continue
        r = SE.check(d.get("script"), fmt)
        m = r["measurements"]
        job = os.path.basename(os.path.dirname(p)).replace("expl_", "")[:12]
        rows.append(m)
        print(f"{job:14s} {(d.get('video_format') or '?')[:4]:5s} {m['words']:5d} "
              f"{m['long_frac'] * 100:5.1f}% {m['short_frac'] * 100:6.1f}% {m['dynamic_range']:5.2f} "
              f"{m['agenda_hits']:5d} {m['second_person_per_100w']:5.2f}  "
              + ("; ".join(f.split(":")[0] for f in r["failures"]) or "-"))
    if rows:
        # fmt.min_long_frac was renamed to the two-sided fmt.long_band; reading the old attribute
        # crashed this script AFTER printing the table, so the corpus summary never appeared.
        lf = sorted(m["long_frac"] for m in rows)
        sf = sorted(m["short_frac"] for m in rows)
        mr = sorted(m["max_short_run"] for m in rows)
        print(f"\n  long_frac  across {len(rows)} scripts: min={lf[0]:.1%} "
              f"median={lf[len(lf) // 2]:.1%} max={lf[-1]:.1%}   band is "
              f"{fmt.long_band[0]:.0%}-{fmt.long_band[1]:.0%}")
        print(f"  short_frac across {len(rows)} scripts: min={sf[0]:.1%} "
              f"median={sf[len(sf) // 2]:.1%} max={sf[-1]:.1%}   band is "
              f"{fmt.short_band[0]:.0%}-{fmt.short_band[1]:.0%}")
        print(f"  max_short_run across {len(rows)} scripts: min={mr[0]} "
              f"median={mr[len(mr) // 2]} max={mr[-1]}   fails at "
              f"{fmt.max_short_run_fail}, reviews above {fmt.max_short_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
