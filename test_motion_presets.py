"""Regression: the UI motion presets must mean the same thing on BOTH formats.

Why this exists. A long-form job submitted with Motion: Standard rendered 55 Ken Burns scenes and
never contacted a provider. Cause: only the "none" preset was wired to an i2v decision; "standard"
and "full" left `i2v=None`, which fell through to the legacy per-format default (social ON, long-form
OFF). Social kept working by accident, so nothing caught it until an 8-minute render came back with
no motion at all.

That is the second time a silently-unwired preset shipped, and both times the symptom was an
expensive render with no motion. These are pure functions -- no network, no spend, ~1s -- so there is
no excuse for not running them.

The last check is the important one: it ties the clip count the UI PROMISES to the clip count the
selector actually BUYS. That invariant is what broke.

Run: /opt/homebrew/bin/python3 test_motion_presets.py
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import hotd                      # loads .env so I2V_PROVIDER is populated
import explainer_pipeline as ep

FORMATS = ("social", "landscape")
PRESETS = ("none", "standard", "full")
fails: list[str] = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:58s} got={got!r} want={want!r}")
    if not ok:
        fails.append(label)


def i2v_on_for(motion, video_format, i2v=None, provider="fal"):
    """Mirror of the resolution in run_explainer_pipeline. Kept in sync deliberately: if the
    pipeline's logic changes shape, this copy must be updated and that is the point of the test."""
    m = (motion or "standard").strip().lower()
    if m == "none":
        i2v = False
    elif m in ("standard", "full"):
        i2v = True
    return bool((i2v if i2v is not None else (video_format == "social")) and provider)


def scenes(n, video_format="landscape"):
    """Fixture scenes whose narration LENGTH matches the format the estimator assumes.

    This matters: the estimator prices from SECS_PER_SCENE, while the selector measures the real
    narration. Feeding social-length scenes (12 words) into a landscape check made the two disagree
    14 vs 9 -- a fixture artifact, not a defect. Deriving word count from the same constant keeps the
    two honest about each other.
    """
    words = max(1, round(ep.SECS_PER_SCENE.get(video_format, 8.5) / 60.0 * 162))
    return [{"narration": " ".join(["word"] * words)} for _ in range(n)]


print("1. i2v_on across every format x preset  (the bug: landscape+standard was False)")
for fmt in FORMATS:
    for m in PRESETS:
        check(f"{fmt} + {m}", i2v_on_for(m, fmt), m != "none")

print("\n2. a caller that sends no preset keeps the historical per-format default")
check("landscape, motion unset, i2v=None", i2v_on_for(None, "landscape"), True)   # defaults standard
check("landscape, explicit i2v=False", i2v_on_for("custom", "landscape", i2v=False), False)
check("landscape, explicit i2v=True", i2v_on_for("custom", "landscape", i2v=True), True)
check("no provider configured -> always off", i2v_on_for("full", "social", provider=""), False)

print("\n3. motion_coverage overrides")
check("none  -> (0.0, 0)", ep.motion_coverage("none", "landscape", 40), (0.0, 0))
check("full  -> (1.0, n)", ep.motion_coverage("full", "landscape", 40), (1.0, 40))
check("standard -> defaults", ep.motion_coverage("standard", "landscape", 40), (None, None))

print("\n4. _select_i2v_indices honours the overrides (generous budget)")
for fmt in FORMATS:
    sc = scenes(40, fmt)
    f0, c0 = ep.motion_coverage("none", fmt, len(sc))
    check(f"{fmt} none -> selects nothing",
          len(ep._select_i2v_indices(sc, "q", fmt, 999, frac=f0, max_clips=c0)), 0)
    f1, c1 = ep.motion_coverage("full", fmt, len(sc))
    check(f"{fmt} full -> selects every scene",
          len(ep._select_i2v_indices(sc, "q", fmt, 999, frac=f1, max_clips=c1)), len(sc))

print("\n5. the estimate the UI SHOWS equals the clips the selector BUYS")
for fmt in FORMATS:
    for m in PRESETS:
        n = 40
        sc = scenes(n, fmt)
        f, c = ep.motion_coverage(m, fmt, n)
        picked = len(ep._select_i2v_indices(sc, "q", fmt, 999, frac=f, max_clips=c))
        promised = ep.estimate_i2v_cost(n, fmt, m)["clips"]
        check(f"{fmt} + {m}: promised == selected", promised, picked)

print()
if fails:
    print(f"FAILED ({len(fails)}): " + "; ".join(fails))
    sys.exit(1)
print("all motion-preset checks passed")
