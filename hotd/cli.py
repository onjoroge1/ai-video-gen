"""One command to build a House of the Dragon episode.

    python -m hotd plan     episodes/s3e4.py                 # no spend, no render
    python -m hotd assets   episodes/s3e4.py --cap 2.00      # emblems + plates + cards + diagrams
    python -m hotd thumb    episodes/s3e4.py
    python -m hotd animate  episodes/s3e4.py --cap 4.00      # i2v over location plates
    python -m hotd build    episodes/s3e4.py [--animate]     # render + gates + package
    python -m hotd all      episodes/s3e4.py --animate --cap 8.00

Every stage is independently runnable and idempotent: emblems, plates, animated clips and rendered
shots are all reused when they already exist. Editing the episode module or the engine invalidates
the rendered shots automatically.

Gates RAISE. A failed check stops the build instead of printing a warning nobody reads.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hotd import gates


def load_episode(path):
    """Load an episode module by file path so episodes/ needs no package plumbing."""
    path = os.path.abspath(path)
    spec = importlib.util.spec_from_file_location(
        "hotd_episode_" + os.path.basename(path)[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    for need in ("episode", "POOLS", "BLOCK_STATE"):
        if not hasattr(mod, need):
            raise SystemExit(f"{path} does not define {need}")
    return mod


def _prepare(mod, require_script=True):
    """Build the Episode with its playlists resolved from the script. Shared by every stage."""
    from hotd import playlists as PL
    ep = mod.episode()
    if not os.path.exists(ep.script):
        if require_script:
            raise SystemExit(f"no script at {ep.script}. Write it (or run the script workflow) first.")
        return ep, None, None
    script = json.load(open(ep.script))
    if hasattr(mod, "PLAYLISTS_EXACT"):
        # episodes authored before the block-pool scheme keep their hand-written shot lists, so
        # their shipped ledger stays reproducible
        ep.playlists = dict(mod.PLAYLISTS_EXACT)
        ep.seg_state = dict(mod.SEG_STATE_EXACT)
        rep = {"segments": len(script["segments"]),
               "shots": sum(len(v) for v in ep.playlists.values()), "cycles": {},
               "exact": True}
    else:
        sw = getattr(mod, "SUBJECT_WORDS", None)
        if sw and getattr(mod, "PERSON_OF", None) and getattr(ep, "figures", None):
            pl, st, rep = PL.resolve_beats(script, mod.POOLS, mod.BLOCK_STATE,
                                           getattr(mod, "BLOCK_ALIASES", None),
                                           sw, ep.figures, mod.PERSON_OF,
                                           role_words=getattr(mod, "ROLE_WORDS", None))
            ep.shot_weights = rep.pop("weights")
        else:
            pl, st, rep = PL.resolve(script, mod.POOLS, mod.BLOCK_STATE,
                                     aliases=getattr(mod, "BLOCK_ALIASES", None),
                                     subject_words=sw,
                                     portraits=getattr(mod, "PORTRAITS", None),
                                     opening=getattr(mod, "OPENING_PACE", None))
        ep.playlists, ep.seg_state = pl, st
    return ep, script, rep


def _cfg_mtime(mod_path, ep):
    """Newest mtime of anything that decides what a shot looks like.

    Clips are cached as c_000.mp4, c_001.mp4 ... by POSITION. So a change to the planner renumbers
    every shot after the first insertion, and a key that only watched render.py would happily reuse
    clip 47 for a completely different shot. Watch the whole package, plus the board renderer.
    Narration is cached separately by filename, so this never re-spends on TTS.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    files = [mod_path, ep.script, os.path.join(os.path.dirname(here), "board_pipeline.py")]
    files += [os.path.join(here, f) for f in os.listdir(here) if f.endswith(".py")]
    return max(os.path.getmtime(f) for f in files if os.path.exists(f))


