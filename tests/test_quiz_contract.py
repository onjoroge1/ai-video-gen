from bolt_video.formats.quiz import QUIZ_V2, clamp_quiz_items, round_narration


def test_quiz_v2_starts_with_gameplay_and_has_no_post_game_tail():
    assert QUIZ_V2.first_clue_at_sec == 0
    assert QUIZ_V2.standalone_intro_sec == 0
    assert QUIZ_V2.standalone_outro_sec == 0
    assert QUIZ_V2.subscribe_teaser_sec == 0


def test_quiz_v2_caps_rounds_and_stays_replayable():
    assert clamp_quiz_items(6) == 3
    assert QUIZ_V2.estimated_duration(3, reveal_sec=1.0) == 10.2
    assert QUIZ_V2.estimated_duration(6, reveal_sec=1.2) == 10.8


def test_round_narration_avoids_repetitive_what_is_it_setup():
    lines = [round_narration("animals", i, 3) for i in range(1, 4)]
    assert lines == ["Three animals. Guess fast.", "Round 2. Harder.", "Final one. Expert."]
    assert all("what is it" not in line.lower() for line in lines)
