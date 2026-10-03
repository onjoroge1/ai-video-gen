"""An evidence state never asks the image for a pose, a mood, or a lighting effect.

Yellowstone (2026-09-30): required object "elk with uniform cast shadows" and state_after
"alert elk with shadows frozen mid-flinch" were redrawn twice and rejected, aborting the first
tranche with 18 accepted images already bought. The verifier can only confirm physical objects.
"""
import longform_evidence as le


def test_the_yellowstone_strings_become_physical_objects():
    assert le.scrub_unverifiable("elk with uniform cast shadows")[0] == "elk"
    assert le.scrub_unverifiable("alert elk with shadows frozen mid-flinch")[0] == "elk"
    assert le.scrub_unverifiable("relaxed grazing elk")[0] == "grazing elk"


def test_physical_descriptions_are_untouched():
    for phrase in ("tall green cane stalks", "pale beetle grubs", "chewed cane roots",
                   "a single cane toad on the ground", "wolf standing on a ridge",
                   "beaver dam across a stream"):
        assert le.scrub_unverifiable(phrase) == (phrase, [])


def test_a_phrase_that_is_only_mood_keeps_its_original_rather_than_vanishing():
    assert le.scrub_unverifiable("ominous")[0] == "ominous"


def test_state_from_beat_applies_the_scrub_and_records_it():
    pack = le.build_continuity_pack({
        "_topic_channel": "", "_story_contract": {"opening_object": "a wolf on a ridge",
                                                 "final_callback_object": "a wolf on a ridge"},
        "scenes": [{"narration": "a", "continuity_anchor": "Lamar Valley"}, {"narration": "b"}]})
    beat = {"purpose": "evidence", "state_before": "relaxed grazing elk",
            "state_after": "alert elk with shadows frozen mid-flinch",
            "required_objects": ["elk with uniform cast shadows"], "anchor_phrase": "the elk froze"}
    state = le._state_from_beat({}, beat, 4, 2, pack, opening=False)
    assert state["required_objects"] == ["elk"]
    assert state["state_after"] == "elk"
    assert "alert" in state["unverifiable_terms_scrubbed"]
