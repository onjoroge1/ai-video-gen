"""What Survives The Fall -- PARALLEL comparison with the SUBJECT as the variable.

This is the first topic in the bank that fixes the world and varies the subject instead of the other
way round. One ledge, one drop, five animals. That makes it markedly cheaper than an "every world"
video -- six unrelated environments become one, and the plates can share a look instead of fighting
for continuity across a comet and a swamp.

THE LOCKED CAMERA IS DOING THE WORK HERE, NOT THE OVERLAY.
Because the camera never moves, terminal velocity is directly readable as screen time: the ant steps
off and is still in frame drifting; the horse is gone before the eye catches it. The numbers confirm
what the shot already showed, which is the right order. A tracking camera would have destroyed this
by normalising every fall to the same apparent speed.

ONE HONEST DEVIATION FROM THE PRESET.
PARALLEL_EXPERIMENT_V1 asks for identical framing in every shot. Camera DISTANCE varies here, because
an ant and a horse cannot both be legible at one distance and an invisible subject compares nothing.
What is held identical is the composition and the datum: the same bare stone edge across the lower
third, the same drop beyond it, the same side-on angle. Declared rather than quietly done.
"""
from __future__ import annotations

from sim.spec import Scene, Simulation
from .physics import BY_KEY, FALL_M


def _chips(key):
    s = BY_KEY[key]
    return (s.name, f"~{s.v_at():.0f} m/s · {s.verdict()}")


CONTINUITY = (
    "The same bare grey stone ledge and the same enormous drop in every shot, photographed side-on "
    "from the same angle in the same flat overcast daylight. Only the animal standing on the edge "
    "changes. Photoreal wildlife photography, no people except where stated"
)

# ZERO_RULE + the fixed datum (sim/direction.py): the measured quantity is FALL SPEED, so the frame
# must contain the thing it is measured from -- the edge the subject leaves. Every plate names the
# ledge and puts the subject in contact with it. A plate of an animal already falling against sky
# would make speed a property of the caption.
PLATE_JOBS = [
    ("00_mouse", "a small brown house mouse standing right at the very edge of a bare grey stone "
                 "ledge at the top of a tall cliff, all four feet on the stone, whiskers out over the drop, the stone edge "
                 "running across the lower third of frame and a vast hazy drop beyond it",
                 "Fixed side-on macro, the ledge edge across the lower third, deep hazy air beyond"),
    ("01_ant", "a single black ant standing at the very edge of the same grey stone cliff ledge, all "
               "six legs on the stone, antennae out over the drop, the stone edge running across the "
               "lower third of frame and a vast hazy drop beyond it",
               "Fixed side-on extreme macro, the ledge edge across the lower third, hazy air beyond"),
    ("02_cat", "a tabby cat standing at the very edge of the same grey stone cliff ledge, all four "
               "paws on the stone, looking down over the drop, the stone edge running across the "
               "lower third of frame and a vast hazy drop beyond it",
               "Fixed side-on shot, the ledge edge across the lower third, deep hazy air beyond"),
    ("03_human", "a man in plain grey clothes standing at the very edge of the same grey stone cliff "
                 "ledge, both boots on the stone, looking out over the drop, the stone edge running "
                 "across the lower third of frame and a vast hazy drop beyond it",
                 "Fixed side-on shot, the ledge edge across the lower third, deep hazy air beyond"),
    ("04_horse", "a brown horse standing at the very edge of the same grey stone cliff ledge, all "
                 "four hooves on the stone, head out over the drop, the stone edge running across "
                 "the lower third of frame and a vast hazy drop beyond it",
                 "Fixed side-on shot, the ledge edge across the lower third, deep hazy air beyond"),
    ("05_ledge", "the same grey stone cliff ledge completely empty, photographed side-on, the stone "
                 "edge running across the lower third of frame with nine hundred metres of hazy air "
                 "and the distant ground far below beyond it",
                 "Fixed side-on shot, empty ledge edge across the lower third, the ground far below"),
    # --- MID-AIR and LANDING. The first cut ended every beat at the edge, so a video called "what
    # survives the fall" never showed a fall or a survivor. These carry the two acts that were
    # missing. The datum travels with the subject: in the air it is the cliff face and the ground
    # below, on landing it is the ground itself.
    # The human and horse landings are deliberately AFTERMATH, not impact -- settling dust on empty
    # rock. The point lands without depicting a body, and a graphic version would be both gratuitous
    # and unpublishable.
    ("06_ant_air", "a single black ant falling through open air far below a grey cliff edge, legs "
                   "splayed out, the rough grey cliff face passing behind it and hazy ground far "
                   "below",
                   "Fixed extreme macro, cliff face behind, hazy ground far below"),
    ("07_ant_land", "a single black ant standing unharmed on flat grey rocky ground at the base of a "
                    "cliff, walking away, tiny pebbles and dust around it",
                    "Fixed extreme macro on the ground at the base of the cliff"),
    ("08_mouse_air", "a small brown house mouse falling through open air below a grey cliff edge, "
                     "legs and tail splayed wide, the rough grey cliff face passing behind it and "
                     "hazy ground far below",
                     "Fixed macro, cliff face behind, hazy ground far below"),
    ("09_mouse_land", "a small brown house mouse standing unharmed on flat grey rocky ground at the "
                      "base of a cliff, shaking itself, dust around its feet",
                      "Fixed macro on the ground at the base of the cliff"),
    ("10_cat_air", "a tabby cat falling through open air below a grey cliff edge, legs spread wide "
                   "and belly down like a parachute, the rough grey cliff face passing behind it "
                   "and hazy ground far below",
                   "Fixed shot, cliff face behind, hazy ground far below"),
    ("11_cat_land", "a tabby cat crouched on all four paws on flat grey rocky ground at the base of "
                    "a cliff, unhurt and alert, a little dust settling around it",
                    "Fixed shot on the ground at the base of the cliff"),
    ("12_human_air", "a man in plain grey clothes falling through open air below a grey cliff edge, "
                     "arms and legs out, seen small and distant, the rough grey cliff face passing "
                     "behind him and hazy ground far below",
                     "Fixed wide shot, cliff face behind, hazy ground far below"),
    ("13_human_land", "empty flat grey rocky ground at the base of a tall cliff with fine dust still "
                      "hanging in the air, no people, no animals, nothing on the ground",
                      "Fixed wide shot of empty ground at the base of the cliff, dust in the air"),
    ("14_horse_land", "empty flat grey rocky ground at the base of a tall cliff with a large cloud "
                      "of dust still settling, no people, no animals, nothing on the ground",
                      "Fixed wide shot of empty ground at the base of the cliff, heavy settling dust"),
]


