import pytest

import causal_story as cs
from longform_evidence import (
    MAX_VISUAL_STATE_SECONDS,
    TARGET_VISUAL_STATE_SECONDS,
    SLOWEST_MEASURED_WORDS_PER_SECOND,
    states_required_for_words,
)
from longform_shots import compile_scene_shots


def test_scene_one_keeps_the_spoken_hook_when_chapter_is_zero(monkeypatch):
    monkeypatch.setattr(cs, "speaks_chapter_markers", lambda: False)
    scenes = [{"chapter": 0, "causal_role": "setup", "narration": "The soil washes away."}]

    cs.finalize_narration(scenes, hook="America paid farmers to plant this vine")
    once = scenes[0]["narration"]
    cs.finalize_narration(scenes, hook="America paid farmers to plant this vine")

    assert once.startswith("America paid farmers to plant this vine.")
    assert scenes[0]["narration"] == once


def test_sparse_survivors_redistribute_the_tail_instead_of_creating_a_43_second_hold():
    duration = 46.08
    narration = "one two three four five six seven eight nine"
    word_times = [(word, index * 0.5, index * 0.5 + 0.2)
                  for index, word in enumerate(narration.split())]
    states = [
        {"state_id": f"state:{index}", "asset_id": f"asset:{index}",
         "asset_strategy": "distinct", "asset_status": "accepted",
         "anchor_phrase": anchor, "purpose": "evidence",
         "verified_visible_information": True}
        for index, anchor in enumerate(("one", "four", "seven"))
    ]

    shots = compile_scene_shots(
        {"narration": narration, "story_role": "mechanism"}, duration, 0,
        word_times=word_times, evidence_states=states)

    assert [shot["duration"] for shot in shots] == pytest.approx([15.36] * 3, abs=0.01)
    assert all(shot["timing_source"] == "even_fallback" for shot in shots)
    assert max(shot["duration"] for shot in shots) < 43.08


def test_planner_targets_two_to_three_seconds_without_moving_the_hard_ceiling():
    words = 36
    seconds = words / SLOWEST_MEASURED_WORDS_PER_SECOND
    states = states_required_for_words(words)

    assert TARGET_VISUAL_STATE_SECONDS == 2.75
    assert MAX_VISUAL_STATE_SECONDS == 3.5
    assert seconds / states <= TARGET_VISUAL_STATE_SECONDS
    assert states == 6
