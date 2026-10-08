#!/usr/bin/env python3
"""Measure a delivered film the way the reference film was measured, and print both side by side.

The 2026-10-07 flow validation compared our bee builds with the reference explainer (the Egypt
mud-brick film, 552 s) by numbers rather than impressions: cut cadence, static stretches,
silences at the story's joints, narration pace, sentence length, and how fast the opening lands
a stake. Those numbers are the acceptance measure for the fixes that followed (cutaway, no
captions, pauses, no bed). This script computes them for any job directory or video so every
build is read against the same yardstick.

    python scripts/measure_vs_reference.py jobs/bees_v13 [--reference path/to/ref.mp4]

Writes <job>/measure_vs_reference.json and prints a table. ffmpeg and ffprobe are required for
the video and audio rows; the narration rows need captions.srt or transcript.txt. Nothing here
calls a provider or changes a job.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys

# The reference film's numbers, measured 2026-10-07 with the same filters below
# (scene threshold 0.25, silence -35 dB for 0.6 s, freeze noise 0.003 for 1 s, whisper base).
REFERENCE = {
    "duration_sec": 551.8,
    "cuts": 153,
    "cuts_first_60s": 19,
    "shot_median_sec": 3.0,
    "shot_mean_sec": 3.6,
    "shot_max_sec": 6.0,
    "frozen_share_first_120s": 0.99,
    "silences": 19,
    "silences_per_minute": 2.07,
    "words_per_minute": 166,
    "sentence_median_words": 13.5,
    "sentence_max_words": 41,
    "first_you_sec": 0.0,
    "first_number_sec": 3.3,
    "first_question_sec": 66.1,
}

SCENE_THRESHOLD = 0.25
SILENCE_DB = -35
SILENCE_MIN_SEC = 0.6
FREEZE_NOISE = 0.003
FREEZE_MIN_SEC = 1.0
FREEZE_WINDOW_SEC = 120.0


# ── narration ───────────────────────────────────────────────────────────────

_SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(text: str) -> list[tuple[float, float, str]]:
    """[(start, end, text)] from SRT text. Tolerates '.' or ',' millisecond separators."""
    segments = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [line for line in block.split("\n") if line.strip()]
        if len(lines) < 2:
            continue
        match = _SRT_TIME.search(lines[0]) or _SRT_TIME.search(lines[1])
        if not match:
            continue
        values = [int(value) for value in match.groups()]
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / 1000
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / 1000
        body = lines[2:] if _SRT_TIME.search(lines[1]) else lines[1:]
        words = " ".join(body).strip()
        if words:
            segments.append((start, end, words))
    return segments


def narration_stats(segments: list[tuple[float, float, str]]) -> dict:
    """Pace, sentence lengths and the opening's first stake, from timed segments."""
    if not segments:
        return {}
    text = " ".join(words for _, _, words in segments)
    words = text.split()
    end = max(stop for _, stop, _ in segments)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    lengths = [len(s.split()) for s in sentences]
    stats = {
        "words": len(words),
        "words_per_minute": round(len(words) / (end / 60), 1) if end else None,
        "sentences": len(sentences),
        "sentence_median_words": statistics.median(lengths) if lengths else None,
        "sentence_max_words": max(lengths) if lengths else None,
        "first_you_sec": _first_time(segments, r"\b(?:you|your|you're|imagine|picture)\b"),
        "first_number_sec": _first_time(
            segments, r"\b(?:\d[\d,]*|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
                      r"hundred|thousand|million|dozen)\b"),
        "first_question_sec": _first_time(segments, r"\?"),
        "first_sentence": sentences[0] if sentences else "",
    }
    return stats


def _first_time(segments, pattern: str):
    regex = re.compile(pattern, re.I)
    for start, _, words in segments:
        if regex.search(words):
            return round(start, 1)
    return None


