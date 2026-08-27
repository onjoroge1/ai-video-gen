"""Overlapping windows of one match are not competing answers.

_find_span's fuzzy layer requires the best candidate to beat the runner-up by 0.08, so a
phrase occurring twice in a scene is not timed to the wrong occurrence. But it compared the
best candidate against OVERLAPPING windows of the same match -- one location viewed at three
widths -- and rejected it for being too close to itself.

Run b1def6df: narration "still smouldering underneath", transcript "still smoldering
underneath". One letter. Candidates were (0.982, start 22, width 3), (0.915, start 22,
width 4), (0.857, start 23, width 2). Gap 0.067 < 0.08, so a near-perfect match was thrown
away and the run died after buying its audio.

This is the sixth cause of anchor mismatch found today, after zero-width timestamps,
cross-sentence anchors, dash-fused tokens, one-sided tokenisation and number words. They are
all the same thing: identical speech producing non-identical tokens. Rejecting a 0.98 match
is what made each of them fatal instead of survivable.
"""

from audio_timing import _find_span, _split_joined


def _timed(sentence, step=0.4):
    words = []
    for index, word in enumerate(sentence.split()):
        words.extend(_split_joined(word, index * step, (index + 1) * step))
    return words


def test_a_spelling_variant_resolves():
    spoken = _timed("the inflammation still smoldering underneath the healed surface")

    assert _find_span(spoken, "still smouldering underneath")


def test_a_single_near_miss_resolves():
    assert _find_span(_timed("a red beeker on the bench"), "a red beaker")


def test_two_near_misses_in_different_places_stay_ambiguous():
    # The guard's real purpose: never time a phrase to the wrong occurrence.
    spoken = _timed("a red beeker on the bench and later a red beakor on the shelf")

    assert _find_span(spoken, "a red beaker") is None


def test_an_exact_match_is_unaffected():
    assert _find_span(_timed("he drank the cloudy broth"), "drank the cloudy broth")


def test_an_unrelated_phrase_still_finds_nothing():
    assert _find_span(_timed("the beaker sat on the bench"), "nobel prize stockholm") is None
