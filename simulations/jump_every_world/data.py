"""What If You Jumped As Hard As You Can On Every World -- PARALLEL comparison.

Same person, same 3 m/s standing jump, six worlds. Height and hang time are computed; the payoff is
that on a comet nucleus an ordinary jump exceeds escape velocity, so the arithmetic ends the video
rather than a writer's flourish.

One number is deliberately NOT on screen: the comet's "height" is 45,000 m, a divide-by-near-zero
artifact of h = v^2/2g as g approaches nothing. The escape check overrides it in physics.py, and the
chip says ESCAPE VELOCITY 0.9 m/s instead -- the true and much better fact.
"""
from __future__ import annotations

from sim.spec import Scene, Simulation
from .physics import BY_KEY, V_JUMP


def _chips(key):
    w = BY_KEY[key]
    if V_JUMP >= w.escape:
        return (w.name, f"ESCAPE {w.escape:.1f} m/s · YOU LEAVE")
    return (w.name, f"{w.height:.1f} m HIGH · {w.hang:.1f}s AIRBORNE")


CONTINUITY = (
    "The same man in a plain white spacesuit with a clear bubble helmet, mid-jump, and the same small "
    "white-and-teal robot standing to one side watching him. Identical suit, identical build, "
    "identical robot in every shot. Photoreal, natural light for that world, shot from the same fixed "
    "side-on angle at the same distance, the horizon in the same place"
)

PLATE_JOBS = [
    # ZERO_RULE (sim/direction.py): the measured quantity is HEIGHT, so every plate must contain the
    # ground it is measured from. The first pass wrote all six as "mid-hop" / "caught high in the
    # air", which made apparent height a property of framing rather than of gravity -- and gave the
    # i2v stage nothing near the camera to move, which is why Ceres failed twice at 0.10 and 0.13.
    ("00_ceres", "the same suited man in the instant of pushing off a grey cratered asteroid surface, "
                 "knees still bent, boots just leaving the dust, a small puff of grey dust at his "
                 "feet, the ground filling the lower third of frame, the small white-and-teal robot "
                 "standing on the surface beside him",
                 "Fixed side-on shot, ground across the bottom of frame, black sky above"),
    ("01_earth", "the same suited man in the instant of launching off pale dry ground on Earth, knees "
                 "bent, toes just leaving the surface, blue sky, the ground filling the lower third "
                 "of frame, the robot standing on the ground beside him",
                 "Fixed side-on shot, horizon low, ground across the bottom of frame"),
    ("02_mars", "the same suited man in the instant of pushing off red dust and rock under a "
                "pink-brown sky, knees bent, boots just leaving the ground, fine red dust lifting at "
                "his feet, the ground filling the lower third of frame, the robot beside him",
                "Fixed side-on shot, ground across the bottom of frame, Martian horizon"),
    ("03_moon", "the same suited man in the instant of a standing jump off grey lunar dust, knees bent, "
                "boots just clearing the surface, dust thrown out in a low flat arc, the ground "
                "filling the lower third of frame, black sky, the robot standing beside him",
                "Fixed side-on shot, ground across the bottom of frame, hard sunlight"),
    ("04_titan", "the same suited man in the instant of a standing jump off a frozen orange-brown shore, "
                 "knees bent, boots just leaving the ice, thick hazy orange air, the ground filling "
                 "the lower third of frame, the robot standing beside him",
                 "Fixed side-on shot, ground across the bottom of frame, dim orange light"),
    ("05_comet", "the same suited man in the instant of pushing off the dark rocky surface of a comet "
                 "nucleus, knees bent, boots just leaving the rock, loose grains drifting up around "
                 "him, the rugged surface filling the lower half of frame, black star field above, "
                 "the robot standing on the rock beside him",
                 "Fixed side-on shot, surface across the lower half of frame, stars above"),
]

def _s(key, sid, stem, secs, narration, motion, onscreen=""):
    return Scene(id=sid, image=stem, narration=narration, seconds=secs,
                 chips=_chips(key) if key else (), onscreen=onscreen, motion=motion)


SCENES = [
    _s("ceres", "hook", "00_ceres", 3.6,
       "Same jump, six worlds. On one of them you never come down.",
       "the man hanging in the air and still rising slowly above the cratered surface, the robot "
       "small below him",
       "SAME JUMP"),
    _s("earth", "earth", "01_earth", 4.2,
       "This is your jump on Earth. Half a metre, back down in six tenths of a second.",
       "the man springing up a few inches and dropping straight back down onto the dry ground"),
    _s("mars", "mars", "02_mars", 4.4,
       "Mars has a third of our gravity. The same jump clears your own head.",
       "the man rising to about head height and floating back down onto the red dust"),
    _s("moon", "moon", "03_moon", 4.6,
       "On the Moon you go nearly three metres up and hang there for almost four seconds.",
       "the man rising high and slowly, hanging near the top of the arc, then drifting down onto "
       "grey dust"),
    _s("titan", "titan", "04_titan", 5.0,
       "Titan is gentler still: three and a third metres, four and a half seconds in the air.",
       "the man drifting slowly upward through the thick orange haze and settling back very gently"),
    _s("ceres", "ceres", "00_ceres", 5.2,
       "On Ceres, the largest asteroid, that same jump takes you sixteen metres up and keeps you "
       "airborne for twenty one seconds.",
       "the man rising very high above the cratered surface, tiny against the black sky, still going "
       "up"),
    _s("comet", "comet", "05_comet", 6.2,
       "And on a comet, escape velocity is under one metre per second. Your jump is three. You do "
       "not land. You just leave.",
       # The first attempt measured 0.38 against a 0.45 floor. "rising steadily... getting
       # smaller" describes a STATE with no rate, and a shrinking subject produces less pixel
       # change every frame -- the generator gave back what was asked for. The fix is to give
       # the frame something large and NEAR to move: the surface falling away, not the man
       # receding.
       "the rocky comet surface drops away fast beneath him and slides down out of the bottom "
       "of frame, loose dust and ice grains lifting off the rock and streaming past, the "
       "horizon rolling as the nucleus turns, the man carried up and away without slowing",
       "YOU JUST LEAVE"),
]

SIM = Simulation(
    slug="jump_every_world",
    title="What If You Jumped As Hard As You Can On Every World",
    root="simulations/jump_every_world",
    scenes=SCENES,
    locked={"camera": "fixed side-on, locked off, identical framing every world",
            "subject": "the same suited man, same build, same 3 m/s jump",
            "robot": "the same small white-and-teal robot, watching, never touching"},
    style="Photoreal, grounded, natural light for that world. No text, no logos, no fantasy effects",
    source_aspect=1024 / 1536,
    speed=1.0, pad_s=0.16,
    target_s=(32.0, 44.0),
    meta={"kind": "parallel", "recurring_object": "the jump", "instrument": "height and hang time",
          "direction": "parallel_experiment_v1", "control": "earth", "badge": "SAME JUMP"},
)
