"""No sentence is said twice in a row (Asian carp, 2026-10-11)."""
import causal_story as cs
import storyboard_repair as sr


def _steps(*texts):
    return [{"step_id": f"s{i}", "situation": t} for i, t in enumerate(texts)]


def test_the_two_carp_repeats_are_caught_inside_and_across_scenes():
    issues = []
    cs._check_sentence_repeats(_steps(
        "Imagine you run a catfish farm in the American South, and your ponds keep turning thick "
        "and green. Your catfish ponds keep turning thick and green. Algae, weeds.",
        "Bigheads first, pulled from Pool 26 in 1991. Then the silvers, showing up in the catch by 1998.",
        "The silvers came last, showing up in the catch by 1998. Two species."), issues)
    assert [i["code"] for i in issues] == ["SENTENCE_REPEATED", "SENTENCE_REPEATED"]
    assert [i["step_id"] for i in issues] == ["s0", "s2"]


def test_rhetorical_follow_ups_are_not_repeats():
    issues = []
    cs._check_sentence_repeats(_steps(
        "The harvest is thin. Thinner than it should be.",
        "Slowly the gentler European bees thinned out of the groves until they were gone.",
        "So the groves kept their bees. These were deaths the old bees had almost never caused.",
        "But these bees did not stay put."), issues)
    assert issues == []


def test_the_repair_is_told_to_say_it_once():
    assert "SENTENCE_REPEATED" in sr.SCENE_EDIT_CODES
    edit = {"errors": [], "scene_edits": [{"scene_id": "s2", "code": "SENTENCE_REPEATED",
                                           "finding": "s2 says the sentence before it again"}],
            "scene_ids": ["s2"]}
    text = sr.prompt({"scenes": [{"scene_id": "s2", "narration": "x"}], "hook": "h"}, edit)
    assert "SAYS A SENTENCE TWICE" in text
