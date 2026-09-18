import numpy as np

from illustrated_score import _compose, score_spec
from longform_evidence import _state_from_beat, build_continuity_pack


def test_action_state_requires_anonymous_people_without_recurring_cast():
    pack = build_continuity_pack({})
    state = _state_from_beat(
        {"human_present": False},
        {"purpose": "action", "anchor_phrase": "workers cut the vine",
         "state_before": "vine covers the field", "state_after": "workers cut the vine"},
        2, 0, pack, opening=False)

    assert state["include_human"] is False
    assert state["anonymous_people_required"] is True


def test_pure_evidence_never_requires_people():
    pack = build_continuity_pack({})
    state = _state_from_beat(
        {"human_present": False},
        {"purpose": "evidence", "anchor_phrase": "roots remain",
         "state_before": "bare soil", "state_after": "roots remain"},
        2, 0, pack, opening=False)

    assert state["pure_evidence"] is True
    assert state["anonymous_people_required"] is False


def test_score_carries_story_turn_energy_and_a_percussion_pulse():
    spec = score_spec(
        "Why did the fix backfire?", "backfiring_solution", 12,
        story_turns=[
            {"position": 0.0, "role": "setup"},
            {"position": 0.4, "role": "hinge"},
            {"position": 0.6, "role": "escalation"},
            {"position": 0.8, "role": "reversal"},
        ])
    audio = _compose(spec)

    assert spec["tempo_bpm"] >= 103
    assert "brushed percussion" in spec["instruments"]
    assert [turn["role"] for turn in spec["story_turns"]] == [
        "setup", "hinge", "escalation", "reversal"]
    assert audio.shape == (12 * spec["sample_rate"], 2)
    assert np.max(np.abs(audio)) <= 0.651
