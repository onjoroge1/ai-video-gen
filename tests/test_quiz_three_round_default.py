from pathlib import Path

from bolt_video.formats.quiz import QUIZ_V2, clamp_quiz_items, tier_label


def test_three_round_default_restores_playable_pacing():
    assert QUIZ_V2.version == "rapid_reveal_v2_4"
    assert QUIZ_V2.max_items == 3
    assert QUIZ_V2.guess_window_sec == 2.4
    assert clamp_quiz_items(4) == 3
    # 9.8s, not 11.0: rounds two and three run a 1.8s countdown instead of 2.4s. The published
    # retention curves fall in a straight line with no plateau, and the countdown was the only
    # stretch long enough for a constant leak to be leaving from.
    assert QUIZ_V2.estimated_duration(3) == 9.8


def test_three_round_story_keeps_the_difficulty_ladder():
    assert [tier_label(i, 3) for i in range(1, 4)] == [
        "CAN YOU GET IT?", "95% FAIL", "IMPOSSIBLE"
    ]


def test_v23_visual_identity_and_generation_quality_are_preserved():
    import _quiz_pipeline_legacy as legacy

    assert Path(legacy.DISPLAY_FONT).name == "LuckiestGuy-Regular.ttf"
    assert "DIFFICULTY IS CONFUSABILITY, NOT OBSCURITY" in legacy._QUIZ_SYSTEM
    assert "Order items MEDIUM -> HARD -> EXPERT" in legacy._QUIZ_SYSTEM
    assert legacy.HABITAT is True
