"""Spoken numbers must match whichever form the transcriber chose.

Whisper writes some spoken numbers as digits and others as words, inconsistently within one
sentence. Run 7f91cdd4, scene 12:

  narration:  ...behind more than nine in every ten of them, up to eight in ten...
  transcript: ...behind more than nine in every 10 of them, up to eight in 10...

"nine" and "eight" stayed words; "ten" became "10" twice. The anchor "more than nine in every
ten" could not match, and no fuzzy fallback bridged it -- the tokens genuinely differ.
"""

from audio_timing import _clean, _find_span, _split_joined


def _timed(sentence, step=0.4):
    words = []
    for index, word in enumerate(sentence.split()):
        words.extend(_split_joined(word, index * step, (index + 1) * step))
    return words


def test_a_word_anchor_matches_digit_speech():
    spoken = _timed("behind more than nine in every 10 of them up to eight in 10")

    assert _find_span(spoken, "more than nine in every ten")


def test_a_digit_anchor_matches_word_speech():
    # The other direction: either side can carry either form.
    spoken = _timed("the bacterium causes ninety percent of them")

    assert _find_span(spoken, "causes 90 percent")


def test_matching_forms_still_work():
    assert _find_span(_timed("up to eight in ten cases"), "eight in ten")
    assert _find_span(_timed("up to 8 in 10 cases"), "8 in 10")


def test_ordinary_words_are_untouched():
    assert _clean("stomach") == "stomach"
    assert _clean("bacterium") == "bacterium"
    assert _find_span(_timed("he drank the cloudy broth"), "drank the cloudy broth")


def test_number_words_and_digits_share_a_key():
    assert _clean("ten") == _clean("10")
    assert _clean("Ninety,") == _clean("90")
    # A word that merely contains a number word is not a number.
    assert _clean("tension") != _clean("10")
