"""One-off Vercel preview render using the repo's Rapid Reveal V2.1 quiz engine."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

# Configure portable FFmpeg before importing the repo renderer.
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
os.environ["FFMPEG_BIN"] = FFMPEG
os.environ["QUIZ_FAL_OPENER"] = "0"  # V2.1 progressive clues are the controlled creative.

import quiz_pipeline as qp

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "static" / "rapid-quiz-preview"
OUT.mkdir(parents=True, exist_ok=True)
qp.FF = FFMPEG


def portable_duration(path: str) -> float:
    proc = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    text = (proc.stderr or "") + "\n" + (proc.stdout or "")
    match = re.search(r"Duration:\s*(\d+):(\d+):([0-9.]+)", text)
    if not match:
        return 0.0
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


qp._dur = portable_duration

result = qp.run_quiz_pipeline(
    category="weird animals",
    output_dir=str(OUT),
    n_items=3,
    voice="echo",
    operator_direction=(
        "Create a fun, broad-audience weird-animal challenge. Pick three recognizable but visually "
        "surprising animals that are not silhouette cliches. The first must require thought immediately; "
        "the second harder; the third genuinely expert. Prefer distinctive partial outlines/details that "
        "work with the progressive crop mechanic. Keep the tone playful and fast."
    ),
    progress_cb=lambda message: print(f"[rapid-quiz] {message}", flush=True),
)

manifest = {
    "title": result.get("title"),
    "category": result.get("category"),
    "duration_sec": result.get("duration_sec"),
    "planned_duration_sec": result.get("planned_duration_sec"),
    "scene_count": result.get("scene_count"),
    "items": result.get("items"),
    "hook": result.get("hook"),
    "quiz_creative": result.get("quiz_creative"),
    "first_clue_at_sec": result.get("first_clue_at_sec"),
    "progressive_clues": result.get("progressive_clues"),
    "subscribe_cta": result.get("subscribe_cta"),
    "visual_qa": result.get("visual_qa"),
    "status": result.get("status"),
    "degraded_reasons": result.get("degraded_reasons"),
    "actual_cost": result.get("actual_cost"),
    "output": "quiz.mp4",
}
(OUT / "result.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
video = OUT / "quiz.mp4"
if not video.is_file() or video.stat().st_size == 0:
    raise SystemExit("Rapid Reveal renderer did not produce quiz.mp4")
print(json.dumps(manifest, indent=2), flush=True)
print(f"[rapid-quiz] artifact={video} bytes={video.stat().st_size}", flush=True)
