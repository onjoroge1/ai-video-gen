"""What If You Got 1mph Faster Every Second? -- GROUNDED HUMAN ESCALATION V1.

The arithmetic is real and is the spine of the piece: v(t) = t mph. Four minutes in he is at
240 mph; ten minutes in he is at 600, faster than an airliner. Nothing is invented -- the chips
just read the clock.

Direction, applied:
  ANGLE    one protagonist (Adam), one recurring object (the paper coffee cup), one metaphor (the
           cup is the only thing that records what is happening to him). Every beat is caused by
           the previous one.
  OPEN     the consequence is already happening in frame one -- he cannot stop walking -- and the
           personal stake lands before any explanation.
  BUILD    coffee spills -> he overshoots his own door -> he passes his daughter -> the cup is
           torn away -> he is gone. Straight line, no branches.
  NEVER    identity, wardrobe, location and style are pinned by CONTINUITY, repeated verbatim into
           every plate prompt. No abstract force made physical. Bolt never causes anything.
"""
from __future__ import annotations

from sim.spec import Scene, Simulation

ROOT = "simulations/one_mph_faster"
PLATES = f"{ROOT}/plates"

# Character reference. generate_image switches to image-edit mode when this is passed, so the SAME
# person appears in every plate. Verified on a two-plate test (one wide, one close): face, jacket,
# tee, jeans and sneakers all transferred, and the staging did NOT collapse toward the reference's
# framing -- the wide stayed wide and the close stayed close.
REFERENCES = ["assets/mascot/human-model.png"]

# Repeated VERBATIM into every plate prompt. This is the anti-drift mechanism: the caller never
# re-describes his, so no scene can quietly restyle his.
CONTINUITY = (
    "Cinematic photoreal frame, grounded realism, natural light, believable real-world environment. "
    "The same man throughout: Adam, early thirties, short dark brown hair, light stubble, navy "
    "zip-up jacket open over a light grey t-shirt, dark indigo jeans, dark grey sneakers. He carries "
    "the same white paper takeaway coffee cup with a brown cardboard sleeve. The same ordinary city "
    "street at grey dawn: wet asphalt, low brick shopfronts, parked cars, bare street trees. A small "
    "friendly white-and-teal robot the size of a toddler stands nearby watching him, never touching "
    "him and never causing anything"
)

# (stem, action, shot) -- ACTION only. Continuity is added by sim.plates.
PLATE_JOBS = [
    ("00_cold_open", "Adam leans backwards at a hard angle trying to stop walking, both heels "
                     "skidding on the wet asphalt, face tight with alarm; coffee streams sideways "
                     "out of the cup in his hand instead of falling straight down",
     "Wide side-on shot, he is mid-street, motion blur on his feet only"),
    ("01_the_rule",  "Adam looks down at his own legs, which are walking faster than he is "
                     "choosing to, his free hand out for balance; the coffee in the cup is tilted "
                     "hard toward the back of the cup",
     "Medium shot from the side, the small robot watching from the pavement"),
    ("02_her_door",  "Adam stretches his arm out toward a blue front door as he is carried past "
                     "it, fingers missing the handle by inches, his keys swinging from his other "
                     "hand; the cup lid has popped off and is gone",
     "Tracking side-on shot, the door already behind him"),
    ("03_the_gate",  "Adam turns his head to look back at a small girl in a yellow raincoat "
                     "standing at a school gate with one hand raised; Adam is already far past "
                     "his, reaching backwards; the paper cup is crushed and buckling in his grip",
     "Wide shot, the girl small in the background, Adam in the foreground going the other way"),
    ("04_the_edge",  "Adam at the edge of the city where the shopfronts end, coat snapping "
                     "violently, hair whipped flat, eyes streaming; the paper cup is "
                     "shredding apart, torn paper peeling off it in his hand",
     "Low wide shot, empty road ahead, the last buildings behind him"),
    ("05_gone",      "An empty stretch of open road at dawn with nobody on it, the crushed white "
                     "paper cup lying alone on the wet asphalt in the foreground, a long faint "
                     "scuff mark on the road leading away toward the horizon",
     "Wide static shot, no people in frame at all"),
    ("06_the_cup",   "The small white-and-teal robot crouches on the empty road and picks up the "
                     "crushed paper cup with both hands, looking off toward the horizon",
     "Low close shot on the robot and the cup, the empty road behind"),
]

