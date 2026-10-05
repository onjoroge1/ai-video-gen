"""Small, deterministic creative layer for illustrated long-form explainers.

This module deliberately does not render media, call providers, or replace the existing
long-form pipeline.  It gives the proven pipeline two things only:

* a story-first direction for its existing script call; and
* a normalized storyboard that records intent and continuity before asset spend.

Keeping those responsibilities pure makes the lane cheap to test and safe to remove.
"""
from __future__ import annotations

import re
from typing import Any

import causal_story as cs


CINEMATIC = "cinematic"
ILLUSTRATED_STORY = "illustrated_story"
SUPPORTED_STYLES = {CINEMATIC, ILLUSTRATED_STORY}
SCHEMA_VERSION = "illustrated_story_v1"
# The continuity budget the lane promises. Named once so the validator, the visual bible and
# the script direction cannot drift apart.
LOCATION_BUDGET = 4

# Locations follow the causal role rather than a position on an arc. Still four values, so the
# fallback stays inside the budget; the scripted environment_type overrides it whenever present.
_LOCATION_BY_ROLE = {
    cs.SETUP: "opening_location",
    cs.INTERVENTION: "planning_location",
    cs.FALSE_RESOLUTION: "planning_location",
    cs.HINGE: "opening_location",
    cs.MECHANISM: "planning_location",
    cs.ESCALATION: "action_location",
    cs.REVERSAL: "consequence_location",
    cs.GENERALIZATION: "consequence_location",
    cs.TOOL: "opening_location",
    cs.VERDICT: "opening_location",
}
# The reference videos both narrate at ~180 words per minute. Scenes carry no timing before TTS,
# so the mechanism-placement check needs an estimate, and the measured rate is the honest one.
REFERENCE_WPM = 180.0


def _text(value: Any) -> str:
    return str(value or "").strip()


def validate_request(*, visual_style: str, video_format: str, story_format: str,
                     controlled_pilot: bool) -> None:
    """Reject cross-flow leakage before any provider call."""
    if visual_style not in SUPPORTED_STYLES:
        raise ValueError(f"Unsupported visual_style: {visual_style}")
    if visual_style != ILLUSTRATED_STORY:
        return
    if video_format != "landscape":
        raise ValueError("Illustrated Story is available only for landscape long-form explainers.")
    if story_format != "standard_explainer":
        raise ValueError("Illustrated Story currently requires the Standard explainer structure.")
    if controlled_pilot:
        raise ValueError("Illustrated Story is not enabled for controlled or directed pilots.")


def is_enabled(*, visual_style: str, video_format: str, story_format: str,
               controlled_pilot: bool) -> bool:
    validate_request(
        visual_style=visual_style,
        video_format=video_format,
        story_format=story_format,
        controlled_pilot=controlled_pilot,
    )
    return visual_style == ILLUSTRATED_STORY


def story_direction(question: str, operator_direction: str = "") -> str:
    """The causal spine plus the illustrated visual bible, as one direction.

    The causal contract owns the story shape; this adds only what is specific to drawing it. The
    previous version required a named protagonist ("Follow Alex"). Neither reference video has
    one — the actors are an institution and a class of people — so mandating a character would
    have excluded exactly the stories this mode is best at.
    """
    illustrated = f"""
ILLUSTRATED TREATMENT — REQUIRED FOR THIS VIDEO:
Keep one consistent human subject through the whole story. It may be a named person, a group, or
an institution, whichever the story actually turns on. Do not invent a protagonist a topic does
not have.
Reuse at most {LOCATION_BUDGET} distinct environment_type values across the whole video, and a
small set of recurring props. The base schema asks you to VARY environment_type; this video
overrides that instruction — recurring locations are what make an illustrated story readable, and
a storyboard over budget is rejected before any asset spend.
Write visuals as simple actions and state changes suitable for a hand-drawn editorial storybook.
Build this video's own hook, phrasing and shot compositions from its sourced events. References
guide clarity and pacing; use our ink-and-cut-paper visual identity and original musical theme.
Avoid reproducing a reference's signature wording, character designs or sequence of images.
Do not request cinematic photography, abstract symbolism, decorative montage, or text inside
generated images. Maps, arrows, labels, counters, and captions are added by the renderer.
Keep Bolt selective: he may assist, measure, warn, or react, but he is not automatically present.
""".strip()
    return cs.story_direction(question, f"{illustrated}\n\n{_text(operator_direction)}".strip())


