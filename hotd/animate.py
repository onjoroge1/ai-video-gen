"""Make the imagery move with the story: turn location plates into living establishing shots.

WHAT ANIMATES, AND WHY ONLY THAT
Characters are never animated. The whole IP posture of this format is that people appear as heraldic
TEXT cards, never as likenesses, and generating moving footage of a character is precisely the thing
that posture exists to avoid. Diagrams are not animated either -- they are information displays and
motion costs legibility.

Location PLATES are original matte paintings we generated ourselves, they are already ~40% of every
episode's shots, and atmosphere is exactly what they lack. Smoke off an occupied town, rain in a
street, firelight in a hall, mist moving in a valley, carrion birds over a battlefield: motion that
carries mood and place without depicting a person.

HOW THE MOTION IS CHOSEN
Two inputs, and the split matters. WHAT can move comes from the ASSET, because that is a fact about
the picture: a sealed bedchamber can have a guttering candle and dust in a light shaft, and cannot
have chimney smoke or passing figures. HOW it should feel comes from the SEGMENT's caption and
narration -- night, fire, rain, cold.

Getting this backwards is not hypothetical: the first pilot derived motion from the narration alone
and put a besieging camp inside a manor hall and chimney smoke inside a locked bedroom, because the
narration under those plates was about the town outside.

FAILURE POLICY
No silent stills. A plate that fails to animate stays a still-with-drift and is REPORTED in the
manifest as unanimated. A caller that asked for animation and got none is told so, per shot.

DURATION
Kling accepts 5 or 10 seconds; Veo accepts 4, 6 or 8. Shots average ~6s. A 5s clip is retimed to the
shot length with setpts (ambient motion tolerates up to ~1.6x stretch without reading as slow
motion); beyond that the shot keeps the still treatment rather than freezing on a clone.
"""
from __future__ import annotations
import json
import os
import subprocess

MAX_STRETCH = 1.6                 # beyond this, a retimed ambient clip reads as slow motion
DEFAULT_SECONDS = 5               # Kling: 5 or 10 only
AMBIENT_NEGATIVE = ("people, human figures, faces, crowds in the foreground, characters, portraits, "
                    "text, letters, watermark, camera pan, camera zoom, camera shake, cuts")


class AnimateCap(Exception):
    pass


# What can physically move is a property of the PICTURE, not of the narration. Deriving motion from
# the narration alone put chimney smoke and passing figures inside a sealed bedchamber, and a
# besieging camp inside a manor hall, because the narration under those plates was about the town.
# So: the asset decides the motion vocabulary; the narration only sets the mood within it.
_SCENE_MOTION = [
    (("quarters", "chamber", "_bed", "family_home"),
     "candle flame guttering, firelight shifting slowly across the walls, dust turning in the "
     "shaft of light from the window, a curtain barely stirring"),
    (("residence", "council", "hall", "sept", "throne_room", "petition"),
     "dust turning slowly in shafts of light, torch and hearth light shifting across stone, "
     "hanging cloth and banners stirring very slightly indoors"),
    (("occupied", "_camp", "tumbleton_street"),
     "cook-smoke drifting up from campfires, banners and tent canvas stirring in the wind, "
     "figures far too small and distant to make out moving between the tents"),
    (("kings_landing", "_city", "market", "food_distribution", "graffiti_street"),
     "chimney smoke rising across the rooftops, awnings and washing moving in the wind, "
     "indistinct distant movement in the streets far below"),
    (("battlefield", "bones", "gullet"),
     "carrion birds circling and settling, thin ash and dust drifting on a cold wind, "
     "faint heat-shimmer over the burnt ground"),
    (("vale", "mountain", "cave", "shepherding", "eyrie", "peak"),
     "low cloud and mist rolling slowly through the valley below, grass and scrub bending in the "
     "wind, light shifting as cloud passes"),
    (("dragonstone", "harbour", "_sea", "water", "riverlands"),
     "water moving with small waves catching the light, mist drifting across the surface, "
     "cloud shadow crossing slowly"),
    (("harrenhal", "red_keep", "oldtown", "farmland", "reach", "castle"),
     "cloud moving across the sky, banners and grass stirring in the wind, light shifting slowly "
     "over the stone"),
]
# Empirical yield, from the paid pilot. Scenes with a LOCAL bright source (candle, hearth, a shaft of
# light) animate strongly because the generator has something concrete to move. Wide exteriors whose
# only motion is "smoke and banners somewhere in the distance" come back near-static and get rejected
# by accept_clip -- billed, unusable. So wide exteriors are ranked BELOW interiors regardless of
# screen time, and their prompts ask for larger, nearer movement.
_YIELD_BONUS = [
    (("quarters", "chamber", "_bed", "family_home", "residence", "council", "hall", "sept",
      "throne_room", "petition"), 1.6),           # local light source: animates reliably
    (("battlefield", "bones", "cave", "shepherding", "vale", "mountain"), 1.0),
    (("occupied", "_camp", "kings_landing", "_city", "farmland", "reach", "harrenhal",
      "red_keep", "oldtown", "dragonstone"), 0.55),   # wide, distant motion: poor yield
]


