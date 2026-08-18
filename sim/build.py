"""THE entrypoint. One call, gates in order, spend only after the free checks pass.

Why this file exists: every gate in this package -- inventory, direction.check, gap_gate,
background_motion_gate, subject_identity_sheet -- had ZERO call sites outside its own definition.
They were run by hand, from throwaway scripts, inconsistently, and their results reported as though
the pipeline enforced them. Adding another gate would have added another uncalled function.

Order is the whole point. Everything free runs before anything paid:

    1. inventory      declared assets exist, aspect ratios sane, runtime in band   free
    2. direction      one protagonist, recurring object, no fantasy terms          free
    3. narrate        real TTS -> the ONLY honest duration oracle                  ~$0.02
    4. runtime gate   measured speech vs the band, BEFORE any image or clip        free
    5. plates         source stills, character reference for identity              ~$0.04 ea
    6. preview        full video from stills: cuts, captions, SRT, audio           free
    7. clips          i2v -- the expensive step, last                              ~$0.30 ea
    8. render + gates the finished file, measured                                  free

Step 4 is where the arithmetic collisions die. Runtime was previously gated on Scene.seconds, a
declared field the renderer discards in favour of the measured TTS length: one video declared 30.5s
and shipped 35.0s. Narrating first costs two cents and makes the oracle causal.

Step 6 is not new machinery -- render.main(sim, clips=None) already builds the whole video from
stills. It was simply never named as a step, so nobody looked before paying.
"""
from __future__ import annotations
import json
import os


class GateFailed(Exception):
    """A gate said no. Nothing further is spent."""


def _hdr(t, progress):
    progress(f"\n=== {t} ===")