def _location_for(scene: dict, role: str) -> str:
    """Prefer the location the script actually chose over the one implied by story position.

    ``_LOCATION_BY_ROLE`` only ever yields four values, so a budget check fed from it alone
    validated this module's own lookup table rather than the script — it could not fail. The
    scripted ``environment_type`` is the real signal, and it is exactly what the four-location
    promise is about, so it is what the budget is now measured against. The role mapping stays
    as the fallback for scenes that declare nothing.
    """
    declared = re.sub(r"[^a-z0-9]+", "_", _text(scene.get("environment_type")).lower()).strip("_")
    # A blank or unknown role must not raise here. Subscripting the table crashed with KeyError
    # before the validator could return UNKNOWN_ROLE, so a script with one mislabelled scene died
    # with a bare exception instead of the readable list of everything wrong with it — and the
    # blank-role case is exactly what a replan that dropped the causal lane produces.
    return declared or _LOCATION_BY_ROLE.get(role, "opening_location")


# "Step one." through "Step eight." — MAX_CHAPTERS is 8, so the table covers every legal chapter.
_SPOKEN_CHAPTER = ("", "one", "two", "three", "four", "five", "six", "seven", "eight")


def announce_chapters(scenes: list) -> list[str]:
    """Speak each chapter number aloud on the scene that opens it.

    The rule was, again, only asked for: "OPEN EACH NEW CHAPTER OUT LOUD ... its narration MUST
    begin with that chapter spoken as words". Every render this session produced at least one
    chapter that did not, and CHAPTER_NOT_ANNOUNCED was the last gate standing. Whether a chapter
    announces itself is decidable by reading the first six characters of a string, so it does not
    need a model.

    This is the retention device the format is built on — all six references open on a hook and
    then say "Step one" — so the fix is to make it true, not to relax the check. The marker is
    PREPENDED, never substituted, so every claim binding and anchor phrase bound to the existing
    narration survives as a substring of the new one.
    """
    added = []
    if not cs.speaks_chapter_markers():
        # Off by default. See causal_story.speaks_chapter_markers for why the device that the
        # corpus references use is not the device this lane wants.
        return added
    seen = set()
    for scene in scenes:
        try:
            chapter = int(scene.get("chapter") or 0)
        except (TypeError, ValueError):
            continue
        if chapter <= 0 or chapter in seen or chapter >= len(_SPOKEN_CHAPTER):
            continue
        seen.add(chapter)
        narration = _text(scene.get("narration"))
        marker = f"Step {_SPOKEN_CHAPTER[chapter]}."
        # PRESENT ANYWHERE, not just at position zero. cs._MARKER is anchored to the start of the
        # string, but the shape this docstring describes -- "open on a hook and then say Step one"
        # -- puts the marker AFTER the hook on the one scene that carries it. The guard therefore
        # could not see the marker finalize_narration had already placed correctly, and prepended a
        # second one in FRONT of the hook. The video opened on the numeral with the promise
        # sentence buried behind it and spoken twice, which is the exact failure both this function
        # and finalize_narration exist to prevent -- each of them writing the same marker without
        # knowing the other had.
        if cs._MARKER.match(narration) or marker.casefold() in narration.casefold():
            continue
        scene["narration"] = f"{marker} {narration}".strip()
        added.append(marker)
    return added


