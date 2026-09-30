"""A still never holds past the ceiling: long holds are split into parts on the same picture.

Cane toad film (2026-09-30): 25 of 91 shots held over 3.5 s (worst 9.04 s) because the writer
returned three or four states for twelve-second scenes; the judge's raw 89 was capped to 69 by
`long_visual_hold`. The split is a pacing repair on verified pictures and claims no information.
"""
import pytest

from longform_evidence import MAX_VISUAL_STATE_SECONDS
from longform_shots import (MIN_SHOT_SECONDS, compile_scene_shots, shot_plan_metrics,
                            split_long_holds)


def _states(anchors):
    return [
        {"state_id": f"state:{index}", "asset_id": f"asset:{index}",
         "asset_strategy": "distinct", "asset_status": "accepted",
         "anchor_phrase": anchor, "purpose": "evidence",
         "verified_visible_information": True}
        for index, anchor in enumerate(anchors)
    ]


def test_three_states_over_twenty_seconds_cut_under_the_ceiling():
    duration = 20.6
    words = ("cane toads were brought to queensland in nineteen thirty five to eat the beetle "
             "grubs that were chewing through the roots of the sugar crop and the plan failed "
             "within a season as the toads spread").split()
    step = duration / len(words)
    word_times = [(w, i * step, i * step + step * 0.8) for i, w in enumerate(words)]
    shots = split_long_holds(compile_scene_shots(
        {"narration": " ".join(words), "story_role": "setup"}, duration, 0,
        word_times=word_times, evidence_states=_states(("cane toads", "grubs that", "toads spread"))))

    assert all(shot["duration"] <= MAX_VISUAL_STATE_SECONDS + 1e-6 for shot in shots)
    assert all(shot["duration"] >= MIN_SHOT_SECONDS for shot in shots)
    assert sum(shot["duration"] for shot in shots) == pytest.approx(duration, abs=0.01)
    starts = [shot["start_sec"] for shot in shots]
    assert starts == sorted(starts)
    # The original three states are still there, in order, and still carry their credit.
    originals = [shot for shot in shots if shot.get("asset_strategy") != "hold_split"]
    assert [shot["source"] for shot in originals] == ["asset:0", "asset:1", "asset:2"]
    assert all(shot["verified_visible_information"] for shot in originals)
    # The parts claim nothing.
    parts = [shot for shot in shots if shot.get("asset_strategy") == "hold_split"]
    assert parts and not any(shot["new_information"] or shot["semantic_aligned"]
                             or shot["verified_visible_information"] for shot in parts)
    assert all(shot["timing_source"] == "hold_split" for shot in parts)


def test_parts_alternate_push_and_wide_return_on_the_same_source():
    shot = {"kind": "still", "source": "asset:7", "duration": 9.04, "start_sec": 2.0,
            "end_sec": 11.04, "motion": "locked", "transition": "hard_cut",
            "purpose": "evidence", "asset_strategy": "distinct", "state_id": "state:7",
            "verified_visible_information": True, "new_information": True,
            "semantic_aligned": True, "timing_source": "measured"}
    parts = split_long_holds([shot])
    assert len(parts) == 3
    assert [round(p["duration"], 3) for p in parts] == [3.013, 3.013, 3.013]
    assert parts[0]["source"] == parts[1]["source"] == parts[2]["source"] == "asset:7"
    assert parts[0]["verified_visible_information"] is True      # the head keeps its credit
    assert parts[1]["transition"] == "push_to_detail" and parts[1]["motion"] == "locked"
    assert parts[2]["transition"] == "pull_to_wide" and parts[2]["motion"].startswith("pan_")
    assert parts[2]["end_sec"] == pytest.approx(11.04, abs=0.01)


def test_short_stills_and_motion_clips_are_untouched():
    still = {"kind": "still", "source": "a", "duration": 3.5, "start_sec": 0.0, "end_sec": 3.5}
    clip = {"kind": "i2v", "source": "b", "duration": 8.0, "start_sec": 3.5, "end_sec": 11.5}
    assert split_long_holds([still, clip]) == [still, clip]


def test_split_parts_are_stills_for_hold_measures_but_not_cuts_for_alignment():
    """The first re-cut opening measured alignment 64% -> 35% and meaningful cuts 100% -> 45%
    purely from counting the parts as cuts; the pictures and their timing had not changed."""
    a = {"kind": "still", "source": "a", "duration": 2.0, "start_sec": 0.0, "end_sec": 2.0,
         "transition": "continuous", "semantic_aligned": True, "new_information": True,
         "asset_strategy": "master", "verified_visible_information": True}
    b = {"kind": "still", "source": "b", "duration": 8.0, "start_sec": 2.0, "end_sec": 10.0,
         "transition": "hard_cut", "semantic_aligned": True, "new_information": True,
         "asset_strategy": "distinct", "verified_visible_information": True}
    before = shot_plan_metrics([[a, b]])
    after = shot_plan_metrics([split_long_holds([a, b])])
    assert after["shot_count"] == 4 and before["shot_count"] == 2
    assert after["cut_count"] == before["cut_count"] == 1
    assert after["narration_aligned_cut_ratio"] == before["narration_aligned_cut_ratio"] == 1.0
    assert after["same_source_hard_cut_count"] == 0
    assert after["max_still_seconds"] <= MAX_VISUAL_STATE_SECONDS
