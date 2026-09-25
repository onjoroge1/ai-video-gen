"""final_callback_object must equal opening_object before the evidence plan is built.

The planner is told they MUST be equal, the continuity pack copies the final object into the
closing state's label, and validate_evidence_plan refuses a run whose labels differ. The first
emperor penguin script to pass the storyboard gate (2026-09-24) died there, after research,
script, fact-check, ledger, runtime and storyboard were all bought, on a wording difference
between two labels of one reused asset.
"""
import explainer_pipeline as ep


def test_a_differing_callback_object_is_aligned_to_the_opening_object():
    script = {"_story_contract": {"opening_object": "a single egg on the male's feet",
                                  "final_callback_object": "the egg, back on the male's feet"}}
    seen = []
    assert ep._align_callback_object(script, seen.append) is True
    assert script["_story_contract"]["final_callback_object"] == "a single egg on the male's feet"
    assert seen and "aligned" in seen[0]


def test_equal_labels_are_left_alone_case_insensitively():
    script = {"_story_contract": {"opening_object": "One Egg", "final_callback_object": "one egg"}}
    assert ep._align_callback_object(script) is False
    assert script["_story_contract"]["final_callback_object"] == "one egg"


def test_a_script_without_a_contract_or_opening_object_is_untouched():
    assert ep._align_callback_object({}) is False
    script = {"_story_contract": {"opening_object": "", "final_callback_object": "x"}}
    assert ep._align_callback_object(script) is False
    assert script["_story_contract"]["final_callback_object"] == "x"
