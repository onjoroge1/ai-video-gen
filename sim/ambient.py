"""Generate LIVING background plates: the world moves, nothing is fired.

WHY THIS EXISTS
The first build let the generator draw the projectile, and it invented a glowing sci-fi comet with
the wrong physics. The fix -- compositing a computed bullet over the still PNG -- was correct about
the object and wrong about the world: measured background motion fell from 0.081-0.238 down to
0.002, roughly 100x, so every planetary shot became a still with one moving sprite on it.

Both attempts made the same mistake in opposite directions: choosing ONE renderer for the whole
frame. A simulation frame is three layers with three different right answers --

    world       -> generative i2v   (dust, cloud, haze: things we cannot compute and need not)
    subject     -> code + physics   (must be identical across worlds and provably correct)
    instrument  -> code             (rulers and readouts must never be hallucinated)

This module owns the first layer only. Every prompt therefore BANS the projectile explicitly: no
bullet, no tracer, no streak, no launch. The launcher and Bolt must hold still and simply exist; the
world around them lives.
"""
from __future__ import annotations

# Calibrated against every clip this project has shipped or thrown away: accepted clips
# measure 0.7-23; everything below ~0.45 has needed regeneration. Ceres passed at 0.10 and
# Mercury at 0.15 under the old floor, and both had to be redone at full price.
MIN_MOTION = 0.45
import os
import threading

# What may move on each world, keyed by plate. Atmosphere only -- never the subject, never the rig.
AMBIENT = {
    "01_earth_baseline":               "slow cumulus clouds drifting across the blue sky, grass and "
                                       "scrub moving gently in the breeze on the plain below, haze "
                                       "shifting along the distant hills",
    "02_venus_dense_air":              "thick orange sulphurous cloud churning and rolling overhead, "
                                       "heat haze rippling above the rock, dust lifting and settling",
    "03_mars_long_arc":                "fine red dust drifting low across the ground, thin high cloud "
                                       "moving slowly, faint dust devils turning far away on the plain",
    "04_mercury_farthest_rocky_world": "harsh unfiltered sunlight, the starfield steady and airless, "
                                       "a very slight settling of grey dust disturbed near the ground",
    "05_jupiter_downward_hook":        "vast banded cloud belts churning and shearing past each other, "
                                       "the great storm slowly rotating, ammonia haze streaming",
    "06_saturn_longer_cloud_descent":  "pale gold cloud decks drifting and separating, ring shadows "
                                       "creeping across the cloud tops, thin haze streaming",
    "07_uranus_haze_descent":          "featureless blue-green methane haze shifting very slowly, "
                                       "faint banding drifting, soft cold light changing",
    "08_neptune_wind_bend":            "deep blue cloud bands torn by supersonic wind, white cirrus "
                                       "streaks racing across the disc, the dark storm turning",
    "09_pluto_return_payoff":          "a still airless world, the starfield steady, a faint nitrogen "
                                       "haze layer on the limb shifting almost imperceptibly",
}

# Said on every prompt. The generator must not invent the thing the physics layer owns.
BAN = ("No projectile, no bullet, no tracer, no glowing streak, no light trail, no beam, no comet, "
       "no missile, no explosion, no muzzle flash, nothing is fired and nothing flies. "
       "The launcher does not move, rotate or fire. The small robot does not move or change shape. "
       "Locked-off camera: no pan, no tilt, no zoom, no push in, no camera shake, no cuts. "
       "No text, no letters, no numbers, no logos, no watermark.")

NEGATIVE = ("bullet, projectile, tracer, streak, light trail, beam, laser, comet, missile, rocket, "
            "explosion, muzzle flash, smoke trail, camera pan, camera zoom, camera shake, cut, "
            "text, letters, watermark, extra robot, deformed robot, morphing")


def build_prompt_custom(motion):
    """Ambient prompt for a topic that supplies its own per-plate motion."""
    return (f"Only the environment and natural body motion move: {motion}. {BAN}"), NEGATIVE


def build_prompt(plate_stem):
    """Atmosphere for this world, plus the ban. The world lives; the experiment does not start."""
    motion = AMBIENT.get(plate_stem, "very slow atmospheric drift, light shifting slowly")
    return (f"Only the environment moves: {motion}. {BAN}"), NEGATIVE


# Travel mode bans the OPPOSITE things to ambient: here the camera must move and the world must
# streak. Reusing the ambient BAN (which forbids pan, tilt and any camera motion) is exactly what
# pinned a 240 mph shot to a locked tripod.
TRAVEL_BAN = ("The subject does not change shape, age, wardrobe or identity. Nobody else enters the "
              "frame. No new objects appear. No text, no letters, no numbers, no logos, no watermark. "
              "No slow motion.")
