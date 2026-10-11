"""Two repairs that failed the Asian carp routine run (2026-10-11), made to converge.

* DANGLING_REFERENCE: told only to "refer back to what the scene before said", the repair swapped
  "That pressure" for "That shortage" -- another noun nothing named.
* SYNTHESIS_SKIPS_A_BEAT: told to echo scene_018 "by one of its own words", the repair kept
  "Spooked by boats, they leaped" -- a paraphrase the word-level check cannot count.
"""
import storyboard_repair as sr

SCENES = [
    {"scene_id": "s1", "causal_role": "setup", "narration": "Imagine your ponds turn green."},
    {"scene_id": "s2", "causal_role": "mechanism",
     "narration": "Every carp strains plankton from the water native fish need."},
    {"scene_id": "s3", "causal_role": "escalation",
     "narration": "More mouths at the same table. Fewer of the fish that belong here."},
    {"scene_id": "s4", "causal_role": "escalation",
     "narration": "That pressure does not stay underwater. Fisheries suffer."},
    {"scene_id": "s5", "causal_role": "escalation",
     "narration": "Startle a silver carp with a boat motor and it launches fifteen feet."},
    {"scene_id": "s6", "causal_role": "synthesis",
     "narration": "So trace it back. Carp strained plankton. Fisheries suffered. Spooked by boats, they leaped."},
    {"scene_id": "s7", "causal_role": "tool", "narration": "Look again at the crate."},
]
ERRORS = [
    "SYNTHESIS_SKIPS_A_BEAT: the synthesis echoes 3/4 chain beats; it never touches s5 -- re-walk "
    "EVERY mechanism and escalation, in order, each as its cause and its cost",
    "DANGLING_REFERENCE: s4 opens on 'That pressure', but the scene before never names a pressure; "
    "refer back only to what was just said",
]


SCRIPT = {"scenes": SCENES, "hook": "Imagine your ponds turn green.",
          "_story_contract": {"opening_object": "the pond-side fish crate"}}


def _edit():
    edit = sr.plan(SCRIPT, {"validation": {"errors": ERRORS}})
    assert edit, "the planner refused a bounded opener-and-recap edit"
    return edit


def test_the_recap_repair_is_handed_the_skipped_beats_own_words():
    edit = _edit()
    words = edit["echo_words"]["s5"]
    assert {"startle", "motor", "launches"} <= set(words)
    assert "spooked" not in words and "leaped" not in words
    text = sr.prompt(SCRIPT, edit)
    assert "the SAME word, not a synonym" in text and "launches" in text


def test_the_opener_repair_sees_what_the_scene_before_said_and_may_not_swap_nouns():
    edit = _edit()
    item = next(i for i in edit["scene_edits"] if i["code"] == "DANGLING_REFERENCE")
    assert item["previous_sentence"] == "Fewer of the fish that belong here."
    assert {"mouths", "table", "fish"} <= set(item["previous_words"])
    text = sr.prompt(SCRIPT, edit)
    assert "Do NOT swap the noun" in text and "Fewer of the fish that belong here." in text