def collapse_locations(beats: list, budget: int = LOCATION_BUDGET) -> list[tuple[str, str]]:
    """Fold the least-used locations into their nearest neighbour until the budget holds.

    The budget was enforced by ASKING for it — "Reuse at most 4 distinct environment_type values" —
    and then failing the run when the script came back with five or six. That is a rule with no
    mechanism behind it, and this session has now watched prompt-only rules lose to structural ones
    every time they were compared. Nothing about "which four places" needs a model: it is a
    frequency count.

    Locations are kept by how often the script actually used them, and each orphaned scene adopts
    the location of the NEAREST kept scene rather than the most common one, because the budget
    exists to make the video feel continuous. Sending one stranded beat to a place the story is not
    currently in would satisfy the count and break the thing the count is for.

    Mutates `beats` and returns the (from, to) moves so the caller can log what it changed.
    """
    order, counts = [], {}
    for beat in beats:
        location = beat["location_id"]
        if location not in counts:
            order.append(location)
            counts[location] = 0
        counts[location] += 1
    if len(order) <= budget:
        return []

    # Most-used first; ties broken by first appearance so the result never depends on dict order.
    keep = set(sorted(order, key=lambda loc: (-counts[loc], order.index(loc)))[:budget])
    kept_indexes = [index for index, beat in enumerate(beats) if beat["location_id"] in keep]
    moves = []
    for index, beat in enumerate(beats):
        if beat["location_id"] in keep:
            continue
        # Nearest kept beat, earlier one winning a tie: a scene is more likely to continue the
        # place it just came from than to pre-empt the one it is going to.
        nearest = min(kept_indexes, key=lambda other: (abs(other - index), other > index))
        moves.append((beat["location_id"], beats[nearest]["location_id"]))
        beat["location_id"] = beats[nearest]["location_id"]
    return moves


def _first_visual(scene: dict) -> str:
    for beat in scene.get("visual_beats") or []:
        if isinstance(beat, dict):
            visual = _text(beat.get("state_after")) or _text(beat.get("visual"))
            if visual:
                return visual
        elif _text(beat):
            return _text(beat)
    return _text(scene.get("image_prompt")) or _text(scene.get("visible_consequence"))


