"""What If It Rained On Every World -- PARALLEL comparison, and the first topic chosen FOR the
engine rather than adapted to it.

Every scar the engine carries is structurally absent here:
  * no empty frames (rain fills them) -- the nine-goat failure class cannot occur
  * no small, slow or distant subject -- rain is everywhere and falling is what i2v does best
  * no exit rule risk -- rain cannot leave frame
  * no character continuity -- the recurring object is the rain and the surface it strikes

The verdicts are VISIBLE, not asserted: Titan's rain falls in slow motion because it computes slow,
Venus's dissolves mid-air, Mars's clouds never deliver. The chips confirm what the eye already saw,
which is the strongest property a shot in this format can have.
"""
from __future__ import annotations

from sim.spec import Scene, Simulation
from .physics import BY_KEY, verdict


def _chips(key):
    w = BY_KEY[key]
    if not w.can_rain or w.key in ("venus", "jupiter"):
        return (w.name, verdict(w))
    return (w.name, f"~{w.d_max*1000:.0f} mm drops · ~{w.v_term:.0f} m/s · {verdict(w)}")


CONTINUITY = (
    "The same man in every ground shot: a dark navy jacket, grey shirt and dark jeans, standing "
    "alone among the rocks seen from behind at a distance, small against the sky, looking up at "
    "the weather. Identical man, identical clothes, identical stance in every shot that contains "
    "him. Broken rocky foreground in the lower quarter of frame, a towering storm sky above. "
    "Photoreal, documentary weather photography, natural light for that world. No other people, "
    "no animals, no buildings"
)

# Jupiter is deliberately UNMANNED: there is nothing to stand on, and the figure's absence in the
# one world with no ground is the composition making the beat's argument.

# ZERO RULE: the measured question is DOES THE RAIN REACH THE GROUND, so the landing surface (or,
# for Jupiter, its explicit absence -- cloud decks below, no floor) must be in frame in every shot.
PLATE_JOBS = [
    ("00_titan", "orange-brown methane rainstorm on Titan: enormous dark raindrops falling in "
                 "slow streaks through thick hazy orange air onto a frozen rocky plain, the same "
                 "man in a navy jacket standing among the rocks seen from behind, small in the "
                 "middle distance looking up at the huge falling drops, the wet rocky ground "
                 "running across the lower quarter of frame, dim orange light",
                 "Fixed wide shot, ground across the lower quarter, heavy slow rain above"),
    ("01_earth", "a grey rainstorm on Earth: sheets of rain falling from a dark storm cloud onto "
                 "a broken rocky plain, the same man in a navy jacket standing among the rocks "
                 "seen from behind in the middle distance looking up into the rain, the wet "
                 "rocky ground across the lower quarter of frame, puddles forming among the rocks",
                 "Fixed wide shot, ground across the lower quarter, rain falling through frame"),
    ("02_mars", "thin white water-ice clouds high in a pink-brown Martian sky over a dry red "
                "rocky plain, a tall thin dust devil column rising from the plain in the middle "
                "distance, the same man in a navy jacket standing on the dry ground seen from "
                "behind watching the dust devil, the dusty ground across the lower quarter of "
                "frame, completely dry, no rain at all, sharp dry sunlight",
                "Fixed wide shot, dry ground across the lower quarter, clouds high above"),
    ("03_venus", "dense yellow-grey sulfuric acid clouds over Venus: dark streaks of rain falling "
                 "from the cloud base and fading away to nothing in the hot haze high above the "
                 "ground, the same man in a navy jacket standing on the baked cracked surface "
                 "seen from behind looking up at the rain that never arrives, the dry cracked "
                 "ground across the lower quarter of frame",
                 "Fixed wide shot, dry baked ground across the lower quarter, rain fading mid-air"),
    ("04_jupiter", "inside Jupiter's atmosphere: colossal towering ammonia cloud walls in brown "
                   "and cream, dark rain falling from an upper cloud deck down past the camera "
                   "toward endless cloud layers far below, no ground anywhere, only deeper cloud "
                   "decks below",
                   "Fixed wide shot from within the cloud canyon, rain falling toward cloud decks "
                   "below"),
    ("05_board", "the same frozen rocky plain on Titan under heavy slow methane rain, the same man "
                 "in a navy jacket standing among the wet rocks seen from behind with his hand "
                 "held out to catch a huge slow raindrop, wet rocky ground across the lower "
                 "quarter of frame, dim orange haze",
                 "Fixed wide shot, ground across the lower quarter, slow heavy rain"),
]


def _s(key, sid, stem, secs, narration, motion, onscreen="", prohibited=(), animate=True):
    return Scene(id=sid, image=stem, narration=narration, seconds=secs,
                 chips=_chips(key) if key else (), onscreen=onscreen, motion=motion,
                 prohibited=tuple(prohibited), animate=animate)


