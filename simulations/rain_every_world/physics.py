"""What if it rained on every world -- computed from drag and breakup, not asserted.

TWO EQUATIONS CARRY THE VIDEO, both borrowed:

  terminal velocity   v_t = sqrt( 4 rho_liq g d / (3 rho_air Cd) )     -- the fall topic's drag law
  maximum drop size   We = rho_air v_t^2 d / sigma = We_crit           -- aerodynamic breakup

A drop grows until the airflow tears it apart, so the largest stable drop and its speed solve the
two equations together. Every constant with real uncertainty (Cd of a wobbling flattened drop,
critical Weber number) is CALIBRATED to Earth's measured rain -- max drop ~6 mm falling ~9 m/s --
the same move the fall topic used when it anchored frontal areas to the measured skydiver. The
model then makes a genuine prediction for Titan, and the literature value (~9.5 mm at ~1.6 m/s)
is the check on it.

rho and g per world come from the fly topic; the triple point rule comes from the water topic.
Three solvers, zero new physics, one calibrated constant pair.
"""
from __future__ import annotations
import math
from dataclasses import dataclass

from simulations.fly_every_world.physics import G_EARTH, RHO_EARTH
from simulations.water_every_world.physics import TRIPLE_PA

# Earth anchors: largest stable raindrop and its terminal velocity, both measured quantities.
D_MAX_EARTH = 0.006          # m
V_MAX_EARTH = 9.0            # m/s
SIGMA_WATER = 0.072          # N/m
RHO_WATER = 1000.0

# calibrate Cd from the terminal-velocity equation at the Earth anchor...
CD = 4 * RHO_WATER * G_EARTH * D_MAX_EARTH / (3 * RHO_EARTH * V_MAX_EARTH ** 2)
# ...and the critical Weber number from the breakup condition at the same anchor
WE_CRIT = RHO_EARTH * V_MAX_EARTH ** 2 * D_MAX_EARTH / SIGMA_WATER


@dataclass
class World:
    key: str
    name: str
    pressure_pa: float
    rho_air: float          # kg/m3 at the level where rain would fall
    g: float
    rho_liq: float          # what actually rains there
    sigma: float            # surface tension of that liquid
    liquid: str
    note: str = ""

    @property
    def can_rain(self):
        return self.pressure_pa >= TRIPLE_PA and self.rho_air > 0

    @property
    def d_max(self):
        """Largest stable drop, m: solve We=WE_CRIT and the v_t equation simultaneously."""
        if not self.can_rain:
            return None
        # substitute v_t^2 = 4 rho_liq g d / (3 rho_air Cd) into the Weber criterion:
        # rho_air * (4 rho_liq g d / 3 rho_air Cd) * d / sigma = WE_CRIT  ->  d^2 = ...
        d2 = WE_CRIT * self.sigma * 3 * CD / (4 * self.rho_liq * self.g)
        return math.sqrt(d2)

    @property
    def v_term(self):
        if not self.can_rain:
            return None
        d = self.d_max
        return math.sqrt(4 * self.rho_liq * self.g * d / (3 * self.rho_air * CD))


WORLDS = [
    World("earth", "EARTH", 101325, RHO_EARTH, G_EARTH, RHO_WATER, SIGMA_WATER, "water",
          "the control"),
    World("mars", "MARS", 610, 0.020, 3.721, RHO_WATER, SIGMA_WATER, "water",
          "at the triple point: clouds exist, rain cannot"),
    # rho_air is the CLOUD DECK's (~50 km, roughly Earth-like), not the surface's 65 kg/m3 --
    # the rain exists only aloft, which is the entire point of the beat. The surface value would
    # have quietly computed the terminal velocity of rain at an altitude the rain never reaches.
    World("venus", "VENUS", 9.2e6, 1.0, 8.87, 1800.0, 0.055, "sulfuric acid",
          "rain forms aloft and evaporates ~25 km above the ground -- virga"),
    World("jupiter", "JUPITER", 101325 * 2, 0.16, 24.79, 700.0, 0.02, "ammonia",
          "no surface anywhere: rain falls until heat vaporises it"),
    World("titan", "TITAN", 146700, 5.28, 1.352, 450.0, 0.017, "methane",
          "thick air, weak gravity, light liquid"),
]
BY_KEY = {w.key: w for w in WORLDS}


def verdict(w):
    if w.key == "venus":
        return "EVAPORATES MID-AIR"
    if w.key == "jupiter":
        return "NEVER LANDS - NO GROUND"
    if not w.can_rain:
        return "RAIN IMPOSSIBLE"
    if w.v_term < 3.0:
        return "GIANT SLOW RAIN"
    return "POURS NORMALLY"


def table():
    L = [f"calibrated: Cd={CD:.2f}, We_crit={WE_CRIT:.1f} (both from Earth's measured 6 mm / 9 m/s)",
         f"{'':8s}{'liquid':>14} {'drop':>8} {'falls at':>10}  verdict"]
    for w in WORLDS:
        d = f"{w.d_max*1000:.0f} mm" if w.can_rain else "--"
        v = f"{w.v_term:.1f} m/s" if w.can_rain else "--"
        L.append(f"{w.name:8s}{w.liquid:>14} {d:>8} {v:>10}  {verdict(w)}")
    return "\n".join(L)


if __name__ == "__main__":
    print(table())
    t = BY_KEY["titan"]
    print(f"\nTitan prediction vs literature (~9.5 mm at ~1.6 m/s): "
          f"{t.d_max*1000:.1f} mm at {t.v_term:.2f} m/s")
    e = BY_KEY["earth"]
    assert abs(e.d_max - D_MAX_EARTH) < 1e-9 and abs(e.v_term - V_MAX_EARTH) < 1e-9, "anchor broken"
    print("Earth anchor reproduces exactly: OK")
