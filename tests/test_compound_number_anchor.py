"""'Twenty-six' in the anchor, '26' in the transcript, and the close that re-speaks the hook's
number (change #6) killed killer bees V10 attempt 1 at the measured-audio gate (2026-10-07)."""
import audio_timing as at


def test_a_compound_number_word_matches_whisper_in_every_shape():
    # whisper writes the figure
    assert at._find_span([("26", 0.0, 0.5), ("queens", 0.5, 0.9)], "Twenty-six queens")[:2] == (0.0, 0.9)
    # whisper writes two words (after _split_joined)
    assert at._find_span([("twenty", 0.0, 0.3), ("six", 0.3, 0.5), ("queens", 0.5, 0.9)],
                         "Twenty-six queens")[:2] == (0.0, 0.9)
    # the anchor writes the figure and whisper the words
    assert at._find_span([("twenty", 0.0, 0.3), ("six", 0.3, 0.5), ("left", 0.5, 0.9)],
                         "26 left")[:2] == (0.0, 0.9)
    # indices stay aligned to the word list after folding: the match must land on 'left', not drift
    span = at._find_span([("the", 0.0, 0.1), ("twenty", 0.1, 0.3), ("six", 0.3, 0.5), ("left", 0.5, 0.9),
                          ("quietly", 0.9, 1.3)], "left quietly")
    assert span[:2] == (0.5, 1.3)
    # plain numbers unaffected
    assert at._find_span([("ten", 0.0, 0.2), ("hives", 0.2, 0.5)], "10 hives")[:2] == (0.0, 0.5)
