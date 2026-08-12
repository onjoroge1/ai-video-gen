"""What If You Poured Water On Every World -- a PARALLEL comparison.

Opposite invariants to the escalation format: the camera is LOCKED, the frame is world-fixed, and the
variable is the condition rather than time. Same glass, same pour, seven worlds.

The instrument is the phase diagram. Whether liquid water can exist depends on exactly two numbers,
and the video reads its verdicts off physics.py rather than asserting them -- Titan is the proof it
is doing real work: thicker air than Earth means water boils HIGHER there, at 111 C, and it is still
rock-hard ice because the ground is -179 C. Nobody would write that from intuition.
"""
from __future__ import annotations

from sim.spec import Scene, Simulation
from .physics import BY_KEY

def _chips(key):
    w = BY_KEY[key]
    p = (f"{w.pressure_pa/1000:.0f} kPa" if w.pressure_pa >= 1000
         else f"{w.pressure_pa:.0f} Pa" if w.pressure_pa >= 1 else "VACUUM")
    return (w.name, f"{p} · {w.surface_c:.0f}°C")

CONTINUITY = (
    "The same clear glass tumbler of water, the same pair of gloved hands pouring it, and the same "
    "small white-and-teal robot standing to one side watching. Identical glass, identical pour, "
    "identical robot in every shot. Photoreal, natural light for that world, shot from the same "
    "fixed side-on angle at the same distance"
)

# (stem, action, shot) -- what is IN the picture. Verdicts come from physics.py, not from here.
PLATE_JOBS = [
    ("00_earth",  "gloved hands tipping a clear glass of water onto pale dry ground, a normal clean "
                  "stream of water falling and pooling, the small robot watching from the left",
                  "Fixed side-on shot, plain daylight, the pour in the centre of frame"),
    ("01_mars",   "gloved hands tipping the same glass onto red dust under a pink-brown sky, the "
                  "falling water bursting into vapour and frost at once, the robot watching",
                  "Fixed side-on shot, thin cold light, Martian dust and rock"),
    # Venus is 464 C, which is hot enough to glow only faintly at night; it is NOT a molten lava
    # field. The surface is scorched basalt plain under a crushing overcast that lets ~2% of sunlight
    # through, so the light is dim, flat and orange -- not the furnace glow the first pass produced.
    ("02_venus",  "gloved hands tipping the same glass onto a flat plain of dark scorched basalt "
                  "rock under a dense overcast orange sky, strong heat shimmer distorting the air "
                  "above the ground, the water turning to vapour before it lands, the robot watching. "
                  "No lava, no molten rock, no glowing ground, no fire, no open flame",
                  "Fixed side-on shot, dim flat diffuse orange light, hazy low visibility, "
                  "weathered rock plain to the horizon"),
    # In vacuum there is no air to be buoyant in, so vapour cannot RISE as a plume. It expands
    # ballistically outward in all directions and the remainder freezes into drifting crystals.
    ("03_moon",   "gloved hands tipping the same glass onto grey lunar dust under a pure black sky, "
                  "the water spraying outward in all directions in a fast expanding burst of fine "
                  "vapour and glittering ice crystals that drift on straight paths, the robot "
                  "watching. No rising steam, no smoke plume, no billowing cloud, no column of vapour",
                  "Fixed side-on shot, hard unfiltered sunlight, black airless sky, sharp shadows"),
    ("04_titan",  "gloved hands tipping the same glass onto a frozen orange-brown shore beside a "
                  "dark methane lake, the water hitting as solid ice, the robot watching",
                  "Fixed side-on shot, dim orange twilight, thick hazy air"),
    # Freezing water makes fine frost and irregular grains, never large clean geometric shards --
    # the first pass produced faceted crystal blocks that read as generated rather than physical.
    ("05_pluto",  "gloved hands tipping the same glass onto pale nitrogen ice under a black starry "
                  "sky, the water freezing into a fine powdery spray of tiny irregular frost grains "
                  "and small rough ice particles drifting down, the robot watching. No large crystals, "
                  "no geometric shards, no faceted gems, no sharp glass-like blocks",
                  "Fixed side-on shot, very dim distant sunlight, icy plain, fine powder snow"),
    ("06_verdict", "the same clear glass standing on a plain surface beside a small puddle of water, "
                   "with the small robot beside it looking at it",
                   "Fixed centred shot, neutral dark background, the glass lit clearly"),
]

