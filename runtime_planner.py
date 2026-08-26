"""Provider-free narration runtime planning used before asset generation."""

from __future__ import annotations

import math
import os
import re


# 2.86, from the only real measurement this pipeline has produced: run 52ed138b spoke 228 words
# in 86.95s of natural-speed TTS, which is 2.857 w/s once the overhead below is subtracted.
#
# This was 1.95, and nothing in the tree agreed with it: explainer_pipeline's opening-tranche
# estimator uses 2.64 for the same physical quantity. Two constants for one fact, ~35% apart, and
# the runtime contract was built on the wrong one -- so a script the contract passed as "120.0s"
# rendered as an 87-second video. Every word budget was a third short.
#
# ONE observation, one topic, one voice. It is a large correction in the right direction rather
# than a calibrated value: 1.95 was wrong by 34% and 2.86 reproduces the single measurement we
# have. It needs several real renders across topics and voices before it deserves trust, and the
# script-only harness CANNOT confirm it -- the harness predicts, it never runs TTS. Only a full
# render measures this.
DEFAULT_WORDS_PER_SECOND = float(
    os.environ.get("PLANNED_TTS_WORDS_PER_SECOND", "2.86")
)
DEFAULT_SCENE_PAUSE_SECONDS = float(
    os.environ.get("PLANNED_TTS_SCENE_PAUSE_SECONDS", "0.15")
)
# Comma and sentence-end pause assumed per scene before a script exists; once there are scenes,
# narration_overhead_seconds counts the real punctuation instead.
#
# NOT a measurement, despite the commit that introduced it saying so. It was derived as
# `estimated_seconds - words/1.95` across three drafts, where estimated_seconds came from
# estimate_narration_seconds itself -- so it measured the estimator against its own punctuation
# model and could only ever agree with it. The three "independent" figures (0.77, 0.82, 0.83)
# were restatements of the same formula, not evidence about speech.
#
# It is kept because words_per_second above was solved WITH this overhead in place, so the pair
# reproduces the one real measurement together. Either both change or neither does.
MEASURED_PUNCTUATION_PAUSE_PER_SCENE = float(
    os.environ.get("PLANNED_TTS_PUNCTUATION_PAUSE_PER_SCENE", "0.66")
)


def narration_word_count(scenes: list[dict]) -> int:
    return sum(
        len(str(scene.get("narration") or "").split())
        for scene in scenes
    )


def narration_overhead_seconds(
    scenes: list[dict],
    *,
    scene_pause_seconds: float = DEFAULT_SCENE_PAUSE_SECONDS,
) -> float:
    """Every second of the estimate that is not words / words_per_second.

    Pulled out so runtime_word_bounds can invert the same number the estimator
    charges. When the bounds guess this instead, the word window and the second
    window describe different scripts and a refit can satisfy one while failing
    the other.
    """
    punctuation_pause = 0.0
    for scene in scenes:
        narration = str(scene.get("narration") or "")
        punctuation_pause += 0.08 * len(re.findall(r"[,;:]", narration))
        punctuation_pause += 0.14 * len(re.findall(r"[.!?](?:\s|$)", narration))
    scene_pause = max(0, len(scenes) - 1) * scene_pause_seconds
    return punctuation_pause + scene_pause


def estimate_narration_seconds(
    scenes: list[dict],
    *,
    words_per_second: float = DEFAULT_WORDS_PER_SECOND,
    scene_pause_seconds: float = DEFAULT_SCENE_PAUSE_SECONDS,
) -> float:
    words = narration_word_count(scenes)
    overhead = narration_overhead_seconds(
        scenes, scene_pause_seconds=scene_pause_seconds
    )
    return round(words / max(0.1, words_per_second) + overhead, 2)


def runtime_word_bounds(
    target_seconds: float,
    scene_count: int,
    *,
    tolerance_seconds: float | None = None,
    words_per_second: float = DEFAULT_WORDS_PER_SECOND,
    scene_pause_seconds: float = DEFAULT_SCENE_PAUSE_SECONDS,
    overhead_seconds: float | None = None,
) -> tuple[int, int, int]:
    tolerance = (
        tolerance_seconds
        if tolerance_seconds is not None
        else max(2.5, target_seconds * 0.03)
    )
    if overhead_seconds is None:
        # No script yet, so use the per-scene overhead real narration actually carries.
        # This assumed one sentence per scene and no commas (0.27s/scene), while three
        # measured 120s drafts came in at 0.77, 0.82 and 0.83 — nearly 3x higher. The
        # ask was therefore ~9 words too generous every time, so draft one overshot by
        # construction and spent refit passes walking back a target that was wrong when
        # it was set. Callers holding scenes should pass the measured overhead instead.
        overhead_seconds = (
            max(0, scene_count - 1) * scene_pause_seconds
            + scene_count * MEASURED_PUNCTUATION_PAUSE_PER_SCENE
        )
    # Convert each edge from seconds independently and round INWARD. Deriving the
    # centre and adding a symmetric word spread cannot express the window exactly: a
    # word is ~0.51s, so both the centre rounding and the spread rounding push the
    # edges outward, and their sum put the allowance outside its own tolerance --
    # 222 words was "allowed" for a 120s request at 116.31s against a 3.6s tolerance.
    def speech(seconds: float) -> float:
        return (seconds - overhead_seconds) * words_per_second

    center = max(1, round(speech(target_seconds)))
    low = max(1, math.ceil(speech(target_seconds - tolerance)))
    high = max(low, math.floor(speech(target_seconds + tolerance)))
    return center, low, high


def plan_runtime(scenes: list[dict], target_seconds: float) -> dict:
    estimated = estimate_narration_seconds(scenes)
    tolerance = max(2.5, float(target_seconds) * 0.03)
    target_words, min_words, max_words = runtime_word_bounds(
        target_seconds,
        len(scenes),
        tolerance_seconds=tolerance,
        overhead_seconds=narration_overhead_seconds(scenes),
    )
    words = narration_word_count(scenes)
    return {
        "target_seconds": round(float(target_seconds), 2),
        "estimated_seconds": estimated,
        "delta_seconds": round(estimated - float(target_seconds), 2),
        "tolerance_seconds": round(tolerance, 2),
        "word_count": words,
        "target_words": target_words,
        "min_words": min_words,
        "max_words": max_words,
        "words_per_second": DEFAULT_WORDS_PER_SECOND,
        "passed": (
            abs(estimated - float(target_seconds)) <= tolerance
            and min_words <= words <= max_words
        ),
    }