def build_storyboard(script: dict, question: str) -> dict:
    """Normalize existing scenes into an auditable intent-and-continuity storyboard."""
    scenes = script.get("scenes") or []
    if not scenes:
        raise ValueError("Illustrated Story requires at least one scripted scene.")

    contract = script.get("_story_contract")
    contract = contract if isinstance(contract, dict) else {}
    protagonist = _text(contract.get("human_subject")) or "Alex"
    goal = (
        _text(contract.get("subject_goal"))
        or _text(next((scene.get("human_intention") for scene in scenes
                       if _text(scene.get("human_intention"))), ""))
        or f"understand {question}"
    )
    opening_object = (
        _text(contract.get("opening_object"))
        or _text(scenes[0].get("continuity_anchor"))
        or "the opening problem"
    )

    # The clock counts narration ONCE, starting at zero.
    #
    # An earlier version also added the hook's spoken seconds up front, reasoning that the
    # reference fixtures reserve 3-5s before their first step. But `finalize_narration` now writes
    # the hook INTO scene 1's narration, so those words are already inside the word count below —
    # adding them again inflated the estimate by a measured 6.3 seconds and moved the mechanism's
    # position against its deadline. The reserved gap and the in-narration hook are two ways of
    # modelling the same seconds; keeping both counts them twice.
    # BEFORE the clock, not after it. The marker is spoken narration, so the words have to exist
    # on the scene before `spoken` counts them. Running this after the loop cleared the gate while
    # leaving the runtime estimate short by exactly the words it had just added — a quieter version
    # of the hook double-count described above, and caught by the same test.
    chapters_announced = announce_chapters(scenes)

    steps, beats, spoken = [], [], 0.0
    for index, scene in enumerate(scenes):
        narration = _text(scene.get("narration"))
        if not narration:
            raise ValueError(f"Illustrated Story scene {index + 1} has no narration.")
        # Declared, not derived. A scene that does not say what caused it fails the chain check
        # below rather than being handed a role because of where it happens to sit.
        role = _text(scene.get("causal_role")).lower()
        location_id = _location_for(scene, role)
        steps.append({
            "step_id": _text(scene.get("scene_id")) or f"scene_{index + 1:03d}",
            "role": role,
            "event_function": scene.get("event_function") or "",
            "chapter": scene.get("chapter") or 0,
            "start_sec": round(spoken, 1),
            "situation": narration,
            "caused_by": _text(scene.get("caused_by")),
            # Which beat-part this scene is. causal_story's role rules count ASSERTING steps, and
            # _normalize_steps drops every field it is not given -- so without this the whole
            # re-scoping is inert here, which is the only place these steps are built for the
            # illustrated lane. A split mechanism would read as two mechanisms, a split setup would
            # fail CAUSED_SETUP and ORPHAN_STEP at once, and each part of a hinge would be charged
            # the full ten words.
            "continues": _text(scene.get("continues")),
            "label": _text(scene.get("text_overlay")),
        })
        spoken += len(narration.split()) / REFERENCE_WPM * 60.0

        beat = {
            "scene_index": index,
            # The scene's two identities, carried so a reader of the storyboard can tell how many
            # STORY beats it holds. Without them the manifest counted rows, which stopped being the
            # beat count once a beat could span scenes.
            "scene_id": _text(scene.get("scene_id")),
            "beat_id": _text(scene.get("beat_id")),
            "continues": _text(scene.get("continues")),
            "role": role,
            "chapter": scene.get("chapter") or 0,
            "caused_by": _text(scene.get("caused_by")),
            "location_id": location_id,
            "protagonist": protagonist,
            "intent": _text(scene.get("human_intention")) or goal,
            "belief_before": (_text(scene.get("human_belief"))
                              or _text(contract.get("accepted_belief"))),
            "action_or_evidence": _first_visual(scene),
            "expected_result": _text(scene.get("expected_outcome")),
            "actual_result": (_text(scene.get("actual_outcome"))
                              or _text(scene.get("visible_consequence"))
                              or _first_visual(scene)),
            "narration_anchor": " ".join(narration.split()[:12]),
            "return_object": opening_object if role in cs.CLOSING_ROLES else "",
        }
        scene["_illustrated_beat"] = beat
        beats.append(beat)

    import story_engines as se
    # Validate against the shape the story declared. Without an engine the generic contract
    # applies, which is what a script written before engines existed will get.
    # isinstance, not truthiness. story_engines.resolve_id is deliberately lenient and maps
    # anything unrecognised to the default engine, so a non-string here does not raise — it
    # silently validates the story against the WRONG engine. Falling through to None applies
    # the generic contract, which is the honest answer when the engine is unreadable.
    declared = script.get("_story_engine")
    engine = (se.get(declared, compiled=bool(script.get("_compiled_story")))
              if isinstance(declared, str) and declared.strip() else None)
    # REPAIR BEFORE VALIDATING, exactly as the spine pass does. _assign_causal_spine has always
    # run repair_chain on its output — "the mechanically decidable mistakes are fixed for free
    # rather than re-bought" — but the storyboard re-derived its steps from the scenes and
    # validated them raw, so a role order repair had already fixed once came back as a hard
    # ENGINE_ORDER failure here. The repair was written; it just was not wired into this path.
    #
    # The repaired role is written back onto the scene, not only into the steps handed to the
    # validator. A repair that satisfies the check without changing the story is the kind of green
    # metric over wrong output this build has been bitten by repeatedly.
    causal_repairs: list = []
    if engine and not script.get("_compiled_story"):
        steps, causal_repairs = cs.repair_chain(steps, engine)
        for scene, step in zip(scenes, steps):
            scene["causal_role"] = step["role"]
    causal = cs.validate_causal_story({
        "runtime_sec": round(spoken, 1),
        "hook": {"line": _text(script.get("hook")),
                 "cold_open": _text(script.get("_cold_open")),
                 # Held only on scripts planned under the cold-open contract: a checkpoint or
                 # cached script written before it carries no key and is judged as before.
                 "require_cold_open": "_cold_open" in script},
        "start_state": _text(contract.get("accepted_belief")),
        "opening_object": opening_object,
        # The generalization check needs the cases the spine pass fetched. Omitting them here made
        # a compliant script fail THIN_GENERALIZATION with cases sitting unread on the script.
        "parallel_cases": script.get("_parallel_cases") or [],
        "steps": steps,
    }, engine)

    # Bring the location count inside the budget BEFORE measuring it. The check stays: a collapse
    # that cannot reach the budget is a real failure and must still stop the run.
    location_moves = collapse_locations(beats)
    # Rendering reads scene.environment_type, not storyboard beat.location_id. Keep one canonical
    # location after repair so validation cannot certify a four-location board while generation
    # still receives a fifth, discarded environment.
    for scene, beat in zip(scenes, beats):
        previous = _text(scene.get("environment_type"))
        if previous and previous != beat["location_id"]:
            scene["environment_type_model"] = previous
        scene["environment_type"] = beat["location_id"]
    locations = sorted({beat["location_id"] for beat in beats})
    validation_errors = [f"{issue['code']}: {issue['message']}" for issue in causal["errors"]]
    if len(locations) > LOCATION_BUDGET:
        validation_errors.append(
            "storyboard uses %d locations against a budget of %d: %s"
            % (len(locations), LOCATION_BUDGET, ", ".join(locations)))
    if any(not beat["intent"] for beat in beats):
        validation_errors.append("every beat requires a declared human intent")

    storyboard = {
        "schema_version": SCHEMA_VERSION,
        "question": question,
        "title": _text(script.get("title")) or question,
        "story": {
            "protagonist": protagonist,
            "goal": goal,
            "opening_object": opening_object,
            "initial_belief": _text(contract.get("accepted_belief")),
            "replacement_belief": _text(contract.get("replacement_model")),
        },
        "visual_bible": {
            "style": "hand-drawn editorial storybook",
            "character_model": "one consistent illustrated human subject",
            "palette": ["warm parchment", "ochre", "rust", "ink black", "muted teal"],
            "location_budget": LOCATION_BUDGET,
            "location_moves": location_moves,
            "causal_repairs": causal_repairs,
            "chapters_announced": chapters_announced,
            "locations": locations,
            "generated_text": False,
        },
        "beats": beats,
        "chain": causal["chain"],
        "chapter_count": causal["chapter_count"],
        "story_engine": causal.get("engine", ""),
        "estimated_runtime_sec": round(spoken, 1),
        "validation": {"passed": not validation_errors, "errors": validation_errors},
    }
    script["_illustrated_story"] = storyboard
    return storyboard