def yield_weight(asset):
    a = asset.lower()
    for keys, w in _YIELD_BONUS:
        if any(k in a for k in keys):
            return w
    return 1.0


_MOOD = [
    (("night", "dark", "candle", "torch"), "at night, very low warm light"),
    (("burn", "fire", "flame", "dragonfire", "sack"), "with firelight and drifting smoke"),
    (("rain", "storm"), "in steady rain, with water dripping and pooling"),
    (("cold", "winter", "ash", "dead"), "in cold grey light"),
]


def _scene_motion(asset):
    a = asset.lower()
    for keys, motion in _SCENE_MOTION:
        if any(k in a for k in keys):
            return motion
    return "very slow atmospheric drift: haze moving, light shifting slowly, distant smoke rising"


def _mood(caption, narration):
    t = f"{caption} {narration}".lower()
    for keys, mood in _MOOD:
        if any(k in t for k in keys):
            return mood
    return ""


def build_prompt(asset, caption, narration, atmosphere=None):
    """Motion from the asset (what can move), mood from the narration (how it should feel)."""
    motion = atmosphere or _scene_motion(asset)
    mood = _mood(caption, narration)
    return (f"{motion}{(', ' + mood) if mood else ''}. The camera does not move at all. "
            f"Nothing enters or leaves the frame and the composition is unchanged. No people in "
            f"the foreground, no faces, no new objects. Photoreal painterly matte-painting look.")


def plan(ep, script, playlists, max_clips=10, seconds=DEFAULT_SECONDS, price_per_clip=None):
    """Choose which plates to animate. No spend. Returns a list of jobs, most valuable first.

    Selection: one clip per DISTINCT plate asset (a plate reused across shots animates once and is
    reused), ranked by how much screen time that plate holds -- the longer a still is on screen, the
    more it gains from moving.
    """
    seg_by_id = {s["id"]: s for s in script["segments"]}
    holds, first_seg = {}, {}
    for sid, shots in playlists.items():
        seg = seg_by_id.get(sid)
        if not seg:
            continue
        share = seg["target_s"] / max(len(shots), 1)
        for it in shots:
            if it[0] != "plate":
                continue
            holds[it[1]] = holds.get(it[1], 0.0) + share
            first_seg.setdefault(it[1], seg)
    if price_per_clip is None:
        import explainer_pipeline as epl
        price_per_clip = round(seconds * epl._RATE_I2V_SEC, 4)
    ranked = sorted(holds.items(), key=lambda kv: -kv[1] * yield_weight(kv[0]))[:max_clips]
    jobs = []
    for asset, secs in ranked:
        seg = first_seg[asset]
        jobs.append({"asset": asset, "screen_seconds": round(secs, 1),
                     "seed_image": ep.asset(asset),
                     "prompt": build_prompt(asset, seg["caption"], seg["narration"]),
                     "from_segment": seg["id"], "seconds": seconds})
    return {"jobs": jobs, "n": len(jobs), "est_usd": round(len(jobs) * price_per_clip, 2)}


