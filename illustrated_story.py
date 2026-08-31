"""Small, deterministic creative layer for illustrated long-form explainers.

This module deliberately does not render media, call providers, or replace the existing
long-form pipeline.  It gives the proven pipeline two things only:

* a story-first direction for its existing script call; and
* a normalized storyboard that records intent and continuity before asset spend.

Keeping those responsibilities pure makes the lane cheap to test and safe to remove.
"""
from __future__ import annotations

from typing import Any


CINEMATIC = "cinematic"
ILLUSTRATED_STORY = "illustrated_story"
SUPPORTED_STYLES = {CINEMATIC, ILLUSTRATED_STORY}
SCHEMA_VERSION = "illustrated_story_v1"

_ROLE_BANDS = (
    (0.00, "hook"),
    (0.12, "goal"),
    (0.25, "plan"),
    (0.42, "attempt"),
    (0.60, "complication"),
    (0.76, "reversal"),
    (0.88, "explanation"),
    (0.96, "payoff"),
)
_LOCATION_BY_ROLE = {
    "hook": "opening_location",
    "goal": "opening_location",
    "plan": "planning_location",
    "attempt": "action_location",
    "complication": "action_location",
    "reversal": "consequence_location",
    "explanation": "consequence_location",
    "payoff": "opening_location",
    "callback": "opening_location",
}


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
    """Add one compact story contract without introducing another model call."""
    base = f"""
ILLUSTRATED STORY CREATIVE — REQUIRED FOR THIS VIDEO:
Tell one continuous causal story about: {question}
Follow Alex, or one clearly identified human group, pursuing a concrete goal. Give them an
initial belief and a visible plan. Every scene must change the situation: decision -> action ->
result -> reaction -> next decision. Do not write an enumerated fact list.
State the central answer within the first 20 percent, then earn it by showing the causal path.
Use at most four recurring locations and a small set of recurring props. Return to the opening
location or object in the final scene. Keep Bolt selective: he may assist, measure, warn, or react,
but he is not automatically present.
Write visuals as simple actions and state changes suitable for a hand-drawn editorial storybook.
Do not request cinematic photography, abstract symbolism, decorative montage, or text inside
generated images. Maps, arrows, labels, counters, and captions are added by the renderer.
""".strip()
    extra = _text(operator_direction)
    return base if not extra else f"{base}\n\nOPERATOR DIRECTION:\n{extra}"


def _role_for(index: int, count: int) -> str:
    if index == count - 1:
        return "callback"
    pct = index / max(1, count - 1)
    role = "hook"
    for floor, candidate in _ROLE_BANDS:
        if pct >= floor:
            role = candidate
    return role


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

    beats = []
    for index, scene in enumerate(scenes):
        narration = _text(scene.get("narration"))
        if not narration:
            raise ValueError(f"Illustrated Story scene {index + 1} has no narration.")
        role = _role_for(index, len(scenes))
        intent = _text(scene.get("human_intention")) or goal
        belief = _text(scene.get("human_belief")) or _text(contract.get("accepted_belief"))
        expected = _text(scene.get("expected_outcome"))
        actual = (
            _text(scene.get("actual_outcome"))
            or _text(scene.get("visible_consequence"))
            or _first_visual(scene)
        )
        location_id = _LOCATION_BY_ROLE[role]
        beat = {
            "scene_index": index,
            "role": role,
            "location_id": location_id,
            "protagonist": protagonist,
            "intent": intent,
            "belief_before": belief,
            "action_or_evidence": _first_visual(scene),
            "expected_result": expected,
            "actual_result": actual,
            "next_question": (
                _text(scene.get("question_opened"))
                or _text(scene.get("new_complication"))
                or _text(scene.get("causal_link"))
            ),
            "narration_anchor": " ".join(narration.split()[:12]),
            "return_object": opening_object if role == "callback" else "",
        }
        scene["_illustrated_beat"] = beat
        beats.append(beat)

    locations = sorted({beat["location_id"] for beat in beats})
    validation_errors = []
    if beats[0]["role"] != "hook":
        validation_errors.append("first beat must be the hook")
    if beats[-1]["role"] != "callback":
        validation_errors.append("last beat must return to the opening")
    if len(locations) > 4:
        validation_errors.append("storyboard exceeds the four-location continuity budget")
    if any(not beat["intent"] for beat in beats):
        validation_errors.append("every beat requires protagonist intent")

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
            "character_model": "simple recurring illustrated Alex",
            "palette": ["warm parchment", "ochre", "rust", "ink black", "muted teal"],
            "location_budget": 4,
            "locations": locations,
            "generated_text": False,
        },
        "beats": beats,
        "validation": {"passed": not validation_errors, "errors": validation_errors},
    }
    script["_illustrated_story"] = storyboard
    return storyboard


def visual_style_suffix(framing: str = "") -> str:
    """Stable visual treatment shared by every evidence-state prompt."""
    return (
        " Visual treatment: hand-drawn editorial storybook illustration on warm parchment, "
        "clean ink outlines, simple readable shapes, restrained ochre/rust/muted-teal palette, "
        "shallow print-like shading, and one unambiguous action or state change. Reuse the same "
        "illustrated Alex identity, clothing, props, and location design whenever they recur. "
        "Composition must read instantly at phone size. Not photorealistic, not 3D, not glossy, "
        "not cinematic concept art, and not an unrelated decorative montage."
        + framing
        + " No text, letters, numbers, labels, arrows, UI, watermark, or accidental writing; "
        "the renderer adds all typography and diagram overlays."
    )
