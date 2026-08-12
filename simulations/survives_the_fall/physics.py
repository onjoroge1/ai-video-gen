"""What survives the same fall -- computed from drag, not asserted.

THE SPINE IS THE SQUARE-CUBE LAW.
Terminal velocity comes from balancing weight against drag:

    v_t = sqrt( 2 m g / (rho Cd A) )

The quantity that decides everything is m/A -- mass per square metre of frontal area. v_t is exactly
its square root, and across ant to horse it spans a factor of about 1,400.

A CLAIM THIS MODULE DOES NOT MAKE. The tempting version is "v_t grows as sqrt(L)", which follows if
mass goes as L^3 and area as L^2. The self-test at the bottom checks that and it FAILS: sqrt(L)
predicts 44 m/s for the horse against an actual 76. Real animals are not scaled copies of one another
-- a horse is far denser in cross-section than an ant, whose splayed legs give it enormous area for
its mass. The mechanism is that mass outruns frontal area, which is true; the clean power law is not,
so it stays out of the narration.

That is the entire video, and it is why the verdict is reported as specific impact energy, v^2/2 in
joules per kilogram. That quantity is INDEPENDENT OF MASS: it says a falling body's fate is set by
its speed alone, so the horse is not doomed for being heavy, it is doomed for being large. Reporting
total kinetic energy instead would have made mass look like the cause and produced the wrong story
from correct arithmetic.

Haldane put the result in one line in 1926, and every number here is a check on it: a mouse walks
away, a man is broken, a horse splashes.

The fall height is 900 m -- Haldane's "thousand-yard mine shaft". It is chosen so every subject is at
terminal velocity on impact; at a more ordinary 100 m the human and the horse are still accelerating
and land at nearly the same speed, which would hide the effect the video is about.

Air density and surface gravity are imported from the fly topic rather than restated. Two modules
holding their own copy of rho is how they drift.
"""
from __future__ import annotations
import math
from dataclasses import dataclass

from simulations.fly_every_world.physics import G_EARTH, RHO_EARTH

FALL_M = 900.0          # Haldane's thousand-yard mine shaft, in metres


@dataclass
class Subject:
    key: str
    name: str
    mass_kg: float
    area_m2: float          # frontal area in the attitude it actually falls in
    cd: float
    length_m: float         # characteristic body length, for the sqrt(L) claim
    note: str = ""

    @property
    def v_term(self):
        """Terminal velocity, m/s."""
        return math.sqrt(2 * self.mass_kg * G_EARTH / (RHO_EARTH * self.cd * self.area_m2))

    def v_at(self, h=FALL_M):
        """Impact speed after falling h metres WITH drag -- the analytic solution, not v=sqrt(2gh).

        v(h) = v_t * sqrt(1 - exp(-2 g h / v_t^2)). Using the drag-free formula here would give the
        ant 133 m/s and destroy the result the video exists to show.
        """
        vt = self.v_term
        return vt * math.sqrt(1 - math.exp(-2 * G_EARTH * h / (vt * vt)))

    def energy_per_kg(self, h=FALL_M):
        """Specific impact energy, J/kg. Mass-independent on purpose -- see the module docstring."""
        v = self.v_at(h)
        return 0.5 * v * v

    def verdict(self, h=FALL_M):
        e = self.energy_per_kg(h)
        if e < 10:
            return "UNHURT"
        if e < 100:
            return "WALKS AWAY"
        if e < 500:
            # "USUALLY SURVIVES" overstated the famous high-rise study, which counted only cats
            # brought to hospital -- survivorship bias in the sample. 90% had thoracic trauma.
            return "OFTEN SURVIVES"
        if e < 2000:
            return "NOT SURVIVABLE"
        return "CATASTROPHIC"

    @property
    def m_over_a(self):
        """Mass per square metre of frontal area. v_term is exactly its square root times a constant,
        so this is the one number that explains the whole spread."""
        return self.mass_kg / self.area_m2

    @property
    def mph(self):
        return self.v_at() * 2.23694


# Masses and lengths are standard; frontal areas are the falling attitude, which is the number with
# real uncertainty here. A cat spreads to roughly a square foot, a skydiver belly-to-earth to about
# half a square metre -- both are measured values, and they anchor the two ends of the middle range.
SUBJECTS = [
    Subject("ant",   "ANT",   3.0e-6, 1.2e-5, 1.0, 0.005, "drag beats weight completely"),
    Subject("mouse", "MOUSE", 0.020,  0.0030, 1.0, 0.080, "Haldane's mouse"),
    Subject("cat",   "CAT",   4.0,    0.090,  1.1, 0.300, "spreads out like a parachute"),
    Subject("human", "HUMAN", 70.0,   0.45,   0.9, 1.800, "belly-to-earth, the measured case"),
    Subject("horse", "HORSE", 500.0,  1.40,   1.0, 2.400, "Haldane's horse"),
]

BY_KEY = {s.key: s for s in SUBJECTS}


def table(h=FALL_M):
    L = [f"fall height {h:.0f} m",
         f"{'':<7}{'mass':>10} {'m/A':>8} {'v_term':>9} {'impact':>9} {'mph':>7} "
         f"{'J/kg':>8}  verdict"]
    for s in SUBJECTS:
        L.append(f"{s.name:<7}{s.mass_kg:>10.4g} {s.m_over_a:>8.1f} {s.v_term:>8.1f}m/s "
                 f"{s.v_at(h):>8.1f}m/s {s.mph:>7.0f} {s.energy_per_kg(h):>8.0f}  {s.verdict(h)}")
    return "\n".join(L)


if __name__ == "__main__":
    print(table())
    # Kept as a REFUTATION, not a check that passes: it is the reason the sqrt(L) story is absent
    # from the script. If a future edit reintroduces that claim, this prints the counter-evidence.
    print("\nsqrt(L) is NOT the law here -- prediction vs actual:")
    base = SUBJECTS[0]
    for s in SUBJECTS:
        pred = base.v_term * math.sqrt(s.length_m / base.length_m)
        print(f"  {s.name:<7} actual {s.v_term:>6.1f}  sqrt(L) says {pred:>6.1f}  "
              f"m/A {s.m_over_a:>7.1f}")