def generate(ep, jobs, cap_usd=4.0, seconds=DEFAULT_SECONDS, provider=None, price_per_clip=None,
             progress=print):
    """Generate the clips. Returns (manifest, failures). Never raises on a provider failure --
    a plate that will not animate simply stays a still, and says so.

    Goes through explainer_pipeline.animate_scene rather than _animate_one, because animate_scene
    already provides three things this module previously reimplemented worse: a REAL cost sink priced
    off _RATE_I2V_SEC instead of a hardcoded guess, the _I2V_CHAIN provider fallback, and
    quota-exhaustion tracking so an exhausted provider is skipped for the rest of the run.
    """
    import explainer_pipeline as epl

    # real measured rate, not an invented constant
    price_per_clip = price_per_clip or round(seconds * epl._RATE_I2V_SEC, 4)
    outdir = os.path.join(ep.work, "animated")
    os.makedirs(outdir, exist_ok=True)
    manifest, failures = {}, []
    costs: list = []
    errs: list = []
    exhausted: set = set()

    for j in jobs:
        out = os.path.join(outdir, f"{j['asset']}.mp4")
        if os.path.exists(out) and os.path.getsize(out) > 10000:
            manifest[j["asset"]] = out
            progress(f"  {j['asset']:34s} reuse")
            continue
        if sum(costs) + price_per_clip > cap_usd:
            failures.append((j["asset"], f"cap ${cap_usd:.2f} reached"))
            progress(f"  {j['asset']:34s} SKIP (cap)")
            continue
        res = epl.animate_scene(j["seed_image"], j["prompt"], out, 1920, 1080,
                                cost_sink=costs, seconds=seconds, err_sink=errs,
                                exhausted=exhausted, motion_style="ambient",
                                negative=AMBIENT_NEGATIVE)
        ok = bool(res)
        if ok and os.path.exists(out) and os.path.getsize(out) > 10000:
            spent = sum(costs)                           # billed whether or not we can use it
            good, m = accept_clip(out)
            if good:
                manifest[j["asset"]] = out
                progress(f"  {j['asset']:34s} ok   motion {m['per_frame_mean']}  (${spent:.2f})")
            else:
                failures.append((j["asset"],
                                 f"clip is near-static (per-frame {m['per_frame_mean']} < "
                                 f"{MIN_CLIP_MOTION}); keeping the still"))
                progress(f"  {j['asset']:34s} REJECT motion {m['per_frame_mean']} "
                         f"< {MIN_CLIP_MOTION}  (${spent:.2f} spent anyway)")
        else:
            why = errs[-1] if errs else "all providers failed"
            failures.append((j["asset"], why))
            progress(f"  {j['asset']:34s} FAIL {why}")

    rep = {"clips": manifest, "failures": failures,
           "spent_usd": round(sum(costs), 4),          # measured, not estimated
           "per_clip_usd": price_per_clip,
           "providers_exhausted": sorted(exhausted),
           "provider_chain": list(epl._I2V_CHAIN), "seconds": seconds}
    json.dump(rep, open(os.path.join(outdir, "manifest.json"), "w"), indent=2)
    progress(f"  animated {len(manifest)}/{len(jobs)} plates, "
             f"${sum(costs):.3f} of ${cap_usd:.2f} (measured)")
    return rep, failures


MIN_CLIP_MOTION = 0.45          # per-frame mean |diff| at 340x192; see the calibration note below


def clip_motion(path):
    """Per-frame motion in a generated clip. Measured, because generators sometimes return a
    near-still for a wide exterior and there is no way to tell from the response.

    Calibrated on the first paid pilot: an interior with firelight came back at 1.48 per-frame mean,
    while a wide occupied-town exterior came back at 0.16 -- below even the 0.25 threshold used for
    'is this frame moving at all'. Paying for the second one buys nothing a still with drift does not
    already give, so it is rejected and the shot keeps the still treatment.
    """
    import numpy as np

    import video_audit as va
    g = va._decode_gray(path, 340, 192).astype(np.int16)
    if len(g) < 2:
        return {"frames": len(g), "per_frame_mean": 0.0, "first_vs_last": 0.0}
    d = np.abs(np.diff(g, axis=0)).mean(axis=(1, 2))
    return {"frames": int(len(g)), "per_frame_mean": round(float(d.mean()), 2),
            "peak": round(float(d.max()), 2),
            "first_vs_last": round(float(np.abs(g[0] - g[-1]).mean()), 2)}


def accept_clip(path, min_motion=MIN_CLIP_MOTION):
    m = clip_motion(path)
    return m["per_frame_mean"] >= min_motion, m


def clip_duration(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", path], capture_output=True, text=True).stdout)


def usable_for(clip_path, frames, fps=30, max_stretch=MAX_STRETCH):
    """A clip may only cover a shot it can be retimed to fill. Otherwise the shot keeps the still
    treatment -- padding with a cloned frame would put a freeze back inside an 'animated' shot."""
    need = frames / fps
    have = clip_duration(clip_path)
    return have > 0 and need / have <= max_stretch, round(need, 2), round(have, 2)
