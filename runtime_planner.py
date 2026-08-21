"""Provider-free narration runtime planning used before asset generation."""

from __future__ import annotations

import os
import re


DEFAULT_WORDS_PER_SECOND = float(
    os.environ.get("PLANNED_TTS_WORDS_PER_SECOND", "1.95")
)
DEFAULT_SCENE_PAUSE_SECONDS = float(
    os.environ.get("PLANNED_TTS_SCENE_PAUSE_SECONDS", "0.15")
)


def narration_word_count(scenes: list[dict]) -> int:
    return sum(
        len(str(scene.get("narration") or "").split())
        for scene in scenes
    )


def estimate_narration_seconds(
    scenes: list[dict],
    *,
    words_per_second: float = DEFAULT_WORDS_PER_SECOND,
    scene_pause_seconds: float = DEFAULT_SCENE_PAUSE_SECONDS,
) -> float:
    words = narration_word_count(scenes)
    punctuation_pause = 0.0
    for scene in scenes:
        narration = str(scene.get("narration") or "")
        punctuation_pause += 0.08 * len(re.findall(r"[,;:]", narration))
        punctuation_pause += 0.14 * len(re.findall(r"[.!?](?:\s|$)", narration))
    scene_pause = max(0, len(scenes) - 1) * scene_pause_seconds
    return round(
        words / max(0.1, words_per_second) + punctuation_pause + scene_pause,
        2,
    )


def runtime_word_bounds(
    target_seconds: float,
    scene_count: int,
    *,
    tolerance_seconds: float | None = None,
    words_per_second: float = DEFAULT_WORDS_PER_SECOND,
    scene_pause_seconds: float = DEFAULT_SCENE_PAUSE_SECONDS,
) -> tuple[int, int, int]:
    tolerance = (
        tolerance_seconds
        if tolerance_seconds is not None
        else max(2.5, target_seconds * 0.03)
    )
    fixed = max(0, scene_count - 1) * scene_pause_seconds + scene_count * 0.14
    center = max(1, round((target_seconds - fixed) * words_per_second))
    spread = max(2, round(tolerance * words_per_second))
    return center, max(1, center - spread), center + spread


def plan_runtime(scenes: list[dict], target_seconds: float) -> dict:
    estimated = estimate_narration_seconds(scenes)
    tolerance = max(2.5, float(target_seconds) * 0.03)
    target_words, min_words, max_words = runtime_word_bounds(
        target_seconds,
        len(scenes),
        tolerance_seconds=tolerance,
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