CREATIVE_PROFILE = "ink_cut_paper_v1"
CAPTION_STYLE = "illustrated_ink"


# ── Paper plates: one stock per story role ──────────────────────────────────────
#
# The delivered films measured a CIRCULAR hue spread of 4.6 degrees across three complete
# videos: every frame sat on the same ivory field at saturation 0.16-0.21, and the first 60
# seconds of the cane toad film was flatter than its own average, which is where the audience
# left (41s of 281s). Recolouring the OBJECTS cannot move that, because the paper is the field
# and the field is most of the frame. So the ink, the hatching, the deckled edge and the mustard
# story accent stay fixed for the whole series -- that is the identity -- and the STOCK the scene
# is printed on changes at every story turn.
#
# Measured on a six-beat continuity test (2026-10-04): circular hue SD 91.4 degrees over 6 of 12
# sectors, cut-to-cut mean |dRGB| 47.8 against the delivered films' 16.7-21.3, and all six frames
# still read as one hand-made series.
PLATES = {
    "setup": ("Printed on warm ivory rag stock: pale ivory-cream paper is the FIELD and covers "
              "most of the frame, with straw and kraft-tan cut-paper shapes and deep umber "
              "blocks. No blue field, no grey field."),
    "intervention": ("Printed on agricultural green stock: the paper itself is a flat olive-green "
                     "covering most of the frame, with ledger-green and dark moss cut-paper "
                     "shapes and pale lime highlights. No ivory, no cream, nothing warm."),
    "false_resolution": ("Printed on pale sky-cyan stock: the paper is a clean pale cyan filling "
                         "the frame, with mineral teal and slate-teal cut-paper shapes and one "
                         "small warm paper accent. The brightest, cleanest plate in the film -- "
                         "the part that appeared to work is the prettiest frame. No ivory field, "
                         "nothing amber."),
    "hinge": ("Printed on near-black midnight-navy stock: the paper itself is a very dark "
              "blue-black covering almost the entire frame, with faint steel-blue shapes barely "
              "lifting out of it. The darkest frame in the film. No ivory, nothing bright, no "
              "open sky."),
    "mechanism": ("Printed on blueprint-blue stock: the paper is a mid blueprint blue filling the "
                  "frame, with deeper indigo and near-black navy cut-paper blocks and chalk-white "
                  "drawing shapes. No ivory, no cream, nothing warm."),
    "escalation": ("Printed on magenta-madder stock: the paper is a saturated rose-madder filling "
                   "the frame, with deep wine and claret cut shapes and dusty rose highlights. "
                   "No ivory, no blue field, nothing cool."),
    "reversal": ("Printed on scarlet-oxide stock: the paper is a deep saturated scarlet filling "
                 "the frame, with blood-oxide and near-black red cut shapes and one "
                 "scorched-apricot highlight. The most saturated frame in the film. No ivory, "
                 "nothing pale."),
    "generalization": ("Printed on rust-orange stock: the paper is a hot rust orange covering the "
                       "frame, with burnt sienna and dark oxide cut shapes and pale apricot "
                       "highlights. No ivory, nothing cool."),
    "tool": ("Printed on bleached stone stock: the paper is a pale colour-drained stone with cool "
             "grey-green and bone cut shapes. The least saturated plate in the film; the mustard "
             "story object is the only warm thing left. No strong colour of any kind."),
    "context": ("Printed on warm ivory rag stock: pale ivory-cream paper is the field, with straw "
                "and kraft-tan cut-paper shapes. No blue field."),
}
_DEFAULT_PLATE = PLATES["setup"]

