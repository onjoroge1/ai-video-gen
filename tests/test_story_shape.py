"""The middle and the ending (2026-10-17): the findings the Chernobyl script earned and the Demon Core
script did not. The opening scene is never judged. No network.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import story_shape as ss  # noqa: E402


def _scenes(*rows):
    return [{"narration": text, "causal_role": role} for role, text in rows]


MEANDER = _scenes(
    ("setup", "You'd think forty years would be enough. It isn't. Hanna Zavorotnya went back to her farm "
              "inside the zone. So why can't anyone live at Chernobyl?"),
    ("intervention", "So the operators ran a test. They lowered the power from 3,200 to 700 megawatts."),
    ("mechanism", "So the core surged. The push fell from four-point-five to zero-point-seven beta."),
    ("escalation", "So how many, all told? About 350,000 people were moved from 2,600 square kilometres."),
    ("escalation", "So what keeps that reason alive? Caesium needs 30 years and strontium 29 years."),
    ("escalation", "So what does forty years buy you? About 60% of it has decayed."),
    ("escalation", "So they built an arch 257 metres wide and 108 metres high."),
    ("reversal", "So what has been done about it? Only temporary patches."),
    ("tool", "So when a fix promises to make something safer, ask what it switches off to prove it."),
)

FOCUSED = _scenes(
    ("setup", "You'd think they would never touch the core by hand. They did. On 21 May 1946, Louis Slotin "
              "was easing two halves of a beryllium shell together. So why did they keep doing it?"),
    ("intervention", "So you join the Weapon Physics Division, where the tests are run by hand."),
    ("hinge", "The first time the dragon woke, one man was alone."),
    ("mechanism", "On 21 August 1945, Harry Daghlian dropped a brick onto the core."),
    ("escalation", "So the rules change: at least two people must be present."),
    ("escalation", "But Slotin carries on by hand. The first death changed who stood in the room."),
    ("escalation", "Until the day we began with. Slotin knocks the halves apart and spares the seven others."),
    ("reversal", "Only after Slotin's accident are the tests run remotely."),
    ("verdict", "Afterwards, a quarter of a mile. Before, the width of a screwdriver."),
)


def _codes(scenes):
    return {f["code"] for f in ss.findings(scenes)}


def test_the_meandering_middle_earns_every_finding():
    assert _codes(MEANDER) >= {"BODY_QUESTIONS", "SO_CADENCE", "NUMBER_DENSE", "HUMAN_THREAD_DROPPED",
                               "LESSON_CLOSE"}


def test_the_focused_script_is_clean():
    assert _codes(FOCUSED) == set()


def test_the_opening_is_never_judged():
    """Questions and figures in scene 1 belong to the opening contract, which is unchanged."""
    opening = dict(FOCUSED[0], narration=FOCUSED[0]["narration"] + " Why? How? What? 1, 2, 3 and 4.")
    assert _codes([opening] + FOCUSED[1:]) == set()


def test_people_come_from_the_opening_not_places_or_things():
    text = ("In those ruins sits the Elephant's Foot. Artur Korneyev, deputy director of the shelter, "
            "was photographed beside it. You're a young physicist at Los Alamos.")
    assert ss.opening_people(text) == ["Korneyev"]


def test_dates_and_pronoun_one_are_not_figures():
    assert ss.numbers_in("On 21 May 1946, Louis Slotin was easing two halves together.") == 1
    assert ss.numbers_in("They switched off the safety systems one by one.") == 0
    assert ss.numbers_in("About 350,000 people were moved from 2,600 square kilometres.") == 2


def test_the_writer_hears_the_ending_only_in_the_last_batch():
    assert "STORY MIDDLE" in ss.writer_rules(False) and "STORY ENDING" not in ss.writer_rules(False)
    assert "STORY ENDING" in ss.writer_rules(True)
    assert "opening rules above are unchanged" in ss.writer_rules(False)
