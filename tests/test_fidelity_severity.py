"""A narration overshoot blocks only if a viewer could repeat it as a fact and be wrong.

Fifteen runs died on this gate. Every one of the phrases in the soft list below was refused as
invented history, and none of them can mislead anyone. Narrowing the judge's prose three times
produced a fresh crop each round, so the threshold was the thing that was wrong, not the wording.
"""
import pytest

from longform_research import fidelity_severity

SOFT = [
    "The bees were in a landscape.",             # setting the event already locates
    "across open ground",
    "The swarm is dark.",                        # staging in a cold open
    "became established",                        # the claim says "became established"
    "that the colony was not inside a crate",    # derived by NEGATION, never asserted
    "The hive boxes stood open.",
]

MATERIAL = [
    "Warwick Kerr brought them into Brazil.",    # a named person doing a thing
    "A beekeeper backs away.",                   # an invented actor and action
    "twenty-six swarms escaped",                 # a number in words, and the wrong noun
    "The colony was found in 1990",              # a date
    "hundreds of farms",                         # a quantity
    "behind mud-brick walls in Hanoi",           # a place
]


@pytest.mark.parametrize("detail", SOFT)
def test_soft_overshoot_does_not_block(detail):
    assert fidelity_severity([detail]) == "soft"


@pytest.mark.parametrize("detail", MATERIAL)
def test_material_overshoot_still_blocks(detail):
    assert fidelity_severity([detail]) == "material"


def test_one_material_detail_makes_the_whole_finding_blocking():
    assert fidelity_severity(["The swarm is dark.", "twenty-six queens escaped"]) == "material"


def test_no_details_is_soft():
    assert fidelity_severity([]) == "soft"
