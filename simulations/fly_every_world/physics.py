"""Can a rotor fly here? Computed from air density and gravity, not asserted.

Lift scales with air DENSITY and weight scales with GRAVITY, so flight difficulty is essentially
rho/g relative to Earth. That ratio is the whole video, and it produces a genuinely counterintuitive
winner: Titan, not Earth. Thick cold nitrogen at 1.45 bar and one seventh of Earth's gravity makes it
the easiest place to fly in the solar system -- a human in a wingsuit could flap and take off. It is
why NASA is sending Dragonfly there rather than a rover.

Mars is the opposite: Ingenuity needed rotors at ~2,500 rpm, roughly five times a terrestrial
helicopter, to lift 1.8 kg.
"""
from __future__ import annotations
from dataclasses import dataclass

G_EARTH, RHO_EARTH = 9.807, 1.225


@dataclass
class World:
    key: str
    name: str
    rho: float          # kg/m3 near the surface
    g: float            # m/s2
    note: str = ""

    @property
    def ease(self):
        """Lift per unit weight, relative to Earth = 1.0. rho gives lift, g takes it away."""
        return (self.rho / RHO_EARTH) / (self.g / G_EARTH)

    @property
    def rpm_factor(self):
        """Rotor speed needed relative to Earth: lift ~ rho * v^2, so v ~ sqrt(1/ease)."""
        return None if self.rho <= 0 else (1.0 / self.ease) ** 0.5

    @property
    def verdict(self):
        if self.rho <= 1e-6:
            return "NO AIR - CANNOT FLY"
        e = self.ease
        if e >= 8:    return "TRIVIALLY EASY"
        if e >= 2:    return "EASIER THAN EARTH"
        if e >= 0.5:  return "ABOUT LIKE EARTH"
        if e >= 0.05: return "BARELY POSSIBLE"
        return "ALMOST IMPOSSIBLE"


WORLDS = [
    World("earth",  "EARTH",   1.225,   9.807, "the control"),
    World("mars",   "MARS",    0.020,   3.721, "Ingenuity needed ~2,500 rpm"),
    World("venus",  "VENUS",  65.000,   8.870, "65x Earth's air density"),
    World("titan",  "TITAN",   5.400,   1.352, "thick cold air, one seventh gravity"),
    World("moon",   "THE MOON", 0.0,    1.625, "vacuum"),
]
BY_KEY = {w.key: w for w in WORLDS}

if __name__ == "__main__":
    for w in WORLDS:
        r = "n/a" if w.rpm_factor is None else f"{w.rpm_factor:5.2f}x"
        print(f"  {w.name:9s} rho {w.rho:7.3f}  g {w.g:5.2f}  ease {w.ease:8.2f}x Earth  "
              f"rotor {r}  ->  {w.verdict}")