# The composition rules, lifted from a reference frame that measured far better than ours and
# then stripped of its medium: a hero subject at dominant scale, a softened foreground, a low
# raking light that rims every cut edge, and the subject arranged as a directional flow. None of
# this requires leaving illustration, and all of it is expressible in the prompt.
_STAGING = (
    " Cinematic staging: ONE hero subject rendered at dominant scale in the near foreground with "
    "crisp ink detail; the cut-paper shapes immediately in front of it simplified and softened as "
    "if thrown out of focus; the background receding through progressively flatter, paler paper "
    "layers. A low raking light rims every cut-paper edge with a bright warm line and throws long "
    "shadows toward the viewer. One unmistakable story action, a strong readable silhouette, and "
    "clear negative space in the lower third for captions.")


def plate_for(role: str) -> str:
    """The paper stock this story role is printed on."""
    return PLATES.get((role or "").strip().lower(), _DEFAULT_PLATE)


def visual_style_suffix(framing: str = "", role: str = "") -> str:
    """Our ink/cut-paper treatment on this role's paper stock, staged for depth.

    `role` selects the plate (see PLATES). Omitted, the warm ivory setup stock applies, which is
    what every frame of the first three films used.
    """
    return (
        " Compose ONE single continuous scene that fills the whole frame: a single moment, seen "
        "once, from one camera. Never a grid, never panels, never a storyboard sheet, never "
        "borders, gutters, insets, numbered boxes or caption strips. "
        " Visual treatment: hand-drawn editorial history illustration with layered cut-paper "
        "shapes on clean ivory stock. Simplified human figures with natural skin tones, varied "
        "angular face silhouettes, small simple facial features, expressive hands and "
        "period-appropriate clothing. Identity is carried by "
        "clothing colour, silhouette, headwear and props — never by facial detail. Visible ink "
        "contour lines, restrained crosshatching, flat gouache colour blocks and a little paper "
        "grain. A single small mustard-yellow paper accent marks the changing story object, on every "
        "plate. Readable silhouettes, layered foreground, middle ground and "
        "background, one unmistakable story action per frame. Reuse the same clothing colours, props and location design "
        "whenever they recur. Composition must read instantly at phone size. "
        + plate_for(role)
        + _STAGING
        + framing
        + " No text, letters, numbers, labels, arrows, UI, watermark, or accidental writing; "
        "the renderer adds all typography and diagram overlays."
        # YEARS ARE THE LEAK. Six frames of the delivered killer bees film carried "1956", "26",
        # "1994", "1990" and "2005" burned into the picture, because a visual description that
        # says "by 2005 the range reached Florida" reads to the image model as an instruction to
        # WRITE the year. The ban has to name the specific thing that keeps appearing.
        + " In particular NEVER draw a year, a date, a count or any digit anywhere in the frame, "
        "and never a map legend, chart axis, signpost, banner or plaque carrying one: show the "
        "moment itself and let the renderer caption it."
    )