# --------------------------------------------------------------------------------- stages
def cmd_plan(args):
    mod = load_episode(args.episode)
    ep, script, plrep = _prepare(mod)
    from hotd import animate as AN, generate as GEN, playlists as PL
    print("== preflight ==")
    info = gates.preflight(ep, script, block_of=lambda i: PL.block_of(i, mod.POOLS,
                                              getattr(mod, "BLOCK_ALIASES", None)),
                           word_band=ep.word_band,
                           subject_words=getattr(mod, "SUBJECT_WORDS", None),
                           role_words=getattr(mod, "ROLE_WORDS", None),
                           strict_target_s=not args.loose_timing
                           and not plrep.get("exact"))
    for k, v in info.items():
        print(f"  {k:28s} {v}")
    thin = PL.thin_pools(plrep)
    print(f"  shot pool reuse            {plrep['cycles']}")
    if thin:
        print(f"  THIN POOLS (shots repeat)  {thin}")
    if hasattr(mod, "SIGIL_PROMPTS"):
        gp = GEN.plan(mod.SIGIL_PROMPTS, mod.LOCATION_PROMPTS, ep.index())
        print(f"  images to generate         {gp['n_new']}  (~${gp['est_usd']})")
        print(f"    new sigils               {gp['sigils_new']}")
        print(f"    new locations            {gp['locations_new']}")
    ap = AN.plan(ep, script, ep.playlists, max_clips=args.max_clips)
    print(f"  animatable plates          {ap['n']}  (~${ap['est_usd']})")
    for j in ap["jobs"][:6]:
        print(f"    {j['asset']:34s} {j['screen_seconds']:5.1f}s on screen  <- {j['from_segment']}")
    from hotd import render as R
    R.main(ep, plan_only=True)
    return 0


def cmd_assets(args):
    mod = load_episode(args.episode)
    ep, _, _ = _prepare(mod, require_script=False)
    from hotd import assets as A, generate as GEN
    A.register_pack(mod.PACK)
    out = os.path.join(mod.PACK, "generated")
    if hasattr(mod, "SIGIL_PROMPTS"):
        print("== generate emblems + plates ==")
        led, fails = GEN.run(mod.SIGIL_PROMPTS, mod.LOCATION_PROMPTS,
                             os.path.join(out, "sigils"), os.path.join(out, "locations"),
                             cap_usd=args.cap, existing_index=ep.index())
        if fails:
            raise SystemExit(f"generation failed for: {fails}")
    print("== code-drawn cards + diagrams ==")
    if hasattr(mod, "CHARACTERS"):
        print(f"  characters {len(A.build_cards(mod.CHARACTERS, out))}")
    if hasattr(mod, "DRAGONS"):
        print(f"  dragons    {len(A.build_dragon_cards(mod.DRAGONS, out))}")
    if hasattr(mod, "DIAGRAMS"):
        stems = A.build_diagrams(mod.DIAGRAMS, out)
        A.overflow_check(out, stems)
        print(f"  diagrams   {len(stems)} (all 1920x1080)")
    return 0


def cmd_thumb(args):
    mod = load_episode(args.episode)
    if not hasattr(mod, "build_thumbnail"):
        raise SystemExit(f"{args.episode} defines no build_thumbnail()")
    from hotd import thumbnail as T
    p = mod.build_thumbnail()
    print(f"  thumbnail -> {p}")
    print(f"  legibility: {T.contrast_report(p)}")
    return 0


def cmd_animate(args):
    mod = load_episode(args.episode)
    ep, script, _ = _prepare(mod)
    from hotd import animate as AN
    plan = AN.plan(ep, script, ep.playlists, max_clips=args.max_clips)
    print(f"== animate {plan['n']} plates (est ${plan['est_usd']}, cap ${args.cap:.2f}) ==")
    rep, fails = AN.generate(ep, plan["jobs"], cap_usd=args.cap)
    if fails:
        print(f"  NOT animated (these shots stay stills): {[f[0] for f in fails]}")
    return 0