TRAVEL_NEGATIVE = ("slow motion, static camera, locked-off camera, still background, frozen "
                   "background, standing still, walking slowly, deformed, malformed, extra limbs, "
                   "extra fingers, duplicated person, morphing, text, letters, watermark, logo")


def build_travel_prompt(subject_action, world_detail=""):
    """Prompt for a shot whose CONTENT is the subject's speed."""
    return (f"{subject_action}. {world_detail} {TRAVEL_BAN}".strip(), TRAVEL_NEGATIVE)


def generate(plates_dir, out_dir, stems, W=1080, H=1920, seconds=5, cap_usd=4.0,
             scene_of=None,
             price_per_clip=0.30, model="fal-ai/kling-video/v3/pro/image-to-video",
             workers=4, prompts=None, motion_style="ambient", min_motion=MIN_MOTION, progress=print):
    """One ambient clip per plate. Returns (manifest, failures). Never raises on a provider error."""
    import explainer_pipeline as epl

    from .animate import accept, clip_motion

    os.makedirs(out_dir, exist_ok=True)
    manifest, failures = {}, []
    spent = 0.0
    lock = threading.Lock()

    def one(stem):
        nonlocal spent
        # key on the SCENE when the caller supplies the mapping: two scenes may share a plate
        # but they do not share an intent, and keying on the plate silently gave one scene the
        # other's prompt.
        key = (scene_of or {}).get(stem, stem)
        out = os.path.join(out_dir, f"{key}.mp4")
        if os.path.exists(out) and os.path.getsize(out) > 10000:
            with lock:
                manifest[stem] = out
            progress(f"  {stem[:30]:30s} reuse")
            return
        with lock:
            if spent + price_per_clip > cap_usd + 1e-6:
                failures.append((stem, f"cap ${cap_usd:.2f} reached"))
                progress(f"  {stem[:30]:30s} SKIP (cap)")
                return
            spent += price_per_clip
        prompt, negative = (prompts or {}).get(stem) or build_prompt(stem)
        try:
            ok, _q, err = epl._animate_one("fal", os.path.join(plates_dir, f"{stem}.png"),
                                           prompt, out, W, H, seconds, fal_model=model,
                                           motion_style=motion_style, negative=negative)
        except Exception as e:
            ok, err = False, f"{type(e).__name__}: {e}"
        if not (ok and os.path.exists(out) and os.path.getsize(out) > 10000):
            with lock:
                spent -= price_per_clip
                failures.append((stem, str(err)[:150]))
            progress(f"  {stem[:30]:30s} FAIL {str(err)[:60]}")
            return
        m = clip_motion(out)
        # An ambient plate only has to LIVE, so the bar is far below an action clip's.
        if m["per_frame_mean"] < min_motion:
            try:
                json.dump({"asset": stem, "prompt": prompt, "negative": negative, "model": model,
                           "motion_style": motion_style, "seconds": seconds,
                           "measured_motion": m, "price_usd": price_per_clip,
                           "accepted": False, "min_motion": min_motion,
                           "reason": f"below motion floor ({m['per_frame_mean']} < {min_motion})"},
                          open(out[:-4] + ".rejected.json", "w"), indent=2)
                os.replace(out, out + ".rejected")
            except Exception:
                pass
            with lock:
                failures.append((stem, f"below motion floor ({m['per_frame_mean']} < {min_motion}) -- billed, unusable"))
            progress(f"  {stem[:30]:30s} REJECT motion {m['per_frame_mean']}")
            return
        # Persist WHAT WAS ASKED FOR, beside what came back. Every clip in this project before this
        # change was generated from an inline prompt in a throwaway script, so a third of the shots
        # became unauditable the moment the script exited -- we had the artifact and no record of how
        # it was made. The sidecar makes the ask recoverable and, later, learnable.
        try:
            json.dump({"asset": stem, "prompt": prompt, "negative": negative,
                       "model": model, "motion_style": motion_style, "seconds": seconds,
                       "measured_motion": m, "price_usd": price_per_clip,
                       "accepted": True, "min_motion": min_motion},
                      open(out[:-4] + ".json", "w"), indent=2)
        except Exception:
            pass
        with lock:
            manifest[stem] = out
        progress(f"  {stem[:30]:30s} ok   motion {m['per_frame_mean']}")

    ts = [threading.Thread(target=one, args=(s,)) for s in stems]
    for i in range(0, len(ts), workers):
        batch = ts[i:i + workers]
        for t in batch: t.start()
        for t in batch: t.join()
    progress(f"  ambient {len(manifest)}/{len(stems)} plates, ${spent:.2f} of ${cap_usd:.2f}")
    return manifest, failures
