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
        if cs._MARKER.match(narration):
            continue
        marker = f"Step {_SPOKEN_CHAPTER[chapter]}."
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
            "chapter": scene.get("chapter") or 0,
            "start_sec": round(spoken, 1),
            "situation": narration,
            "caused_by": _text(scene.get("caused_by")),
            "label": _text(scene.get("text_overlay")),
        })
        spoken += len(narration.split()) / REFERENCE_WPM * 60.0

        beat = {
            "scene_index": index,
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
    engine = se.get(declared) if isinstance(declared, str) and declared.strip() else None
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
    if engine:
        steps, causal_repairs = cs.repair_chain(steps, engine)
        for scene, step in zip(scenes, steps):
            scene["causal_role"] = step["role"]
    causal = cs.validate_causal_story({
        "runtime_sec": round(spoken, 1),
        "hook": {"line": _text(script.get("hook"))},
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


def visual_style_suffix(framing: str = "") -> str:
    """Stable visual treatment shared by every evidence-state prompt.

    The round white head is the load-bearing detail, not decoration. A lane like this generates
    fifty to ninety images of the same people, and matching a detailed face across that many
    independent generations is the single hardest consistency problem there is. Both reference
    videos sidestep it entirely: heads are plain ovals with minimal features, and identity is
    carried by clothing colour, silhouette and prop instead. Asking for detailed faces would make
    inconsistency the loudest defect in the finished video.

    SINGLE SCENE, stated first and positively. A measured render came back as grids of numbered
    comic panels — "3. A WILD IDEA", "5. PUTTING THE PLAN IN MOTION" — with captions lettered into
    the artwork. Nothing forbade it: the negative prompt banned "comic-book superhero style", which
    is an aesthetic, not a layout, and "one unmistakable story action per frame" sat buried
    mid-paragraph where it read as a style note. Generators weight an opening positive instruction
    far more heavily than a clause in the middle or an entry on a negative list.
    """
    return (
        " Compose ONE single continuous scene that fills the whole frame: a single moment, seen "
        "once, from one camera. Never a grid, never panels, never a storyboard sheet, never "
        "borders, gutters, insets, numbered boxes or caption strips. "
        " Visual treatment: hand-drawn editorial history illustration on warm parchment. "
        "Minimalist human figures with round white heads, small simple black facial features, "
        "thin expressive limbs, and simple period-appropriate clothing. Identity is carried by "
        "clothing colour, silhouette, headwear and props — never by facial detail. Visible ink "
        "contour lines, soft watercolour and gouache shading, muted ochre, rust, umber, sage and "
        "desaturated teal. Readable silhouettes, layered foreground, middle ground and "
        "background, one unmistakable story action per frame, and clear negative space in the "
        "lower third for captions. Reuse the same clothing colours, props and location design "
        "whenever they recur. Composition must read instantly at phone size."
        + framing
        + " No text, letters, numbers, labels, arrows, UI, watermark, or accidental writing; "
        "the renderer adds all typography and diagram overlays."
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
        "photorealism, cinematic photography, 3D render, plastic skin, anime, comic-book "
        "superhero style, detailed rendered faces, excessive detail, distorted hands, extra "
        "limbs, watermarks, modern clothing, inconsistent characters, crowded "
        "focal point, multiple unrelated actions, generic stock illustration"
    )
