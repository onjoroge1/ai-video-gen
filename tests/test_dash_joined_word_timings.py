"""A transcriber-fused token must not delete a word boundary.

Whisper emits "two-the" as ONE token for narration punctuated "two. The", and _clean strips
the dash rather than splitting on it -- producing "twothe", a word that appears in no anchor
and matches nothing. Every phrase spanning that point then failed as "not present in measured
speech" for narration that was spoken perfectly, and no fuzzy fallback could recover it
because the word genuinely was not in the token list.

Run 4ed2fe67, scene 12: anchor "The real culprits were two." against a haystack reading
['the','real','culprits','were','twothe','infection',...].
"""

from audio_timing import _find_span, _split_joined, build_audio_timing_report

NARRATION = "The real culprits were two. The infection and everyday painkillers"
ANCHOR = "The real culprits were two."


def _fused_timings():
    """What the transcriber actually returned: 'two-the' as a single token."""
    tokens = ["The", "real", "culprits", "were", "two—the", "infection", "and",
              "everyday", "painkillers"]
    return [(word, i * 0.4, (i + 1) * 0.4) for i, word in enumerate(tokens)]


def _report(word_times):
    return build_audio_timing_report(
        [{"narration": NARRATION, "visual_beats": [{"anchor_phrase": ANCHOR}]}],
        ["scene_11.mp3"], [word_times], target_seconds=len(NARRATION.split()) * 0.4,
        duration_probe=lambda _p: len(NARRATION.split()) * 0.4 + 1.0,
        audio_transformations=[{
            "speed_multiplier": 1.0, "operations": [], "audio_sha256": "x" * 8}],
    )


def test_a_dash_fused_token_splits_into_its_words():
    assert _split_joined("two—the", 1.0, 1.4) == [("two", 1.0, 1.2), ("the", 1.2, 1.4)]


def test_an_ordinary_word_is_left_alone():
    assert _split_joined("infection", 1.0, 1.4) == [("infection", 1.0, 1.4)]
    assert _split_joined("don't", 1.0, 1.4) == [("don't", 1.0, 1.4)]


def test_the_anchor_resolves_across_a_fused_token():
    codes = {issue["code"] for issue in _report(_fused_timings()).get("errors", [])}

    assert "unmatched_phrase_timestamp" not in codes, (
        "a dash-fused token deleted a word boundary and broke the anchor")


def test_the_split_pieces_stay_inside_the_original_span():
    # Timings are approximate but must not escape the token they came from, or a visual
    # cue lands outside the audio it belongs to.
    pieces = _split_joined("two—the", 2.0, 2.6)

    assert pieces[0][1] >= 2.0 and pieces[-1][2] <= 2.6
    assert all(start < end for _w, start, end in pieces)


def test_a_clean_transcript_still_matches():
    unfused = [(w, i * 0.4, (i + 1) * 0.4) for i, w in enumerate(NARRATION.split())]

    assert _find_span(unfused, ANCHOR)


def test_a_genuinely_hyphenated_word_still_matches():
    """The regression the one-sided split caused.

    _split_joined breaks dash-joined tokens in the HAYSTACK. If the needle is not split the
    same way, "once-healthy" cleans to "oncehealthy" and can never match the "once","healthy"
    the haystack now holds -- so fixing the fused-token bug broke every hyphenated anchor.
    Run 45a87541 died on "A biopsy of his once-healthy stomach", which had been fine before.
    """
    spoken = ["A", "biopsy", "of", "his", "once-healthy", "stomach", "comes", "back"]
    words = []
    for index, word in enumerate(spoken):
        words.extend(_split_joined(word, index * 0.4, (index + 1) * 0.4))

    assert _find_span(words, "A biopsy of his once-healthy stomach"), (
        "a hyphenated anchor must survive the same split its haystack gets"
    )
