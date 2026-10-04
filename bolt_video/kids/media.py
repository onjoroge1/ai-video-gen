"""Bounded local media operations. No creative or timing rules from other lanes."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile

from media_binaries import ffmpeg, ffprobe

RENDER_VERSION = "kids_media_v1"
FPS = 24
WIDTH, HEIGHT = 1280, 720


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(args, timeout=180):
    return subprocess.run(args, check=True, stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=timeout)


def encode(args, timeout=180):
    return run([ffmpeg(), "-nostdin", "-y", "-threads", "1", "-filter_threads", "1",
                "-filter_complex_threads", "1", *map(str, args)], timeout)


def probe(path):
    value = json.loads(run([ffprobe(), "-v", "error", "-show_streams", "-show_format",
                            "-of", "json", str(path)], 30).stdout)
    duration = float(value.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or duration <= 0 or duration > 600:
        raise ValueError("Media duration must be finite, positive and at most 600 seconds")
    return {"duration_sec": duration, "streams": value.get("streams", [])}


def inspect_asset(path, expected_mime):
    """Decode rather than trust a filename, Content-Type, or minimum byte count."""
    if Path(path).stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Kids source asset exceeds 32 MiB")
    if expected_mime.startswith("image/"):
        from PIL import Image
        with Image.open(path) as image:
            if image.width * image.height > 25_000_000 or min(image.size) < 64:
                raise ValueError("Image dimensions outside the supported range")
            actual = {"PNG": "image/png", "JPEG": "image/jpeg"}.get(image.format)
            image.verify()
        if actual != expected_mime:
            raise ValueError("Image bytes do not match the declared MIME")
        return {"mime_type": actual}
    info = probe(path)
    streams = info["streams"]
    audio = any(s.get("codec_type") == "audio" for s in streams)
    video = any(s.get("codec_type") == "video" for s in streams)
    if expected_mime.startswith("audio/") and (not audio or video):
        raise ValueError("Expected a decodable audio-only asset")
    if expected_mime == "video/mp4" and not video:
        raise ValueError("Expected a decodable video asset")
    header = Path(path).read_bytes()[:16]
    if expected_mime == "audio/wav" and not (header.startswith(b"RIFF") and header[8:12] == b"WAVE"):
        raise ValueError("Expected WAV container")
    if expected_mime == "audio/mpeg" and not (header.startswith(b"ID3") or header[:1] == b"\xff"):
        raise ValueError("Expected MP3 container")
    if expected_mime == "video/mp4" and header[4:8] != b"ftyp":
        raise ValueError("Expected MP4 container")
    # No shell, remote playlist inputs, or partial decode admitted to the catalog.
    encode(["-protocol_whitelist", "file,pipe", "-i", path, "-f", "null", "-"], 90)
    return {"mime_type": expected_mime, "duration_sec": info["duration_sec"]}


def normalized_audio(source, output, duration=None):
    if source is None:
        encode(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", duration,
                "-c:a", "pcm_s16le", output])
    else:
        encode(["-i", source, "-vn", "-af", "loudnorm=I=-18:TP=-2:LRA=7",
                "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", output])


def compile_timeline(episode, measured):
    """Actual audio owns time; response pauses are explicit, unscaled timeline intervals."""
    beats, cues, shots, cursor = [], [], [], 0.0
    for beat in episode.beats:
        start = cursor
        for cue in beat.audio:
            duration = cue.duration_sec if cue.kind == "pause" else measured[cue.id]
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError(f"Unmeasured audio cue {cue.id}")
            cues.append({"id": cue.id, "beat_id": beat.id, "kind": cue.kind,
                         "start_sec": cursor, "end_sec": cursor + duration})
            cursor += duration
        total_weight = sum(s.weight for s in beat.shots)
        shot_cursor = start
        for n, shot in enumerate(beat.shots):
            end = cursor if n == len(beat.shots) - 1 else shot_cursor + (cursor-start)*shot.weight/total_weight
            shots.append({"id": shot.id, "asset_id": shot.asset_id, "beat_id": beat.id,
                          "role": beat.role, "start_sec": shot_cursor, "end_sec": end,
                          "requires_motion": shot.requires_motion})
            shot_cursor = end
        beats.append({"id": beat.id, "start_sec": start, "end_sec": cursor})
    return {"version": RENDER_VERSION, "duration_sec": cursor, "beats": beats,
            "cues": cues, "shots": shots, "audio_time_stretch": False}


def _concat(paths, destination):
    # Paths are controlled local workspace files, never authored ffconcat lines.
    destination.write_text("".join("file '" + str(Path(p).resolve()).replace("'", "'\\''") + "'\n"
                                   for p in paths), encoding="utf-8")


def mix_audio(paths, output):
    with tempfile.TemporaryDirectory(dir=Path(output).parent, prefix="kids_mix_") as work:
        listing = Path(work) / "audio.txt"
        _concat(paths, listing)
        encode(["-f", "concat", "-safe", "0", "-i", listing, "-ar", "48000", "-ac", "2",
                "-c:a", "pcm_s16le", output])


def render_shot(source, output, seconds, *, motion, loopable=False):
    frames = max(1, round(seconds * FPS))
    # A promised action cannot degrade to a still or freeze-frame tail.
    if motion:
        duration = probe(source)["duration_sec"]
        if duration + 1/FPS < frames/FPS and not loopable:
            raise ValueError("One-time action is shorter than its measured shot; repair timing")
        inputs = (["-stream_loop", "-1"] if loopable else []) + ["-i", source]
    else:
        inputs = ["-loop", "1", "-i", source]
    encode([*inputs, "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=0xf9f5ec,setsar=1,fps={FPS},format=yuv420p",
            "-frames:v", frames, "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-threads", "2", output])


def assemble(shots, soundtrack, output):
    with tempfile.TemporaryDirectory(dir=Path(output).parent, prefix="kids_mux_") as work:
        listing = Path(work)/"shots.txt"
        _concat(shots, listing)
        encode(["-f", "concat", "-safe", "0", "-i", listing, "-i", soundtrack,
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
                "-b:a", "192k", "-movflags", "+faststart", output])


def samples(path, seconds, output_dir, count=5):
    """Ordered, real frames; sampling is explicitly not exhaustive video verification."""
    root = Path(output_dir); root.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(count):
        at = min(max(0, seconds - .08), seconds * i / max(1, count-1))
        target = root / f"frame_{i:02}.jpg"
        encode(["-ss", f"{at:.4f}", "-i", path, "-frames:v", "1", "-vf", "scale=640:-2", target], 30)
        paths.append(str(target))
    return paths


def technical_report(path, timeline):
    info = probe(path)
    video = next((s for s in info["streams"] if s.get("codec_type") == "video"), {})
    audio = next((s for s in info["streams"] if s.get("codec_type") == "audio"), {})
    result = encode(["-i", path, "-af", "loudnorm=I=-18:TP=-2:LRA=7:print_format=json", "-f", "null", "-"], 120)
    matches = re.findall(r'\{\s*"input_i"[\s\S]*?\}', result.stderr.decode(errors="replace"))
    loudness = json.loads(matches[-1]) if matches else {}
    integrated = float(loudness.get("input_i", "-inf"))
    peak = float(loudness.get("input_tp", "inf"))
    checks = {
        "decode": True, "h264": video.get("codec_name") == "h264",
        "aac": audio.get("codec_name") == "aac",
        "dimensions": (video.get("width"),video.get("height")) == (WIDTH,HEIGHT),
        "av_duration": bool(video and audio) and abs(float(video.get("duration", 0))-float(audio.get("duration", 0))) <= .25,
        "timeline_duration": abs(info["duration_sec"]-timeline["duration_sec"]) <= .25,
        "loudness": -22 <= integrated <= -14,
        "true_peak": peak <= -1.0,
    }
    return {"checks": checks, "observed": {"duration_sec":info["duration_sec"],
            "integrated_lufs": integrated if math.isfinite(integrated) else None,
            "true_peak_dbtp": peak if math.isfinite(peak) else None},
            "artifact_sha256": sha256(path)}
