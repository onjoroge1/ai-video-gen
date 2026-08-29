from runtime_planner import (
    DEFAULT_WORDS_PER_SECOND,
    estimate_narration_seconds,
    narration_overhead_seconds,
    narration_word_count,
    plan_runtime,
    runtime_word_bounds,
)


def _scenes(words: int, count: int = 18):
    per_scene = words // count
    remainder = words % count
    return [
        {"narration": " ".join(["word"] * (per_scene + (1 if i < remainder else 0))) + "."}
        for i in range(count)
    ]


def test_old_198_word_pilot_is_rejected_before_assets_for_90_second_request():
    """Still rejected, but the direction flipped when words_per_second was corrected.

    At 1.95 w/s this asserted 198 words OVERRUN a 90s request at >100s. Real TTS measured
    2.86 w/s, so 198 words UNDERRUN it -- about 74s of speech for 90s of video. The pilot
    was always outside the contract; the old constant just had the sign wrong.
    """
    report = plan_runtime(_scenes(198), 90)

    assert report["passed"] is False
    assert abs(report["delta_seconds"]) > report["tolerance_seconds"]


def test_runtime_word_window_targets_the_requested_duration():
    # Given the overhead the script actually carries, the word window and the second
    # window describe the same script. They used to be computed from two different
    # models, so a draft could sit inside the word allowance and still fail on
    # seconds -- a real 120s run landed 227 words inside a 222-236 window at 123.8s.
    # _scenes always emits one sentence per scene, so its overhead does not vary with
    # word count and the probe measures what _scenes(target) will carry.
    overhead = narration_overhead_seconds(_scenes(200))
    target, low, high = runtime_word_bounds(90, 18, overhead_seconds=overhead)
    report = plan_runtime(_scenes(target), 90)

    assert low <= narration_word_count(_scenes(target)) <= high
    assert abs(report["delta_seconds"]) <= report["tolerance_seconds"]
    assert report["passed"] is True


def test_word_window_and_second_window_agree_at_both_edges():
    # The property the run above violated: both edges of the word allowance must
    # produce a duration inside tolerance. The old bounds failed this on BOTH sides --
    # at 120s/9 scenes the minimum allowed word count came out 8s under target.
    for duration, count in ((60, 6), (90, 12), (120, 9), (240, 16)):
        overhead = narration_overhead_seconds(_scenes(200, count))
        _, low, high = runtime_word_bounds(
            duration, count, overhead_seconds=overhead)
        for words in (low, high):
            report = plan_runtime(_scenes(words, count), duration)
            assert abs(report["delta_seconds"]) <= report["tolerance_seconds"], (
                f"{words} words is inside the allowance for {duration}s/{count} "
                f"scenes but estimates {report['estimated_seconds']}s")


def test_pre_script_fallback_assumes_real_narration_punctuation():
    # With no scenes yet the bounds must assume the punctuation real narration
    # carries. Assuming one sentence per scene and no commas made every first draft
    # overshoot by construction: measured drafts run ~0.8s per scene of pause, so a
    # 120s/9-scene ask was ~9 words too generous before the model wrote a line.
    # Derive from the live constant. This hardcoded 1.95, so correcting words_per_second to
    # 2.86 made the arithmetic report a negative overhead -- the test was pinned to a number it
    # was not testing.
    target, _, _ = runtime_word_bounds(120, 9)
    assumed_overhead = 120 - target / DEFAULT_WORDS_PER_SECOND
    assert assumed_overhead > 5.0, (
        f"fallback assumes only {assumed_overhead:.1f}s of pause across 9 scenes; "
        "measured drafts carry ~7s")


def test_punctuation_and_scene_boundaries_are_included_in_estimate():
    plain = [{"narration": "one two three four"}]
    paused = [{"narration": "one, two. Three? Four!"}]

    assert estimate_narration_seconds(paused) > estimate_narration_seconds(plain)
