from runtime_planner import (
    estimate_narration_seconds,
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
    report = plan_runtime(_scenes(198), 90)

    assert report["estimated_seconds"] > 100
    assert report["passed"] is False


def test_runtime_word_window_targets_the_requested_duration():
    target, low, high = runtime_word_bounds(90, 18)
    report = plan_runtime(_scenes(target), 90)

    assert low <= narration_word_count(_scenes(target)) <= high
    assert abs(report["delta_seconds"]) <= report["tolerance_seconds"]
    assert report["passed"] is True


def test_punctuation_and_scene_boundaries_are_included_in_estimate():
    plain = [{"narration": "one two three four"}]
    paused = [{"narration": "one, two. Three? Four!"}]

    assert estimate_narration_seconds(paused) > estimate_narration_seconds(plain)