def cmd_build(args):
    mod = load_episode(args.episode)
    ep, script, plrep = _prepare(mod)
    from hotd import deliver as D, playlists as PL, render as R
    print("== preflight ==")
    info = gates.preflight(ep, script, block_of=lambda i: PL.block_of(i, mod.POOLS,
                                              getattr(mod, "BLOCK_ALIASES", None)),
                           word_band=ep.word_band,
                           subject_words=getattr(mod, "SUBJECT_WORDS", None),
                           role_words=getattr(mod, "ROLE_WORDS", None),
                           strict_target_s=not args.loose_timing
                           and not plrep.get("exact"))
    print(f"  {info}")

    anim = None
    if args.animate:
        mp = os.path.join(ep.work, "animated", "manifest.json")
        if not os.path.exists(mp):
            raise SystemExit("--animate given but no clips yet; run `python -m hotd animate` first")
        anim = json.load(open(mp))
        print(f"  animation manifest: {len(anim.get('clips', {}))} clip(s)")

    rev = None
    if not args.no_reveals:
        print("== diagram reveals (free) ==")
        from hotd import reveal as RV
        rev = RV.build_for_episode(ep, ep.playlists, script)
        print(f"  {len(rev['clips'])} diagram shot(s) will build claim-by-claim")

    print("== render ==")
    rep = R.main(ep, cfg_mtime=_cfg_mtime(os.path.abspath(args.episode), ep),
                 animate=anim, reveals=rev)

    print("== gates ==")
    post = gates.postflight(ep, rep, duration_band_min=ep.duration_band_min)
    m = post["motion"]
    print(f"  per-shot motion  PASS  {m['n_shots']} shots, 0 frozen, "
          f"min {m['min_displacement']}, median {m['median_displacement']}")
    print(f"  audio            {post['audio']}")
    print(f"  duration         {post.get('duration_s', 0)/60:.2f} min")

    print("== package ==")  # package_gate runs after deliver, not before
    if ep.chapter_groups:
        ep.meta["chapters"] = list(ep.chapter_groups)
    else:
        order, seen = [], set()
        for s in script["segments"]:
            b = PL.block_of(s["id"], mod.POOLS, getattr(mod, "BLOCK_ALIASES", None))
            if b not in seen:
                seen.add(b); order.append(b)
        ep.meta["chapters"] = [(ep.chapter_titles.get(b, b.replace("_", " ").title()),
                                [s["id"] for s in script["segments"]
                                 if PL.block_of(s["id"], mod.POOLS, getattr(mod, "BLOCK_ALIASES", None)) == b]) for b in order]
    D.deliver(ep, ep.meta)
    gates.package_gate(ep)
    print("  package complete")
    return 0


def cmd_scaffold(args):
    from hotd import scaffold as S
    info = S.parse(args.episode)          # here `episode` is the SPEC path
    print(S.report(info))
    if args.slug:
        d, e = S.write(info, args.slug, args.prev_pack, force=args.force)
        print(f"\nwrote {d}\nwrote {e}\nNext: fill the TODOs, then `python -m hotd plan {e}`")
    else:
        print("\n(no --slug given, so nothing was written)")
    return 0


def cmd_all(args):
    for fn in (cmd_assets, cmd_thumb):
        fn(args)
    if args.animate:
        cmd_animate(args)
    return cmd_build(args)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hotd", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, helptext in (
            ("plan", cmd_plan, "validate and report, no spend and no render"),
            ("assets", cmd_assets, "generate emblems/plates and draw cards/diagrams"),
            ("thumb", cmd_thumb, "build the thumbnail"),
            ("animate", cmd_animate, "generate i2v clips for location plates"),
            ("build", cmd_build, "render, gate and package"),
            ("all", cmd_all, "assets + thumb + (animate) + build"),
            ("scaffold", cmd_scaffold, "read a spec markdown and scaffold an episode module")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("episode", help="path to an episode module, e.g. episodes/s3e4.py")
        p.add_argument("--cap", type=float, default=4.0, help="hard USD cap for this stage")
        p.add_argument("--animate", action="store_true", help="use animated plates when available")
        p.add_argument("--max-clips", type=int, default=10, help="most plates to animate")
        p.add_argument("--loose-timing", action="store_true",
                       help="skip the target_s arithmetic check")
        p.add_argument("--slug", help="scaffold only: episode slug, e.g. s3e5")
        p.add_argument("--prev-pack", default="house-of-dragons/"
                       "house_of_the_dragon_s3e4_complete_asset_pack/images",
                       help="scaffold only: the pack to inherit art from")
        p.add_argument("--force", action="store_true", help="scaffold only: overwrite")
        p.add_argument("--no-reveals", action="store_true",
                       help="disable the free diagram build-up animation")
        p.set_defaults(func=fn)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
