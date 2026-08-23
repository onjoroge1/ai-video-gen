"""Measured natural-speed audio timing contracts for long-form explainers."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Callable


def _clean(value: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", str(value or "").casefold())


def _find_span(words: list[tuple[str, float, float]], phrase: str) -> tuple[float, float, str, float] | None:
    needle = [_clean(token) for token in str(phrase or "").split()]
    needle = [token for token in needle if token]
    haystack = [_clean(item[0]) for item in words]
    if not needle:
        return None
    for start in range(len(haystack) - len(needle) + 1):
        if haystack[start:start + len(needle)] == needle:
            return (float(words[start][1]), float(words[start + len(needle) - 1][2]),
                    "measured_word_timestamps", 1.0)
    # Whisper occasionally expands contractions or substitutes one short token. Permit only a
    # high-confidence local alignment, and reject ambiguous matches instead of guessing a timestamp.
    candidates: list[tuple[float, int, int]] = []
    for width in range(max(1, len(needle) - 1), len(needle) + 2):
        for start in range(len(haystack) - width + 1):
            window = haystack[start:start + width]
            token_ratio = SequenceMatcher(None, needle, window).ratio()
            character_ratio = SequenceMatcher(None, " ".join(needle), " ".join(window)).ratio()
            ratio = max(token_ratio, character_ratio)
            if ratio >= 0.84:
                candidates.append((ratio, start, width))
    if candidates:
        candidates.sort(reverse=True)
        best = candidates[0]
        if len(candidates) == 1 or best[0] - candidates[1][0] >= 0.08:
            _, start, width = best
            return (float(words[start][1]), float(words[start + width - 1][2]),
                    "measured_word_timestamps_fuzzy", round(best[0], 3))
    return None


def build_audio_timing_report(
    scenes: list[dict],
    audio_paths: list[str],
    word_times: list[list],
    target_seconds: float,
    *,
    duration_probe: Callable[[str], float],
) -> dict:
    """Measure final-speed audio and require real word/phrase timestamps."""
    errors: list[dict] = []
    scene_reports: list[dict] = []
    phrase_timestamps: list[dict] = []
    cursor = 0.0

    if not (len(scenes) == len(audio_paths) == len(word_times)):
        return {
            "version": 1, "passed": False, "target_seconds": float(target_seconds),
            "errors": [{"code": "audio_scene_count_mismatch", "message": "Scene, audio, and timing counts differ."}],
        }

    for index, (scene, path, timings) in enumerate(zip(scenes, audio_paths, word_times), 1):
        try:
            duration = float(duration_probe(path))
        except Exception:
            duration = 0.0
        if duration <= 0:
            errors.append({"code": "invalid_audio_duration", "scene": index, "message": "Audio duration is missing or invalid."})
        clean_words = []
        for item in timings or []:
            try:
                word, start, end = str(item[0]), float(item[1]), float(item[2])
            except (TypeError, ValueError, IndexError):
                continue
            if _clean(word) and 0 <= start < end <= duration + 0.25:
                clean_words.append((word, start, end))
        script_word_count = len(str(scene.get("narration") or "").split())
        coverage = len(clean_words) / max(1, script_word_count)
        if not clean_words or not 0.70 <= coverage <= 1.30:
            errors.append({
                "code": "word_timing_coverage", "scene": index,
                "message": f"Measured word timing coverage is {coverage:.0%}; expected 70–130%.",
            })
        scene_reports.append({
            "scene": index, "audio_path": path, "start_sec": round(cursor, 3),
            "duration_sec": round(duration, 3), "end_sec": round(cursor + duration, 3),
            "script_words": script_word_count, "timed_words": len(clean_words),
            "timing_coverage": round(coverage, 3),
        })
        for beat_index, beat in enumerate(scene.get("visual_beats") or [], 1):
            if not isinstance(beat, dict):
                continue
            phrase = str(beat.get("anchor_phrase") or "").strip()
            if not phrase:
                continue
            span = _find_span(clean_words, phrase)
            if not span:
                errors.append({
                    "code": "unmatched_phrase_timestamp", "scene": index,
                    "message": f"Visual beat phrase is not present in measured speech: {phrase}",
                })
                continue
            phrase_timestamps.append({
                "scene": index, "visual_beat": beat_index, "phrase": phrase,
                "start_sec": round(cursor + span[0], 3), "end_sec": round(cursor + span[1], 3),
                "source": span[2], "match_confidence": span[3],
            })
        cursor += duration

    tolerance = float(target_seconds) * 0.03
    delta = cursor - float(target_seconds)
    if abs(delta) - tolerance > 1e-6:
        errors.append({
            "code": "measured_runtime_outside_tolerance",
            "message": f"Measured narration is {cursor:.2f}s for a {target_seconds:.2f}s target (±{tolerance:.2f}s).",
        })
    return {
        "version": 1,
        "passed": not errors,
        "natural_speed": True,
        "post_stretched": False,
        "target_seconds": round(float(target_seconds), 3),
        "tolerance_seconds": round(tolerance, 3),
        "minimum_seconds": round(float(target_seconds) - tolerance, 3),
        "maximum_seconds": round(float(target_seconds) + tolerance, 3),
        "measured_seconds": round(cursor, 3),
        "delta_seconds": round(delta, 3),
        "scenes": scene_reports,
        "phrase_timestamps": phrase_timestamps,
        "errors": errors,
    }
