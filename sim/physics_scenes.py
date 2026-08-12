"""Render the planetary scenes from computed trajectories onto the cleaned plates.

Bolt's beats (cold open, experiment lock, the no-surface title, the resolution) keep their generated
motion -- they were never the problem. Every scene where a projectile flies is now composited from
the integrator instead.
"""
from __future__ import annotations
import os

from . import ballistics as B, projectile as P

CLEAN = "simulation/bullet_every_planet_package/images_clean"
# generated plates in which NOTHING is fired -- the world layer under the computed projectile
AMBIENT_DIR = "renders/bullet_every_planet/work/ambient"

# Muzzle position per plate, normalised, VERIFIED against a crosshair overlay rather than eyeballed
# from a contact sheet. The first pass guessed eight of these and only the three I had actually
# looked at were right -- which is exactly why the shot drifted away from the barrel as the sequence
# went on. Regenerate the check with tools/anchor_check.py after touching any plate.
SCENES = {
    "earth":    ("01_earth_baseline",                 "earth",   (0.135, 0.520)),
    "venus":    ("02_venus_dense_air",                "venus",   (0.185, 0.545)),
    "mars":     ("03_mars_long_arc",                  "mars",    (0.112, 0.505)),
    "mercury":  ("04_mercury_farthest_rocky_world",   "mercury", (0.152, 0.530)),
    "jupiter":  ("05_jupiter_downward_hook",          "jupiter", (0.212, 0.272)),
    "saturn":   ("06_saturn_longer_cloud_descent",    "saturn",  (0.300, 0.430)),
    "uranus":   ("07_uranus_haze_descent",            "uranus",  (0.172, 0.272)),
    "neptune":  ("08_neptune_wind_bend",              "neptune", (0.320, 0.335)),
    "pluto_setup":   ("09_pluto_return_payoff",       "pluto",   (0.356, 0.760)),
    "pluto_orbit_a": ("09_pluto_return_payoff",       "pluto",   (0.356, 0.760)),
    "pluto_orbit_b": ("09_pluto_return_payoff",       "pluto",   (0.356, 0.760)),
}


def build(sim, outdir, progress=print):
    """One physics clip per planetary scene, at that scene's exact frame count."""
    os.makedirs(outdir, exist_ok=True)
    clips, stats = {}, {}
    by_id = {s.id: s for s in sim.scenes}
    for sid, (stem, world_key, muzzle) in SCENES.items():
        sc = by_id.get(sid)
        if sc is None:
            continue
        frames = max(2, int(round(sc._dur * sim.fps)))
        out = os.path.join(outdir, f"{sid}.mp4")
        amb = os.path.join(AMBIENT_DIR, f"{stem}.mp4")
        st = P.render_scene(os.path.join(CLEAN, f"{stem}.png"), B.WORLDS[world_key],
                            muzzle, frames, out, fps=sim.fps, out_wh=(sim.W, sim.H),
                            ambient_mp4=(amb if os.path.exists(amb) else None),
                            scale_bar=True)
        clips[sid], stats[sid] = out, st
        progress(f"  {sid:16s} {frames:4d}f  range {st['range_m']/1000:8.2f} km  "
                 f"{'no air' if B.WORLDS[world_key].rho == 0 else 'trail':6s}  "
                 f"world: {st.get('world_layer')}")
    return clips, stats
