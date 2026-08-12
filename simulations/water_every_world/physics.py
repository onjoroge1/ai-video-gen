"""What actually happens to a glass of water on each world -- computed, not asserted.

The spine is the PHASE DIAGRAM. Whether liquid water can exist anywhere depends on two numbers, and
only two: pressure and temperature. Below the triple point (611.657 Pa, 273.16 K) liquid water cannot
exist at any temperature -- it goes straight from ice to vapour. Above the boiling curve it flashes
to steam. The verdict on every world falls out of where that world sits on the curve, so the video
never has to assert an outcome: it reads it off.

Boiling point at pressure uses the Antoine equation (NIST coefficients, 1..100 degC range,
extrapolated outside it and flagged when so).
"""
from __future__ import annotations
import math
from dataclasses import dataclass

TRIPLE_PA, TRIPLE_K = 611.657, 273.16          # below this pressure: no liquid water, ever
A, B, C = 8.07131, 1730.63, 233.426            # Antoine, mmHg / degC


def boiling_c(pressure_pa):
    """Boiling point in degC at a given pressure. None below the triple point -- there isn't one."""
    if pressure_pa < TRIPLE_PA:
        return None
    mmhg = pressure_pa / 133.322
    return B / (A - math.log10(max(mmhg, 1e-9))) - C


@dataclass
class World:
    key: str
    name: str
    pressure_pa: float
    surface_c: float
    note: str = ""

    @property
    def boil_c(self):
        return boiling_c(self.pressure_pa)

    @property
    def verdict(self):
        """The outcome, derived. Order matters: no-liquid-possible beats every other test."""
        if self.pressure_pa < TRIPLE_PA:
            return ("BOILS AND FREEZES" if self.surface_c > -100 else "FREEZES, THEN SUBLIMES")
        b = self.boil_c
        if self.surface_c >= b:
            return "FLASHES TO STEAM"
        if self.surface_c <= 0:
            return "FREEZES SOLID"
        return "POURS NORMALLY"

    @property
    def detail(self):
        b = self.boil_c
        if b is None:
            return f"{self.pressure_pa:.0f} Pa is below the triple point: no liquid water at any temperature"
        return f"water boils at {b:.0f} C here; the ground is {self.surface_c:.0f} C"


WORLDS = [
    World("earth",   "EARTH",   101325,   15,  "the control"),
    World("mars",    "MARS",       610,  -60,  "just below the triple point"),
    World("venus",   "VENUS",  9200000,  464,  "92 bar, hot enough to glow"),
    World("moon",    "THE MOON",     0, -20,  "vacuum"),
    World("titan",   "TITAN",   146700, -179,  "thicker air than Earth, far colder"),
    World("europa",  "EUROPA",      1e-6, -160, "effectively vacuum"),
    World("pluto",   "PLUTO",         1, -229,  "a whisper of nitrogen"),
]
BY_KEY = {w.key: w for w in WORLDS}


def table():
    rows = []
    for w in WORLDS:
        b = w.boil_c
        rows.append({"world": w.name, "pressure_pa": w.pressure_pa, "surface_c": w.surface_c,
                     "boil_c": None if b is None else round(b, 1), "verdict": w.verdict})
    return rows


if __name__ == "__main__":
    for r in table():
        b = "none (below triple point)" if r["boil_c"] is None else f"{r['boil_c']:>7.1f} C"
        print(f"  {r['world']:9s} {r['pressure_pa']:>10.0f} Pa  surface {r['surface_c']:>5.0f} C  "
              f"boils {b:>26s}  ->  {r['verdict']}")
