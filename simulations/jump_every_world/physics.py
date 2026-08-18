"""One human jump, six worlds. Height and escape are computed, not asserted.

A standing jump leaves the ground at about 3.0 m/s -- that is a half-metre hop on Earth. Everything
else follows from two numbers per world:

    height   h = v^2 / 2g
    escape   v_esc = sqrt(2 G M / r)

The payoff falls out of the arithmetic rather than being written in: on a comet nucleus the escape
velocity is under a metre per second, so an ordinary jump exceeds it and you simply do not come back.
Nobody has to be told that is dramatic; the number says it.
"""
from __future__ import annotations
import math
from dataclasses import dataclass

V_JUMP = 3.0            # m/s, a normal standing jump (0.46 m on Earth)
G = 6.674e-11


@dataclass
class World:
    key: str
    name: str
    g: float            # m/s2
    mass: float         # kg
    radius: float       # m
    note: str = ""

    @property
    def height(self):
        return V_JUMP ** 2 / (2 * self.g)

    @property
    def escape(self):
        return math.sqrt(2 * G * self.mass / self.radius)

    @property
    def hang(self):
        """Seconds in the air, up and back down."""
        return 2 * V_JUMP / self.g

    @property
    def verdict(self):
        if V_JUMP >= self.escape:
            return "YOU NEVER COME BACK"
        h = self.height
        if h < 1:    return "A NORMAL HOP"
        if h < 5:    return "A ROOFTOP JUMP"
        if h < 30:   return "HIGHER THAN A HOUSE"
        return "MINUTES IN THE AIR"


WORLDS = [
    World("earth",  "EARTH",   9.807, 5.972e24, 6.371e6, "the control"),
    World("mars",   "MARS",    3.721, 6.417e23, 3.390e6, ""),
    World("titan",  "TITAN",   1.352, 1.345e23, 2.575e6, "thick air, weak gravity"),
    World("moon",   "THE MOON", 1.625, 7.342e22, 1.737e6, ""),
    World("ceres",  "CERES",   0.284, 9.384e20, 4.730e5, "largest asteroid"),
    World("comet",  "COMET 67P", 1.0e-4, 9.982e12, 1.65e3, "escape velocity under 1 m/s"),
]
BY_KEY = {w.key: w for w in WORLDS}

if __name__ == "__main__":
    for w in WORLDS:
        esc = f"{w.escape:7.2f} m/s"
        print(f"  {w.name:10s} g {w.g:7.3f}  jump {w.height:8.2f} m  hang {w.hang:7.1f} s  "
              f"escape {esc}  ->  {w.verdict}")
