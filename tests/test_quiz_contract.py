from bolt_video.formats.quiz import (
    QUIZ_V2,
    clamp_quiz_items,
    clue_zoom,
    final_reveal_narration,
    round_narration,
)


def test_quiz_v2_starts_with_gameplay_and_has_no_post_game_tail():
    assert QUIZ_V2.first_clue_at_sec == 0
    assert QUIZ_V2.standalone_intro_sec == 0
    assert QUIZ_V2.standalone_outro_sec == 0
    assert QUIZ_V2.subscribe_teaser_sec == 0


def test_quiz_v2_caps_rounds_and_stays_replayable():
    assert clamp_quiz_items(6) == 3
    assert QUIZ_V2.estimated_duration(3, reveal_sec=1.0) == 11.0
    assert QUIZ_V2.estimated_duration(6, reveal_sec=1.2, final_reveal_sec=2.4) == 12.0


def test_round_narration_avoids_repetitive_what_is_it_setup():
    lines = [round_narration("animals", i, 3) for i in range(1, 4)]
    assert lines == ["Three animals are hiding. Spot them.",
                     "Round 2. Harder.",
                     "Last one. This fools everyone."]
    assert all("what is it" not in line.lower() for line in lines)


def test_round_lines_fit_the_guess_window():
    """Each line plays over its own countdown; a longer one talks over the reveal that follows.

    Measured TTS on this phrasing runs ~16.5 characters per second; the guard uses a slower 15.0
    so it trips before a real render collides. This is what rules out narrating the full
    "Three animals are hiding in the wild. The last one fools almost everyone." — 4.39s measured
    against a 2.4s window.
    """
    for index in range(1, 4):
        line = round_narration("animals", index, 3)
        assert len(line) / 15.0 <= QUIZ_V2.guess_window_sec, (index, line)


def test_quiz_v2_progressively_reveals_harder_clues():
    assert clue_zoom("medium", 0) < clue_zoom("hard", 0) < clue_zoom("expert", 0)
    assert clue_zoom("expert", 0) > clue_zoom("expert", 1) > clue_zoom("expert", 2)
    assert clue_zoom("expert", 2) == 1.0


def test_subscription_cta_is_inside_the_final_reveal():
    assert final_reveal_narration("ANTEATER") == "ANTEATER! Subscribe — tomorrow's quiz is harder."
    assert QUIZ_V2.subscribe_teaser_sec == 0


def test_final_reveal_narration_fits_the_closing_card():
    """The closing card is sized from this line and capped, so an over-long line is clipped.

    Rate is measured, not assumed: real TTS on this phrasing ran 2.74s for "Tapir!" (45 chars)
    and 3.12s for "Hippopotamus!" (52 chars) — about 16.5 characters per second. The guard uses
    a deliberately slower 15.0 so it trips before a real render clips, and checks the longest
    realistic answer against the cap plus the 0.12s pad the renderer adds.

    This guards the copy, not the renderer — a previous wording overran a 2.4s cap on any
    answer from "Pangolin" up and silently lost its last word.
    """
    longest = final_reveal_narration("Hippopotamus")
    projected_sec = len(longest) / 15.0
    assert projected_sec + 0.12 <= QUIZ_V2.final_reveal_max_sec, (longest, projected_sec)


def test_the_closing_card_can_hold_an_ask_and_a_reason():
    """The cap exists to bound the ending, not to dictate the copy.

    2.4s was too tight for any CTA carrying both a request and a reason to act on it, which is
    why the ending read as abrupt. Guard the headroom so a future trim does not silently
    reintroduce the constraint that shaped the old one-clause ending.
    """
    assert QUIZ_V2.final_reveal_max_sec >= 3.2
    assert QUIZ_V2.final_reveal_max_sec > QUIZ_V2.final_reveal_min_sec