def transcript_as_segments(text: str, duration_sec: float) -> list[tuple[float, float, str]]:
    """A plain transcript spread evenly over the runtime, one segment per sentence, when no
    timed captions exist. First-stake timings are then estimates, and are marked as such."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    total = sum(len(s.split()) for s in sentences) or 1
    segments, clock = [], 0.0
    for sentence in sentences:
        share = len(sentence.split()) / total * duration_sec
        segments.append((clock, clock + share, sentence))
        clock += share
    return segments


# ── video and audio ─────────────────────────────────────────────────────────

def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stderr


def probe_duration(video: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", video], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def scene_cuts(video: str) -> list[float]:
    log = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", video,
                "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',showinfo",
                "-fps_mode", "vfr", "-f", "null", "-"])
    return [float(value) for value in re.findall(r"pts_time:([0-9.]+)", log)]


def cut_stats(cuts: list[float], duration: float) -> dict:
    lengths = [b - a for a, b in zip([0.0] + cuts, cuts + [duration])]
    return {
        "cuts": len(cuts),
        "cuts_first_60s": sum(1 for t in cuts if t < 60),
        "shot_median_sec": round(statistics.median(lengths), 2) if lengths else None,
        "shot_mean_sec": round(statistics.mean(lengths), 2) if lengths else None,
        "shot_max_sec": round(max(lengths), 2) if lengths else None,
    }


def silences(video: str) -> list[tuple[float, float]]:
    log = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", video,
                "-af", f"silencedetect=n={SILENCE_DB}dB:d={SILENCE_MIN_SEC}", "-f", "null", "-"])
    starts = [float(v) for v in re.findall(r"silence_start: ([0-9.]+)", log)]
    lengths = [float(v) for v in re.findall(r"silence_duration: ([0-9.]+)", log)]
    return list(zip(starts, lengths))


def frozen_share(video: str, window: float = FREEZE_WINDOW_SEC) -> float | None:
    log = _run(["ffmpeg", "-hide_banner", "-nostats", "-t", str(window), "-i", video,
                "-vf", f"freezedetect=n={FREEZE_NOISE}:d={FREEZE_MIN_SEC}", "-f", "null", "-"])
    frozen = sum(float(v) for v in re.findall(r"freeze_duration: ([0-9.]+)", log))
    duration = min(window, probe_duration(video))
    return round(frozen / duration, 2) if duration else None


# ── report ──────────────────────────────────────────────────────────────────

ROWS = [
    ("duration_sec", "runtime (s)"),
    ("cuts", "scene cuts"),
    ("cuts_first_60s", "cuts in first 60 s"),
    ("shot_median_sec", "shot median (s)"),
    ("shot_mean_sec", "shot mean (s)"),
    ("shot_max_sec", "shot max (s)"),
    ("frozen_share_first_120s", "static share, first 120 s"),
    ("silences", "silences >= 0.6 s"),
    ("silences_per_minute", "silences per minute"),
    ("words_per_minute", "narration wpm"),
    ("sentence_median_words", "sentence median (words)"),
    ("sentence_max_words", "sentence max (words)"),
    ("first_you_sec", "first 'you' (s)"),
    ("first_number_sec", "first number (s)"),
    ("first_question_sec", "first question (s)"),
]


def measure(video: str, captions: str | None, transcript: str | None,
            structural_roles_sec: list[float] | None = None) -> dict:
    duration = probe_duration(video)
    cuts = scene_cuts(video)
    quiet = silences(video)
    result = {"video": os.path.abspath(video), "duration_sec": round(duration, 1)}
    result.update(cut_stats(cuts, duration))
    result["frozen_share_first_120s"] = frozen_share(video)
    result["silences"] = len(quiet)
    result["silences_per_minute"] = round(len(quiet) / (duration / 60), 2) if duration else None
    result["silence_times_sec"] = [round(start, 1) for start, _ in quiet]
    segments, timed = [], False
    if captions and os.path.exists(captions):
        with open(captions, encoding="utf-8") as handle:
            segments = parse_srt(handle.read())
        timed = bool(segments)
    if not segments and transcript and os.path.exists(transcript):
        with open(transcript, encoding="utf-8") as handle:
            segments = transcript_as_segments(handle.read(), duration)
    result.update(narration_stats(segments))
    result["first_stake_timing"] = "measured" if timed else ("estimated" if segments else "none")
    if structural_roles_sec:
        # A pause within 1.5 s before a structural row counts as landed on its joint.
        landed = sum(1 for t in structural_roles_sec
                     if any(0 <= t - start <= 1.5 for start, _ in quiet))
        result["structural_joints"] = len(structural_roles_sec)
        result["structural_joints_with_pause"] = landed
    return result


def structural_row_times(job_dir: str) -> list[float]:
    """Start times of the hinge, mechanism, reversal and synthesis scenes, from the audio
    timing report when the job has one. Used to check that the pauses landed on the joints."""
    path = os.path.join(job_dir, "audio_timing_report.json")
    state_path = os.path.join(job_dir, "_state.json")
    try:
        with open(path, encoding="utf-8") as handle:
            report = json.load(handle)
        with open(state_path, encoding="utf-8") as handle:
            scenes = (json.load(handle).get("script") or {}).get("scenes") or []
    except (OSError, ValueError):
        return []
    timed = report.get("scenes") or []
    starts = [entry.get("start_sec") for entry in timed if isinstance(entry, dict)]
    if not starts or len(starts) != len(scenes) or any(s is None for s in starts):
        return []
    roles = {"hinge", "mechanism", "reversal", "synthesis"}
    return [float(starts[i]) for i, scene in enumerate(scenes)
            if str(scene.get("causal_role") or scene.get("story_role") or "").lower() in roles
            and i > 0]


def format_table(ours: dict, reference: dict) -> str:
    width = max(len(label) for _, label in ROWS)
    lines = [f"{'measure':<{width}}  {'reference':>10}  {'this film':>10}"]
    for key, label in ROWS:
        ref = reference.get(key)
        value = ours.get(key)
        lines.append(f"{label:<{width}}  {_fmt(ref):>10}  {_fmt(value):>10}")
    if "structural_joints" in ours:
        lines.append(f"{'joints with a pause':<{width}}  {'all':>10}  "
                     f"{str(ours['structural_joints_with_pause']) + '/' + str(ours['structural_joints']):>10}")
    if ours.get("first_sentence"):
        lines.append("")
        lines.append("first sentence: " + ours["first_sentence"][:120])
        if ours.get("first_stake_timing") == "estimated":
            lines.append("(first-stake times are estimated from an untimed transcript)")
    return "\n".join(lines)


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("target", help="job directory (explainer.mp4 + captions.srt) or a video file")
    parser.add_argument("--reference", help="measure this video as the reference instead of the "
                                            "stored 2026-10-07 numbers")
    parser.add_argument("--json", action="store_true", help="print JSON instead of the table")
    args = parser.parse_args(argv)

    if os.path.isdir(args.target):
        job_dir = args.target
        video = os.path.join(job_dir, "explainer.mp4")
        captions = os.path.join(job_dir, "captions.srt")
        transcript = os.path.join(job_dir, "transcript.txt")
        joints = structural_row_times(job_dir)
    else:
        job_dir = None
        video = args.target
        stem = os.path.splitext(video)[0]
        captions, transcript, joints = stem + ".srt", stem + ".txt", []
    if not os.path.exists(video):
        print(f"no video at {video}", file=sys.stderr)
        return 2

    reference = dict(REFERENCE)
    if args.reference:
        stem = os.path.splitext(args.reference)[0]
        reference = measure(args.reference, stem + ".srt", stem + ".txt")
    ours = measure(video, captions, transcript, joints)
    ours["reference"] = reference
    if job_dir:
        with open(os.path.join(job_dir, "measure_vs_reference.json"), "w", encoding="utf-8") as handle:
            json.dump(ours, handle, indent=1, ensure_ascii=False)
    if args.json:
        print(json.dumps(ours, indent=1, ensure_ascii=False))
    else:
        print(format_table(ours, reference))
    return 0


if __name__ == "__main__":
    sys.exit(main())
