"""Creative direction as structure, not prose.

A direction arrives as a written brief -- "one protagonist, one recurring object, every beat caused by
the previous, never reset identity, never turn abstract words into fantasy tools". Most of it was
being enforced by whoever happened to be paying attention.

Each clause actually belongs to a different mechanism, and this module routes them:

    identity, wardrobe, location, style   -> CONTINUITY text + a character reference image
                                             (already enforced by construction in sim/plates.py)
    no fantasy tools, no malformed anatomy -> prohibits, injected into prompt + provider negative
    look and register                      -> the style block, injected verbatim
    one protagonist, recurring object,
    causal chain, open on consequence      -> check(), which is what did not exist

check() is deliberately mechanical and honest about its limits. It returns hard failures for the
things a string can decide, and REVIEW items for the things it cannot -- rather than pretending a
keyword scan can judge whether beat 4 is caused by beat 3. A check that guesses is worse than no
check, because it launders an unverified assumption into a green tick.

MOTION IS PART OF THE DIRECTION. A preset declares the motion mode its content needs. The 1mph video
was rendered through the "ambient" i2v mode, whose prompt prefix reads "Subtle, restrained motion...
very slow gentle drift" -- a video about accelerating to 3,600 mph was explicitly prompted to be slow
and to hold the camera still. That is why it looked like slow motion and why the speed never read.
A direction that says "escalation" must not silently inherit a motion mode that says "restrained".
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

# Words that turn an abstract idea into a fantasy object. The direction bans these outright; they are
# also the exact failure that produced a glowing sci-fi comet when the brief said "a bullet".
FANTASY = ("magic", "magical", "glowing energy", "energy wave", "force field", "shield", "laser",
           "beam", "aura", "portal", "lightning bolt", "shockwave", "spirit", "ghostly", "ethereal",
           "levitat", "telekine", "superpower", "supernatural")

ANATOMY = ("extra limbs", "deformed", "malformed", "distorted face", "melted", "morphing",
           "duplicated person", "second head", "extra fingers")


@dataclass
class Direction:
    """A named, versioned creative direction with the machinery to enforce it."""
    name: str
    look: str                                   # injected verbatim into every plate prompt
    prohibits: tuple                            # prose bans, appended to the prompt
    negative: str                               # provider negative_prompt fragment
    motion_mode: str = "ambient"                # i2v motion style this direction's content needs
    requires: dict = field(default_factory=dict)  # structural rules, checked by check()

    def prohibit_text(self):
        return " ".join(p.rstrip(".") + "." for p in self.prohibits)


GROUNDED_HUMAN_ESCALATION_V1 = Direction(
    name="GROUNDED HUMAN ESCALATION V1",
    look=("Grounded cinematic realism, natural human behaviour, believable real-world environment, "
          "natural light. The guide is small and consistent; the human carries the emotion"),
    prohibits=(
        "No magic, no glowing energy, no waves, no shields, no lasers, no fantasy effects",
        "Nothing abstract is turned into a physical object",
        "No malformed anatomy, no extra limbs, no duplicated person, no morphing",
        "No uncontrolled whole-frame transformation; only the recurring object may change",
        "The guide never causes the event and never touches the protagonist",
        "No text, no letters, no numbers, no logos, no watermark",
    ),
    negative=("magic, glowing energy, energy wave, force field, shield, laser, beam, aura, "
              "deformed, malformed, extra limbs, extra fingers, duplicated person, morphing, "
              "warping, style change, cartoon, illustration, anime, "
              "text, letters, numbers, watermark, logo, subtitles"),
    # Escalation content needs travel, not restraint. Inheriting "ambient" is what made a video about
    # acceleration play as slow motion with a locked camera.
    motion_mode="travel",
    requires={
        "one_protagonist": True,
        "recurring_object": True,       # must appear in every beat so change is measurable
        "open_on_consequence": True,    # first beat shows the effect, not the cause
        "causal_chain": True,           # each beat results from the previous (REVIEW, not mechanical)
        "no_identity_reset": True,      # enforced upstream by CONTINUITY + reference image
        # Escalation needs the datum LADDER, not a fixed datum: the reference changes as the
        # magnitude grows. Declare meta["datum_axis"] and Scene.magnitude and datum_check bands it.
        "zero_in_frame": True,
    },
)


# ---------------------------------------------------------------------------------------------
# THE ZERO RULE. If a video MEASURES a quantity, the frame must contain that quantity's zero.
#
# Three separate defects, one cause, each found by a human watching the finished file:
#   * the bullet appeared mid-sky instead of leaving the barrel -- no origin, so "same gun" was
#     unverifiable
#   * each world's arc was fitted to its own frame, so 3 km and 458 km looked identical -- fixed by
#     drawing an explicit scale bar whose UNIT changes per world
#   * every jump plate was written "caught high in the air" / "mid-hop", so no shot contained the
#     ground -- apparent height became a property of framing rather than of gravity
#
# The measured quantity needs a visible datum IN FRAME: the muzzle for a projectile, the ground for a
# jump, a ruler for a distance. Without it the viewer is asked to trust the number instead of reading
# it, which is the opposite of what a controlled experiment is for.
#
# Applies to the PLATE prompt, not just the motion prompt -- a clip can only animate what the picture
# already contains, and no i2v instruction can add a horizon that was never generated.
ZERO_RULE = ("The frame must show the reference the measurement starts from: the ground under a jump, "
             "the muzzle of a launcher, the rim of a container. The subject begins AT that datum, in "
             "contact with it, not already mid-flight")

# ---------------------------------------------------------------------------------------------
# THE DATUM LADDER. The zero rule above is written for a FIXED datum -- the ground stays the ground
# for every world in a parallel comparison. An escalation has no such luxury: the reference itself
# changes as the magnitude grows, and demanding "show the ground" at 100 km asks the generator for a
# picture that cannot exist.
#
# Get this wrong in either direction and the measurement stops being readable:
#
#   * ask for ground detail too high  -> rooftops at 30 km. The generator will happily draw it, and
#     the altitude silently becomes a property of the caption rather than the image.
#   * ask for curvature too low       -> a curved horizon at 300 m, which reads as space and throws
#     away every beat below it, because the viewer has already arrived.
#   * ask for nothing at all          -> consecutive beats become interchangeable. This is the real
#     failure mode of the escalation format: without a datum the climb is a cut, not a measurement.
#
# So the datum is banded. Each band names the cues that are TRUE at that magnitude, and the check
# both requires one from the right band and rejects cues borrowed from a distant band.
#
# Bands are (lo, hi, label, cues). lo is inclusive, hi exclusive, hi=None means open-ended.
DATUM_LADDER = {
    "altitude_m": [
        (0, 150, "ground detail",
         ("ground", "grass", "rooftop", "treetop", "trees below", "the field below", "launch pad",
          "people below", "pavement", "runway")),
        (150, 2_000, "ground pattern",
         ("fields below", "patchwork", "roads as lines", "river below", "cars as dots",
          "the town below", "streets below", "farmland below")),
        (2_000, 12_000, "horizon line",
         ("horizon", "flat horizon", "cloud tops", "cloud layer below", "haze band",
          "the land as a flat map", "above the clouds")),
        (12_000, 50_000, "darkening sky",
         ("dark blue sky above", "black sky above", "thin band of atmosphere", "the horizon far below",
          "cloud deck far below", "the sky turning black")),
        (50_000, 400_000, "curved horizon",
         ("curved horizon", "curvature of the earth", "the curve of the planet", "thin blue line",
          "blue limb", "black sky", "the edge of the atmosphere")),
        (400_000, None, "the whole disc",
         ("the whole planet", "the disc of the earth", "the limb of the planet", "full disc",
          "the planet below as a sphere")),
    ],
    # Depth is the mirror problem and worse: below the photic zone there is genuinely nothing to see,
    # which is exactly why real deep-sea footage always keeps a light cone, a tether or the vehicle's
    # own hull in frame. The datum has to be CARRIED down, because the world stops supplying one.
    "depth_m": [
        (0, 10, "the surface above",
         ("the surface above", "sunlight shafts", "bright surface", "the hull above", "the boat above",
          "waves overhead", "swimming down from the surface")),
        (10, 60, "draining colour",
         ("dim blue", "the surface as a bright ceiling", "colour draining", "blue-green gloom",
          "fading daylight", "the surface far above")),
        (60, 200, "the dive light",
         ("dive light", "torch beam", "twilight", "the surface gone", "gloom", "a cone of light")),
        (200, 1_000, "marine snow",
         ("marine snow", "black water", "the lights of the vehicle", "particles drifting in the beam",
          "only the lamp", "total darkness beyond the beam")),
        (1_000, None, "the vehicle itself",
         ("the submersible hull", "manipulator arm", "viewport", "the vehicle's lamps",
          "the sub's lights", "instrument glow", "the hull in frame")),
    ],
    # Speed has no datum of its own -- a subject alone in frame at 10 m/s and 300 m/s looks identical.
    # It has to be read against something FIXED that the subject passes.
    "speed_ms": [
        (0, 15, "passing detail",
         ("fence posts", "kerb", "roadside grass", "a walker passing", "lane markings")),
        (15, 100, "streaking foreground",
         ("streaking foreground", "blurred verge", "poles flashing past", "motion blur on the roadside",
          "the road rushing under")),
        (100, None, "a fixed far reference",
         ("distant mountains holding still", "the horizon steady while the foreground tears past",
          "ground streaked to lines", "a fixed far ridge")),
    ],
}


def datum_band(axis, magnitude):
    """The band a magnitude falls in, or None if the axis or value is unknown."""
    for i, (lo, hi, label, cues) in enumerate(DATUM_LADDER.get(axis, [])):
        if magnitude >= lo and (hi is None or magnitude < hi):
            return i, label, cues
    return None

# ---------------------------------------------------------------------------------------------
# RULES FROM THE RAIN NEGATIVE VALIDATION (55 findings, 5 lenses -- tool-results/b5havgc9k.txt).
# Each of these is a failure class that SHIPPED because nothing owned it. The one-off frame fixes
# stay in that file; what lives here is only what makes the next video unable to repeat them.

# The model equates "dramatic burst" with explosion vocabulary. A 12 mm drop carries about a
# tablespoon; the shipped video gave it a body-height geyser and a building-scale cauliflower
# plume, brighter than the sky that supposedly lit it. Ejecta can never exceed what arrived.
SPLASH_RULE = ("A splash redistributes only the liquid that arrived: no geysers, no plumes, no "
               "mushroom clouds, no smoke, no explosions. A small drop makes a small crown")
SPLASH_BANNED = ("geyser", "plume", "mushroom", "explosion", "erupt", "eruption", "pyroclastic",
                 "smoke", "blast")

# i2v drifts away from the plate's phenomenon over the clip: the virga existed in one of three
# sampled frames of the very beat whose caption said EVAPORATES MID-AIR. A claim is only shown if
# the motion prompt RENEWS it for the full shot -- the same class as the exit rule, applied to
# phenomena instead of subjects.
RENEWAL_TERMS = ("throughout", "continuously", "for the entire shot", "for the whole shot",
                 "constantly", "keeps ", "the whole time", "new drops entering", "one band after "
                 "another", "keep forming")

# Reactions shipped as stock poses: a flinch facing away from the burst, a relaxed sun-visor
# "salute" against stinging dust, a palm impact with no blink and no wrist give. A reaction is
# legible only as a stimulus -> vector -> response chain, so a prompt that names a reaction must
# also name what it reacts to and where the body points.
REACTION_VERBS = ("flinch", "recoil", "shield", "dodge", "duck", "wince", "brace", "startl",
                  "steps aside", "step aside", "jump back", "jumps back")
STIMULUS_NOUNS = ("drop", "burst", "splash", "rain", "dust", "wind", "gust", "spray", "impact",
                  "grit", "sand", "streak")
VECTOR_TERMS = ("toward", "away from", "eyes on", "eyes snap", "watching", "tracking", "looking at",
                "turns from", "turned away", "into the", "at the")

# Reference conditioning imports the reference's STUDIO LIGHTING along with the wardrobe: the same
# man read clean neutral-white on Titan (all-orange ambient), Venus (sulfur yellow) and Mars (no
# shadow at all, beside pebbles casting crisp ones). Plates that contain the figure must NAME his
# lighting and his contact shadow, because a named thing is what the generator draws.
INTEGRATION_RULE = ("The person is lit by this scene's own ambient light -- their skin and clothes "
                    "carry its colour cast -- and a soft contact shadow pools under their feet")
INTEGRATION_TERMS = ("contact shadow", "ambient light", "colour cast", "color cast", "scene's light",
                     "lit by the")
# Matched with word boundaries: "he " as a substring lives inside "the ", which made every plate
# read as person-bearing and flagged the two deliberately unmanned ones.
PERSON_RE = re.compile(r"\b(man|woman|person|figure|he|she|his|her)\b")


PARALLEL_EXPERIMENT_V1 = Direction(
    name="PARALLEL EXPERIMENT V1",
    look=("Photoreal, grounded, natural light for that condition. Identical framing, identical "
          "subject, identical action in every shot; only the condition changes"),
    prohibits=(
        "No magic, no glowing energy, no fantasy effects",
        "The camera does not move: fixed, locked off, identical framing in every shot",
        "The subject and the action are identical in every shot; only the world changes",
        "No malformed anatomy, no extra limbs, no duplicated subject, no morphing",
        "No text, no letters, no numbers, no logos, no watermark",
        ZERO_RULE,
        SPLASH_RULE,
    ),
    negative=("mid-air start, already airborne, floating, no ground visible, "
              "camera pan, camera zoom, camera shake, moving camera, cut, "
              "magic, glowing energy, fantasy effect, "
              "explosion, mushroom cloud, geyser, pyroclastic plume, smoke plume, "
              "deformed, malformed, extra limbs, extra hands, duplicated subject, morphing, "
              "cartoon, illustration, anime, text, letters, numbers, watermark, logo"),
    # The camera is LOCKED here on purpose: the variable is the condition, not time. This is the
    # opposite invariant to the escalation preset, and conflating the two is what forked `locked`
    # into a dict in one topic and a str in the other.
    motion_mode="action",
    requires={
        "recurring_object": True,
        "verdict_per_beat": True,      # each condition must produce a distinct visible outcome
        "open_on_surprise": True,      # the FIRST beat may not be the control
        "zero_in_frame": True,         # the measured quantity's datum must be visible -- see ZERO_RULE
        "no_identity_reset": True,
    },
)

PRESETS = {"grounded_human_escalation_v1": GROUNDED_HUMAN_ESCALATION_V1,
           "parallel_experiment_v1": PARALLEL_EXPERIMENT_V1}


def get(name):
    key = (name or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key not in PRESETS:
        raise KeyError(f"unknown direction {name!r}; have {sorted(PRESETS)}")
    return PRESETS[key]


# ------------------------------------------------------------------ the structure check
# Words that signal a beat is EXPLAINING rather than showing a consequence. The direction says state
# the personal stake before explaining the cause, so these in beat one are a failure.
_EXPLAINER = ("every second", "the rule is", "that is the whole rule", "because", "which means",
              "the reason", "here is why", "it works like")


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def check(sim, direction, recurring_object=None, protagonist=None, plate_jobs=None):
    """Validate a simulation against a direction. -> dict with failures, reviews and measurements.

    `plate_jobs` is the (stem, action, shot) list that describes what is actually IN each picture.
    Without it this check reported the recurring object missing from all seven beats of a video in
    which it appears in all seven -- because Scene carries narration and motion, not the plate action.
    A scene has no field for "what is in frame", which is itself the gap that let a declared
    empty-road shot render with the protagonist still in it.

    FAILURES are mechanical and certain. REVIEWS are things only a reader can judge; they are listed
    explicitly so they are consciously waived rather than silently skipped.
    """
    scenes = list(sim.scenes)
    fails, reviews, notes = [], [], {}
    req = direction.requires

    obj = (recurring_object or (sim.meta or {}).get("recurring_object") or "").strip().lower()
    who = (protagonist or (sim.meta or {}).get("protagonist") or "").strip()

    # --- recurring object: it is the measuring stick, so it must be in every beat's imagery
    if req.get("recurring_object"):
        if not obj:
            fails.append("no recurring_object declared: nothing for the viewer to measure change against")
        else:
            head = obj.split()[-1]                      # 'coffee cup' -> 'cup'
            by_stem = {j[0]: " ".join(str(x) for x in j[1:]) for j in (plate_jobs or [])}
            missing = []
            for sc in scenes:
                # Instrument shots -- code-drawn diagrams -- are a different layer from world
                # shots; demanding the recurring object inside a square-cube diagram would force a
                # cliff into a chart. The marker is HAVING NO PLATE JOB: an image that was never
                # generated is code-drawn. (This originally also required animate=False, which
                # broke the moment the diagram got a reveal animation -- being animated does not
                # make a chart a world shot.)
                if plate_jobs and sc.image not in by_stem:
                    continue
                blob = f"{sc.motion} {sc.onscreen} {sc.narration} {by_stem.get(sc.image, '')}".lower()
                if head not in blob:
                    missing.append(sc.id)
            if not plate_jobs:
                reviews.append("no plate_jobs passed: object recurrence checked against narration "
                               "only, which is not where the picture is described")
            notes["object_in_beats"] = f"{len(scenes)-len(missing)}/{len(scenes)}"
            if missing:
                fails.append(f"recurring object {obj!r} absent from: {', '.join(missing)}")

    # --- one protagonist: a second proper name in the narration means a second lead
    if req.get("one_protagonist") and who:
        names = set()
        for sc in scenes:
            # skip the first word of every sentence: capitalisation there carries no information
            for sent in _sentences(sc.narration):
                for m in re.finditer(r"\b([A-Z][a-z]{2,})\b", sent):
                    if m.start() == 0:
                        continue
                    names.add(m.group(1))
        extra = names - {who}
        notes["names_in_narration"] = sorted(names)
        # The declared protagonist never being spoken is a stale-data smell, not a style choice.
        # The 1mph topic kept meta.protagonist="Mara" after the lead became Adam; the check saw one
        # unexpected name, which was under the threshold, and said nothing.
        if who not in names:
            fails.append(f"declared protagonist {who!r} never appears in the narration "
                         f"(found {sorted(names) or 'no names'}) -- meta is stale or the lead changed")
        if len(extra) > 1:
            reviews.append(f"more than one other proper name appears ({sorted(extra)}) -- confirm "
                           f"the story still follows one protagonist")

    # --- open on consequence: beat one shows the effect, does not explain the cause
    if req.get("open_on_consequence") and scenes:
        first = (scenes[0].narration or "").lower()
        hits = [e for e in _EXPLAINER if e in first]
        if hits:
            fails.append(f"first beat explains the cause ({hits}) before showing the consequence")
        if not _sentences(scenes[0].narration):
            fails.append("first beat has no narration: the personal stake is never stated")

    # --- fantasy and anatomy: scan what will actually be sent to the generator
    for sc in scenes:
        text = f"{sc.motion} {sc.onscreen}".lower()
        for w in FANTASY:
            if w in text:
                fails.append(f"{sc.id}: prompt contains fantasy term {w!r}")
        for w in ANATOMY:
            if w in text:
                fails.append(f"{sc.id}: prompt contains anatomy risk {w!r}")

    # --- the zero rule: catchable in the PLATE text, which is where it was missed
    if req.get("zero_in_frame") and plate_jobs:
        MIDFLIGHT = ("mid-air", "midair", "caught high", "already high", "high above",
                     "mid-hop", "mid-jump", "mid-flight", "midflight", "floating above",
                     "hanging in the air", "rising above")
        # The scan is about the SUBJECT being airborne, not about weather. "dust still hanging in
        # the air" is an atmosphere cue and exactly what the exit rule asks for, so a bare substring
        # match condemns the fix it just demanded. Only flag when no airborne-medium noun precedes.
        AIRBORNE_MEDIUM = ("dust", "haze", "cloud", "mist", "grit", "spray", "particles", "snow",
                           "smoke", "vapour", "vapor", "motes", "pollen", "rain", "drizzle", "virga")
        bad = []
        for j in plate_jobs:
            text = " ".join(str(x) for x in j[1:]).lower()
            for w in MIDFLIGHT:
                at = text.find(w)
                while at != -1:
                    lead = text[max(0, at - 46):at]
                    if not any(m in lead for m in AIRBORNE_MEDIUM):
                        bad.append((j[0], w))
                        break
                    at = text.find(w, at + 1)
        if bad:
            fails.append("plates start mid-measurement, so the frame has no datum to read against "
                         f"(ZERO_RULE): {sorted({f'{a}:{b}' for a, b in bad})}")
        # The negative scan above only proves no plate SAYS mid-flight. It cannot prove any plate
        # contains a reference, which is the thing actually required. That gap is why the jump video
        # could have passed with six shots of a figure against empty sky.
        dfails, dnotes = datum_check(sim, plate_jobs)
        fails.extend(dfails)
        notes.update(dnotes)

    # --- causal chain: not mechanically decidable, so it is surfaced, never auto-passed
    if req.get("causal_chain"):
        reviews.append(f"causal chain across {len(scenes)} beats: confirm each results from the "
                       f"previous, not merely follows it")

    # --- open on the surprise, not on the control
    # A parallel comparison that opens on its control spends its most valuable seconds proving the
    # boring case. The shipped water video opened on "On Earth this is boring" and the first
    # surprising result did not land until 3.80s. Nothing objected, because only the escalation
    # preset had an opening rule.
    if req.get("open_on_surprise") and scenes:
        ctrl = (sim.meta or {}).get("control", "").strip().lower()
        first = scenes[0]
        notes["opens_on"] = first.id
        if ctrl and (first.id.lower() == ctrl or ctrl in (first.narration or "").lower()[:40]):
            fails.append(f"opens on the control condition ({first.id!r}): the first beat must show "
                         f"a surprising result, not the baseline")
        dull = ("this is boring", "nothing happens", "as expected", "no surprise")
        for d in dull:
            if d in (first.narration or "").lower():
                fails.append(f"first beat says {d!r} -- the video announces itself as boring")

    # --- verdict per beat: every condition must produce a distinct visible outcome
    if req.get("verdict_per_beat"):
        seen, dup = {}, []
        for sc in scenes:
            v = (sc.motion or "").strip().lower()
            if v and v in seen:
                dup.append(f"{sc.id} repeats {seen[v]}'s outcome")
            seen[v] = sc.id
        if dup:
            fails.append("conditions without a distinct outcome: " + "; ".join(dup))

    # --- the exit rule: a locked camera plus a subject that leaves frame is a STILL PHOTOGRAPH for
    # the rest of the shot. Found in the fall video, where the man exits in under a second and the
    # density gate then measured 3.2 seconds of frozen ledge -- the render passed every per-shot
    # displacement test, because the displacement all happened in the first few frames.
    # A shot whose subject exits must hand the frame to something that keeps moving.
    if direction.motion_mode == "action":
        EXIT = ("out of frame", "out of the frame", "gone from frame", "leaves frame",
                "off frame", "out of shot", "exits frame", "drops away", "plunges away",
                "falls away", "disappears")
        PERSIST = ("continuous", "continuously", "keeps", "streaming", "streams", "pours",
                   "surge", "rolling", "drifting", "trickles", "still moving", "goes on")
        thin = [sc.id for sc in scenes
                if any(e in (sc.motion or "").lower() for e in EXIT)
                and not any(p in (sc.motion or "").lower() for p in PERSIST)]
        if thin:
            fails.append(f"subject exits frame with nothing left moving, so the shot freezes after "
                         f"the exit: {thin}. Name what keeps moving (cloud, grit, haze)")

    # --- splash energy: ejecta vocabulary that exceeds what arrived (negative validation, class 4)
    for sc in scenes:
        text = f"{sc.motion} {sc.onscreen}".lower()
        hits = [w for w in SPLASH_BANNED if w in text]
        if hits:
            fails.append(f"{sc.id}: motion asks for {hits} -- a splash never exceeds the liquid "
                         f"that arrived (SPLASH_RULE)")

    # --- renewal: an animated scene whose phenomenon is the claim must renew it for the full shot
    # (negative validation, class 5: the virga existed in one of three sampled frames of its beat)
    if direction.motion_mode == "action":
        stale = [sc.id for sc in scenes
                 if sc.animate and sc.motion
                 and not any(t in sc.motion.lower() for t in RENEWAL_TERMS)]
        if stale:
            fails.append(f"motion prompt does not renew its phenomenon, so i2v can let it die "
                         f"mid-clip: {stale}. Add renewal language ('throughout', 'new X entering', "
                         f"'one band after another')")

    # --- reactions: a named reaction needs its stimulus and a body vector in the same prompt
    # (negative validation, class 3: a flinch facing away from the burst, a salute against dust)
    for sc in scenes:
        m = (sc.motion or "").lower()
        verbs = [v for v in REACTION_VERBS if v in m]
        if verbs:
            if not any(s in m for s in STIMULUS_NOUNS):
                fails.append(f"{sc.id}: reaction {verbs} has no named stimulus -- the pose will be "
                             f"generic (stock-pose class)")
            elif not any(v in m for v in VECTOR_TERMS):
                fails.append(f"{sc.id}: reaction {verbs} has no body vector (toward/away/eyes on) "
                             f"-- the reaction will not point at its cause")

    # --- figure integration: person-bearing plates must name scene lighting and contact shadow
    # (negative validation, class 2: studio-lit man on three worlds, hovering feet on all of them)
    if plate_jobs:
        unlit = []
        for j in plate_jobs:
            text = " ".join(str(x) for x in j[1:]).lower()
            if PERSON_RE.search(text):
                if not any(t in text for t in INTEGRATION_TERMS):
                    unlit.append(j[0])
        if unlit:
            fails.append(f"person in plate with no integration language: {unlit} -- the reference "
                         f"image's studio lighting will be imported verbatim (INTEGRATION_RULE); "
                         f"name the ambient cast and the contact shadow")

    # --- motion mode: a direction declares the motion its content needs
    notes["motion_mode"] = direction.motion_mode

    return {"direction": direction.name, "passed": not fails,
            "failures": fails, "requires_review": reviews, "measurements": notes}


def datum_check(sim, plate_jobs):
    """Every plate must CONTAIN the reference its measurement is read against. -> (failures, notes).

    Two shapes, because the two format invariants need opposite things:

      FIXED datum (parallel comparison) -- meta["datum"] = ("ledge", "ground", ...). The reference is
      the same in every shot precisely because the world is the only variable. Every plate must name
      one of those cues.

      LADDERED datum (escalation) -- meta["datum_axis"] = "altitude_m" plus Scene.magnitude. The
      reference changes with the magnitude, so each plate is checked against ITS band, and against
      the bands it must not borrow from. A plate is allowed to reach one band either side (a horizon
      is legitimately visible from 1,800 m and from 3,000 m); two bands away is a contradiction, not
      a judgement call.

    Silent when neither is declared -- but it says so in the notes, because a zero_in_frame direction
    with no datum declared is enforcing nothing, and that should be visible rather than green.
    """
    fails, notes = [], {}
    meta = sim.meta or {}
    by_stem = {j[0]: " ".join(str(x) for x in j[1:]).lower() for j in (plate_jobs or [])}
    if not by_stem:
        return fails, notes

    fixed = tuple(c.lower() for c in (meta.get("datum") or ()))
    axis = meta.get("datum_axis")

    if fixed:
        missing = sorted(s for s, t in by_stem.items() if not any(c in t for c in fixed))
        notes["datum"] = f"fixed {list(fixed)} -> {len(by_stem)-len(missing)}/{len(by_stem)} plates"
        if missing:
            fails.append(f"plates with no datum in frame (none of {list(fixed)}): {missing}")
        return fails, notes

    if axis:
        if axis not in DATUM_LADDER:
            fails.append(f"unknown datum_axis {axis!r}; have {sorted(DATUM_LADDER)}")
            return fails, notes
        ladder = DATUM_LADDER[axis]
        by_scene = {sc.image: sc for sc in sim.scenes}
        placed, prev_i = [], None
        for stem, text in by_stem.items():
            sc = by_scene.get(stem)
            mag = getattr(sc, "magnitude", None) if sc else None
            if mag is None:
                fails.append(f"{stem}: datum_axis {axis!r} is declared but the scene has no "
                             f"magnitude, so no band can be chosen")
                continue
            band = datum_band(axis, mag)
            if band is None:
                fails.append(f"{stem}: magnitude {mag} falls outside the {axis} ladder")
                continue
            i, label, cues = band
            hits = [c for c in cues if c in text]
            if not hits:
                fails.append(f"{stem}: at {mag:g} the datum should be {label!r} "
                             f"({list(cues)[:3]}...), and the plate names none of it")
            # Foreign cues are scanned against the text with the CORRECT band's matches removed.
            # Bands share vocabulary by nature -- "curved horizon" contains "horizon", which belongs
            # two bands lower -- so a naive substring scan rejects the very plates it should accept.
            rest = text
            for c in sorted(hits, key=len, reverse=True):
                rest = rest.replace(c, " ")
            for j, (_, _, jl, jcues) in enumerate(ladder):
                if abs(j - i) < 2:
                    continue
                foreign = [c for c in jcues if c in rest]
                if foreign:
                    fails.append(f"{stem}: at {mag:g} the plate names {foreign[0]!r}, which belongs "
                                 f"to the {jl!r} band -- not visible at this magnitude")
            placed.append((stem, mag, label))
        notes["datum"] = f"{axis}: " + ", ".join(f"{s}={l}" for s, _, l in placed)
        # An escalation whose datum never advances is not escalating; it is repeating.
        labels = [l for _, _, l in placed]
        if len(set(labels)) == 1 and len(labels) > 2:
            fails.append(f"every beat sits in the same datum band ({labels[0]!r}): the magnitude "
                         f"changes but nothing in frame does, so the climb is not readable")
        return fails, notes

    notes["datum"] = "NOT DECLARED -- zero_in_frame is enforcing only the negative scan"
    return fails, notes


def copy_matches_scenes(sim, *copy_paths, names=None):
    """Published copy may not name a condition that never appears on screen.

    The water video's description published a seven-row physics table including Europa, a world with
    no scene and no plate, because the copy was generated from the physics module rather than from
    the scenes. Nothing compared the two. This does.
    """
    import os
    import re
    on_screen = {(sc.chips[0] if sc.chips else "").strip().upper() for sc in sim.scenes}
    on_screen.discard("")
    known = {n.strip().upper() for n in (names or [])} or on_screen
    ghosts, checked = {}, []
    for path in copy_paths:
        if not os.path.exists(path):
            continue
        checked.append(path)
        text = open(path, encoding="utf8").read().upper()
        for n in known - on_screen:
            if re.search(rf"\b{re.escape(n)}\b", text):
                ghosts.setdefault(os.path.basename(path), []).append(n)
    return {"passed": not ghosts, "checked": checked,
            "on_screen": sorted(on_screen), "named_but_absent": ghosts}


def report(res):
    out = [f"DIRECTION {res['direction']} -> {'PASS' if res['passed'] else 'FAIL'}"]
    for k, v in (res.get("measurements") or {}).items():
        out.append(f"  {k}: {v}")
    for f in res["failures"]:
        out.append(f"  FAIL   {f}")
    for r in res["requires_review"]:
        out.append(f"  REVIEW {r}")
    return "\n".join(out)