def _s(key, sid, stem, secs, narration, motion, onscreen="", prohibited=(), animate=True,
       empty_frame=False):
    return Scene(id=sid, image=stem, narration=narration, seconds=secs,
                 chips=_chips(key) if key else (), onscreen=onscreen, motion=motion,
                 prohibited=tuple(prohibited), animate=animate, empty_frame=empty_frame)


# STRUCTURE AFTER THE 48/100 REVIEW. Verified against the file before acting:
#   * a mountain goat, invented by the i2v model, walked through BOTH "empty" shots -- over the
#     HORSE 74 m/s chip and again behind the closing line. Empty scenes now carry no-wildlife
#     negatives, and the two goat clips are retired.
#   * one black frame at every cut (a per-shot fade-in in the renderer, now removed)
#   * the hook set up the location, not the contradiction, and the mouse appeared twice
#   * "size is the whole story" overclaimed -- our own physics module documents that m/A, not pure
#     scale, is the law. The closing line now matches the module.
#   * cat/human claims hedged; the horse number gets its spoken unit; Haldane gets an intro.
# The square-cube diagram scene gives the payoff claim its own picture, drawn by code.
SCENES = [
    # The hook is the CONTRADICTION, over the outcome footage: dust where the horse landed.
    _s(None, "hook", "14_horse_land", 4.6,
       "Gravity treats every animal the same. So why does the ant walk away from this fall, when "
       "the horse cannot?",
       "a heavy cloud of dust billows and drifts continuously over the empty rocky ground at the "
       "base of the cliff, thinning slowly",
       "ANT WALKS. HORSE DOESN'T.", prohibited=("animal", "goat", "deer", "wildlife", "creature", "person", "figure")),

    _s("ant", "ant_edge", "01_ant", 1.8,
       "The ant steps off.",
       "the ant at the stone edge waves its antennae over the drop and steps off, haze rolling "
       "continuously through the canyon beyond"),
    _s("ant", "ant_air", "06_ant_air", 3.2,
       "Drag caps it at about two metres per second.",
       "the ant drifts downward very slowly with its legs splayed, the cliff face creeping past "
       "behind it, dust motes turning continuously in the air"),
    _s("ant", "ant_land", "07_ant_land", 2.2,
       "It lands, and walks away.",
       "the ant walks steadily away across the rocky ground, its legs clearly stepping, small dust "
       "grains stirring continuously around it"),

    _s("mouse", "mouse_air", "08_mouse_air", 3.0,
       "A mouse falls five times faster than the ant.",
       "the mouse drops steadily with legs and tail splayed wide, its fur rippling hard, the cliff "
       "face streaming upward past it continuously"),
    _s("mouse", "mouse_land", "09_mouse_land", 2.4,
       "It hits, shakes itself, and leaves.",
       "the mouse lands on the rocky ground, shakes itself hard and trots away, dust drifting "
       "continuously around it"),

    _s("cat", "cat_edge", "02_cat", 2.0,
       "A cat spreads out like a parachute,",
       "the cat at the stone edge crouches and springs off, its fur rippling, cloud pouring "
       "continuously past the edge behind it"),
    _s("cat", "cat_air", "10_cat_air", 2.6,
       "and still reaches roughly twenty five.",
       "the cat falls belly-down with all four legs spread wide, the cliff face rushing past behind "
       "it continuously"),
    _s("cat", "cat_land", "11_cat_land", 3.0,
       "Cats sometimes survive falls like this. Many are left badly hurt.",
       "the cat lands on all four paws on the rock and rises alert, dust settling continuously "
       "around it"),

    _s("human", "human_edge", "03_human", 2.0,
       "You can spread out too.",
       "the man at the stone edge leans out over the drop and steps off, cloud pouring continuously "
       "past the lip and grit spilling down the rock face"),
    _s("human", "human_air", "12_human_air", 3.4,
       "It barely helps: about fifty three metres per second.",
       # Rejected twice at local 0.28/0.51: a small distant subject produces almost no pixel
       # change, same class as the comet shot. The motion has to live in the LARGE NEAR thing --
       # the rock face itself streaming upward -- with the man as the fixed point it streams past.
       "the entire rough rock face streams rapidly upward past the falling man, cracks and ledges "
       "of the cliff rushing up through the frame in a continuous blur, streamers of haze whipping "
       "upward around him, his clothes flapping hard"),
    _s("human", "human_land", "13_human_land", 2.2,
       "On bare rock, that is not survivable.",
       "small rocks and gravel bounce, roll and scatter across the rocky ground, a low sheet of "
       "dust rolling fast over the surface, debris raining down and kicking up grit where it lands", prohibited=("animal", "goat", "deer", "wildlife", "creature", "person", "figure")),

    _s("horse", "horse_edge", "04_horse", 2.6,
       "The horse reaches roughly seventy four metres per second.",
       "the horse at the stone edge shifts its weight and drops from the lip, dust blasting off the "
       "stone and cloud surging continuously past"),
    _s("horse", "horse_land", "14_horse_land", 3.4,
       "Biologist Haldane put it in one line: the horse splashes.",
       "small rocks and gravel bounce, tumble and come to rest on the ground as the heavy dust "
       "cloud rolls and billows continuously, debris still raining down through it", prohibited=("animal", "goat", "deer", "wildlife", "creature", "person", "figure")),

    # The payoff claim gets its own picture: the square-cube diagram, code-drawn. Spoken over an
    # animal it was the only claim in the video with no visual; here the visual IS the claim.
    _s(None, "sqcube", "15_sqcube", 4.2,
       "Double the size: eight times the mass, only four times the area.",
       # animated by hotd.reveal -- the diagram assembles band by band, which IS the claim landing.
       # Deterministic and free; the clip sits in work/clips/sqcube.mp4 and the provider never runs
       # for this scene because the reuse path finds it first.
       "", ""),

    # Loop back to the opening contradiction: the ant, walking away. "Size drives the pattern"
    # replaces "size is the whole story" -- our own physics module refutes the stronger claim.
    _s("ant", "loop", "07_ant_land", 3.6,
       "Size sets the pattern. Posture bends it. The ant just walks away.",
       "the ant walks steadily away across the rocky ground toward the horizon, dust grains "
       "stirring continuously around it",
       "SMALL HITS SOFT"),
]

SIM = Simulation(
    slug="survives_the_fall",
    title="Why An Ant Survives A 900m Fall But A Horse Does Not",
    root="simulations/survives_the_fall",
    scenes=SCENES,
    locked={"camera": "fixed side-on, locked off, the stone edge across the lower third every shot",
            "ledge": f"the same bare grey stone ledge and the same {FALL_M:.0f} m drop in every shot",
            "action": "the subject steps off the edge under its own power; nothing pushes it",
            "framing": "composition and datum identical; camera DISTANCE scales so each animal "
                       "reads at its true size (see module docstring)"},
    style="Photoreal wildlife and nature photography, flat overcast daylight, no text, no logos",
    source_aspect=1024 / 1536,
    speed=1.0, pad_s=0.16,
    target_s=(38.0, 54.0),   # 15 shots inside it: a new image every ~2.7s
    meta={"kind": "parallel", "recurring_object": "the cliff",
          "instrument": "terminal velocity and impact energy",
          "direction": "parallel_experiment_v1", "control": "human", "review_baseline": "48/100 external review, 2026-08-10",
          "datum": ("ledge", "edge", "ground", "cliff"), "badge": "SAME LEDGE"},
)
