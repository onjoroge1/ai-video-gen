"""Stage 1 of splitting a beat across scenes: two identities, and proof the split is inert.

A beat is a factual identity -- it asserts a role, owns claims, sits in the cause chain. A scene is
a unit of screen time. They were one object because they were always 1:1, with `scene_id` minted
arithmetically from the beat number.

Traced through the real validators, three scenes sharing one id produce duplicate keys collapsing
in causal_story._check_chain (a child edge silently retargets the LAST copy, and BACKWARD_CAUSE
fires) and DUPLICATE_BEAT_ID in story_fact_model.validate_structure, which marks the beat
`structurally_blocked` so its already-verified citations stop being judged at all.

The whole point of this stage is that it changes NOTHING yet. Part 0 mints exactly the ids the old
arithmetic minted, so the plumbing can land and be proved harmless before behaviour depends on it.
"""
import pytest

import story_compiler as sc


BEAT = {"beat_id": "event_08", "causal_role": "mechanism", "n": 6}


def test_part_zero_is_byte_identical_to_the_old_arithmetic():
    """The inertness proof. An unsplit run must mint what it minted before, exactly."""
    for n in (1, 6, 13, 99):
        ids = sc.scene_identities({"beat_id": f"event_{n:02d}"}, n)
        assert ids["scene_id"] == f"scene_{n:03d}"
        assert ids["beat_id"] == f"event_{n:02d}"
        assert ids["continues"] == ""
        assert ids["beat_part"] == 1


def test_the_legacy_beat_id_fallback_is_preserved():
    """A beat with no beat_id still falls back to the beat number, as it always did."""
    assert sc.scene_identities({}, 6)["beat_id"] == "beat_06"


def _parts(first_n=6, count=3):
    """Parts as the pipeline builds them: consecutive slot numbers, one call each.

    Slots are renumbered densely before identities are minted, so part k of a beat starting at
    slot 6 is slot 6+k. Passing the same n for every part -- as an earlier version of this file
    did -- tests a call the pipeline never makes.
    """
    return [sc.scene_identities(BEAT, first_n + i, part_index=i, part_count=count)
            for i in range(count)]


def test_every_part_of_a_split_beat_gets_its_own_scene_and_beat_id():
    """Unique ids are what keep _check_chain from collapsing edges onto the last copy."""
    ids = _parts()
    assert [x["scene_id"] for x in ids] == ["scene_006", "scene_006b", "scene_006c"]
    assert [x["beat_id"] for x in ids] == ["event_08", "event_08b", "event_08c"]
    assert len({x["scene_id"] for x in ids}) == 3
    assert len({x["beat_id"] for x in ids}) == 3


def test_all_parts_of_one_beat_share_a_scene_number():
    """scene_005 / 005b / 005c, not 005 / 006b / 007c -- the parts read as one beat."""
    assert [x["scene_id"] for x in _parts()] == ["scene_006", "scene_006b", "scene_006c"]


def test_continues_chains_each_part_to_the_one_before_it():
    """Part-to-part and strictly forward, which is also the true causal statement."""
    ids = _parts()
    assert ids[0]["continues"] == ""
    assert ids[1]["continues"] == "event_08"
    assert ids[2]["continues"] == "event_08b"


def test_exactly_one_part_asserts_the_beat():
    """The property every role-uniqueness rule needs: a continuation is not a second mechanism."""
    steps = _parts()
    for step in steps:
        step["role"] = "mechanism"
    asserting = sc.asserting_steps(steps)
    assert len(asserting) == 1
    assert asserting[0]["beat_id"] == "event_08"


def test_asserting_steps_leaves_genuinely_distinct_beats_alone():
    """Two DIFFERENT beats both claiming mechanism must still both count. That check is real."""
    steps = [{"beat_id": "event_03", "role": "mechanism", "continues": ""},
             {"beat_id": "event_09", "role": "mechanism", "continues": ""}]
    assert len(sc.asserting_steps(steps)) == 2


def test_asserting_steps_tolerates_junk_rows():
    assert sc.asserting_steps([None, "x", {"continues": ""}, {}]) == [{"continues": ""}, {}]
    assert sc.asserting_steps(None) == []


def test_a_split_wider_than_the_suffix_alphabet_raises():
    """Fail loudly rather than mint a colliding id, which is the failure this stage exists to stop."""
    with pytest.raises(ValueError):
        sc.part_identity("event_08", len(sc.PART_SUFFIXES) + 1)


def test_part_identity_is_stable_and_ordered():
    """Ids must sort in play order, because several reports group scenes by sorting on the id."""
    ids = [sc.part_identity("scene_006", i) for i in range(4)]
    assert ids == sorted(ids)
