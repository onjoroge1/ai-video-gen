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
    note: str = ""


# Surface gravity and near-surface atmospheric density. Venus is ~65x Earth's air, which is why it
# is the shortest shot despite near-Earth gravity -- the single most counterintuitive result here.
WORLDS = {
    "earth":   World("earth", "EARTH", 9.81, 1.225),
    "venus":   World("venus", "VENUS", 8.87, 65.0),
    "mars":    World("mars", "MARS", 3.72, 0.020),
    "mercury": World("mercury", "MERCURY", 3.70, 0.0),
    "jupiter": World("jupiter", "JUPITER", 24.79, 0.16, surface=False, note="no surface"),
    "saturn":  World("saturn", "SATURN", 10.44, 0.19, surface=False, note="no surface"),
    "uranus":  World("uranus", "URANUS", 8.87, 0.42, surface=False, note="no surface"),
    "neptune": World("neptune", "NEPTUNE", 11.15, 0.45, surface=False, note="no surface"),
    "pluto":   World("pluto", "PLUTO", 0.62, 0.0),
    "moon":    World("moon", "THE MOON", 1.62, 0.0),
}


def integrate(world, v0=MUZZLE_V, angle_deg=LAUNCH_DEG, dt=0.002, max_t=600.0,
              deck_depth=4000.0):
    """Return (points, stats). points are (t, x, y, speed) in metres from the muzzle.

    Stops at ground return for worlds with a surface, or at deck_depth below the launch plane for
    gas giants. No small-angle or no-drag shortcuts: one integrator for every world so the
    comparison is honest.
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
            break
        if not world.surface and y <= -deck_depth:
            break
    stats = {"range_m": pts[-1][1], "peak_m": peak, "flight_s": pts[-1][0],
             "impact_speed": pts[-1][3], "surface": world.surface,
             "g": world.g, "rho": world.rho}
    return pts, stats


def summary():
    """Every world's result, for sanity-checking the numbers before anything is rendered."""
    out = {}
    for k, w in WORLDS.items():
        _, s = integrate(w)
        out[k] = {"range_km": round(s["range_m"] / 1000, 2),
                  "peak_km": round(s["peak_m"] / 1000, 2),
                  "flight_s": round(s["flight_s"], 1),
                  "g": w.g, "rho": w.rho, "surface": w.surface}
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(summary(), indent=2))
