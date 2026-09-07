"""Compute the trajectory instead of drawing it.

The previous revision failed because the arc was ART: Mars's path stretched because someone drew it
stretching, not because Mars has 0.38g and thin air. Nothing on screen was a measurement, so nothing
read as an experiment.

Here the arc is integrated from real constants. Same muzzle speed, same launch angle, same projectile
mass and calibre on every world; only g and atmospheric density change. Whatever comes out is the
answer, including when it is boring.

Drag uses the standard quadratic model, F = 0.5 * rho * v^2 * Cd * A, opposing the velocity vector.
Cd 0.295 and a 7.62mm 9.5g projectile are ordinary rifle-bullet figures. On airless worlds rho is 0
and the integration reduces to a clean parabola -- which is the point: the VACUUM CASE IS VISIBLY
DIFFERENT because the physics is different, not because the art says so.

Gas giants have no surface. The integration stops at a chosen "cloud deck" depth so the projectile
disappears into cloud rather than landing, which is the spec's own beat: there is nothing to hit.
"""
from __future__ import annotations
import math
from dataclasses import dataclass

from . import worlds as WD

MUZZLE_V = 900.0          # m/s, ordinary rifle muzzle velocity
LAUNCH_DEG = 32.0         # same on every world
MASS_KG = 0.0095
CALIBRE_M = 0.00762
CD = 0.295
AREA = math.pi * (CALIBRE_M / 2) ** 2


@dataclass
class World:
    key: str
    label: str
    g: float                    # m/s^2 surface gravity
    rho: float                  # kg/m^3 atmospheric density at the surface / cloud deck
    surface: bool = True        # False -> gas giant, nothing to hit
    radius_m: float = 0.0       # m, needed to know whether flat-ground physics is even legal here
    note: str = ""

    @property
    def orbital_v(self):
        """m/s for a circular orbit skimming the surface. The validity limit on this whole model."""
        return math.sqrt(self.g * self.radius_m) if self.radius_m else float("inf")


# g and rho now come from sim/worlds.py, the single table every topic shares. This module used to
# carry its own copy, which had drifted: earth 9.810 vs 9.807, moon 1.620 vs 1.625, mars 3.720 vs
# 3.721. Venus is still the shortest shot for the same reason -- ~65x Earth's air against near-Earth
# gravity -- but now it is the same 65.0 the fly topic uses.
WORLDS = {k: World(b.key, b.label, b.g, b.rho, b.surface, b.radius_m, b.note)
          for k, b in WD.BODIES.items() if k not in ("ceres", "comet")}


# The flat-ground, constant-g model is only legal while the shot stays small compared with the
# world. Two limits, both reported rather than assumed:
#   * muzzle velocity approaching circular orbital velocity -- past this the projectile does not
#     land at all, it orbits, and "range" stops being a distance along the ground;
#   * an arc subtending a large angle at the centre, where "flat ground" stops being flat.
# Pluto fails the first outright: v_orb at its surface is 858 m/s against a 900 m/s muzzle.
ORBITAL_FRAC_LIMIT = 0.70       # v0/v_orb above this -> curvature dominates, model void
ARC_DEG_LIMIT = 10.0            # degrees of arc above this -> flat ground is a visible lie


def integrate(world, v0=MUZZLE_V, angle_deg=LAUNCH_DEG, dt=0.002, max_t=3600.0,
              deck_depth=4000.0):
    """Return (points, stats). points are (t, x, y, speed) in metres from the muzzle.

    Stops at ground return for worlds with a surface, or at deck_depth below the launch plane for
    gas giants. No small-angle or no-drag shortcuts: one integrator for every world so the
    comparison is honest.

    stats carries its own honesty flags. `landed` says the run ended by hitting something rather
    than by running out of clock; `truncated` is its complement and used to be invisible -- max_t
    was 600 s while Pluto's flight needs 1538 s, so Pluto reported 458 km / 600 s in exactly the
    format a real landing uses, with the bullet still 174 km up. `flat_ground_valid` says whether
    the model was entitled to produce a range at all.
    """
    th = math.radians(angle_deg)
    vx, vy = v0 * math.cos(th), v0 * math.sin(th)
    x = y = t = 0.0
    pts = [(0.0, 0.0, 0.0, v0)]
    peak = 0.0
    k = 0.5 * world.rho * CD * AREA / MASS_KG      # drag accel per (m/s)^2
    while t < max_t:
        v = math.hypot(vx, vy)
        ax, ay = 0.0, -world.g
        if k > 0 and v > 0:
            ax -= k * v * vx
            ay -= k * v * vy
        vx += ax * dt
        vy += ay * dt
        x += vx * dt
        y += vy * dt
        t += dt
        peak = max(peak, y)
        pts.append((t, x, y, math.hypot(vx, vy)))
        if world.surface and y <= 0 and t > 0.05:
            landed = True
            break
        if not world.surface and y <= -deck_depth:
            landed = True                      # reached the cloud deck: the gas-giant equivalent
            break
    else:
        landed = False
    rng_m = pts[-1][1]
    arc_deg = (math.degrees(rng_m / world.radius_m) if world.radius_m else 0.0)
    orb_frac = v0 / world.orbital_v if world.orbital_v else 0.0
    reasons = []
    if orb_frac >= ORBITAL_FRAC_LIMIT:
        reasons.append(f"muzzle {v0:.0f} m/s is {orb_frac:.0%} of orbital velocity "
                       f"({world.orbital_v:.0f} m/s) -- this shot orbits, it does not land")
    if arc_deg >= ARC_DEG_LIMIT:
        reasons.append(f"arc spans {arc_deg:.1f} deg of the surface -- flat ground and constant g "
                       f"no longer apply")
    stats = {"range_m": rng_m, "peak_m": peak, "flight_s": pts[-1][0],
             "impact_speed": pts[-1][3], "surface": world.surface,
             "g": world.g, "rho": world.rho,
             "landed": landed, "truncated": not landed,
             "arc_deg": arc_deg, "orbital_frac": orb_frac,
             "flat_ground_valid": not reasons, "invalid_because": reasons}
    return pts, stats


def summary():
    """Every world's result, for sanity-checking the numbers before anything is rendered."""
    out = {}
    for k, w in WORLDS.items():
        _, s = integrate(w)
        out[k] = {"range_km": round(s["range_m"] / 1000, 2),
                  "peak_km": round(s["peak_m"] / 1000, 2),
                  "flight_s": round(s["flight_s"], 1),
                  "landed": s["landed"], "flat_ground_valid": s["flat_ground_valid"],
                  "invalid_because": s["invalid_because"],
                  "g": w.g, "rho": w.rho, "surface": w.surface}
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(summary(), indent=2))
