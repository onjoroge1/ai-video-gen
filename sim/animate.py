"""Kling V3 image-to-video for simulation scenes.

Every scene animates here, unlike the HotD format where only atmosphere moved. In a simulation the
MOTION IS THE CONTENT: the viewer is watching what the projectile does differently on each world, so
a still frame with a drawn-on arc is a diagram, not a simulation.

Two safeguards, both learned by paying for the lesson:
  * a hard USD cap checked before each call, so a loop bug cannot run away;
  * an acceptance gate on the returned clip. A generator that hands back a near-still is billed
    either way, and on the previous format 40% of wide exteriors came back unusable. A rejected clip
    falls back to the still with drift and is REPORTED, never silently substituted.
"""
from __future__ import annotations

# Calibrated against every clip this project has shipped or thrown away: accepted clips
# measure 0.7-23; everything below ~0.45 has needed regeneration. Ceres passed at 0.10 and
# Mercury at 0.15 under the old floor, and both had to be redone at full price.
MIN_MOTION = 0.45
import json
import os

KLING_V3 = "fal-ai/kling-video/v3/pro/image-to-video"
DEFAULT_SECONDS = 5                 # Kling accepts 5 or 10 only
# ACCEPTANCE, and why it takes two measures.
# A whole-frame mean is the wrong single test for this format. Mercury's shot is a small bullet on a
# static airless plain -- physically correct, visibly moving, and it scored 0.33 while a dusty Mars
# shot scored 4.36. Rejecting it would have thrown away the accurate shots and kept only the busy
# ones. So a clip passes on EITHER broad motion OR consistent localized motion, and the second
# criterion is what sees a small fast object.
MIN_CLIP_MOTION = 0.45              # whole-frame mean |diff| (broad motion: dust, cloud, haze)
MIN_LOCAL_PEAK = 30                 # a pixel changing this much counts as real local movement
MIN_LOCAL_FRAC = 0.55               # ...and it must happen in this share of frames


class Cap(Exception):
    pass


def clip_motion(path):
    import numpy as np
    import video_audit as va
    g = va._decode_gray(path, 192, 340).astype(np.int16)      # portrait decode
    if len(g) < 2:
        return {"frames": len(g), "per_frame_mean": 0.0, "local_frac": 0.0, "first_vs_last": 0.0}
    d = np.abs(np.diff(g, axis=0))
    peak = d.max(axis=(1, 2))
    return {"frames": int(len(g)),
            "per_frame_mean": round(float(d.mean(axis=(1, 2)).mean()), 2),
            "local_frac": round(float((peak > MIN_LOCAL_PEAK).mean()), 2),
            "first_vs_last": round(float(np.abs(g[0] - g[-1]).mean()), 2)}


def accept(m, min_motion=MIN_CLIP_MOTION):
    """Broad motion OR sustained localized motion. Either is a moving picture."""
    return m["per_frame_mean"] >= min_motion or m["local_frac"] >= MIN_LOCAL_FRAC


def camera_drift(path):
    """Global translation first-to-last. The locked camera is what makes the comparison valid, so
    it is measured rather than hoped for."""
    import numpy as np
    import video_audit as va
    g = va._decode_gray(path, 240, 426).astype(np.float32)
    def sh(a, b, axis):
        pa, pb = a.mean(axis=axis), b.mean(axis=axis)
        pa, pb = pa - pa.mean(), pb - pb.mean()
        return int(np.argmax(np.correlate(pa, pb, mode="full")) - (len(pb) - 1))
    return {"dx": sh(g[0], g[-1], 0), "dy": sh(g[0], g[-1], 1)}


