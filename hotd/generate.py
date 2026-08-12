"""Generate the images an episode needs that earlier packs do not already have.

Three things the previous per-episode generator scripts lacked, and which cost real money or real
time when they were missing:

  * A SPEND CAP. The old scripts looped over a prompt dict with no ceiling; a duplicated entry or a
    retry loop could have spent arbitrarily. Every call here is checked against a hard cap first.
  * RETRY. The old loop caught Exception, printed, and continued -- leaving the asset MISSING, which
    then surfaced much later as a crash or a blank shot. Here a failure is retried, and a permanent
    failure is collected and reported as a set, so the caller sees every gap at once.
  * REUSE ACROSS PACKS. Reuse was decided by hand per episode. `plan()` reports exactly which
    prompts would be skipped because an earlier pack already has that stem.
"""
from __future__ import annotations
import os
import time

EMBLEM_PREAMBLE = (
    "Flat vector heraldic emblem, perfectly symmetrical, centred, single antique-gold emblem on a "
    "pure black background, clean bold silhouette, medieval coat-of-arms style, high contrast, "
    "no text, no letters, no border, no frame, no shading gradients, no photorealism, no people, "
    "no faces. Subject: ")
DRAGON_PREAMBLE = (
    "Flat vector heraldic emblem of a single dragon in flight, side profile, wings spread, "
    "symmetrical composition, centred on a pure black background, bold clean silhouette with "
    "minimal internal detail, no text, no border, no people. Scale colour: ")
PLATE_PREAMBLE = (
    "Cinematic matte-painting illustration, painterly, muted desaturated palette, dramatic low "
    "light, wide establishing shot, no text, no lettering, no logos, no recognisable faces, "
    "original artwork not resembling any film or television production. Scene: ")

# gpt-image-2 garbles lettering. Anything that wants writing in frame must ask for MARKS, and the
# legible text gets drawn in code afterwards.
NO_LETTERING = ("absolutely no readable letters or words, only crude marks and shapes")


class SpendCap(Exception):
    pass


class Ledger:
    def __init__(self, cap_usd):
        self.cap = float(cap_usd)
        self.costs = []

    @property
    def spent(self):
        return sum(self.costs)

    def check(self, expect=0.05):
        if self.spent + expect > self.cap:
            raise SpendCap(f"would exceed cap: spent ${self.spent:.3f} + ${expect:.3f} "
                           f"> ${self.cap:.2f}")


def plan(sigils, locations, existing_index):
    """What would actually be generated, given what earlier packs already provide."""
    todo_s = {k: v for k, v in sigils.items() if f"sig_{k}" not in existing_index}
    todo_l = {k: v for k, v in locations.items() if k not in existing_index}
    return {"sigils_new": sorted(todo_s), "sigils_reused": sorted(set(sigils) - set(todo_s)),
            "locations_new": sorted(todo_l), "locations_reused": sorted(set(locations) - set(todo_l)),
            "n_new": len(todo_s) + len(todo_l),
            "est_usd": round((len(todo_s) + len(todo_l)) * 0.041, 3)}


def run(sigils, locations, sig_dir, loc_dir, cap_usd=3.0, retries=2, existing_index=None,
        progress=print):
    """Generate missing emblems and plates. Returns (ledger, failures)."""
    import explainer_pipeline as ep

    os.makedirs(sig_dir, exist_ok=True)
    os.makedirs(loc_dir, exist_ok=True)
    led = Ledger(cap_usd)
    failures = []
    existing_index = existing_index or {}

    jobs = [("sigil", k, v, os.path.join(sig_dir, f"sig_{k}.png"), "1024x1024")
            for k, v in sigils.items()]
    jobs += [("plate", k, v, os.path.join(loc_dir, f"{k}.png"), "1536x1024")
             for k, v in locations.items()]

    for kind, name, prompt, path, size in jobs:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            progress(f"  {kind} {name:30s} reuse (this pack)")
            continue
        stem = f"sig_{name}" if kind == "sigil" else name
        if stem in existing_index:
            progress(f"  {kind} {name:30s} reuse (earlier pack)")
            continue
        for attempt in range(retries + 1):
            try:
                led.check()
                ep.generate_image(prompt, path, cost_sink=led.costs, size=size)
                progress(f"  {kind} {name:30s} ok   (${led.spent:.3f})")
                break
            except SpendCap:
                raise
            except Exception as e:
                if attempt == retries:
                    failures.append((kind, name, f"{type(e).__name__}: {e}"))
                    progress(f"  {kind} {name:30s} FAIL after {retries + 1} tries: {e}")
                else:
                    time.sleep(2 + 3 * attempt)
    progress(f"  image spend: ${led.spent:.3f} of ${cap_usd:.2f} cap")
    return led, failures