SPEED_AT = lambda t: t          # v(t) = t mph, by construction

SCENES = [
    Scene(id="cold_open", image="00_cold_open", seconds=4.0,
          narration="Four minutes ago Adam walked out for coffee. He has not stopped since.",
          chips=("00:04:00", "240 MPH"), onscreen="SHE CANNOT STOP"),
    Scene(id="the_rule", image="01_the_rule", seconds=4.0,
          narration="Every second, he gets one mile per hour faster. That is the whole rule.",
          chips=("THE RULE", "+1 MPH / SEC")),
    Scene(id="her_door", image="02_her_door", seconds=4.0,
          narration="At one minute he was jogging. He just passed his own front door at the speed of a car.",
          chips=("00:02:00", "120 MPH")),
    Scene(id="the_gate", image="03_the_gate", seconds=5.0,
          narration="His daughter waits at the school gate. Adam has time to turn his head. Not to stop.",
          chips=("00:03:00", "180 MPH"), onscreen="SHE HAD TIME TO LOOK"),
    Scene(id="the_edge", image="04_the_edge", seconds=5.0,
          narration="By ten minutes he is faster than an airliner. The air starts taking things from him.",
          chips=("00:10:00", "600 MPH")),
    Scene(id="gone", image="05_gone", seconds=4.0,
          narration="Every second that passes makes stopping less survivable than continuing.",
          chips=("00:14:00", "840 MPH"), onscreen="NO WAY BACK"),
    Scene(id="the_cup", image="06_the_cup", seconds=4.5,
          narration="An hour in, he is at thirty six hundred miles an hour. This is all that is left.",
          chips=("01:00:00", "3600 MPH")),
]

SIM = Simulation(
    slug="one_mph_faster",
    title="What If You Got 1mph Faster Every Second?",
    root=ROOT,
    scenes=SCENES,
    # gpt-image-2 has no 9:16 size; plates are 2:3 and the renderer centre-crops.
    # Declared so inventory reports the 15.6% width loss instead of failing or hiding it.
    source_aspect=1024/1536,
    locked=("Locked-off camera unless stated. The same man, wardrobe, street and cup in every "
            "shot. Grounded realism; the only unusual thing in frame is what is happening to him."),
    style="Photoreal cinematic, grey dawn city, natural light, handheld-documentary restraint",
    voice="echo", speed=1.0, pad_s=0.16,
    W=1080, H=1920, fps=30,
    target_s=(28.0, 42.0), max_gap_s=3.3,
    meta={"protagonist": "Adam", "recurring_object": "white paper coffee cup",
          "direction": "GROUNDED HUMAN ESCALATION V1"},
)


# Per-plate ambient motion. The world and his body may move; nothing may be added or transformed.
AMBIENT = {
    "00_cold_open": "his jacket flapping hard, coffee streaming sideways out of the "
                    "cup, spray lifting off the wet road, the robot's head turning to follow him",
    "01_the_rule":  "his legs striding, jacket swinging, breath visible in the cold, light rain "
                    "drifting, the robot watching from the pavement",
    "02_her_door":  "his arm stretching toward the door as he is carried past, coat flaring, keys "
                    "swinging, wet road spray behind his heels",
    "03_the_gate":  "his head turning to look back, jacket streaming, the small girl in yellow "
                    "lowering her raised hand, rain drifting across the street",
    "04_the_edge":  "his jacket snapping violently in the wind, hair flattened, torn paper "
                    "peeling off the cup and flying away, cloud moving fast overhead",
    "05_gone":      "the crushed paper cup rocking slightly in the wind on the empty wet road, "
                    "cloud moving, a puddle rippling, no people anywhere",
    "06_the_cup":   "the robot lifting the crushed cup and turning its head toward the horizon, "
                    "light rain falling, cloud moving overhead",
}
