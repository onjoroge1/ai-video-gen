"""Measured natural-speed audio timing contracts for long-form explainers."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Callable


# Whisper writes some spoken numbers as digits and others as words, inconsistently WITHIN one
# sentence: "more than nine in every 10 of them, up to eight in 10". The narration said "ten"
# both times. So the anchor "more than nine in every ten" could not match the transcript, and no
# fuzzy fallback bridged it -- "ten" and "10" are simply different tokens.
#
# Both forms therefore map to one key. Normalising in a single direction would not help, since
# either side can carry either form.
_NUMBER_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11",
    "twelve": "12", "thirteen": "13", "fourteen": "14", "fifteen": "15", "sixteen": "16",
    "seventeen": "17", "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80",
    "ninety": "90", "hundred": "100", "thousand": "1000", "million": "1000000",
    "first": "1st", "second": "2nd", "third": "3rd",
}


def _clean(value: str) -> str:
    token = re.sub(r"[^a-z0-9']+", "", str(value or "").casefold())
    return _NUMBER_WORDS.get(token, token)


_JOINER = re.compile(r"[\u2010-\u2015\-/]+")


def _split_joined(word: str, start: float, end: float) -> list:
    """Split a token the transcriber fused with a dash into its real words.

    Whisper emits "two-the" as ONE token for narration punctuated "two. The", and _clean
    deletes the dash rather than splitting on it -- producing "twothe", a word that appears
    in no anchor and matches nothing. The words were all spoken and the transcript was
    complete; the tokenisation destroyed the boundary, so every phrase spanning that point
    failed as "not present in measured speech" and no fuzzy fallback could recover it.

    The pieces share the original span. That is approximate, but a phrase boundary landing a
    few hundred milliseconds off is a visual cue timed slightly early -- against the previous
    behaviour, which was to fail the run outright after buying the audio.
    """
    parts = [part for part in _JOINER.split(word) if _clean(part)]
    if len(parts) <= 1:
        return [(word, start, end)]
    step = (end - start) / len(parts)
    return [(part, start + i * step, start + (i + 1) * step) for i, part in enumerate(parts)]


def _find_span(words: list[tuple[str, float, float]], phrase: str) -> tuple[float, float, str, float] | None:
    # Split the needle on the SAME joiners as the haystack. _split_joined breaks a
    # transcriber-fused "two-the" into two tokens; if the phrase is not split identically then a
    # legitimately hyphenated word ("once-healthy") cleans to "oncehealthy" and can never match
    # the "once","healthy" the haystack now holds. One-sided tokenisation trades one mismatch for
    # another -- which is exactly what my first version of this did.
    needle = [_clean(part) for token in str(phrase or "").split()
              for part in _JOINER.split(token)]
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
    # A long anchor may contain a transcription substitution while retaining an exact, unique
    # consecutive subphrase. Use only an unambiguous subphrase so timing never silently jumps to
    # another repeated phrase.
    for width in range(min(3, len(needle)), 1, -1):
        matches: list[tuple[int, int]] = []
        for needle_start in range(len(needle) - width + 1):
            fragment = needle[needle_start:needle_start + width]
            for start in range(len(haystack) - width + 1):
                if haystack[start:start + width] == fragment:
                    matches.append((start, width))
        if len(matches) == 1:
            start, matched_width = matches[0]
            return (float(words[start][1]), float(words[start + matched_width - 1][2]),
                    "measured_unique_subphrase", round(matched_width / len(needle), 3))
    unique_tokens = [token for token in needle if len(token) >= 4
                     and needle.count(token) == 1 and haystack.count(token) == 1]
    if len(unique_tokens) == 1:
        start = haystack.index(unique_tokens[0])
        return (float(words[start][1]), float(words[start][2]),
                "measured_unique_token", round(1 / len(needle), 3))
    return None


def build_audio_timing_report(
    scenes: list[dict],
    audio_paths: list[str],
    word_times: list[list],
    target_seconds: float,
    *,
    duration_probe: Callable[[str], float],
    audio_transformations: list[dict] | None = None,
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

    transformations = audio_transformations if isinstance(audio_transformations, list) else []
    if len(transformations) != len(scenes):
        errors.append({
            "code": "audio_transformation_ledger_missing",
            "message": "Every narration scene requires an audio transformation ledger entry.",
        })

    normalized_transformations = []
    for index, item in enumerate(transformations, 1):
        if not isinstance(item, dict):
            errors.append({"code": "invalid_audio_transformation", "scene": index,
                           "message": "Audio transformation entry is not an object."})
            continue
        try:
            speed = float(item.get("speed_multiplier"))
        except (TypeError, ValueError):
            speed = 0.0
        operations = item.get("operations") if isinstance(item.get("operations"), list) else None
        if speed <= 0 or operations is None or not str(item.get("audio_sha256") or "").strip():
            errors.append({"code": "invalid_audio_transformation", "scene": index,
                           "message": "Audio transformation entry lacks speed, operations, or file hash."})
        normalized_transformations.append({
            "scene": index,
            "provider": str(item.get("provider") or ""),
            "model": str(item.get("model") or ""),
            "voice": str(item.get("voice") or ""),
            "speed_multiplier": speed,
            "operations": operations or [],
            "audio_sha256": str(item.get("audio_sha256") or ""),
            "cache_status": str(item.get("cache_status") or ""),
        })

    time_operations = {"atempo", "rubberband", "time_stretch", "speed_change"}
    post_stretched = any(
        abs(float(item.get("speed_multiplier") or 0.0) - 1.0) > 1e-9
        or bool(time_operations.intersection({str(op).casefold() for op in item.get("operations") or []}))
        for item in normalized_transformations
    )
    natural_speed = bool(normalized_transformations) and not post_stretched

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
            # start <= end, not start < end. Whisper emits a zero-width span for some words, and
            # the strict comparison silently DROPPED them -- two of twenty-three in the run that
            # exposed this. The words survive in the transcript and vanish from the list the gate
            # searches, so a phrase containing one is torn in half and reported as "not present in
            # measured speech" when it was spoken perfectly clearly. Losing 2 of 23 words is 91%
            # coverage, which sails through the check below, so nothing else caught it either.
            # The bound this filter exists to enforce is the UPPER one: timestamps past the audio.
            if _clean(word) and 0 <= start <= end <= duration + 0.25:
                clean_words.extend(_split_joined(word, start, end))
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

    # Same widened band as the planner, from one constant. A measured gate stricter than the
    # planned one rejects scripts the planner just approved.
    from runtime_planner import RUNTIME_TOLERANCE_FRACTION
    tolerance = float(target_seconds) * RUNTIME_TOLERANCE_FRACTION
    delta = cursor - float(target_seconds)
    if abs(delta) - tolerance > 1e-6:
        errors.append({
            "code": "measured_runtime_outside_tolerance",
            "message": f"Measured narration is {cursor:.2f}s for a {target_seconds:.2f}s target (±{tolerance:.2f}s).",
        })
    return {
        "version": 1,
        "passed": not errors,
        "natural_speed": natural_speed,
        "post_stretched": post_stretched,
        "audio_transformations": normalized_transformations,
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