def negative_prompt() -> str:
    """What the lane must never render. This lane had no negative prompt at all until now.

    `directed_longform` already carries a `negative_prompt` field, so the concept existed in the
    codebase and this lane simply was not using it.
    """
    return (
        # "comic-book superhero style" banned an aesthetic and left the LAYOUT unforbidden, so a
        # render came back as grids of numbered panels with lettered captions. The layout terms
        # below are the ones that were missing; text is banned outright rather than only when
        # unreadable, because legible baked-in lettering was the actual defect.
        "comic strip, comic panels, multi-panel layout, storyboard sheet, contact sheet, grid of "
        "images, split screen, panel borders, gutters, insets, numbered boxes, caption boxes, "
        "speech bubbles, any lettering or text, titles, headlines, signage text, labels, "
        "years, dates, digits, numerals, map legends, chart axes, plaques, banners, "
        "photorealism, cinematic photography, 3D render, plastic skin, anime, comic-book "
        "superhero style, detailed rendered faces, excessive detail, distorted hands, extra "
        "limbs, watermarks, modern clothing, inconsistent characters, crowded "
        "focal point, multiple unrelated actions, generic stock illustration, blank white balloon "
        "heads, sepia parchment vignette, purple-on-white caption cards"
    )


# ── Shot grammar ───────────────────────────────────────────────────────────────
#
# Measured across the three delivered films: close + detail was 4/25, 3/22 and 3/27 scenes,
# while wide + aerial ran 9/25, 14/22 and 18/27. The films are a sequence of landscapes with
# almost no face or object at scale, which is the other half of why they read as static. The
# writer picks shot_type per scene and nothing ever checked the distribution.
CLOSE_TYPES = ("close", "detail")
WIDE_TYPES = ("wide", "aerial")
CLOSE_MIN_RATIO = 0.40
WIDE_MAX_RATIO = 0.28
MAX_CONSECUTIVE_WIDES = 1
MAX_SAME_TYPE_RUN = 2

# Which shot sizes each role should favour, most-preferred first. A diagram beat belongs in the
# detail register at hand scale, not as a map seen from orbit.
_ROLE_PREFERENCE = {
    "setup": ("detail", "close", "medium", "wide"),
    "intervention": ("medium", "close", "detail"),
    "false_resolution": ("detail", "wide", "medium"),
    "hinge": ("detail", "close"),
    "mechanism": ("close", "detail", "medium"),
    "escalation": ("close", "detail", "medium", "wide"),
    "reversal": ("close", "medium", "detail"),
    "tool": ("medium", "close"),
}


def shot_grammar_report(scenes: list) -> dict:
    """How the plan's shot sizes measure against the grammar. Deterministic, no model."""
    types = [str((s or {}).get("shot_type") or "medium").strip().lower() for s in scenes or []]
    n = max(1, len(types))
    close = sum(1 for t in types if t in CLOSE_TYPES)
    wide = sum(1 for t in types if t in WIDE_TYPES)
    run_w, worst_w, run_s, worst_s, prev = 0, 0, 0, 0, None
    for t in types:
        run_w = run_w + 1 if t in WIDE_TYPES else 0
        worst_w = max(worst_w, run_w)
        run_s = run_s + 1 if t == prev else 1
        worst_s = max(worst_s, run_s)
        prev = t
    fails = []
    if close / n < CLOSE_MIN_RATIO:
        fails.append(f"close+detail {close}/{len(types)} ({close / n:.0%}) under {CLOSE_MIN_RATIO:.0%}")
    if wide / n > WIDE_MAX_RATIO:
        fails.append(f"wide+aerial {wide}/{len(types)} ({wide / n:.0%}) over {WIDE_MAX_RATIO:.0%}")
    if worst_w > MAX_CONSECUTIVE_WIDES:
        fails.append(f"{worst_w} consecutive wides (max {MAX_CONSECUTIVE_WIDES})")
    if worst_s > MAX_SAME_TYPE_RUN:
        fails.append(f"{worst_s} consecutive scenes share one shot size (max {MAX_SAME_TYPE_RUN})")
    return {"close": close, "wide": wide, "n": len(types), "close_ratio": round(close / n, 2),
            "wide_ratio": round(wide / n, 2), "longest_wide_run": worst_w,
            "longest_same_run": worst_s, "fails": fails, "passed": not fails}


