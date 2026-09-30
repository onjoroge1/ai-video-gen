"""An evidence state never forbids an object it also requires.

Cane toads (2026-09-30, attempt 7): the setup beat forbade "toads" (the field before toads
arrived), the establishing frame appended the opening object "a single cane toad on the ground
of a Queensland cane field" to required_objects, and the verifier rejected the opening image on
every redraw for containing the toad it was told to contain. The clash is dropped at plan time;
every other forbidden object is still enforced.
"""
import longform_evidence as le


def _pack(opening="a single cane toad on the ground of a Queensland cane field"):
    return le.build_continuity_pack({
        "_topic_channel": "", "_story_contract": {"opening_object": opening,
                                                 "final_callback_object": opening},
        "scenes": [{"narration": "a", "continuity_anchor": "cane field"},
                   {"narration": "b"}]})


def test_opening_state_drops_a_forbidden_object_it_requires():
    pack = _pack()
    beat = {"purpose": "setup", "state_after": "tall green cane stalks",
            "required_objects": ["tall green cane stalks"],
            "forbidden_objects": ["toads", "people"], "anchor_phrase": "imported cane"}
    state = le._state_from_beat({}, beat, 0, 0, pack, opening=True)
    assert any("cane toad" in item for item in state["required_objects"])
    assert "toads" not in state["forbidden_objects"]
    assert "people" in state["forbidden_objects"]


def test_later_states_keep_their_forbidden_objects():
    pack = _pack()
    beat = {"purpose": "consequence", "state_after": "pale beetle grubs on chewed cane roots",
            "required_objects": ["pale beetle grubs", "chewed cane roots"],
            "forbidden_objects": ["toads"], "anchor_phrase": "predators started dying"}
    state = le._state_from_beat({}, beat, 0, 1, pack, opening=False)
    assert state["forbidden_objects"] == ["toads"]


def test_clash_matching_is_by_object_word_not_by_shared_filler():
    assert le._objects_clash("toads", ["a single cane toad on the ground"])
    assert le._objects_clash("beetles", ["yellow scarab beetle"])
    assert not le._objects_clash("people", ["a single cane toad on the ground of a field"])
    assert not le._objects_clash("Bolt", ["tall green cane stalks"])


def test_opening_gate_only_holds_bought_scenes_to_accepted_assets():
    """Attempt 8 (2026-09-30): scenes 1-4 bought and accepted, scenes 5-7 still 'opening' by
    story percentage and unbought; the gate must pass the tranche it purchased."""
    import copy
    # Build a minimal plan by compiling a two-scene script and marking scene 0 accepted.
    script = {"_topic_channel": "", "_story_contract": {"opening_object": "a cane toad",
                                                       "final_callback_object": "a cane toad"},
              "scenes": [{"narration": "one " * 12, "story_pct": 10, "continuity_anchor": "field",
                          "visual_beats": [{"purpose": "setup", "state_after": "a cane toad",
                                            "required_objects": ["a cane toad"],
                                            "anchor_phrase": "one one"}]},
                         {"narration": "two " * 12, "story_pct": 20,
                          "visual_beats": [{"purpose": "evidence", "state_after": "a beetle",
                                            "required_objects": ["a beetle"],
                                            "anchor_phrase": "two two"}]}]}
    plan = le.compile_evidence_plan(script)
    # The synthetic two-scene script is structurally thin on purpose; only the asset checks
    # are under test, so structural codes are the same on both sides and ignored below.
    bought = copy.deepcopy(plan)
    for state in bought["scenes"][0]["states"]:
        state["asset_status"] = "accepted"
    strict = le.validate_evidence_plan(bought, require_verified_assets=True, opening_only=True)
    bounded = le.validate_evidence_plan(bought, require_verified_assets=True, opening_only=True,
                                        purchased_through=1)
    unbought_codes = {e["code"] for e in strict["errors"] if e.get("scene") == 2}
    assert "rejected_or_missing_asset" in unbought_codes
    assert not [e for e in bounded["errors"] if e.get("scene") == 2
                and e["code"] == "rejected_or_missing_asset"]


def test_opening_cut_ratio_is_measured_over_bought_scenes_only():
    """Attempt 9: every bought opening cut verified, three unbought scenes counted as failures,
    ratio reported 56% against the 70% floor."""
    import copy
    script = {"_topic_channel": "", "_story_contract": {"opening_object": "a cane toad",
                                                       "final_callback_object": "a cane toad"},
              "scenes": [{"narration": "one " * 12, "story_pct": 10, "continuity_anchor": "field",
                          "visual_beats": [{"purpose": "setup", "state_after": "a cane toad",
                                            "required_objects": ["a cane toad"],
                                            "anchor_phrase": "one one"},
                                           {"purpose": "evidence", "state_after": "a grub",
                                            "required_objects": ["a grub"],
                                            "anchor_phrase": "one one one"}]},
                         {"narration": "two " * 12, "story_pct": 20,
                          "visual_beats": [{"purpose": "evidence", "state_after": "a beetle",
                                            "required_objects": ["a beetle"],
                                            "anchor_phrase": "two two"},
                                           {"purpose": "evidence", "state_after": "a root",
                                            "required_objects": ["a root"],
                                            "anchor_phrase": "two two two"}]}]}
    plan = copy.deepcopy(le.compile_evidence_plan(script))
    for state in plan["scenes"][0]["states"]:
        state["asset_status"] = "accepted"
        state["verified_visible_information"] = True
    strict = le.validate_evidence_plan(plan, require_verified_assets=True, opening_only=True)
    bounded = le.validate_evidence_plan(plan, require_verified_assets=True, opening_only=True,
                                        purchased_through=1)
    assert any(e["code"] == "opening_visible_information_ratio" for e in strict["errors"])
    assert not any(e["code"] == "opening_visible_information_ratio" for e in bounded["errors"])
