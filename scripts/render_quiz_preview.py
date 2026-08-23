"""Temporary preview-build runner for the quiz pilot.

Uses the repository's production quiz_pipeline.run_quiz_pipeline unchanged for content/render logic.
This file only adapts the local macOS ffmpeg/font paths to Vercel's Linux build environment and
copies the resulting artifacts under static/quiz-pilot for review.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg
import matplotlib.font_manager as fm

import quiz_pipeline as qp


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "static" / "quiz-pilot"
OUT.mkdir(parents=True, exist_ok=True)

# quiz_pipeline deliberately uses local macOS paths in the studio. Point the same renderer at
# imageio-ffmpeg's bundled Linux binary for this build-only pilot.
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
qp.FF = FFMPEG
os.environ["IMAGEIO_FFMPEG_EXE"] = FFMPEG
qp.FONT = fm.findfont("DejaVu Sans", fallback_to_default=True)


def portable_duration(path: str) -> float:
    """ffprobe-free duration reader using the ffmpeg binary already available to the build."""
    proc = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
    )
    text = (proc.stderr or "") + "\n" + (proc.stdout or "")
    match = re.search(r"Duration:\s*(\d+):(\d+):([0-9.]+)", text)
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


qp._dur = portable_duration

result = qp.run_quiz_pipeline(
    category="planets",
    output_dir=str(OUT),
    n_items=3,
    voice="echo",
    operator_direction=(
        "Make this a high-retention YouTube Short for Bolt Explains the World. "
        "Use three visually distinctive Solar System planets, ordered easy to hard to expert. "
        "Keep spoken lines very short, factual, playful, and suitable for a broad audience."
    ),
    progress_cb=lambda message: print(f"[quiz-pilot] {message}", flush=True),
)

# Persist a compact manifest next to the video so the preview can be audited without running code.
manifest = {
    "title": result.get("title"),
    "category": result.get("category"),
    "duration_sec": result.get("duration_sec"),
    "scene_count": result.get("scene_count"),
    "items": result.get("items"),
    "hook": result.get("hook"),
    "status": result.get("status"),
    "degraded_reasons": result.get("degraded_reasons"),
    "actual_cost": result.get("actual_cost"),
    "output": "quiz.mp4",
}
(OUT / "result.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

video = OUT / "quiz.mp4"
if not video.is_file() or video.stat().st_size == 0:
    raise SystemExit("quiz_pipeline returned without a non-empty quiz.mp4")

print(json.dumps(manifest, indent=2), flush=True)
print(f"[quiz-pilot] artifact={video} bytes={video.stat().st_size}", flush=True)