def enforce_shot_grammar(scenes: list, log=lambda message: None) -> int:
    """Rewrite shot_type so the plan meets the grammar. Returns how many scenes changed.

    Deterministic and content-aware only through the role preference: it never reorders scenes
    or touches narration, it only decides how close the camera sits. Wides are converted first
    (they are the surplus), choosing each scene's most-preferred close size for its role.
    """
    rows = [s for s in (scenes or []) if isinstance(s, dict)]
    if not rows:
        return 0
    changed = 0

    def typ(s):
        return str(s.get("shot_type") or "medium").strip().lower()

    def role(s):
        return str(s.get("causal_role") or s.get("story_role") or "").strip().lower()

    def preferred_close(s):
        for cand in _ROLE_PREFERENCE.get(role(s), ("close", "detail")):
            if cand in CLOSE_TYPES:
                return cand
        return "close"

    n = len(rows)
    # 1. Raise the close ratio, converting wides before mediums.
    need = int(CLOSE_MIN_RATIO * n + 0.999) - sum(1 for s in rows if typ(s) in CLOSE_TYPES)
    if need > 0:
        order = ([s for s in rows if typ(s) in WIDE_TYPES]
                 + [s for s in rows if typ(s) == "medium"])
        for s in order[:need]:
            s["shot_type"] = preferred_close(s)
            changed += 1
    # 2. Break runs of wides and runs of one size.
    for i in range(1, len(rows)):
        if typ(rows[i]) in WIDE_TYPES and typ(rows[i - 1]) in WIDE_TYPES:
            rows[i]["shot_type"] = preferred_close(rows[i])
            changed += 1
    for i in range(MAX_SAME_TYPE_RUN, len(rows)):
        if len({typ(rows[j]) for j in range(i - MAX_SAME_TYPE_RUN, i + 1)}) == 1:
            current = typ(rows[i])
            rows[i]["shot_type"] = preferred_close(rows[i]) if current not in CLOSE_TYPES else "medium"
            changed += 1
    if changed:
        report = shot_grammar_report(rows)
        log(f"Shot grammar: adjusted {changed} scene(s) -> close+detail {report['close_ratio']:.0%}, "
            f"wide+aerial {report['wide_ratio']:.0%}, longest wide run {report['longest_wide_run']}")
    return changed


_SHOT_FRAMING = {
    "detail": (" FRAMING: a DETAIL shot. One object, surface or pair of hands fills the frame at "
               "hand scale. The wider location is barely present."),
    "close": (" FRAMING: a CLOSE-UP. The single subject fills at least two thirds of the frame; if "
              "it is an animal or a person, the head and eyes are large and clearly readable. No "
              "establishing landscape."),
    "medium": (" FRAMING: a MEDIUM shot. The subject occupies about half the frame with just "
               "enough surroundings to place it."),
    "wide": (" FRAMING: a WIDE shot. The landscape is the subject, but keep ONE foreground element "
             "large and sharp so the eye has somewhere to land."),
    "aerial": (" FRAMING: a high AERIAL view, with one foreground element large in the near field "
               "so the frame is not uniformly distant."),
}


# What a scene must SHOW rather than diagram. Measured on the delivered killer bees film: four
# frames were tinted maps of the Americas with dots on them and several more were flat overhead
# dioramas, so "cinematic staging" had no subject to stage. A map is a picture of information;
# this channel draws the moment the information is about.
NO_DIAGRAM = (
    " Draw the MOMENT, never a diagram of it: no maps, no territory outlines, no pins, dots or "
    "arrows on a region, no charts, no timelines, no cutaway schematics and no specimen boards. "
    "If the beat is about somewhere spreading or arriving, show one concrete thing in one real "
    "place at eye level -- a swarm over a roadside orchard, a hive on a porch, a stand of trees "
    "going quiet -- not the geography it happened across.")


def shot_framing(shot_type: str) -> str:
    """Prompt language for a scene's shot size. Without this the size only changed the Ken Burns
    move and every image came back a landscape regardless of the plan."""
    return _SHOT_FRAMING.get((shot_type or "medium").strip().lower(), _SHOT_FRAMING["medium"])
