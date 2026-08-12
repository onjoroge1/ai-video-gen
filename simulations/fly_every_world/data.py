"""What If You Tried To Fly On Every World -- a PARALLEL comparison.

Applies four lessons from the water video's regression:
  * every narration claim gets a matching VISUAL instruction (Pluto's sublimation had none, and was
    banned by the negative while the voiceover asserted it)
  * the NUMBER reaches the screen (Titan's 111 C was voiceover-only; here the ease factor and the
    rotor multiplier are on the chips)
  * prohibitions are reasoned PER WORLD (Venus inherited the Moon's vacuum rule, where a plume is
    actually the correct result at 92 bar)
  * the hook opens on the surprise, and Earth is not the answer -- Titan is
"""
from __future__ import annotations

from sim.spec import Scene, Simulation
from .physics import BY_KEY


def _chips(key):
    w = BY_KEY[key]
    if w.rho <= 1e-6:
        return (w.name, "NO AIR · CANNOT FLY")
    return (w.name, f"{w.ease:.0f}x EARTH · ROTOR {w.rpm_factor:.2f}x"
            if w.ease >= 2 else f"{w.ease:.2f}x EARTH · ROTOR {w.rpm_factor:.1f}x")


CONTINUITY = (
    "The same small white quadcopter drone with four rotors, hovering just above the ground, and the "
    "same small white-and-teal robot standing to one side watching it. Identical drone, identical "
    "size, identical robot in every shot. Photoreal, natural light for that world, shot from the "
    "same fixed side-on angle at the same distance"
)

# Prohibitions are per-world and REASONED. Copying one world's ban onto another is how Venus was told
# not to make a vapour plume in a 92-bar atmosphere where a plume is correct.
PLATE_JOBS = [
    ("00_titan", "the same white quadcopter climbing easily and fast into a hazy orange sky above a "
                 "frozen shore, rotors turning slowly and lazily, the robot watching from below. "
                 "No smoke, no exhaust, no flame",
                 "Fixed side-on shot, dim orange twilight, thick hazy air, drone high in frame"),
    ("01_mars",  "the same white quadcopter straining just centimetres off red dust, rotors a "
                 "blurred disc spinning violently fast, dust barely disturbed beneath it because the "
                 "air is too thin to move, the robot watching. No thick dust cloud, no billowing "
                 "plume, the thin air cannot lift much dust",
                 "Fixed side-on shot, pink-brown Martian sky, drone very low to the ground"),
    ("02_earth", "the same white quadcopter hovering steadily at chest height above pale dry ground "
                 "on a clear day, rotors a normal blur, light dust moving beneath it, the robot "
                 "watching",
                 "Fixed side-on shot, plain daylight, drone at mid frame height"),
    ("03_venus", "the same white quadcopter floating almost effortlessly above a flat plain of dark "
                 "scorched basalt under a dense overcast orange sky, rotors barely turning, thick "
                 "air visibly swirling and rolling around it in heavy currents, the robot watching. "
                 "No lava, no molten rock, no glowing ground, no fire",
                 "Fixed side-on shot, dim flat diffuse orange light, hazy low visibility"),
    ("04_titan", "the same white quadcopter very high up in a hazy orange sky above a frozen shore, "
                 "climbing steadily on slow lazy rotors, the small robot tiny on the ground far "
                 "below watching it go. No smoke, no exhaust, no flame",
                 "Fixed side-on shot, dim orange twilight, drone high and small, wide view"),
    ("04_moon",  "the same white quadcopter sitting motionless and dead on grey lunar dust under a "
                 "pure black sky, all four rotors completely still, no movement at all, the robot "
                 "watching it. No dust cloud, no motion, nothing moving in the air because there is "
                 "no air",
                 "Fixed side-on shot, hard unfiltered sunlight, black airless sky, drone on the ground"),
    ("05_verdict", "the same white quadcopter resting on a plain neutral surface with the small robot "
                   "standing beside it looking at it",
                   "Fixed centred shot, neutral dark background, the drone lit clearly"),
]


def _s(key, sid, stem, secs, narration, motion, onscreen=""):
    return Scene(id=sid, image=stem, narration=narration, seconds=secs,
                 chips=_chips(key) if key else (), onscreen=onscreen, motion=motion)


SCENES = [
    _s("titan", "hook", "00_titan", 3.0,
       "Same drone, five worlds. The easiest is not Earth.",
       "the drone climbing fast and easily up through the hazy orange air, rotors turning slowly",
       "NOT EARTH"),
    _s("mars", "mars", "01_mars", 5.0,
       "Mars air is so thin the rotors spin nearly five times faster just to lift off.",
       "the rotors spinning violently fast into a blurred disc while the drone barely lifts off the "
       "red dust, the thin air moving almost no dust beneath it"),
    _s("earth", "earth", "02_earth", 3.4,
       "Earth is the baseline. Normal rotors, normal hover.",
       "the drone hovering steadily at chest height, rotors a normal blur, light dust moving below"),
    _s("venus", "venus", "03_venus", 5.2,
       "Venus has sixty five times our air density. It almost floats, if the heat spared it.",
       "the drone floating almost effortlessly with its rotors barely turning, the thick air rolling "
       "visibly around it in heavy currents"),
    _s("titan", "titan", "04_titan", 6.0,
       "Titan wins. Thick air, one seventh gravity: thirty two times easier than Earth. You could "
       "take off by flapping.",
       "the drone climbing on slow lazy rotors, then banking hard and accelerating away across the "
       "frame, orange haze streaming past it"),
    _s("moon", "moon", "04_moon", 3.4,
       "The Moon has no air. Rotors do nothing.",
       "the drone sitting completely dead and motionless on the grey dust, all four rotors perfectly "
       "still, nothing moving anywhere in frame"),
    _s(None, "verdict", "05_verdict", 4.6,
       "NASA is sending a rotorcraft to Titan for exactly this reason. We built flight for the only "
       "air we had ever known, and two worlds out there make Earth look like the hard setting.",
       "the drone resting still on a plain surface, one rotor turning over slowly once and stopping",
       "TITAN WINS"),
]

SIM = Simulation(
    slug="fly_every_world",
    title="What If You Tried To Fly On Every World",
    root="simulations/fly_every_world",
    scenes=SCENES,
    locked={"camera": "fixed side-on, locked off, identical framing every world",
            "drone": "the same small white quadcopter, same size, same rotors",
            "robot": "the same small white-and-teal robot, watching, never touching"},
    style="Photoreal, grounded, natural light for that world. No text, no logos, no fantasy effects",
    source_aspect=1024 / 1536,
    speed=1.0, pad_s=0.16,
    target_s=(32.0, 44.0),
    meta={"kind": "parallel", "recurring_object": "quadcopter drone",
          "instrument": "ease vs Earth", "direction": "parallel_experiment_v1",
          "control": "earth"},
)