def generate(sim, scenes=None, cap_usd=6.0, seconds=DEFAULT_SECONDS, model=KLING_V3,
             price_per_clip=0.35, min_motion=MIN_CLIP_MOTION, workers=4, progress=print):
    """-> (manifest {scene_id: mp4}, failures, spent). Never raises on a provider failure.

    NOTE ON price_per_clip: this is an ESTIMATE, not a figure read back from the provider. Nothing in
    explainer_pipeline reports a real per-clip i2v price, so the cap bounds the NUMBER of clips at an
    assumed rate rather than true dollars. Verify against the fal dashboard before trusting it as a
    spend control on a large run.

    Clips are generated concurrently: one Kling V3 Pro clip measured 144s, so sixteen in series is
    over half an hour. The provider is a queue API, so concurrency is on its side, not ours.
    """
    import explainer_pipeline as epl
    from sim.prompts import build

    import threading
    from concurrent.futures import ThreadPoolExecutor

    todo = [s for s in (scenes or sim.scenes) if s.animate]
    outdir = os.path.join(sim.work, "clips")
    os.makedirs(outdir, exist_ok=True)
    manifest, failures, spent = {}, [], 0.0
    lock = threading.Lock()

    def one(sc):
        nonlocal spent
        out = os.path.join(outdir, f"{sc.id}.mp4")
        if os.path.exists(out) and os.path.getsize(out) > 10000:
            # Size alone let a truncated download through: a clip with no moov atom passed reuse,
            # then crashed the render half an hour later. Probe before trusting.
            import subprocess as sp
            ok = sp.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "csv=p=0", out], capture_output=True, text=True)
            if ok.returncode == 0 and float(ok.stdout.strip() or 0) > 1.0:
                with lock:
                    manifest[sc.id] = out
                progress(f"  {sc.id:16s} reuse")
                return
            os.remove(out)
            progress(f"  {sc.id:16s} corrupt on disk -- regenerating")
        with lock:
            if spent + price_per_clip > cap_usd + 1e-6:
                failures.append((sc.id, f"cap ${cap_usd:.2f} reached before this clip"))
                progress(f"  {sc.id:16s} SKIP (cap)")
                return
            spent += price_per_clip          # reserve before the call, refund on failure
        prompt, negative = build(sc, sim.locked, sim.style)
        try:
            ok, quota, err = epl._animate_one(
                "fal", sim.asset(sc.image), prompt, out,
                sim.W, sim.H, seconds, fal_model=model,
                motion_style="action", negative=negative)
        except Exception as e:
            ok, err = False, f"{type(e).__name__}: {e}"
        if not (ok and os.path.exists(out) and os.path.getsize(out) > 10000):
            with lock:
                spent -= price_per_clip      # not billed for a call that produced nothing
                failures.append((sc.id, str(err)[:160]))
            progress(f"  {sc.id:16s} FAIL {str(err)[:70]}")
            return
        m = clip_motion(out)
        # The gate premise is "the plate is empty, so nothing new may appear". That is a property
        # of the SCENE, not of its negatives: inferring it from wildlife negatives rejected seven
        # clips of rain for containing rain. Scenes declare it explicitly.
        empty_scene = getattr(sc, "empty_frame", False)
        if empty_scene:
            import video_audit as _va
            inv = _va.invented_subject_gate(out, sim.asset(sc.image))
            if not inv["passed"]:
                os.rename(out, out[:-4] + ".invented.mp4")
                try:
                    import json as _json
                    _json.dump({"asset": sc.image, "scene": sc.id, "prompt": prompt,
                                "negative": negative, "model": model, "invented": inv,
                                "accepted": False, "price_usd": price_per_clip},
                               open(out[:-4] + ".rejected.json", "w"), indent=2)
                except Exception:
                    pass
                with lock:
                    failures.append((sc.id, f"invented subject in empty scene "
                                            f"(blob {inv['score']})"))
                progress(f"  {sc.id:16s} REJECT invented subject (blob {inv['score']})")
                return
        if not accept(m, min_motion):
            try:
                import json as _json
                _json.dump({"asset": sc.image, "scene": sc.id, "prompt": prompt,
                            "negative": negative, "model": model, "measured_motion": m,
                            "min_motion": min_motion, "accepted": False,
                            "price_usd": price_per_clip},
                           open(out[:-4] + ".rejected.json", "w"), indent=2)
            except Exception:
                pass
            with lock:
                failures.append((sc.id, f"near-static (mean {m['per_frame_mean']}, "
                                        f"local {m['local_frac']})"))
            progress(f"  {sc.id:16s} REJECT mean {m['per_frame_mean']} local {m['local_frac']}")
            os.replace(out, out + ".rejected")
            return
        with lock:
            manifest[sc.id] = out
        progress(f"  {sc.id:16s} ok  mean {m['per_frame_mean']:5.2f} local {m['local_frac']:.2f}")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, todo))

    json.dump({"clips": manifest, "failures": failures, "spent_usd": round(spent, 2),
               "model": model, "seconds": seconds},
              open(os.path.join(outdir, "manifest.json"), "w"), indent=2)
    progress(f"  animated {len(manifest)}/{len(todo)}, ${spent:.2f} of ${cap_usd:.2f}")
    return manifest, failures, spent
