"""Executed only by the credential-stripping parent in an isolated Python environment.

Use selected local-media functions, not upstream app/task startup, model loading,
script generation, footage search, galleries or social publishing.
"""
import json
import math
import os
from pathlib import Path
import subprocess
import sys


def main():
    target, payload, output = map(lambda p: Path(p).resolve(), sys.argv[1:4])
    data = json.loads(payload.read_text())
    request, paths = data["request"], data["paths"]
    # Tripwire against a future upstream import trying to contact any service.
    def no_network(event, args):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            raise RuntimeError("Provider/network access is forbidden for local-media engine jobs")
    sys.addaudithook(no_network)
    sys.path.insert(0, str(target))
    def ffmpeg(*args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, timeout=240)
    if request["engine"] == "moneyprinterturbo":
        from app.models.schema import VideoParams, VideoAspect, VideoConcatMode, VideoFitMode
        from app.services.video import combine_videos, generate_video
        audio, bed = output.with_name("narration.wav"), output.with_name("bed.mp4")
        ffmpeg("-i", paths["source"], "-map", "0:a:0", "-vn", str(audio))
        info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", paths["source"]],
            capture_output=True, text=True, check=True, timeout=30)
        # Sequential mode takes one segment from each source. Preserve full
        # ordered clips rather than recycling their first three seconds.
        clip_limit = max(1, math.ceil(float(info.stdout.strip())))
        combine_videos(str(bed), [paths[f"material-{i}"] for i in range(len(request["material_video_ids"]))],
                       str(audio), VideoAspect.portrait, VideoConcatMode.sequential,
                       max_clip_duration=clip_limit, threads=2, video_fit_mode=VideoFitMode.contain)
        generate_video(str(bed), str(audio), "", str(output), VideoParams(
            video_subject=request["title"], video_aspect="9:16", video_fit_mode="contain",
            bgm_type="", subtitle_enabled=False, video_count=1, n_threads=2))
    elif request["engine"] == "openshorts":
        from ffmpeg_utils import cut_clip
        cut = output.with_name("cut.mp4")
        cut_clip(paths["source"], str(cut), request["start_sec"], request["end_sec"], 1)
        w, h = (720, 1280) if request["aspect_ratio"] == "9:16" else (1280, 720)
        # Preserve the entire explanation, not an unreviewed face-tracking crop.
        vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        ffmpeg("-i", str(cut), "-map", "0:v:0", "-map", "0:a:0", "-vf", vf,
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(output))
    else:
        raise ValueError("Unsupported isolated Python engine")


if __name__ == "__main__":
    main()