def _s(key, sid, stem, secs, narration, motion, onscreen=""):
    return Scene(id=sid, image=stem, narration=narration, seconds=secs,
                 chips=_chips(key) if key else (), onscreen=onscreen, motion=motion)

SCENES = [
    # Opens on the SURPRISE, not the control. The shipped cut opened on "On Earth this is boring" and
    # made the viewer wait 3.80s for the first real result. Earth now lands second-to-last as the
    # reveal, and the close states the thesis instead of restating the premise.
    # Two hook beats at ~1.7s each: a claim still lands at 1.7s; three shots inside one second would
    # be noise, not retention.
    _s("mars", "hook_a", "01_mars", 1.7,
       "Same glass. Six worlds.",
       "the falling water bursting into vapour and frost at once as it leaves the glass",
       "WATER ON 6 WORLDS"),
    _s("venus", "hook_b", "02_venus", 1.9,
       "Only one leaves a puddle.",
       "the water flashing into vapour in mid-air before it reaches the ground",
       "ONLY ONE STAYS LIQUID"),
    _s("mars", "mars", "01_mars", 4.4,
       "Mars has too little air for liquid water. It boils and freezes at once.",
       "the water tearing into vapour and frost together, none of it landing as liquid"),
    _s("venus", "venus", "02_venus", 5.2,
       "Venus is the opposite. Ninety two bar pushes boiling to three hundred degrees, and the "
       "ground is hotter still.",
       "the water flashing to vapour in mid-air well before the ground"),
    _s("moon", "moon", "03_moon", 4.2,
       "The Moon has no air, so it boils away, and what is left freezes.",
       "the water bursting outward into vapour and glittering ice crystals as it falls"),
    _s("titan", "titan", "04_titan", 5.6,
       "Titan is the strange one. Thicker air than ours, so water boils higher. It still lands as "
       "rock. Minus one seventy nine.",
       "the water freezing solid as it falls and landing as a hard lump of ice"),
    _s("pluto", "pluto", "05_pluto", 4.0,
       "On Pluto it freezes before it lands, then vanishes to vapour.",
       "the water freezing into fine crystals mid-air and drifting onto nitrogen ice"),
    _s("earth", "earth", "00_earth", 3.4,
       "And Earth? It just pools.",
       "the stream of water falling from the glass and pooling normally on the ground"),
    _s(None, "verdict", "06_verdict", 5.0,
       "Across the solar system, ice and vapour are normal. The strange result was the puddle.",
       "the glass beside a small puddle of water, a last drop running down the inside",
       "THE WEIRD WORLD: EARTH"),
]

SIM = Simulation(
    slug="water_every_world",
    title="What If You Poured Water On Six Worlds",
    root="simulations/water_every_world",
    scenes=SCENES,
    # PARALLEL kind: the camera is locked on purpose. The variable is the world, not time.
    locked={"camera": "fixed side-on, locked off, identical framing every world",
            "glass": "the same clear tumbler, same fill level, same pour height",
            "pour": "identical pouring action every world",
            "robot": "the same small white-and-teal robot, watching, never touching"},
    style="Photoreal, grounded, natural light for that world. No text, no logos, no fantasy effects",
    source_aspect=1024 / 1536,
    speed=1.0,
    pad_s=0.16,
    target_s=(36.0, 46.0),
    meta={"kind": "parallel", "recurring_object": "glass of water",
          "instrument": "phase diagram", "direction": "parallel_experiment_v1",
          "control": "earth"},
)
