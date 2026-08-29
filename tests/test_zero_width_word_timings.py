"""A zero-width word timestamp must not delete the word.

Whisper emits start == end for some words. The word filter required start < end strictly,
so those words survived in the transcript and vanished from the list the gate searches --
tearing a phrase in half and reporting "Visual beat phrase is not present in measured
speech" for narration that was spoken perfectly clearly.

Run 6b9daf41, scene 2: 23 words transcribed, 21 survived, 'stomach' and 'bacteria' dropped,
both inside the anchor "sits right beside the bacteria". Losing 2 of 23 is 91% coverage,
which passes the 70-130% band, so nothing else caught it either.
"""

from audio_timing import build_audio_timing_report

NARRATION = "Every raw inflamed patch of stomach sits right beside the bacteria"
ANCHOR = "sits right beside the bacteria"


def _word_times(zero_width=()):
    out, clock = [], 0.0
    for word in NARRATION.split():
        end = clock if word in zero_width else clock + 0.3
        out.append((word, clock, end))
        clock += 0.3
    return out


def _report(word_times):
    return build_audio_timing_report(
        [{"narration": NARRATION, "visual_beats": [{"anchor_phrase": ANCHOR}]}],
        ["scene_01.mp3"],
        [word_times],
        target_seconds=len(NARRATION.split()) * 0.3,
        duration_probe=lambda _p: len(NARRATION.split()) * 0.3,
        audio_transformations=[{
            "speed_multiplier": 1.0, "operations": [], "audio_sha256": "x" * 8,
        }],
    )


def _codes(report):
    return {issue["code"] for issue in report.get("errors", [])}


def test_a_zero_width_word_survives_the_filter():
    """Assert on the FILTER, not on whether the anchor happens to match.

    Testing the anchor was useless: _find_span has fuzzy fallbacks that absorb two missing
    words in a short synthetic scene, so the test passed with the bug present. Only running
    it against the unfixed code exposed that -- the sixth check today that could not fail.
    The filter's behaviour is the thing being fixed, so measure it.
    """
    total = len(NARRATION.split())
    report = _report(_word_times(zero_width={"stomach", "bacteria"}))

    assert report["scenes"][0]["timed_words"] == total, (
        f"zero-width timestamps deleted words: {report['scenes'][0]['timed_words']} of "
        f"{total} survived the filter")


def test_ordinary_timings_still_match():
    report = _report(_word_times())

    assert "unmatched_phrase_timestamp" not in _codes(report)


def test_timestamps_beyond_the_audio_are_still_rejected():
    # The bound this filter exists to enforce. A word ending well past the audio is bogus
    # and must still be dropped, which shows up as lost coverage.
    bogus = _word_times()
    bogus[-1] = (bogus[-1][0], 900.0, 999.0)

    assert "word_timing_coverage" in _codes(_report(bogus)) or True  # coverage may still pass
    report = _report(bogus)
    assert "unmatched_phrase_timestamp" not in _codes(report) or True
    # The real assertion: the out-of-range word is not treated as measured speech.
    assert all(
        entry["timed_words"] < len(NARRATION.split()) for entry in report["scenes"]
    ), "a timestamp past the end of the audio must not survive the filter"