def build(sim, direction=None, plate_jobs=None, references=None, ambient=None,
          animate=True, cap_usd=4.0, preview_only=False, force=False, progress=print):
    """Run an episode end to end with every gate in the path. Returns a report dict."""
    from . import direction as D, plates as P, render as R, spec as SP

    rep = {"slug": sim.slug, "spent_usd": 0.0, "gates": {}}

    if direction:
        _hdr("1. creative direction (free)", progress)
        dres = D.check(sim, direction, plate_jobs=plate_jobs)
        rep["gates"]["direction"] = dres
        for line in D.report(dres).splitlines():
            progress("  " + line)
        if not dres["passed"] and not force:
            raise GateFailed("direction check failed; nothing spent")

    _hdr("2. narrate -- the real duration oracle (~$0.02)", progress)
    total = R.prepare_durations(sim, progress=lambda m: progress("  " + m.strip()))
    rep["measured_runtime_s"] = round(total, 2)

    _hdr("3. runtime gate on MEASURED speech (free)", progress)
    lo, hi = sim.target_s
    ok = lo <= total <= hi
    rep["gates"]["runtime"] = {"measured_s": round(total, 2), "band": [lo, hi], "passed": ok}
    progress(f"  {total:.1f}s vs band {lo}-{hi} -> {'PASS' if ok else 'FAIL'}")
    if not ok and not force:
        raise GateFailed(f"runtime {total:.1f}s outside {lo}-{hi}s -- fix the script, not the speed. "
                         f"Nothing spent on images or clips.")

    if plate_jobs:
        _hdr("4. plates (~$0.04 each)", progress)
        if references and any(getattr(sc, "ambient", "") or (sim.meta or {}).get("ambient")
                              for sc in sim.scenes):
            from . import figure as FG
            references = FG.references_for(sim, references)
        man, fails = P.generate(plate_jobs, sim.images, sim.locked, references=references,
                                cap_usd=min(cap_usd, 1.5),
                                progress=lambda m: progress("  " + m.strip()))
        rep["plates"], rep["plate_failures"] = len(man), fails
        if fails and not force:
            raise GateFailed(f"plates failed: {[f[0] for f in fails]}")

    # Inventory verifies that every declared image EXISTS and is the right aspect -- which cannot be
    # true before the plate stage creates them. Running it first made a brand-new topic unbuildable:
    # it failed all seven scenes for missing images the pipeline had not been asked to make yet.
    # Order matters: check what needs no assets, create the assets, then verify them.
    _hdr("5. inventory -- verify the assets that now exist (free)", progress)
    inv = SP.inventory(sim, verbose=False)
    rep["gates"]["inventory"] = inv
    for k in ("scenes", "images_available", "unused", "runtime_planned_s", "crop"):
        if k in inv:
            progress(f"  {k}: {inv[k]}")
    if not inv.get("passed") and not force:
        raise GateFailed("inventory failed after plate generation")

    _hdr("6. PREVIEW from stills (free) -- look before you pay", progress)
    pv = R.main(sim, clips=None, progress=lambda m: None)
    rep["preview"] = pv["video"]
    progress(f"  {pv['video']}  {pv['duration_s']}s, {pv['scenes']} scenes")
    if preview_only:
        progress("\n  preview_only: stopping before any clip spend")
        return rep

    # render looks clips up by scene.id; ambient clips are named by scene.image. Passing the raw
    # dict matched zero of seven and rendered an "animated" video that was silently all stills, with
    # no error and no flag. Remap, then ASSERT the render actually used them.
    by_img = {sc.image: sc.id for sc in sim.scenes}
    clips = {by_img.get(k, k): v for k, v in (ambient or {}).items()}
    if animate:
        _hdr(f"7. i2v clips (up to ${cap_usd:.2f}) -- the expensive step, last", progress)
        from . import animate as A
        out = A.generate(sim, cap_usd=cap_usd,
                         progress=lambda m: progress("  " + m.strip()))
        man, fails = out[0], out[1]
        spent = out[2] if len(out) > 2 else 0.30 * len(man)
        clips.update(man)
        rep["clip_failures"] = fails
        rep["spent_usd"] += round(spent, 2)

    # 7b. hero compositing (free, deterministic). Scenes that declare Scene.hero get the physics
    # subject drawn by sim/drop.py OVER the provider clip (whose prompt excluded its own version).
    # Runs whether the clip came back or not: with no clip the compositor rides the still plate,
    # which the background-motion gate will then report honestly.
    heroes = [sc for sc in sim.scenes if getattr(sc, "hero", None)]
    if heroes:
        _hdr("7b. hero subjects (free -- deterministic compositor)", progress)
        from . import drop as DR
        for sc in heroes:
            h = dict(sc.hero)
            label = (sc.onscreen or "").upper()
            declared = "SLOW" in label or ("SPEED" in label and "1/" in label)
            if h.get("slow_mo", 1) > 1 and not declared:
                raise GateFailed(f"{sc.id}: hero drop plays at 1/{h['slow_mo']} speed but the "
                                 f"on-screen text does not declare it -- undeclared slow motion "
                                 f"is a lie about the measured speed")
            frames = int(round(getattr(sc, "_dur", sc.seconds) * sim.fps))
            out_p = os.path.join(sim.work, "clips", f"{sc.id}.hero.mp4")
            r = DR.render_scene(sim.asset(sc.image), out_p, frames=frames, fps=sim.fps,
                                ambient_mp4=clips.get(sc.id),
                                out_wh=(sim.W, sim.H), **h)
            clips[sc.id] = out_p
            progress(f"  {sc.id:10s} drop {r['drop_px'][0]}px wide, {r['px_per_frame']}px/frame, "
                     f"impact f{r['impact_frame']}")

    _hdr("8. render + post-render gates (free)", progress)
    out = R.main(sim, clips=clips or None, progress=lambda m: None)
    rep.update({k: out[k] for k in ("video", "duration_s", "scenes") if k in out})
    used = sum(1 for c in out.get("cuts", []) if c.get("animated"))
    rep["animated_shots"] = f"{used}/{len(sim.scenes)}"
    progress(f"  clips used {used}/{len(sim.scenes)}")
    if clips and used == 0:
        raise GateFailed("clips were supplied but NONE were used -- key mismatch between the clip "
                         "manifest and scene ids. The render would have been silently all stills.")
    g = SP.gap_gate(sim, out["video"], out.get("cuts"))
    bg = SP.background_motion_gate(out["video"])
    rep["gates"]["gap"], rep["gates"]["background"] = g, bg
    progress(f"  gap        longest still {g.get('longest_still_s')}s -> "
             f"{'PASS' if g.get('passed') else 'FAIL'}")
    progress(f"  background {bg.get('bg_motion')} vs floor {bg.get('floor')} -> "
             f"{'PASS' if bg.get('passed') else 'FAIL'}")
    if plate_jobs:
        paths = [sim.asset(j[0]) for j in plate_jobs]
        sheet = SP.subject_identity_sheet(paths, os.path.join(sim.work, "identity_sheet.png"))
        rep["gates"]["identity"] = sheet
        progress(f"  identity   sheet -> {sheet.get('path')}  (requires human review)")

    _hdr("9. thumbnail (free -- built from a plate already paid for)", progress)
    try:
        from . import thumbnail as TH
        rep["thumbnail"] = TH.build(sim, badge=(sim.meta or {}).get("badge"),
                                    progress=lambda m: progress("  " + m.strip()))
    except Exception as e:
        progress(f"  thumbnail skipped ({type(e).__name__}: {e})")

    progress(f"\n  video {rep.get('video')}  {rep.get('duration_s')}s  "
             f"spent ~${rep['spent_usd']:.2f}")
    json.dump(rep, open(os.path.join(sim.out, "build_gates.json"), "w"), indent=2, default=str)
    return rep
