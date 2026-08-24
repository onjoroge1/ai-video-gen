#!/usr/bin/env python3
"""Prove this host can actually render, for $0 and with no provider credentials.

A long-form render spends real money on script, image, motion, narration, and judge calls
*before* it reaches its first encode, so a missing or broken ffmpeg surfaces late and
expensive. This drives the real assembly functions from `explainer_pipeline`
(`_make_scene_segment` and `_assemble`) with locally generated images and tones, and
reports whether a valid MP4 came out.

It exercises the media boundary only. It does not call any provider and therefore proves
nothing about script quality, evidence, or the rendered gate.

    python scripts/render_smoke.py [--output DIR] [--keep]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import media_binaries  # noqa: E402

SCENES = ((180, 60, 60), (60, 140, 90), (50, 90, 180))


def _build_inputs(work: Path, ffmpeg: str) -> tuple[list[str], list[str]]:
    from PIL import Image, ImageDraw

    images, audios = [], []
    for index, colour in enumerate(SCENES):
        image_path = work / f"scene_{index}.png"
        image = Image.new("RGB", (1536, 1024), colour)
        draw = ImageDraw.Draw(image)
        # A moving light block gives consecutive frames genuinely different pixels, so the
        # encode is not a still and the boundary measurements have something to measure.
        draw.rectangle([200 + index * 90, 300, 900 + index * 90, 700], fill=(250, 250, 250))
        image.save(image_path)
        images.append(str(image_path))

        audio_path = work / f"scene_{index}.mp3"
        subprocess.run(
            [ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", f"sine=frequency={300 + index * 120}:duration={2.0 + index * 0.5}",
             "-c:a", "libmp3lame", str(audio_path)],
            check=True, stdin=subprocess.DEVNULL, timeout=120)
        audios.append(str(audio_path))
    return images, audios


def render_smoke(output_dir: str | None = None) -> dict:
    """Render a tiny multi-scene video through the real pipeline. Returns a report."""
    preflight = media_binaries.preflight()
    if not preflight["ready"]:
        return {"ok": False, "stage": "preflight", "preflight": preflight,
                "error": f"missing media binaries: {', '.join(preflight['missing'])}"}

    import explainer_pipeline as pipeline

    work = Path(output_dir or tempfile.mkdtemp(prefix="render_smoke_"))
    work.mkdir(parents=True, exist_ok=True)
    ffmpeg = media_binaries.ffmpeg()
    images, audios = _build_inputs(work, ffmpeg)

    segments = []
    for index, (image_path, audio_path) in enumerate(zip(images, audios)):
        segment = work / f"segment_{index}.mp4"
        pipeline._make_scene_segment(
            image_path, audio_path, str(segment),
            f"Scene {index + 1}", "evidence state", motion="kenburns_in", tail=0.3)
        segments.append(str(segment))

    final = work / "render_smoke.mp4"
    pipeline._assemble(segments, audios, str(final), str(work))

    probe = subprocess.run(
        [media_binaries.ffprobe(), "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(final)],
        capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL, timeout=60)
    info = json.loads(probe.stdout)
    streams = {item["codec_type"]: item for item in info.get("streams", [])}
    video = streams.get("video", {})

    return {
        "ok": bool(video) and "audio" in streams and float(info["format"]["duration"]) > 0,
        "stage": "complete",
        "preflight": preflight,
        "output_path": str(final),
        "size_bytes": final.stat().st_size,
        "duration_sec": round(float(info["format"]["duration"]), 3),
        "video_codec": video.get("codec_name", ""),
        "resolution": f"{video.get('width', 0)}x{video.get('height', 0)}",
        "audio_codec": streams.get("audio", {}).get("codec_name", ""),
        "segment_count": len(segments),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", default="", help="Directory for the render (default: temp)")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    args = parser.parse_args()

    report = render_smoke(args.output or None)
    if args.json:
        print(json.dumps(report, indent=2))
    elif not report["ok"]:
        print(f"RENDER SMOKE FAILED at {report['stage']}: {report.get('error', '')}")
        remedy = report.get("preflight", {}).get("remedy")
        if remedy:
            print(remedy)
    else:
        binaries = report["preflight"]["binaries"]
        print(f"ffmpeg  : {binaries['ffmpeg']['path']} ({binaries['ffmpeg']['source']})")
        print(f"ffprobe : {binaries['ffprobe']['path']} ({binaries['ffprobe']['source']})")
        print(f"rendered: {report['output_path']}")
        print(f"          {report['resolution']} {report['video_codec']}+"
              f"{report['audio_codec']}, {report['duration_sec']}s, "
              f"{report['size_bytes'] / 1024:.0f} KB, {report['segment_count']} scenes")
        print("RENDER SMOKE PASSED")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
