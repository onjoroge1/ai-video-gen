"""Bolt Explains Nature: the rules that differ from the history and world lanes, in one place.

Every rule here is keyed on the channel string and returns the lane's default for any other
channel, so the illustrated history/world flow is byte-for-byte unchanged when this module is
consulted. The first emperor penguin long-form (job 59d6106d, 2026-09-24) showed four defaults
leaking in from the history references:

  * the causal lead tag "explained like you are five" spoken after the hook;
  * `anonymous_people_required` on 24 of 43 image states, which drew researchers beside the
    penguins and people apparently assembling the huddle;
  * a thumbnail headline ("DAD CAN'T MOVE 65 DAYS") carrying a number the narration never says,
    over a flaming skull drawn by the "threat looms from the right" formula;
  * a script graded 67/100 rendered anyway under the advisory profile.

Callers: explainer_pipeline (format tag, evidence prompt cast line, script floor, thumbnail) and
longform_evidence (state builder, continuity pack).
"""
from __future__ import annotations

import re

from nature_story_flow import NATURE_WRITING_CONTRACT

NATURE = "nature"

# Forbidden in every Nature image state. Handed to the evidence verifier as forbidden objects, so
# a frame with a person in it is rejected and redrawn rather than merely discouraged.
FORBIDDEN_PEOPLE = ("any human being, person, researcher, observer, expedition member, human hand, "
                    "human clothing, tent, vehicle, camera, notebook or other human-made equipment")

# Thumbnail: the animal is the subject and the environment is the pressure. The generic formula's
# "threat looms from the right edge" produced a skull; here it must be weather, distance or time.
THUMBNAIL_STEER = (
    "NATURE CHANNEL RULES: the affected_subject is the animal (or its egg/young) named in the "
    "transcript. The threat_source is environmental and literal -- cold, wind, distance, darkness, "
    "hunger, time -- never a monster, skull, demon, ghost, face in the sky, or a predator the "
    "transcript does not name. Any NUMBER in consequence_text must appear verbatim in the "
    "transcript; if the transcript has no such number, use none. Draw the animal with correct "
    "anatomy: wings/flippers, not arms.")

# Shared by both the authored Short and model-authored Long profiles. Keeping the string in
# nature_story_flow makes the two outputs follow one editorial contract instead of drifting.
WRITING_RULES = NATURE_WRITING_CONTRACT


def writing_rules_block(channel: str | None) -> str:
    """The Nature writing contract as a prompt addendum; empty on every other channel."""
    if not is_nature(channel):
        return ""
    return "\n\nNATURE CHANNEL WRITING CONTRACT (the channel owner's standing rules):\n" + WRITING_RULES


_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "twenty": "20",
    "thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80",
    "ninety": "90", "hundred": "100", "thousand": "1000",
}


def is_nature(channel: str | None) -> bool:
    return (channel or "").strip().lower() == NATURE


def format_tag(channel: str | None, default: str) -> str:
    """The spoken lead tag after the hook. Nature speaks none; other channels keep theirs."""
    return "" if is_nature(channel) else default


def people_allowed(channel: str | None) -> bool:
    """May an image state put anonymous people or the recurring human lead in frame?"""
    return not is_nature(channel)


def script_floor_is_hard(channel: str | None) -> bool:
    """Nature refuses to render a script under the quality floor; other lanes keep the env flag."""
    return is_nature(channel)


def cast_line(subject_sheet: str = "") -> str:
    """The cast clause of a Nature evidence prompt. Replaces every people/mascot clause."""
    sheet = (subject_sheet or "").strip()
    line = ("NO PEOPLE ANYWHERE IN FRAME: no researcher, observer, expedition member, human hand, "
            "tent, vehicle, camera or equipment. The animals are the only actors; they perform "
            "the declared action themselves, with correct anatomy (flippers or wings, never arms; "
            "an egg rests on the feet, never held). ")
    if sheet:
        line += f"SUBJECT SHEET, keep identical in every frame: {sheet} "
    return line


def numbers_in(text: str) -> set[str]:
    """Digit runs plus spelled-out numbers, normalised to digits ("65", "two" -> "2")."""
    found = set(re.findall(r"\d+(?:[.,]\d+)?", text or ""))
    for word in re.findall(r"[A-Za-z]+", text or ""):
        digits = _NUMBER_WORDS.get(word.lower())
        if digits:
            found.add(digits)
    return {n.replace(",", "") for n in found}


def headline_numbers_supported(headline: str, narration: str) -> bool:
    """Every number on the thumbnail must be spoken in the narration.

    "65 DAYS" over a script that says "roughly seven, eight weeks" asserts a figure no source
    gate checked. Spelled numbers count on both sides, so "two months" supports "2 MONTHS".
    """
    return numbers_in(headline) <= numbers_in(narration)


def subject_sheet_request(question: str, species_hint: str = "") -> tuple[str, str]:
    """(system, user) for the one model call that fixes the family's look for the whole film."""
    system = (
        "You are the character designer for an illustrated natural-history film. Return ONLY JSON: "
        '{"species":"common name","adult":"one sentence: fixed, checkable visual description of an '
        'adult of this species -- body shape, proportions, plumage or coat colours and where each '
        'colour sits, beak/limb form","egg_or_newborn":"one sentence for the egg or newborn, or '
        '\\"\\"","young":"one sentence for the chick/cub/juvenile as it looks when being fed, or '
        '\\"\\"","never":"one sentence listing anatomy errors to avoid for this species"}. '
        "Describe only what field guides record; no personality, no size numbers.")
    user = f"Question the film answers: {question}"
    if species_hint:
        user += f"\nSpecies: {species_hint}"
    return system, user


def subject_sheet_text(sheet: dict | None) -> str:
    """Flatten the designer's JSON into the sentence the image prompt carries."""
    if not isinstance(sheet, dict):
        return ""
    parts = []
    for key, label in (("adult", "Adult"), ("egg_or_newborn", "Egg/newborn"),
                       ("young", "Young"), ("never", "Never draw")):
        value = (sheet.get(key) or "").strip()
        if value:
            parts.append(f"{label}: {value.rstrip('.')}.")
    return " ".join(parts)