# Manned scenes ban only WILDLIFE -- banning "person, figure" while the prompt asks for a man is a
# negative fighting its own positive. Jupiter, the unmanned world, keeps the full ban.
NO_ANIMALS = ("animal", "creature", "bird", "wildlife", "second person, crowd")
NO_LIFE = ("animal", "person", "figure", "creature", "bird", "wildlife")

SCENES = [
    # Open on the surprise: the dodgeable raindrop. Titan is also the closer, so the video loops.
    _s("titan", "hook", "00_titan", 4.4,
       "On one world, raindrops grow twice the size of Earth's biggest, and fall slowly enough "
       "to dodge.",
       "heavy dark raindrops falling continuously through the orange haze, new drops entering "
       "from the top of frame for the entire shot, each impact bursting on the wet rocks with a "
       "visible splash, the man's jacket moving in the wind as he watches, puddle surfaces "
       "rippling constantly, haze rolling throughout",
       "RAIN YOU COULD DODGE", prohibited=NO_ANIMALS),
    _s("earth", "earth", "01_earth", 3.6,
       "On Earth a drop can only reach six millimetres. Any bigger, the air tears it apart.",
       "successive curtains of rain falling across the rocky plain, one band after another for "
       "the whole shot, drops striking the puddles and splashing throughout, the man standing "
       "still in the rain with his jacket flapping, the storm cloud churning slowly overhead", prohibited=NO_ANIMALS),
    _s("mars", "mars", "02_mars", 4.2,
       "Mars has clouds of water ice. But its air is too thin and too cold for rain. The clouds "
       "can never deliver.",
       "the dust devil spinning continuously in mid-frame, pulling a swirling column of dust off "
       "the dry ground, wind gusts raking streams of sand past the man's legs as he watches, "
       "thin white clouds moving overhead throughout", prohibited=NO_ANIMALS),
    _s("venus", "venus", "03_venus", 4.6,
       "Venus's clouds drizzle sulfuric acid. Every drop evaporates about thirty kilometres up. "
       "Not one survives the fall.",
       "curtains of dark rain streaks continuously falling from the yellow cloud base, each "
       "streak evaporating in mid-air while new streaks keep forming above it for the entire "
       "shot, the cloud base churning throughout, heat haze shimmering around the man standing "
       "on the cracked ground looking up",
       prohibited=NO_ANIMALS),
    _s("jupiter", "jupiter", "04_jupiter", 4.4,
       "Jupiter has no ground at all. Its rain just falls until the heat vaporises it. Forever.",
       "from a fixed vantage, dark rain streaks descending past the towering cloud walls, the "
       "walls churning and rolling continuously, deeper cloud decks sliding slowly far below",
       prohibited=NO_LIFE),
    _s("titan", "titan", "00_titan", 5.0,
       "Titan is the prize: thick air, weak gravity, and methane drops up to a centimetre wide, "
       "falling at a brisk walking pace.",
       "huge dark raindrops descending in slow motion, new drops entering at the top of frame "
       "throughout, each bursting on the rocks with a visible splash, the man turning slowly to "
       "watch one drop fall past him, ripples crossing the puddles constantly", prohibited=NO_ANIMALS),
    _s("titan", "close", "05_board", 4.2,
       "The air sets the size. Gravity sets the speed. And today, rain lands on only two of "
       "these worlds.",
       "the slow methane rain falling steadily with new drops entering from the top of frame, "
       "the man holding out his hand as a huge drop bursts across it, drops bursting on the wet "
       "rocks, orange haze rolling through the frame throughout",
       "ONLY 2 WORLDS HEAR RAIN", prohibited=NO_ANIMALS),
]

SIM = Simulation(
    slug="rain_every_world",
    title="What If It Rained On Every World",
    root="simulations/rain_every_world",
    scenes=SCENES,
    locked={"camera": "fixed wide shot, locked off, the landing surface across the lower quarter",
            "framing": "storm sky above, ground (or cloud deck below, for Jupiter) in frame -- the "
                       "question is always whether the rain reaches it",
            "subject": "the rain, and the same lone man watching it (absent only on Jupiter, which has nowhere to stand); no animals, no structures"},
    style="Photoreal documentary weather photography, natural light for that world. No text, no "
          "logos, no fantasy effects",
    source_aspect=1024 / 1536,
    speed=1.0, pad_s=0.16,
    target_s=(36.0, 50.0),
    meta={"kind": "parallel", "recurring_object": "the rain",
          "instrument": "drop size and fall speed",
          "direction": "parallel_experiment_v1", "control": "earth",
          "datum": ("ground", "rock", "surface", "cloud deck"), "badge": "RAIN",
          # impact audio exists ONLY on the worlds where rain reaches the ground: the close line
          # says "rain lands on only two of these worlds" and the mix is the proof of it
          "sfx": {"earth_rain": ["earth"], "titan_rain": ["hook", "titan", "close"]}},
)
