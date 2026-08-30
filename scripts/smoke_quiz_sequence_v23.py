from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="quiz_sequence_smoke_"))

# Resolve the same bundled portable binary used in Vercel production, then import the facade so
# the preserved renderer receives that path before it binds its module globals.
import media_binaries

FF = media_binaries.ffmpeg()
os.environ["FFMPEG_BIN"] = FF
os.environ.pop("FFPROBE_BIN", None)
media_binaries.reset_cache()

import quiz_pipeline as qp

legacy = qp._legacy
legacy.FF = FF
legacy.FP = "ffprobe"
legacy._dur = media_binaries.probe_duration

W, H, FPS = legacy.W, legacy.H, legacy.FPS
CDN = 0.8
TRANSITION = legacy._REVEAL_TRANSITION_SEC
ROUND_REVEAL = 1.0
FINAL_REVEAL = 1.8


def make_card(path: Path, background: tuple[int, int, int], accent: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (W, H), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((140, 420, W - 140, H - 330), radius=90, fill=accent)
    draw.ellipse((320, 690, W - 320, 1190), fill=(15, 18, 28))
    image.save(path)


def make_overlay(path: Path, marker: int, cta: bool = False) -> None:
    image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((105, 110, W - 105, 310), radius=45, fill=(10, 18, 38, 225))
    draw.rounded_rectangle((115, H - 430, W - 115, H - 180), radius=55,
                           fill=((210, 70, 70, 235) if cta else (25, 120, 170, 230)))
    # Distinct geometry is enough for overlay/fade/loop verification; text rendering is covered
    # by the permanent quiz contract tests and the real paid assets already generated.
    width = 100 + marker * 34
    draw.rectangle((W // 2 - width, 165, W // 2 + width, 245), fill=(255, 255, 255, 245))
    image.save(path)


def make_transition(path: Path, rgb: tuple[int, int, int]) -> None:
    color = "0x%02x%02x%02x" % rgb
    result = subprocess.run(
        [
            FF, "-y", "-f", "lavfi", "-i",
            f"color=c={color}:s={W}x{H}:r={FPS}:d={TRANSITION:.3f}",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "synthetic transition encode failed: "
            + result.stderr.decode(errors="replace")[-1600:]
        )


clues: list[Path] = []
reveals: list[Path] = []
countdown_overlays: list[list[Path]] = []
answer_overlays: list[Path] = []
transition_clips: list[Path] = []

palette = [
    ((105, 145, 95), (195, 180, 105)),
    ((42, 100, 75), (90, 175, 120)),
    ((105, 145, 95), (205, 150, 95)),
]
for round_index, (background, accent) in enumerate(palette, 1):
    clue = WORK / f"clue{round_index}.png"
    reveal = WORK / f"reveal{round_index}.png"
    make_card(clue, background, accent)
    make_card(reveal, tuple(min(255, c + 40) for c in background),
              tuple(min(255, c + 25) for c in accent))
    clues.append(clue)
    reveals.append(reveal)

    round_overlays: list[Path] = []
    for stage in range(3):
        overlay = WORK / f"round{round_index}_stage{stage}.png"
        make_overlay(overlay, marker=round_index * 3 + stage)
        round_overlays.append(overlay)
    countdown_overlays.append(round_overlays)

    answer_overlay = WORK / f"answer{round_index}.png"
    make_overlay(answer_overlay, marker=10 + round_index)
    answer_overlays.append(answer_overlay)

    transition = WORK / f"transition{round_index}.mp4"
    make_transition(transition, accent)
    transition_clips.append(transition)

cta_overlay = WORK / "final_cta.png"
make_overlay(cta_overlay, marker=15, cta=True)

specs = []
zoom_ladder = [1.16, 1.08, 1.0]
for round_index in range(3):
    for stage, overlay in enumerate(countdown_overlays[round_index]):
        specs.append(
            (
                str(clues[round_index]),
                CDN,
                False,
                {
                    "overlay": str(overlay),
                    "z_from": zoom_ladder[stage - 1] if stage else None,
                    "z_to": zoom_ladder[stage],
                },
            )
        )

    specs.append((str(transition_clips[round_index]), TRANSITION, True))
    if round_index < 2:
        specs.append(
            (
                str(reveals[round_index]),
                ROUND_REVEAL - TRANSITION,
                False,
                {"overlay": str(answer_overlays[round_index]), "z_to": 1.0},
            )
        )
    else:
        answer_beat = CDN - TRANSITION
        cta_beat = FINAL_REVEAL - CDN
        answer_end_zoom = 1.0 + min(
            legacy._DRIFT_CLOSING_MAX,
            legacy._DRIFT_CLOSING_PER_SEC * answer_beat,
        )
        specs.append(
            (
                str(reveals[round_index]),
                answer_beat,
                False,
                {
                    "overlay": str(answer_overlays[round_index]),
                    "z_to": 1.0,
                    "drift": legacy._DRIFT_CLOSING_PER_SEC,
                    "drift_max": legacy._DRIFT_CLOSING_MAX,
                },
            )
        )
        specs.append(
            (
                str(reveals[round_index]),
                cta_beat,
                False,
                {
                    "overlay": str(cta_overlay),
                    "z_to": answer_end_zoom,
                    "drift": legacy._DRIFT_CLOSING_PER_SEC,
                    "drift_max": legacy._DRIFT_CLOSING_MAX,
                    "overlay_fade": (
                        cta_beat
                        - (legacy._LOOP_DISSOLVE_SEC + legacy._LOOP_SETTLE_SEC)
                        - legacy._LOOP_TEXT_CLEAR_SEC,
                        legacy._LOOP_TEXT_CLEAR_SEC,
                    ),
                },
            )
        )

# The production loop appends the exact first base/overlay/zoom and consumes the closing card
# entirely inside the dissolve, so it adds no runtime.
specs.append(
    (
        str(clues[0]),
        legacy._LOOP_DISSOLVE_SEC + legacy._LOOP_SETTLE_SEC,
        False,
        {
            "overlay": str(countdown_overlays[0][0]),
            "z_to": zoom_ladder[0],
            "drift": 0,
            "xfade_prev": legacy._LOOP_DISSOLVE_SEC,
        },
    )
)

expected = 3 * (3 * CDN) + 2 * ROUND_REVEAL + FINAL_REVEAL
out = WORK / "three_round_sequence_smoke.mp4"
legacy._render_sequence(specs, str(out), expected)
probe = media_binaries.probe_media(str(out))
summary = {
    "status": "passed",
    "ffmpeg": FF,
    "spec_count": len(specs),
    "input_slot_count": sum(1 + int(bool(len(spec) > 3 and spec[3].get("overlay"))) for spec in specs),
    "expected_duration_sec": expected,
    "probe": probe,
    "output_size_bytes": out.stat().st_size,
}
print("QUIZ_SEQUENCE_SMOKE=" + json.dumps(summary, default=str), flush=True)
