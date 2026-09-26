"""Fail-closed evidence-state and continuity contracts for long-form explainers."""

from __future__ import annotations

import hashlib
import math
import re
import shutil
from pathlib import Path
from typing import Any


PURE_EVIDENCE_PURPOSES = {"evidence", "mechanism", "scale", "location", "record", "diagram"}
USEFUL_BOLT_PURPOSES = {
    "action", "assistance", "decision", "demonstration", "measurement", "reaction", "test",
    "warning",
}
ASSET_STRATEGIES = {"master", "distinct", "detail_reframe", "exact_reuse"}
ACCEPTED_ASSET_STATUSES = {"accepted", "reused_exact"}
MIN_EVIDENCE_STATE_SECONDS = 1.5
# Imported rather than redefined: a second copy of this number is how the runtime
# contract ended up 34% wrong while agreeing with itself.
from runtime_planner import DEFAULT_WORDS_PER_SECOND as WORDS_PER_SECOND

import nature_channel


def _text(value: Any) -> str:
    return str(value or "").strip()


def _slug(value: str, fallback: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", _text(value).casefold()).strip("-")
    return (clean[:48] or fallback).strip("-")


def _stable_id(prefix: str, value: str, fallback: str) -> str:
    slug = _slug(value, fallback)
    digest = hashlib.sha1(_text(value).casefold().encode("utf-8")).hexdigest()[:8]
    return f"{prefix}:{slug}:{digest}"


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    if _text(value):
        return [_text(value)]
    return []


def _issue(code: str, message: str, *, scene: int | None = None,
           state_id: str = "") -> dict:
    result = {"code": code, "message": message}
    if scene is not None:
        result["scene"] = scene
    if state_id:
        result["state_id"] = state_id
    return result


def _story_contract(script: dict) -> dict:
    return script.get("_story_contract") if isinstance(script.get("_story_contract"), dict) else {}


def _opening_scene_count(scenes: list[dict]) -> int:
    if not scenes:
        return 0
    explicit = []
    for index, scene in enumerate(scenes):
        try:
            percent = float(scene.get("story_pct"))
        except (TypeError, ValueError):
            continue
        if percent <= 30:
            explicit.append(index)
    if explicit:
        return max(explicit) + 1
    return max(1, min(len(scenes), round(len(scenes) * 0.30)))


def build_continuity_pack(script: dict) -> dict:
    """Create stable IDs for the identities, clothing, first-act location, and callback object."""
    scenes = script.get("scenes") or []
    contract = _story_contract(script)
    opening_object = _text(contract.get("opening_object"))
    callback_object = _text(contract.get("final_callback_object"))
    first_anchor = next((_text(scene.get("continuity_anchor")) for scene in scenes
                         if _text(scene.get("continuity_anchor"))), "")
    location_label = _text(contract.get("recurring_location")) or first_anchor
    callback_scene = next((index for index, scene in reversed(list(enumerate(scenes)))
                           if _text(scene.get("story_role")).casefold() in
                           {"final_payoff", "resonant_end"}), max(0, len(scenes) - 1))
    opening_asset_id = "asset:s001:e01"
    return {
        "version": 1,
        # Which channel's rules the plan was drawn under, and the fixed look of the animal family
        # on a Nature episode. Empty for every other channel; nothing else here changes.
        "channel": _text(script.get("_topic_channel")),
        "subject_sheet": _text(script.get("_subject_sheet")),
        "human": {
            "identity_id": "character:alex:v1",
            "name": "Alex",
            "reference_asset_id": "reference:alex:human-model:v1",
            "clothing_id": "clothing:alex:navy-overshirt-gray-shirt:v1",
            "required_traits": [
                "same adult male face and apparent age", "short brown hair", "light stubble",
                "navy overshirt", "light gray T-shirt", "dark jeans", "dark sneakers",
            ],
        },
        "bolt": {
            "identity_id": "character:bolt:v1",
            "reference_asset_id": "reference:bolt:mascot:v1",
        },
        # Whether this story puts NAMED recurring characters on screen at all. A cast-free lane
        # draws the anonymous, period-coded figures the references actually use, and the rules
        # below that require Bolt to do useful work describe a lane that has a Bolt. Recorded on
        # the pack rather than read from the environment so the plan stays self-describing: an
        # artifact on disk says which contract it was built under.
        "cast": ("none" if not any(
            scene.get("mascot_present") or scene.get("human_present")
            for scene in (script.get("scenes") or [])) else "recurring"),
        "first_act_location": {
            "location_id": _stable_id("location", location_label, "recurring-first-act"),
            "label": location_label,
        },
        "opening_object": {
            "object_id": _stable_id("object", opening_object, "opening-object"),
            "label": opening_object,
            "opening_source_asset_id": opening_asset_id,
        },
        "callback": {
            # Existing illustrated flows keep the exact-opening callback by default. A specialized
            # flow may explicitly disable it when returning to frame one would reverse age,
            # chronology, or another one-way state change. Nature Story uses this for episodes
            # such as the harp seal; no legacy caller changes behavior without opting out.
            "enabled": bool(script.get("_allow_opening_callback", True)),
            "label": callback_object,
            "scene_index": callback_scene,
            "reuse_source_asset_id": opening_asset_id,
        },
        "opening_scene_count": _opening_scene_count(scenes),
    }


def _visual_beats(scene: dict) -> list[dict]:
    """Beats as objects, coercing a bare string rather than discarding it.

    The planner returns visual_beats as an array of objects, but a prompt edit once shifted it to
    an array of plain phrases -- and this dropped every one of them, silently, because they were
    not dicts. The scene then compiled to ZERO states, the opening gate rejected it, and the error
    said "every opening beat requires two to six evidence states" about a scene whose beats were
    all present and readable. A shape wobble should cost the extra fields, not the whole beat.
    """
    out: list[dict] = []
    for beat in scene.get("visual_beats") or []:
        if isinstance(beat, str) and _text(beat):
            out.append({"anchor_phrase": _text(beat)})
        elif isinstance(beat, dict) and _text(beat.get("anchor_phrase")):
            out.append(dict(beat))
    return out


def _derive_bolt_action(beat: dict, scene: dict, subject: str) -> str:
    """A concrete Bolt action, never a bare category word.

    The old fallback was `beat.bolt_action or scene.bolt_mode`, and that could not work:
    validate_longform_story forces bolt_mode into {measurement, demonstration, warning, reaction,
    assistance}, every one of which is a member of USEFUL_BOLT_PURPOSES — the exact set
    `action_is_specific` rejects. So whenever the model omitted bolt_action, the code substituted a
    value guaranteed to fail its own validator, and the run died on bolt_without_useful_action
    before any spend.

    Naming what the action is performed ON turns the category back into a specific action, which is
    what the check is actually asking for.
    """
    action = _text(beat.get("bolt_action"))
    if action and action.casefold() not in USEFUL_BOLT_PURPOSES:
        return action
    mode = _text(scene.get("bolt_mode")) or _text(beat.get("purpose")) or "demonstration"
    target = _text(subject) or _text(beat.get("visual"))
    if not target:
        return action or ""
    verb = {"measurement": "measures", "demonstration": "demonstrates", "warning": "warns about",
            "reaction": "reacts to", "assistance": "helps with", "test": "tests",
            "decision": "decides on", "action": "acts on"}.get(mode.casefold(), "demonstrates")
    return f"{verb} {target}"


def _state_from_beat(scene: dict, beat: dict, scene_index: int, state_index: int,
                     pack: dict, *, opening: bool) -> dict:
    purpose = _text(beat.get("purpose")).casefold() or ("setup" if state_index == 0 else "evidence")
    source = _text(beat.get("source")).casefold()
    strategy = _text(beat.get("asset_strategy")).casefold()
    if strategy not in ASSET_STRATEGIES:
        strategy = ("detail_reframe" if source in {"detail", "reframe", "crop"}
                    else ("distinct" if state_index or source in {"broll", "alternate", "distinct"}
                          else "master"))
    pure_evidence = bool(beat.get("pure_evidence", purpose in PURE_EVIDENCE_PURPOSES))
    # Scene-level mascot presence is permission, not a command to paste Bolt into every view.
    include_bolt = (bool(scene.get("mascot_present")) and not pure_evidence
                    and bool(beat.get("bolt_visible", purpose == "action")))
    include_human = bool(scene.get("human_present")) and bool(
        beat.get("human_visible", not pure_evidence or purpose in {"measurement", "test"}))
    # Cast-free means no recurring host, not an empty world. Frames where someone DOES something,
    # or where something is done TO someone, need the period-coded people who perform or suffer the
    # verb; otherwise a story about officials, farmers or workers becomes a slideshow of unattended
    # desks and landscapes.
    #
    # The default set used to be {action, decision, intervention, reaction, assistance}, and only
    # one of those five is a purpose the writer actually emits. Measured over 94 states of a
    # delivered film: setup 26, evidence 21, consequence 31, action 15, callback 1 -- so the rule
    # fired on 10 states, 11%, all of them `action`, and the other four names matched nothing.
    #
    # `consequence` is the one that matters and the one that was missing. It is the largest group
    # and it is precisely where a human figure supplies scale and stakes: a vine over a forest is a
    # texture, a vine over a forest with a farmer beneath it is a consequence. `setup` is left out
    # deliberately -- the opening establishes a place before anyone acts in it -- and the
    # pure-evidence purposes are excluded above, so a document or a diagram never grows a bystander.
    anonymous_people_required = bool(
        not pure_evidence
        and beat.get("anonymous_people_required", purpose in {
            "action", "consequence", "decision", "intervention", "reaction", "assistance",
        })
        and not include_human
    )
    people_allowed = nature_channel.people_allowed(pack.get("channel"))
    if not people_allowed:
        # Nature: the animal performs the verb. The rule above drew researchers beside the
        # penguins and people assembling the huddle (job 59d6106d).
        include_human = False
        include_bolt = False
        anonymous_people_required = False
    before = _text(beat.get("state_before"))
    after = _text(beat.get("state_after")) or _text(beat.get("visual"))
    required = _list(beat.get("required_objects"))
    if not required and after:
        required = [after]
    opening_label = _text(pack.get("opening_object", {}).get("label"))
    # The opening object's exact initial state belongs only to the establishing frame. Later
    # states must be free to transform that same object (lit candle -> extinguished candle).
    if scene_index == 0 and state_index == 0 and opening_label and opening_label not in required:
        required.append(opening_label)
    forbidden = _list(beat.get("forbidden_objects"))
    if pure_evidence and "Bolt" not in forbidden:
        forbidden.append("Bolt")
    if not people_allowed and nature_channel.FORBIDDEN_PEOPLE not in forbidden:
        # Forbidden objects reach the verifier, so a frame with a person is redrawn, not tolerated.
        forbidden.append(nature_channel.FORBIDDEN_PEOPLE)
    asset_id = f"asset:s{scene_index + 1:03d}:e{state_index + 1:02d}"
    source_asset_id = ""
    if strategy == "detail_reframe":
        # Reframe the state that immediately introduced the evidence, not always the master.
        source_index = max(1, state_index)
        source_asset_id = f"asset:s{scene_index + 1:03d}:e{source_index:02d}"
    references = []
    if include_human:
        references.extend([
            pack["human"]["reference_asset_id"], pack["human"]["clothing_id"]])
    if include_bolt:
        references.append(pack["bolt"]["reference_asset_id"])
    return {
        "state_id": f"state:s{scene_index + 1:03d}:e{state_index + 1:02d}",
        "asset_id": asset_id,
        "scene_index": scene_index,
        "opening": opening,
        "anchor_phrase": _text(beat.get("anchor_phrase")),
        "purpose": purpose,
        "visual": _text(beat.get("visual")) or after,
        "state_before": before,
        "state_after": after,
        "required_objects": required,
        "forbidden_objects": forbidden,
        "asset_strategy": strategy,
        "source_asset_id": source_asset_id,
        "detail_target": _text(beat.get("detail_target")),
        "pure_evidence": pure_evidence,
        "include_human": include_human,
        "include_bolt": include_bolt,
        "anonymous_people_required": anonymous_people_required,
        # `after` already falls back to beat["visual"] where it exists; referencing a bare `visual`
        # here was a NameError waiting for the first Bolt beat with no state_after — it would crash
        # instead of producing the incomplete_object_state_spec error this validator is built to
        # report.
        "bolt_action": _derive_bolt_action(beat, scene, after) if include_bolt else "",
        "reference_ids": references,
        "human_identity_id": pack["human"]["identity_id"] if include_human else "",
        "clothing_id": pack["human"]["clothing_id"] if include_human else "",
        "location_id": pack["first_act_location"]["location_id"] if opening else "",
        "opening_object_id": pack["opening_object"]["object_id"] if scene_index == 0 else "",
        # Planning metadata never awards a retention event. The asset verifier owns this field.
        "new_information": False,
        "verified_visible_information": False,
        "asset_status": "planned",
        "rejection_reasons": [],
    }


# The SLOWEST narration rate measured across real renders, not the planning average.
#
# runtime_planner.DEFAULT_WORDS_PER_SECOND is 2.86 and is the right number for predicting how
# long a script will run. It is the wrong number for sizing states. Holds are duration/count, so
# a scene that speaks SLOWER than average runs longer and holds each state longer -- sizing on
# the average leaves every slow scene over the ceiling. runtime_planner:41 records the spread
# from identical word counts across runs: 2.588 and 2.733 w/s.
#
# 2.588 / 3.5 gives a divisor of 9.06, which is where the prompt's hand-written "N/9" came from
# and why tests/test_state_count_matches_scene_duration pins 9 and records that N/10 "was tried
# first and breaks at several real scene lengths". Deriving from 2.86 reproduces exactly that
# rejected N/10.01. The literal was right; what was missing was the constant behind it.
SLOWEST_MEASURED_WORDS_PER_SECOND = 2.588
# The desired editorial rhythm is tighter than the rejection line. Planning directly against the
# 3.5s maximum made every ordinary result sit on the cliff: a slightly slow TTS read or one failed
# asset turned an otherwise valid scene into a hard failure. 2.75s is the centre of the requested
# 2-3 second cadence and leaves real recovery room while 3.5s remains the rendered hard ceiling.
TARGET_VISUAL_STATE_SECONDS = 2.75

# WHAT THE WRITER ACTUALLY RETURNS FOR ONE SCENE, measured rather than hoped for.
#
# states_required_for_words asks a scene of 122 words for 18 states. Across four delivered films
# the per-scene counts were:
#
#   [3, 3, 3, 3, 3, 7, 7, 7, 6, 7]   [4, 4, 3, 4, 9, 7, 7, 6, 8]
#   [4, 4, 4, 7, 7, 7, 6, 7]         [3, 3, 3, 3, 4, 4, 5]
#
# Never above 9, and 7 is the mode of every long scene. The ask is uncorrelated with the answer
# past that point: one 15.2s scene needing 6 returned 7, while scenes needing 14, 16 and 17
# returned 7, 6 and 7. Asking a single scene for eighteen distinct visible changes does not
# produce eighteen; it produces seven and a shortfall nobody priced.
#
# This is therefore a property of the producer, not a preference, and every downstream number has
# to be derived from it instead of from the ask. A scene longer than this many states can cover at
# the target cadence CANNOT be cut to cadence, however the prompt is worded.
MAX_STATES_PER_SCENE = 7


def illustratable_scene_seconds() -> float:
    """The longest scene that can still be cut at target cadence: 7 states x 2.75s."""
    return MAX_STATES_PER_SCENE * TARGET_VISUAL_STATE_SECONDS


def cadence_feasible_seconds(scene_count: int) -> float:
    """The longest runtime `scene_count` scenes can deliver at target cadence.

    The arithmetic nobody was doing. A 300s film built from 8 beats needs 98 states to hold 2.75s
    each; 8 scenes can supply 56. No prompt wording closes a 42-state gap -- the runtime was
    infeasible before a single image was bought, and the rendered gate only said so afterwards,
    as long_visual_hold, after about $5.
    """
    return max(0, int(scene_count or 0)) * illustratable_scene_seconds()



def states_required_for_words(words: int) -> int:
    """The state count a scene of this many words NEEDS, from the constants the gate measures.

    validate_evidence_timing computes `ceil(duration / MAX_VISUAL_STATE_SECONDS)` and the rendered
    gate fails `long_visual_hold` on the same threshold. The script prompt carried its own prose
    copy of that arithmetic -- "about 2.9 words per second ... AT LEAST N/9 states" -- with the
    rate, the divisor and the ceiling all written out as literals. Three numbers free to drift
    from the constants they restate.

    One function now, called by the prompt builder and by the opening-beat ceiling, so the count
    the writer is asked for is the count the gate measures. It reproduces the hand-tuned examples
    exactly -- 18->2, 27->3, 36->4, 45->5 -- and keeps going where prose stopped: 198->22.
    """
    words = max(0, int(words or 0))
    if not words:
        return 1
    seconds = words / SLOWEST_MEASURED_WORDS_PER_SECOND
    return max(1, math.ceil(seconds / TARGET_VISUAL_STATE_SECONDS))


def states_required_for_capacity(capacity: int) -> int:
    """The hold-derived requirement, recovered from a scene's state_capacity.

    validate_evidence_plan sees `state_capacity` -- `seconds // MIN_EVIDENCE_STATE_SECONDS` --
    not the narration, so it cannot call states_required_for_words directly. Inverting gives
    seconds within one 1.5s step, which is precise enough for a CEILING and errs upward, which is
    the safe direction: a ceiling that is slightly too generous accepts a good plan, one that is
    slightly too tight rejects a plan the writer was told to produce.
    """
    capacity = max(0, int(capacity or 0))
    if not capacity:
        return 1
    seconds = capacity * MIN_EVIDENCE_STATE_SECONDS
    return max(1, math.ceil(seconds / TARGET_VISUAL_STATE_SECONDS))


def state_count_rule() -> str:
    """The prompt sentence for how many evidence states a scene needs, generated not written.

    WHY THIS IS GENERATED. The hand-written version stated the correct scaling rule and then
    contradicted it in the next clause: "...needs AT LEAST N/9 states, rounded up: 18 words needs
    2, 27 words needs 3, 36 words needs 4, 45 words needs 5. Count the words in the scene you are
    writing and apply that. Within the first 30% of runtime use 3-4 states, later 2-4."

    Measured on a delivered 252.5s film, the model obeyed the concrete range and ignored the
    formula, in every scene:

        scene  words  rule demands  produced
            1     34             4         3
            4     39             5         3
            5    198            22         4
            6    177            20         4
            7    204            23         5

    Producing 3,3,3,3,4,4,5 -- "first 30% use 3-4, later 2-4" almost exactly. 25 states across
    252.5s is a 10.10s average hold against a 3.5s ceiling, which is `long_visual_hold` and
    `visual_state_cadence`, both hard failures, on both delivered films.

    Two things made the range win. It was concrete where the formula was arithmetic, and every
    worked example was a short scene -- the longest was 45 words, while real long-form scenes in
    this lane run to 204. A model given examples spanning 18-45 words has no anchor for 198 and
    falls back on the range it was handed.

    So: the range is gone, the examples are generated from the real distribution including the
    long end, and the arithmetic comes from the constants rather than from prose.
    """
    examples = ", ".join(
        f"{words} words needs {states_required_for_words(words)}"
        for words in (30, 60, 120, 200))
    return (
        "HOW MANY is arithmetic, not taste. Each state is held for the scene duration divided by "
        "the state count, and any hold longer than "
        f"{MAX_VISUAL_STATE_SECONDS} SECONDS is rejected downstream as a hard failure. Plan for "
        f"about {TARGET_VISUAL_STATE_SECONDS} seconds per state so normal variation and one "
        "recoverable asset miss do not put the edit on that cliff. Narration "
        f"can run as slow as {SLOWEST_MEASURED_WORDS_PER_SECOND} words per second, so a scene "
        f"of N words can run N/{SLOWEST_MEASURED_WORDS_PER_SECOND} seconds and needs "
        f"ceil(N / {SLOWEST_MEASURED_WORDS_PER_SECOND} / {TARGET_VISUAL_STATE_SECONDS}) states, "
        f"which is about N/7: {examples}. "
        "COUNT THE WORDS IN THE SCENE YOU JUST WROTE AND RETURN THAT MANY STATES. There is no "
        "upper band and no house style to fall back on: a long scene needs many states, and "
        "twenty-odd states in one scene is normal and correct when the narration is long enough "
        "to require them. Under-producing here is the single most common way this lane fails. "
        "If a scene would need more states than you can find distinct visible changes for, the "
        "scene is too long -- say less in it. Never answer that by adding a scene: the batch "
        "returns exactly one scene per assigned beat. ")


# MEASURED AFTER THE FIX, on the same topic, engine and duration as the film that exposed it
# (script-only harness, 300s, backfiring_solution):
#
#   scene  words  required  before  after
#       1     35         4       3      3
#       4     30         4       3      3
#       5    228        26       4      8
#       6    210        24       4      6
#       7    225        25       5      7
#   totals: 25 -> 33 states, average hold 10.10s -> 9.39s, ceiling 3.5s
#
# The rule change is real -- long scenes gained ~65% more states -- and it is NOT SUFFICIENT.
# Asked for 26 states in one scene the model returns 8, and it is not being stubborn: a 228-word
# scene runs 88 seconds, and there are not 26 distinct visible changes in 88 seconds of one
# argument. The instruction is now correct and the writer still cannot satisfy it.
#
# That makes SCENE LENGTH the binding constraint, not states per scene. Seven scenes across 300s
# is 43s per scene, and no prompt makes a 43-second scene densely illustratable. Scene count comes
# from the factual event count, and that is bounded further up: factual_plan_prompt asked for 57
# events, the planner returned 8, and it cannot honestly return many more because the research
# dossier held 19 verified claims. 19 claims cannot support 57 sourced events.
#
# So the chain is: claims -> events -> scenes -> scene length -> states -> holds. This function
# fixes the last link. Whoever takes the next one should start at the first: either research
# deeper for long runtimes, or cap scene length and accept more scenes per event, or stop
# offering 300s on a 19-claim dossier. Do not "fix" it by asking the model more loudly.


# TRIED AND NOT SHIPPED: a per-scene word ceiling.
#
# After the research scaling landed, the remaining gap was distribution -- 11 scenes, 656 words,
# split 14/20/20/18/24/23 then 113/98/99/103/124. The six short scenes each met the state
# requirement; all five long ones did not. Spread evenly that is 60 words a scene, 7 states each,
# and a ~3.3s hold: under the ceiling with nothing else changed. So a rule capping any scene at
# 64 words (SECONDS_PER_SCENE_TARGET at the slowest narration rate) looked like the last step.
#
# It did not work. Measured with the rule in place, the long scenes got LONGER -- 145/121/135/156
# against 113/98/99/103/124 without it -- and the average hold went 4.78s to 5.80s. One sample
# each way, so this is not proof it hurts; it is an absence of any evidence that it helps, which
# is the same reason the state rule's old "3-4 / 2-4" band had to go. Two prompt rules now ask the
# writer to say less in a long scene and both are ignored on exactly the scenes that matter.
#
# The pattern points somewhere else. In both runs scenes 1-7 ran 15-34 words and scenes 8-11 ran
# 121-156, and that split follows the CHUNK boundary: the ending batch is separately instructed to
# carry a false-relief beat, the final escalation, the final payoff, the callback to the opening
# object and a resonant close. It is long because it was asked for five things, not because the
# writer forgot a word limit. Whoever picks this up should start at that instruction, not at
# another ceiling.


def state_capacity(scene: dict, seconds: float | None = None) -> int:
    """How many evidence states this scene's runtime can physically hold.

    The same arithmetic _states_that_fit trims by, exposed so the validator can tell a scene that
    UNDER-PRODUCED states from one that could never carry two. A state must hold for at least
    MIN_EVIDENCE_STATE_SECONDS, so a beat under twice that -- roughly nine spoken words -- has room
    for exactly one however it is written.
    """
    if seconds is None:
        words = len(_text(scene.get("narration")).split())
        seconds = words / WORDS_PER_SECOND if words else 0.0
    if seconds <= 0:
        return 4
    return max(1, int(seconds // MIN_EVIDENCE_STATE_SECONDS))


def _states_that_fit(beats: list, scene: dict, seconds: float | None = None,
                     reserve: int = 0) -> list:
    """Trim a scene's beats to the number its RUNTIME can hold.

    Each state is held for scene_duration / state_count, and both ends are bounded: shorter than
    MIN_EVIDENCE_STATE_SECONDS reads as a flash frame, longer than MAX_VISUAL_STATE_SECONDS is
    rejected by the rendered gate. So the count is not a preference, it is arithmetic on the
    scene's own length -- and this used a flat beats[:4] regardless of duration.

    Run 9c1fa296 carried both failures at once: "3 states in 4.42s would force 1.47s flash frames"
    and "3 state(s) across 12.60s holds each for 4.20s". One number cannot serve a 4-second scene
    and a 13-second one.

    Only TRIMS. A scene with too few beats keeps them and the validator reports it, because adding
    a state means inventing a visual that no beat asked for -- the same line I held on claim
    references. Dropping a surplus beat merges coverage; fabricating one asserts content.
    """
    if not beats:
        return beats
    # MEASURED seconds when the caller has them. Fitting against the planned word count and
    # then aligning against real audio is how states that fit on paper failed to fit in fact --
    # the same planned-versus-measured split that made the runtime contract 34% wrong.
    if seconds is None:
        words = len(_text(scene.get("narration")).split())
        seconds = words / WORDS_PER_SECOND if words else 0.0
    if seconds <= 0:
        return beats[:4]
    # What the runtime can actually hold, with no floor bolted on.
    #
    # This was max(2, ...) so a motion-test fixture of ~2-second scenes would keep two states.
    # That made the function emit plans validate_evidence_timing rejects on the next check: a
    # 6-word scene is 2.1s, two states hold 1.05s each, under the 1.5s flash floor. A function
    # whose job is to fit states to runtime must not return a count that cannot fit.
    #
    # A scene too short for two states IS too short, and opening_state_count says so honestly.
    # The fixture was unrealistic -- real long-form scenes run 25-30 words -- and distorting
    # production arithmetic to satisfy it was the wrong way round.
    # `reserve` is screen time already promised to a state this function never sees. The callback
    # is appended to its scene AFTER this trim, so without the reservation the scene ends up at
    # capacity+1 and compile_scene_shots raises "cannot fit without sub-minimum cuts". Measured on
    # a 7.48s scene: capacity 4, plus the callback is 5, and 7.48/5 = 1.496 against a 1.5s floor.
    # It never bit while scenes ran 40s; it bites as soon as a beat is split into short parts.
    most = max(1, int(seconds // MIN_EVIDENCE_STATE_SECONDS) - max(0, int(reserve or 0)))
    fewest = max(1, math.ceil(seconds / MAX_VISUAL_STATE_SECONDS))
    return beats[:max(fewest, most)] if len(beats) > most else beats


def _promote_opening_reframe(states: list, scene_index: int, opening: bool,
                             capacity: int) -> list[dict]:
    """Let an opening beat earn its own image instead of deadlocking on an unmeetable rule.

    `insufficient_distinct_evidence_assets` requires an opening beat with room for two states to
    carry two GENERATED assets, or a detail reframe whose crop has been pixel-verified. At plan
    time no image exists, so `detail_verification_passed` cannot be true — it is only written after
    generation. The strategy is the model's choice: the script prompt offers
    master|distinct|detail_reframe per beat. So whenever the model picks `detail_reframe` for the
    opening's second beat, the run aborts with no repair path, before any media spend but after
    research, script, fact-check and claim repair are all paid for. Measured: one of four live
    attempts on the same topic died exactly here.

    Asking the model to choose differently is the pattern this file already rejects everywhere else
    -- `collapse_locations` counts frequencies rather than asking for four locations, `repair_chain`
    fixes role order rather than asking for it. Which strategy the opening's second state uses is
    not a judgement: if the opening needs two distinct assets and has one, the reframe becomes
    distinct and buys its own image. One extra generation, ~$0.045, against a ~$1.50 abort.

    `source_asset_id` MUST be cleared on promotion. A distinct state that still declares a source
    trips `missing_source_asset`'s sibling check and swaps one hard failure for another.

    Returns the repairs made, so the caller records what it changed rather than silently differing
    from the script.
    """
    if not opening or capacity < 2:
        return []
    generated = [state for state in states
                 if _text(state.get("asset_strategy")) in {"master", "distinct"}]
    if len(generated) >= 2:
        return []
    repairs = []
    for state in states:
        if len(generated) >= 2:
            break
        if _text(state.get("asset_strategy")) != "detail_reframe":
            continue
        state["asset_strategy"] = "distinct"
        state["source_asset_id"] = ""
        state["detail_target"] = ""
        generated.append(state)
        repairs.append({
            "code": "opening_reframe_promoted",
            "scene": scene_index + 1,
            "state_id": _text(state.get("state_id")),
            "message": ("Opening reframe promoted to a distinct generated asset so the opening "
                        "carries two; a plan-time crop cannot be pixel-verified."),
        })
    return repairs
def _anchor_key(phrase: str) -> str:
    """Compare anchors on words, not punctuation. "…back" and "…back." are the same span."""
    return " ".join(re.findall(r"[a-z0-9]+", _text(phrase).casefold()))


def _closing_anchor_phrase(scene: dict, existing_states: list) -> str:
    """A phrase from the tail of the narration, so the closing shot can be timed where it plays.

    The callback returns to the opening object after the answer has landed, so it is always the
    last shot of its scene, and `compile_scene_shots` requires monotonically increasing starts.
    Its anchor therefore has to resolve LATER than every anchor before it.

    Two cases, and the second is the one that bites. Usually the final clause is unclaimed and is
    exactly right. But the scene's last evidence state often already owns that clause -- measured
    on a real render, state `e04` held "Now nothing could pull them back" and the whole clause was
    the tail. Reusing it resolves to the same instant, the gap is zero, and the scene collapses
    just as surely as an anchor from the beginning would. So when the tail is taken, fall back to
    a strict SUFFIX of it: fewer words, starting later, still verbatim on the page.
    """
    narration = _text(scene.get("narration"))
    if not narration:
        # Nothing to derive a position from. Ordering is moot here too -- without narration there
        # are no measured word timings, so `compile_scene_shots` never runs its monotonic check on
        # this scene. Keep the historical sources so a script that predates narration on the final
        # scene still carries an anchor for the caption and the audit trail.
        return (_text(scene.get("motion_anchor_phrase"))
                or _text((existing_states or [{}])[-1].get("anchor_phrase")))
    taken = {_anchor_key(state.get("anchor_phrase"))
             for state in existing_states or [] if _text(state.get("anchor_phrase"))}
    words = narration.split()

    clauses = [part.strip() for part in re.split(r"(?<=[.!?;:])\s+|,\s+", narration) if part.strip()]
    if clauses:
        tail = clauses[-1]
        tail_words = tail.split()
        candidate = " ".join(tail_words[-6:]) if len(tail_words) > 6 else tail
        if _anchor_key(candidate) not in taken and len(candidate.split()) >= 2:
            return candidate

    # The tail is already anchored. Walk in from its end, shortest first, so the phrase we return
    # starts as late as the narration allows while staying at least two words long.
    for size in (2, 3, 4):
        if size > len(words):
            break
        suffix = " ".join(words[-size:])
        if _anchor_key(suffix) not in taken:
            return suffix
    return " ".join(words[-3:]) if len(words) >= 3 else narration


def compile_evidence_plan(script: dict, scene_seconds: dict | None = None) -> dict:
    """Compile narration beats into explicit visual states without pretending crops are evidence."""
    scenes = script.get("scenes") or []
    measured = scene_seconds or {}
    pack = build_continuity_pack(script)
    opening_count = int(pack["opening_scene_count"])
    scene_plans = []
    repairs: list[dict] = []
    # Known before the loop so the scene that will receive it can budget for it.
    callback_enabled = bool(pack.get("callback", {}).get("enabled", True))
    reserved_for_callback = (int(pack.get("callback", {}).get("scene_index", -1))
                             if callback_enabled else -1)
    for scene_index, scene in enumerate(scenes):
        opening = scene_index < opening_count
        capacity = state_capacity(scene, measured.get(scene_index))
        beats = _visual_beats(scene)
        states = [
            _state_from_beat(scene, beat, scene_index, state_index, pack, opening=opening)
            for state_index, beat in enumerate(
                _states_that_fit(beats, scene, measured.get(scene_index),
                                 reserve=1 if scene_index == reserved_for_callback else 0))
        ]
        repairs.extend(_promote_opening_reframe(states, scene_index, opening, capacity))
        seconds = measured.get(scene_index)
        previous_states = scene_plans[-1]["states"] if scene_plans else []
        if (seconds is not None and 0 < float(seconds) < MIN_EVIDENCE_STATE_SECONDS
                and previous_states and states):
            # A scene too short to hold one image ("There is no nest." at 1.10s, job c96cb9dc)
            # keeps the previous scene's last image on screen instead of cutting to a flash
            # frame. One exact-reuse state, anchored at the scene's first words, so the shot
            # compiler has a state and the viewer sees no cut.
            held = previous_states[-1]
            first_words = " ".join(_text(scene.get("narration")).split()[:4])
            states = [dict(
                held,
                state_id=f"state:s{scene_index + 1:03d}:e01",
                asset_id=f"asset:s{scene_index + 1:03d}:e01",
                scene_index=scene_index,
                opening=opening,
                anchor_phrase=first_words or _text(held.get("anchor_phrase")),
                purpose="continuation",
                visual=f"Hold the previous image: {_text(held.get('state_after'))}",
                state_before=_text(held.get("state_after")),
                state_after=f"{_text(held.get('state_after'))} (held while the line lands)",
                asset_strategy="exact_reuse",
                source_asset_id=_text(held.get("asset_id")),
                detail_target="",
                new_information=False,
                verified_visible_information=False,
                asset_status="planned",
                rejection_reasons=[],
            )]
            repairs.append({
                "code": "short_scene_holds_previous_image",
                "state_id": states[0]["state_id"],
                "message": f"scene {scene_index + 1} measures {float(seconds):.2f}s, under the "
                           f"{MIN_EVIDENCE_STATE_SECONDS}s state minimum; it reuses "
                           f"{states[0]['source_asset_id']}",
            })
        scene_plans.append({
            "scene_index": scene_index,
            "story_role": _text(scene.get("story_role")),
            "evidence_id": _text(scene.get("evidence_id")),
            "opening": opening,
            "state_capacity": capacity,
            "states": states,
        })

    callback_index = int(pack["callback"]["scene_index"])
    if callback_enabled and scene_plans and 0 <= callback_index < len(scene_plans):
        callback_states = scene_plans[callback_index]["states"]
        callback_scene = scenes[callback_index]
        # The callback is the LAST shot of the video by construction -- it returns to the opening
        # object once the answer has landed -- so its anchor has to be at the END of the narration.
        # Both previous sources guaranteed the opposite. `motion_anchor_phrase` is chosen for
        # motion, not for position, and the fallback took the PRECEDING state's anchor, which by
        # definition is not after it.
        #
        # Measured on a real render: the callback for a 22.2-second scene was anchored to
        # "the toads marched" -- word 9 of 59, about 3.4s in -- while the state before it started
        # at 19.9s. `compile_scene_shots` requires monotonically increasing starts, so the check
        # failed and the ENTIRE five-state scene fell back to even spacing, losing alignment on
        # four cuts that had resolved perfectly. One misplaced anchor, a whole scene of visuals
        # detached from the words they describe.
        callback_anchor = _closing_anchor_phrase(callback_scene, callback_states)
        ends_on_young = (not nature_channel.people_allowed(pack.get("channel"))
                         and len(callback_states) >= 2)
        if ends_on_young:
            # Nature ends on the young being fed, not on the egg. The callback still returns to
            # the exact opening asset, but at the HEAD of the closing scene ("look again at that
            # single egg"), in place of its first planned state, and the scene's last planned
            # state stays the final shot. The first penguin long-form closed on the egg while
            # the narration said the chick was fed.
            replaced = callback_states[0]
            callback_anchor = _text(replaced.get("anchor_phrase")) or callback_anchor
            for later in callback_states[1:]:
                if _text(later.get("source_asset_id")) == _text(replaced.get("asset_id")):
                    later["source_asset_id"] = ""
                    later["asset_strategy"] = "distinct"
        callback_state = {
            "state_id": f"state:s{callback_index + 1:03d}:callback",
            "asset_id": f"asset:s{callback_index + 1:03d}:callback",
            "scene_index": callback_index,
            "opening": False,
            "anchor_phrase": callback_anchor,
            "purpose": "callback",
            "visual": f"Return to the exact opening object: {pack['opening_object']['label']}",
            "state_before": "the object carried the opening anomaly",
            "state_after": "the same object is reinterpreted by the final answer",
            "required_objects": [pack["opening_object"]["label"]],
            "forbidden_objects": [],
            "asset_strategy": "exact_reuse",
            "source_asset_id": pack["callback"]["reuse_source_asset_id"],
            "detail_target": "",
            "pure_evidence": False,
            "include_human": False,
            "include_bolt": False,
            "reference_ids": [],
            "human_identity_id": "",
            "clothing_id": "",
            "location_id": "",
            "opening_object_id": pack["opening_object"]["object_id"],
            "new_information": False,
            "verified_visible_information": False,
            "asset_status": "planned",
            "rejection_reasons": [],
        }
        if ends_on_young:
            callback_states[0] = callback_state
        else:
            callback_states.append(callback_state)
    # A planned state whose before equals its after is a MASTER that establishes something, not
    # a change; the planner wrote "whole intact ice sheet" on both sides of an establishing shot
    # and the validator refused the whole plan after research, script, ledger and storyboard were
    # bought (job 60b97bcf, 2026-09-25). The visible change of an establishing shot is from the
    # previous shot, so the before is the previous state's after; with no previous state, or an
    # identical one, the before is marked as not yet shown. Recorded as a repair, never silent.
    previous_after = ""
    for scene_plan in scene_plans:
        for state in scene_plan.get("states") or []:
            # A state cannot require an object AND forbid it exposed: "warm-coral egg" required,
            # "exposed egg" forbidden, "pouch clearly covering egg" after. Two redraws and a
            # rejection later the render refused (job 45711ddf). The covering object is the
            # proof; the bare object is dropped from the requirement so a covered egg can pass.
            hidden = [f for f in (state.get("forbidden_objects") or [])
                      if re.match(r"^(exposed|visible|uncovered|bare|open)\b", _text(f).lower())]
            if hidden:
                nouns = {w for f in hidden for w in re.findall(r"[a-z]{3,}", _text(f).lower())
                         if w not in ("exposed", "visible", "uncovered", "bare", "open")}
                kept, dropped = [], []
                for required_object in state.get("required_objects") or []:
                    words = set(re.findall(r"[a-z]{3,}", _text(required_object).lower()))
                    covering = re.search(r"\b(over|covering|under|beneath|inside|tucked)\b",
                                         _text(required_object).lower())
                    if words & nouns and not covering:
                        dropped.append(required_object)
                    else:
                        kept.append(required_object)
                if dropped and kept:
                    state["required_objects"] = kept
                    repairs.append({
                        "code": "required_object_conflicts_with_forbidden",
                        "state_id": _text(state.get("state_id")),
                        "message": f"dropped required {dropped} because {hidden} is forbidden; "
                                   f"kept {kept}",
                    })
            before = _text(state.get("state_before"))
            after = _text(state.get("state_after"))
            if after and before.casefold() == after.casefold():
                if previous_after and previous_after.casefold() != after.casefold():
                    state["state_before"] = previous_after
                else:
                    state["state_before"] = f"not yet shown: {after}"
                repairs.append({
                    "code": "unchanged_evidence_state_repaired",
                    "state_id": _text(state.get("state_id")),
                    "message": f"before equalled after ({after!r}); before is now the "
                               f"previous shot ({state['state_before']!r})",
                })
            if after:
                previous_after = after
    plan = {"version": 1, "continuity_pack": pack, "scenes": scene_plans, "repairs": repairs}
    plan["validation"] = validate_evidence_plan(plan)
    return plan


MAX_VISUAL_STATE_SECONDS = 3.5


def validate_evidence_plan(plan: dict, *, require_verified_assets: bool = False,
                           opening_only: bool = False) -> dict:
    errors: list[dict] = []
    pack = plan.get("continuity_pack") if isinstance(plan, dict) else None
    scenes = plan.get("scenes") if isinstance(plan, dict) else None
    if not isinstance(pack, dict):
        errors.append(_issue("missing_continuity_pack", "The evidence plan has no continuity pack."))
        pack = {}
    if not isinstance(scenes, list) or not scenes:
        errors.append(_issue("missing_evidence_scenes", "The evidence plan contains no scenes."))
        scenes = []

    opening_cuts = []
    compiled_states = []
    useful_bolt_states = []
    seen_state_ids: set[str] = set()
    seen_asset_ids: set[str] = set()
    for scene_plan in scenes:
        scene_index = int(scene_plan.get("scene_index") or 0)
        states = scene_plan.get("states") if isinstance(scene_plan.get("states"), list) else []
        opening = bool(scene_plan.get("opening"))
        # Upper bound raised from 4 to 6. The hold ceiling is physics -- a state held longer
        # than MAX_VISUAL_STATE_SECONDS is rejected downstream -- and a 45-word opening scene
        # needs 5 states to satisfy it. Capping at 4 made such a scene unsatisfiable: two rules,
        # each defensible, that cannot both hold.
        #
        # The floor is now conditioned on the same physics, for the same reason. A state must hold
        # MIN_EVIDENCE_STATE_SECONDS, so a beat shorter than twice that -- about nine spoken words
        # -- has room for exactly one state however it is written, and demanding two of it is a
        # rule that cannot be satisfied rather than a defect it can report. The causal lane writes
        # exactly such beats ON PURPOSE: it caps the hinge at ten words because "a long hinge is
        # not a hinge", and its intervention and false_resolution beats are deliberately curt.
        # Held to the old floor, a five-word "Cash for every dead cobra." was unrenderable by
        # construction, and the two contracts could not both hold on the same script.
        #
        # A one-state opening beat is still a still frame, and for a beat with the runtime to do
        # better that is still an error. This exempts only the beats physics already decided for.
        capacity = int(scene_plan.get("state_capacity") or 0)
        floor = 2 if capacity >= 2 else 1
        # The ceiling has to move with the narration, or it contradicts the hold rule. Six was a
        # flat literal: fine for a 40-word opening, which needs 4, and unsatisfiable for a
        # 100-word one, which needs 10 to stay under MAX_VISUAL_STATE_SECONDS. A writer told to
        # produce the hold-derived count and then failed for producing it has been handed two
        # rules that cannot both hold -- the same shape as the 3-4/2-4 band this lane just lost.
        # Six remains the floor of the ceiling, so nothing tightens for a short opening.
        ceiling = max(6, states_required_for_capacity(capacity))
        if opening and not floor <= len(states) <= ceiling:
            errors.append(_issue(
                "opening_state_count",
                f"Every opening beat requires {floor} to {ceiling} evidence states."
                + ("" if floor == 2 else
                   " This beat is too short to hold two, so one is the whole budget."),
                scene=scene_index + 1))
        accepted_distinct = set()
        verified_detail = False
        for state_index, state in enumerate(states):
            if _text(state.get("purpose")) != "callback":
                compiled_states.append(state)
            state_id = _text(state.get("state_id"))
            asset_id = _text(state.get("asset_id"))
            if not state_id or state_id in seen_state_ids:
                errors.append(_issue("invalid_state_id", "Evidence state IDs must be present and unique.",
                                     scene=scene_index + 1, state_id=state_id))
            if not asset_id or asset_id in seen_asset_ids:
                errors.append(_issue("invalid_asset_id", "Evidence asset IDs must be present and unique.",
                                     scene=scene_index + 1, state_id=state_id))
            seen_state_ids.add(state_id)
            seen_asset_ids.add(asset_id)
            for field in ("state_before", "state_after", "required_objects", "forbidden_objects"):
                value = state.get(field)
                if (field.endswith("objects") and not isinstance(value, list)) or (
                        not field.endswith("objects") and not _text(value)):
                    errors.append(_issue(
                        "incomplete_object_state_spec",
                        f"Evidence state is missing {field}.", scene=scene_index + 1,
                        state_id=state_id))
            if not state.get("required_objects"):
                errors.append(_issue(
                    "missing_required_objects", "Every evidence state must name visible proof.",
                    scene=scene_index + 1, state_id=state_id))
            if (_text(state.get("state_before")).casefold()
                    == _text(state.get("state_after")).casefold()):
                errors.append(_issue(
                    "unchanged_evidence_state", "State before and after are not visibly different.",
                    scene=scene_index + 1, state_id=state_id))
            strategy = _text(state.get("asset_strategy"))
            if strategy not in ASSET_STRATEGIES:
                errors.append(_issue("invalid_asset_strategy", "Unknown evidence asset strategy.",
                                     scene=scene_index + 1, state_id=state_id))
            if strategy == "detail_reframe" and state.get("new_information") is True \
                    and not state.get("detail_verification_passed"):
                errors.append(_issue(
                    "unverified_reframe_information",
                    "A reframe cannot claim new information before detail verification passes.",
                    scene=scene_index + 1, state_id=state_id))
            if state.get("pure_evidence") and state.get("include_bolt"):
                errors.append(_issue(
                    "bolt_in_pure_evidence", "Pure evidence assets must omit Bolt.",
                    scene=scene_index + 1, state_id=state_id))
            if state.get("pure_evidence") and "bolt" not in {
                    _text(item).casefold() for item in state.get("forbidden_objects") or []}:
                errors.append(_issue(
                    "bolt_not_forbidden_in_evidence",
                    "Pure evidence must explicitly forbid Bolt in the generated pixels.",
                    scene=scene_index + 1, state_id=state_id))
            if state.get("include_bolt"):
                purpose = _text(state.get("purpose")).casefold()
                action = _text(state.get("bolt_action"))
                action_is_specific = bool(action) and action.casefold() not in USEFUL_BOLT_PURPOSES
                # TWO VOCABULARIES, one set. USEFUL_BOLT_PURPOSES is the bolt_mode category list --
                # _derive_bolt_action names it as exactly that -- and it was also being required to
                # contain the STATE's purpose, which comes from the visual beat and reads setup /
                # action / evidence / consequence / callback. The two overlap only on "action", so
                # Bolt was legal in an action state and nowhere else, and a state carrying
                # "Bolt recoils, shocked, from the wave of released cobras" failed a check whose
                # message says the action must be concrete. It was; its purpose was "consequence".
                #
                # Where Bolt must not appear is already stated once, as PURE_EVIDENCE_PURPOSES, and
                # enforced by bolt_not_forbidden_in_evidence above. That is the purpose rule; this
                # one is about the action being real. Both are checked, neither restates the other.
                if purpose in PURE_EVIDENCE_PURPOSES or not action_is_specific:
                    errors.append(_issue(
                        "bolt_without_useful_action",
                        "Every compiled Bolt state must declare a concrete useful action, not merely "
                        "repeat its measurement, test, reaction, warning, assistance, or decision category.",
                        scene=scene_index + 1, state_id=state_id))
                else:
                    useful_bolt_states.append(state)
            refs = state.get("reference_ids") if isinstance(state.get("reference_ids"), list) else []
            if bool(state.get("include_human")) != (pack.get("human", {}).get("reference_asset_id") in refs):
                errors.append(_issue(
                    "human_reference_mismatch", "Human reference inclusion is not deterministic.",
                    scene=scene_index + 1, state_id=state_id))
            expected_bolt_ref = bool(state.get("include_bolt")) and not state.get("pure_evidence")
            if expected_bolt_ref != (pack.get("bolt", {}).get("reference_asset_id") in refs):
                errors.append(_issue(
                    "bolt_reference_mismatch", "Bolt reference inclusion is not deterministic.",
                    scene=scene_index + 1, state_id=state_id))
            if strategy in {"detail_reframe", "exact_reuse"} and not _text(state.get("source_asset_id")):
                errors.append(_issue(
                    "missing_source_asset", "Reframe/reuse state has no declared source asset.",
                    scene=scene_index + 1, state_id=state_id))
            verify_state = require_verified_assets and (not opening_only or opening)
            if verify_state:
                if _text(state.get("asset_status")) not in ACCEPTED_ASSET_STATUSES:
                    errors.append(_issue(
                        "rejected_or_missing_asset", "Evidence asset was not explicitly accepted.",
                        scene=scene_index + 1, state_id=state_id))
                if strategy in {"master", "distinct", "exact_reuse"} and \
                        _text(state.get("asset_status")) in ACCEPTED_ASSET_STATUSES:
                    accepted_distinct.add(_text(state.get("asset_id")))
                if strategy == "detail_reframe" and state.get("detail_verification_passed"):
                    verified_detail = True
            else:
                if strategy in {"master", "distinct"}:
                    accepted_distinct.add(_text(state.get("asset_id")))
                if strategy == "detail_reframe" and state.get("detail_verification_passed"):
                    verified_detail = True
            if opening and state_index > 0:
                opening_cuts.append(state)
        # The twin of the state-count floor above, and it needs the same physics guard. Two
        # DISTINCT assets cannot come out of a beat with room for one state -- the rule was
        # demanding a second asset for a state that does not exist. Where the runtime can hold two
        # states, needing two distinct assets is still a real contract and still reported.
        if (opening and capacity >= 2 and len(accepted_distinct) < 2
                and not verified_detail):
            errors.append(_issue(
                "insufficient_distinct_evidence_assets",
                "Opening beats need two distinct source/state assets unless a detail reframe is verified.",
                scene=scene_index + 1))

    # `or {}` on each, not just the isinstance guard on `pack`. A pack that exists but carries a
    # null opening_object made this raise AttributeError instead of reporting the missing identity,
    # and the caller that catches it treats an exception as "checkpoint unreadable" -- so an
    # incomplete plan was indistinguishable from a corrupt one.
    opening_object = (pack.get("opening_object") if isinstance(pack, dict) else {}) or {}
    callback = (pack.get("callback") if isinstance(pack, dict) else {}) or {}
    if not _text(opening_object.get("object_id")) or not _text(opening_object.get("label")):
        errors.append(_issue("missing_opening_object_identity", "Opening object identity is incomplete."))
    if bool(callback.get("enabled", True)):
        if _text(callback.get("reuse_source_asset_id")) != _text(opening_object.get("opening_source_asset_id")):
            errors.append(_issue("callback_asset_mismatch", "Ending does not reuse the exact opening source asset."))
        if _text(callback.get("label")).casefold() != _text(opening_object.get("label")).casefold():
            errors.append(_issue("callback_object_mismatch", "Ending callback object differs from the opening object."))
    human = (pack.get("human") if isinstance(pack, dict) else {}) or {}
    location = (pack.get("first_act_location") if isinstance(pack, dict) else {}) or {}
    if not _text(human.get("identity_id")) or not _text(human.get("clothing_id")):
        errors.append(_issue("incomplete_human_continuity", "Human identity or clothing lock is missing."))
    if not _text(location.get("location_id")) or not _text(location.get("label")):
        errors.append(_issue("incomplete_location_continuity", "First-act location lock is missing."))

    bolt_count = len(useful_bolt_states)
    bolt_ratio = bolt_count / max(1, len(compiled_states))
    # Only where the lane HAS a mascot. A cast-free story has no Bolt to give useful work to, and
    # demanding one turned "draw the period's own anonymous figures" into an unsatisfiable plan.
    cast_mode = _text((pack or {}).get("cast")) or "recurring"
    if compiled_states and bolt_count == 0 and cast_mode != "none":
        errors.append(_issue(
            "missing_useful_bolt_state",
            "Long-form requires at least one compiled visual state where Bolt performs useful story work."))
    if bolt_ratio > 0.35:
        errors.append(_issue(
            "bolt_state_budget_exceeded",
            f"Bolt occupies {bolt_ratio:.0%} of compiled visual states; no more than 35% is allowed."))

    verified_cuts = sum(1 for state in opening_cuts if state.get("verified_visible_information"))
    ratio = verified_cuts / len(opening_cuts) if opening_cuts else 0.0
    if require_verified_assets and ratio < 0.70:
        errors.append(_issue(
            "opening_visible_information_ratio",
            f"Only {ratio:.0%} of opening cuts add verified visible information; 70% required."))
    return {
        "version": 1,
        "passed": not errors,
        "opening_cut_count": len(opening_cuts),
        "verified_information_cut_count": verified_cuts,
        "verified_information_ratio": round(ratio, 3),
        "compiled_visual_state_count": len(compiled_states),
        "useful_bolt_state_count": bolt_count,
        "bolt_visual_state_ratio": round(bolt_ratio, 3),
        "rejected_asset_count": sum(
            1 for scene in scenes for state in scene.get("states") or []
            if _text(state.get("asset_status")) == "rejected"),
        "errors": errors,
    }


def record_asset_verification(state: dict, *, asset_path: str,
                              verification: dict | None, generation_error: str = "") -> dict:
    """Record acceptance/rejection explicitly; never convert failure into a disguised reframe."""
    reasons = []
    if generation_error:
        reasons.append(generation_error)
    if not asset_path or not Path(asset_path).is_file():
        reasons.append("asset file is missing")
    if not isinstance(verification, dict):
        reasons.append("asset verifier unavailable or invalid")
    elif not verification.get("passed"):
        reasons.extend(_list(verification.get("reasons")) or ["asset verification failed"])
    state["asset_path"] = asset_path
    state["verification"] = verification or {}
    state["rejection_reasons"] = reasons
    if reasons:
        state["asset_status"] = "rejected"
        state["verified_visible_information"] = False
        state["new_information"] = False
        return state
    state["asset_status"] = ("reused_exact" if state.get("asset_strategy") == "exact_reuse"
                             else "accepted")
    visible = bool(verification.get("visible_information"))
    if state.get("asset_strategy") == "detail_reframe":
        state["detail_verification_passed"] = visible
    state["verified_visible_information"] = visible
    state["new_information"] = visible
    return state


def reuse_exact_asset(source_path: str, output_path: str) -> dict:
    """Copy a callback asset byte-for-byte and return a fail-closed verification result."""
    source = Path(source_path)
    output = Path(output_path)
    if not source.is_file():
        raise FileNotFoundError("exact opening-object source asset is unavailable")
    shutil.copyfile(source, output)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    matched = source_hash == output_hash
    return {
        "passed": matched,
        "visible_information": False,
        "source_sha256": source_hash,
        "exact_reuse_sha256": output_hash,
        "reasons": [] if matched else ["callback bytes differ"],
    }


def evidence_asset_counts(plan: dict) -> dict:
    states = [state for scene in plan.get("scenes") or [] for state in scene.get("states") or []]
    generated = [state for state in states if state.get("asset_strategy") in {"master", "distinct"}]
    reframes = [state for state in states if state.get("asset_strategy") == "detail_reframe"]
    reused = [state for state in states if state.get("asset_strategy") == "exact_reuse"]
    return {
        "planned_state_count": len(states),
        "distinct_source_count": len(generated),
        "reframe_count": len(reframes),
        "exact_reuse_count": len(reused),
        "accepted_count": sum(1 for state in states if state.get("asset_status") in ACCEPTED_ASSET_STATUSES),
        "rejected_count": sum(1 for state in states if state.get("asset_status") == "rejected"),
    }


def validate_evidence_timing(plan: dict, audio_timing: dict) -> dict:
    """Reject state density that would force flash frames before buying any images."""
    errors = []
    scene_timings = audio_timing.get("scenes") if isinstance(audio_timing, dict) else []
    scenes = plan.get("scenes") if isinstance(plan, dict) else []
    if len(scene_timings or []) != len(scenes or []):
        errors.append(_issue(
            "evidence_timing_count_mismatch", "Evidence scenes and measured audio scenes differ."))
        return {"version": 1, "passed": False, "errors": errors}
    intervals = []
    for scene_plan, timing in zip(scenes, scene_timings):
        count = len(scene_plan.get("states") or [])
        duration = float(timing.get("duration_sec") or 0.0)
        interval = duration / count if count else 0.0
        intervals.append(round(interval, 3))
        if count and interval < MIN_EVIDENCE_STATE_SECONDS:
            errors.append(_issue(
                "evidence_states_too_dense",
                f"{count} states in {duration:.2f}s would force {interval:.2f}s flash frames.",
                scene=int(scene_plan.get("scene_index") or 0) + 1))
        # The other side of the same interval. This guarded only the dense end, while the
        # rendered gate hard-fails the sparse end at MAX_VISUAL_STATE_SECONDS -- so a plan
        # could be approved here and be rejectable on arithmetic already known, with the
        # rejection arriving after every image and every second of narration was paid for.
        # A 2-state opening beat is explicitly permitted by opening_state_count and only
        # clears the ceiling if its scene runs under 7s; long-form scenes run about 13s.
        if count and interval > MAX_VISUAL_STATE_SECONDS:
            needed = math.ceil(duration / MAX_VISUAL_STATE_SECONDS)
            errors.append(_issue(
                "evidence_states_too_sparse",
                f"{count} state(s) across {duration:.2f}s holds each for {interval:.2f}s; the "
                f"rendered gate rejects any hold over {MAX_VISUAL_STATE_SECONDS}s. "
                f"Plan at least {needed} states.",
                scene=int(scene_plan.get("scene_index") or 0) + 1))
    return {
        "version": 1, "passed": not errors,
        "minimum_state_seconds": MIN_EVIDENCE_STATE_SECONDS,
        "maximum_state_seconds": MAX_VISUAL_STATE_SECONDS,
        "scene_average_state_seconds": intervals,
        "errors": errors,
    }
