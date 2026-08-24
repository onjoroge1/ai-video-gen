#!/usr/bin/env python3
"""Generate zero-cost short- and long-form renderer pilots from the current production code.

This audit harness deliberately replaces paid provider calls with deterministic local fixtures while
keeping the real quiz renderer and long-form edit/assembly functions. It proves media portability,
layout, timing, audio assembly, codecs, dimensions, and artifact creation without bypassing the
production rendered-story or calibration gates.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QUIZ_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

from PIL import Image, ImageDraw  # noqa: E402

import media_binaries as media  # noqa: E402


def _tone(path: Path, duration: float, frequency: int = 440) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [media.ffmpeg(), "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"sine=frequency={frequency}:duration={duration:.3f}",
         "-c:a", "libmp3lame", str(path)],
        check=True, stdin=subprocess.DEVNULL, timeout=120,
    )


def _probe(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [media.ffprobe(), "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL, timeout=60,
    )
    payload = json.loads(result.stdout)
    streams = {stream.get("codec_type"): stream for stream in payload.get("streams", [])}
    video = streams.get("video") or {}
    audio = streams.get("audio") or {}
    return {
        "path": str(path),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "duration_sec": round(float((payload.get("format") or {}).get("duration") or 0), 3),
        "video_codec": video.get("codec_name", ""),
        "audio_codec": audio.get("codec_name", ""),
        "resolution": f"{video.get('width', 0)}x{video.get('height', 0)}",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "",
    }


def _longform_pilot(root: Path) -> dict[str, Any]:
    """Render a 45-second, 15-state landscape opening through the real long-form editor."""
    import explainer_pipeline as pipeline

    work = root / "longform"
    work.mkdir(parents=True, exist_ok=True)
    segments: list[str] = []
    audios: list[str] = []
    motions = ("kenburns_in", "pan_left", "pan_right")

    for index in range(15):
        image_path = work / f"state_{index:02d}.png"
        image = Image.new("RGB", (1536, 1024),
                          ((38 + index * 19) % 210, (65 + index * 31) % 210,
                           (95 + index * 23) % 210))
        draw = ImageDraw.Draw(image)
        x0 = 90 + (index % 5) * 180
        y0 = 210 + (index % 3) * 110
        draw.rounded_rectangle((x0, y0, x0 + 650, y0 + 370), radius=45,
                               fill=(235, 240, 245), outline=(20, 30, 45), width=12)
        draw.ellipse((980 - index * 18, 260, 1320 - index * 18, 600),
                     fill=(245, 190, 55), outline=(20, 30, 45), width=10)
        image.save(image_path)

        audio_path = work / f"state_{index:02d}.mp3"
        _tone(audio_path, 3.0, 280 + index * 27)
        segment_path = work / f"segment_{index:02d}.mp4"
        # `_assemble` crossfades over a held visual tail so narration is never covered.
        # Production always passes `FADE_DUR`; the audit fixture must preserve that contract.
        pipeline._make_scene_segment(
            str(image_path), str(audio_path), str(segment_path),
            f"Evidence state {index + 1}", "new visible information",
            motion=motions[index % len(motions)], tail=pipeline.FADE_DUR,
        )
        segments.append(str(segment_path))
        audios.append(str(audio_path))

    final = work / "longform_45s_audit_pilot.mp4"
    pipeline._assemble(segments, audios, str(final), str(work))
    report = _probe(final)
    report.update({
        "ok": report["exists"] and report["video_codec"] == "h264"
              and report["audio_codec"] == "aac" and report["duration_sec"] >= 44.0,
        "kind": "longform_renderer_audit",
        "visual_state_count": len(segments),
        "paid_provider_calls": 0,
        "scope": "real long-form segment compiler and assembler; deterministic local evidence fixtures",
    })
    return report


def _short_quiz_pilot(root: Path) -> dict[str, Any]:
    """Render a complete three-round vertical quiz through the real Shorts quiz pipeline."""
    import quiz_pipeline as quiz_pipeline

    legacy = quiz_pipeline._legacy
    legacy.FONT = os.environ["QUIZ_FONT"]

    quiz = {
        "title": "Can You Name These 3 Space Objects?",
        "category": "space objects",
        "hook": "Guess all three space objects. The last one is the hardest.",
        "outro": "How many did you get? Comment your score.",
        "items": [
            {"subject": "Moon", "difficulty": "easy",
             "clue_visual": "close-up of a cratered gray surface",
             "reveal_visual": "the Moon centered on a clean studio background",
             "answer": "MOON", "reaction": "Good start!", "fact": "The Moon is Earth's satellite.",
             "color": "sky"},
            {"subject": "Saturn", "difficulty": "hard",
             "clue_visual": "cropped golden bands and a curved ring",
             "reveal_visual": "Saturn centered on a clean studio background",
             "answer": "SATURN", "reaction": "Tricky one!", "fact": "Saturn has a broad ring system.",
             "color": "gold"},
            {"subject": "Europa", "difficulty": "expert",
             "clue_visual": "close-up of pale ice crossed by reddish fractures",
             "reveal_visual": "Europa centered on a clean studio background",
             "answer": "EUROPA", "reaction": "Expert level!", "fact": "Europa is a moon of Jupiter.",
             "color": "lavender"},
        ],
    }

    def fake_generate(*_args: Any, cost_sink: list | None = None, **_kwargs: Any) -> dict:
        if cost_sink is not None:
            cost_sink.append(0.0)
        return json.loads(json.dumps(quiz))

    def fake_factcheck(value: dict, cost_sink: list | None = None, **_kwargs: Any):
        if cost_sink is not None:
            cost_sink.append(0.0)
        return value, []

    def fake_image(_prompt: str, path: str, size: str, cost_sink: list | None,
                   fallback_label: str = "", **_kwargs: Any) -> None:
        width, height = (int(value) for value in size.lower().split("x"))
        seed = int(hashlib.sha256(path.encode()).hexdigest()[:8], 16)
        bg = (55 + seed % 140, 65 + (seed // 11) % 140, 75 + (seed // 29) % 140)
        image = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(image)
        margin = max(60, width // 9)
        draw.ellipse((margin, height // 4, width - margin, height * 3 // 4),
                     fill=(235, 235, 230), outline=(18, 25, 40), width=max(8, width // 90))
        draw.arc((margin + 30, height // 3, width - margin - 30, height * 2 // 3),
                 195, 345, fill=(245, 190, 55), width=max(12, width // 55))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        if cost_sink is not None:
            cost_sink.append(0.0)

    def fake_tts(text: str, output_path: str, *_args: Any, **_kwargs: Any) -> str:
        duration = max(0.8, min(2.2, len(str(text).split()) * 0.23))
        _tone(Path(output_path), duration, 430 + len(str(text)) % 150)
        return output_path

    def fake_description(category: str, title: str, items: list[dict], hook: str,
                         output_dir: str, *_args: Any, **_kwargs: Any) -> str:
        path = Path(output_dir) / "description.txt"
        path.write_text(f"{title}\n\n{hook}\n\nCategory: {category}\n", encoding="utf-8")
        return str(path)

    legacy.generate_quiz = fake_generate
    legacy.factcheck_quiz = fake_factcheck
    legacy._safe_image = fake_image
    legacy.ep.generate_tts = fake_tts
    legacy.ep._animate_one = lambda *_args, **_kwargs: (False, 0.0, "audit-local-fallback")
    legacy.get_music_path = lambda *_args, **_kwargs: None
    legacy.generate_quiz_description = fake_description

    work = root / "short_quiz"
    result = quiz_pipeline.run_quiz_pipeline(
        "space objects", str(work), n_items=3, voice="echo",
        progress_cb=lambda message: print(f"[short] {message}"),
        operator_direction="Zero-cost deterministic renderer audit.",
    )
    final = Path(result["output_path"])
    report = _probe(final)
    report.update({
        "ok": report["exists"] and report["video_codec"] == "h264"
              and report["audio_codec"] == "aac" and report["resolution"] == "1080x1920",
        "kind": "short_quiz_renderer_audit",
        "scene_count": result.get("scene_count", 0),
        "pipeline_status": result.get("status"),
        "degraded_reasons": result.get("degraded_reasons", []),
        "paid_provider_calls": 0,
        "scope": "real quiz timeline, overlays, countdown, audio mix and final assembly; deterministic local content fixtures",
    })
    return report


def main() -> int:
    output_root = Path(os.environ.get("AUDIT_OUTPUT_DIR", "audit_pilot_artifacts")).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    preflight = media.preflight()
    report: dict[str, Any] = {
        "schema_version": 1,
        "git_sha": os.environ.get("GITHUB_SHA", ""),
        "preflight": preflight,
        "paid_provider_calls": 0,
    }
    if not preflight["ready"]:
        report.update({"ok": False, "error": "media preflight failed"})
    else:
        report["short"] = _short_quiz_pilot(output_root)
        report["longform"] = _longform_pilot(output_root)
        report["ok"] = bool(report["short"]["ok"] and report["longform"]["ok"])

    report_path = output_root / "audit_pilot_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
