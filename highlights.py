"""
Sports highlight detection pipeline.

Steps:
  1. Extract audio → find crowd-noise energy peaks (NumPy)
  2. Extract a frame at each peak → Claude Vision confirms type + excitement score
  3. Cut clips around confirmed moments (ffmpeg, fast re-encode)

Returns a list of clip metadata dicts.
"""

import os
import json
import base64
import subprocess
import wave

import numpy as np
import anthropic

from media_binaries import ffmpeg as _ffmpeg_bin, probe_duration as _probe_duration

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


# ── Video helpers ──────────────────────────────────────────────────────────────

def _video_duration(video_path: str) -> float:
    return _probe_duration(video_path)


def _extract_audio_wav(video_path: str, out_wav: str, sample_rate: int = 22050) -> None:
    subprocess.run(
        [_ffmpeg_bin(), "-i", video_path, "-vn", "-acodec", "pcm_s16le",
         "-ar", str(sample_rate), "-ac", "1", out_wav, "-y"],
        check=True, capture_output=True,
    )


def _extract_frame_jpg(video_path: str, t: float, out_path: str) -> None:
    subprocess.run(
        [_ffmpeg_bin(), "-ss", f"{t:.3f}", "-i", video_path,
         "-frames:v", "1", "-q:v", "5", out_path, "-y"],
        check=True, capture_output=True,
    )


def _cut_clip(video_path: str, start: float, end: float, out_path: str,
              vertical: bool = False) -> None:
    base_args = [
        _ffmpeg_bin(),
        "-ss", f"{start:.3f}",
        "-i", video_path,
        "-t", f"{end - start:.3f}",
    ]
    encode_args = ["-c:v", "libx264", "-preset", "fast", "-crf", "23",
                   "-c:a", "aac", "-b:a", "128k", out_path, "-y"]

    if vertical:
        # Blur-background 9:16: source fills frame blurred, then source fits on top centred
        vf = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=25:5[bg];"
            "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[out]"
        )
        subprocess.run(
            base_args + ["-filter_complex", vf, "-map", "[out]", "-map", "0:a?"] + encode_args,
            check=True, capture_output=True,
        )
    else:
        subprocess.run(base_args + encode_args, check=True, capture_output=True)


# ── Audio analysis ─────────────────────────────────────────────────────────────

def _uniform_filter(values: np.ndarray, size: int) -> np.ndarray:
    """NumPy equivalent of scipy.ndimage.uniform_filter1d's defaults.

    ``symmetric`` padding matches SciPy's default ``reflect`` boundary behavior,
    including the left-of-centre alignment used for even window sizes.
    """
    values = np.asarray(values)
    if values.ndim != 1:
        raise ValueError("values must be one-dimensional")
    if size < 1:
        raise ValueError("size must be at least 1")
    if values.size == 0 or size == 1:
        return values.copy()

    before = size // 2
    after = size - 1 - before
    padded = np.pad(values, (before, after), mode="symmetric")
    kernel = np.full(size, 1.0 / size, dtype=np.float64)
    # SciPy preserves the input dtype. Matching that avoids tiny rounding changes
    # around the percentile threshold used by the highlight detector.
    return np.convolve(padded, kernel, mode="valid").astype(values.dtype, copy=False)


def _find_peaks(values: np.ndarray,
                min_height: float,
                min_distance: int) -> tuple[np.ndarray, np.ndarray]:
    """Find local maxima using the subset of SciPy semantics this pipeline needs.

    Flat peaks resolve to their midpoint. When peaks are too close, the taller
    one wins; the returned indices remain chronological.
    """
    values = np.asarray(values)
    if values.ndim != 1:
        raise ValueError("values must be one-dimensional")

    candidates: list[int] = []
    i = 1
    while i < values.size - 1:
        if values[i] > values[i - 1]:
            right = i + 1
            while right < values.size and values[right] == values[i]:
                right += 1
            if right < values.size and values[i] > values[right]:
                candidates.append((i + right - 1) // 2)
            i = right
        else:
            i += 1

    peaks = np.asarray(candidates, dtype=np.int64)
    if peaks.size == 0:
        return peaks, np.asarray([], dtype=values.dtype)

    peaks = peaks[values[peaks] >= min_height]
    distance = max(1, int(min_distance))
    if distance > 1 and peaks.size > 1:
        # Stable sorting plus reversal matches scipy.signal.find_peaks' tie
        # behavior while making the normal (non-tied) case straightforward.
        priority = np.argsort(values[peaks], kind="stable")[::-1]
        kept: list[int] = []
        for position in priority:
            candidate = int(peaks[position])
            if all(abs(candidate - other) >= distance for other in kept):
                kept.append(candidate)
        peaks = np.asarray(sorted(kept), dtype=np.int64)

    return peaks, values[peaks]

def _find_energy_peaks(wav_path: str,
                       chunk_sec: float = 0.5,
                       min_gap_sec: float = 20.0,
                       top_n: int = 20) -> list:
    """Return timestamps (seconds) of crowd-noise energy peaks."""
    with wave.open(wav_path, "rb") as wf:
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    chunk_len = int(sr * chunk_sec)
    n_chunks = len(samples) // chunk_len
    if n_chunks == 0:
        return []

    energies = np.array([
        np.sqrt(np.mean(samples[i * chunk_len:(i + 1) * chunk_len] ** 2))
        for i in range(n_chunks)
    ])
    times = np.arange(n_chunks) * chunk_sec + chunk_sec / 2.0

    smoothed = _uniform_filter(energies, size=20)
    threshold = np.percentile(smoothed, 78)
    min_dist = max(1, int(min_gap_sec / chunk_sec))
    peaks, peak_heights = _find_peaks(smoothed, min_height=threshold, min_distance=min_dist)

    if len(peaks) == 0:
        return []

    # Take top_n by height, return sorted by time
    top_idx = np.argsort(peak_heights)[::-1][:top_n]
    selected = sorted(peaks[top_idx].tolist())
    return [float(times[i]) for i in selected]


# ── Vision analysis ────────────────────────────────────────────────────────────

def _analyze_frame(jpg_path: str) -> dict:
    """Ask Claude Vision to classify and score this sports moment."""
    with open(jpg_path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()

    resp = _get_client().messages.create(
        model="claude-opus-4-7",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": data},
                },
                {
                    "type": "text",
                    "text": (
                        "Frame from a sports video. Reply with JSON only:\n"
                        '{"is_sport":true,"excitement":0-10,'
                        '"type":"goal"|"celebration"|"save"|"shot"|"foul"|"corner"|"regular"|"other",'
                        '"label":"short label e.g. Goal!"}\n'
                        "Score 8-10 for goal/celebration, 5-7 for shot/save/foul, 1-4 for regular play."
                    ),
                },
            ],
        }]
    )
    try:
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1].lstrip("json").strip()
        return json.loads(text)
    except Exception:
        return {"is_sport": False, "excitement": 0, "type": "unknown", "label": ""}


# ── YouTube download ───────────────────────────────────────────────────────────

def download_youtube(url: str, output_dir: str, progress_cb=None) -> str:
    """
    Download a YouTube video with yt-dlp (max 1080p MP4).
    Streams yt-dlp's progress lines to progress_cb.
    Returns the path of the downloaded file.
    """
    output_template = os.path.join(output_dir, "input.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--newline",
        "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "--merge-output-format", "mp4",
        "-o", output_template,
        url,
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        # Surface download-progress and info lines; skip noisy ffmpeg merge lines
        if progress_cb and ("[download]" in line or "[info]" in line or "[youtube]" in line):
            clean = line.split("] ", 1)[-1]  # strip the [tag] prefix
            progress_cb(clean)

    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp exited with code {proc.returncode}")

    for fname in sorted(os.listdir(output_dir)):
        if fname.startswith("input.") and fname.endswith(".mp4"):
            return os.path.join(output_dir, fname)

    raise RuntimeError("Downloaded file not found in output directory")


# ── Highlight reel assembly ────────────────────────────────────────────────────

def assemble_highlight_reel(clip_paths: list, output_path: str,
                             transition_sec: float = 0.5,
                             progress_cb=None) -> None:
    """
    Stitch clips into a single reel with fadeblack transitions between each clip.
    Audio tracks are concatenated cleanly (no gaps).
    """
    n = len(clip_paths)
    if n == 0:
        raise ValueError("No clips to assemble")

    if progress_cb:
        progress_cb(f"Assembling reel from {n} clip(s)...")

    if n == 1:
        import shutil as _shutil
        _shutil.copy(clip_paths[0], output_path)
        if progress_cb:
            progress_cb("Reel ready (single clip, no transitions needed)")
        return

    durations = [_video_duration(p) for p in clip_paths]
    # Keep transition short enough to never exceed 40% of the shortest clip
    D = min(transition_sec, min(durations) * 0.4)

    input_args = []
    for p in clip_paths:
        input_args += ["-i", p]

    filter_parts = []

    # Video: chain xfade transitions
    offset = durations[0] - D
    filter_parts.append(
        f"[0:v][1:v]xfade=transition=fadeblack:duration={D:.3f}:offset={offset:.3f}[vx0]"
    )
    for i in range(2, n):
        offset += durations[i - 1] - D
        filter_parts.append(
            f"[vx{i-2}][{i}:v]xfade=transition=fadeblack:duration={D:.3f}:offset={offset:.3f}[vx{i-1}]"
        )

    # Audio: simple concat (clean cuts, avoids acrossfade edge cases)
    audio_inputs = "".join(f"[{i}:a]" for i in range(n))
    filter_parts.append(f"{audio_inputs}concat=n={n}:v=0:a=1[aout]")

    final_v = f"vx{n - 2}"
    filter_complex = ";".join(filter_parts)

    try:
        subprocess.run(
            [_ffmpeg_bin()] + input_args + [
                "-filter_complex", filter_complex,
                "-map", f"[{final_v}]",
                "-map", "[aout]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                output_path, "-y",
            ],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        # Fallback: video-only reel (skip audio concat if clips lack audio tracks)
        filter_parts_v = [p for p in filter_parts if "aout" not in p]
        subprocess.run(
            [_ffmpeg_bin()] + input_args + [
                "-filter_complex", ";".join(filter_parts_v),
                "-map", f"[{final_v}]",
                "-an",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                output_path, "-y",
            ],
            check=True, capture_output=True,
        )

    if progress_cb:
        progress_cb(f"Reel ready: {os.path.basename(output_path)}")


# ── Main pipeline ──────────────────────────────────────────────────────────────

def run_highlights(
    video_path: str,
    output_dir: str,
    pre_sec: float = 15.0,
    post_sec: float = 20.0,
    max_clips: int = 6,
    vertical: bool = True,
    # ── Overlay options ────────────────────────────────────────────────────────
    score: str = "",                # e.g. "Leeds 2 - 1 PLG"  (empty = no banner)
    predicted_team: str = "",       # e.g. "Leeds"            (empty = no banner)
    prediction_result: str = "",    # "hit" | "missed"
    win_probability: int = 68,
    confidence: str = "HIGH",
    model_accuracy: int = 61,
    progress_cb=None,
) -> list:
    """
    Full pipeline. progress_cb(msg) is called with progress strings;
    prefix "stage:" signals a major stage transition.

    Returns list of dicts: index, filename, clip_path, peak_time,
    start, end, moment_type, label, excitement.
    """

    def log(msg: str):
        if progress_cb:
            progress_cb(msg)

    # ── Step 1: Audio energy peaks ─────────────────────────────────────────────
    log("stage:Extracting audio track...")
    wav_path = os.path.join(output_dir, "_audio.wav")
    wav_ok = False
    try:
        _extract_audio_wav(video_path, wav_path)
        wav_ok = True
    except subprocess.CalledProcessError as e:
        log(f"Audio extraction failed: {e.stderr.decode()[:120]}")

    duration = _video_duration(video_path)
    log(f"Video duration: {int(duration // 60)}m {int(duration % 60):02d}s")

    if wav_ok and os.path.exists(wav_path):
        log("Scanning for crowd-noise energy peaks...")
        peaks = _find_energy_peaks(wav_path)
        os.remove(wav_path)
        log(f"Found {len(peaks)} candidate moment(s) via audio analysis")
    else:
        peaks = []

    if not peaks:
        n = max_clips * 2
        peaks = list(np.linspace(duration * 0.1, duration * 0.9, n))
        log(f"No clear audio peaks — sampling {n} evenly-spaced frames as fallback")

    # ── Step 2: Vision confirmation ────────────────────────────────────────────
    log("stage:Analyzing frames with Claude Vision...")
    confirmed = []
    candidates = peaks[:20]

    for i, t in enumerate(candidates):
        mm, ss = int(t // 60), int(t % 60)
        log(f"Frame {i + 1}/{len(candidates)} @ {mm}:{ss:02d}...")
        jpg = os.path.join(output_dir, f"_frame_{i}.jpg")
        try:
            _extract_frame_jpg(video_path, t, jpg)
            info = _analyze_frame(jpg)
            score = info.get("excitement", 0)
            if score >= 4:
                confirmed.append({"t": t, **info})
                log(f"  ✓ {info.get('label', info.get('type', ''))} (score {score})")
            else:
                log(f"  – {info.get('type', 'low')} (score {score})")
        except Exception as e:
            log(f"  skipped: {e}")
        finally:
            if os.path.exists(jpg):
                os.remove(jpg)

    log(f"{len(confirmed)} highlights confirmed by vision analysis")

    if not confirmed:
        log("No highlights above threshold — using top audio peaks as clips")
        confirmed = [
            {"t": t, "excitement": 5, "type": "highlight", "label": "Highlight"}
            for t in peaks[:max_clips]
        ]

    # Best N by excitement score, then sort chronologically
    confirmed.sort(key=lambda x: x["excitement"], reverse=True)
    confirmed = confirmed[:max_clips]
    confirmed.sort(key=lambda x: x["t"])

    # ── Step 3: Cut clips ──────────────────────────────────────────────────────
    log("stage:Cutting highlight clips...")
    results = []

    for i, m in enumerate(confirmed):
        t = m["t"]
        start = max(0.0, t - pre_sec)
        end = min(duration, t + post_sec)
        fname = f"highlight_{i + 1:02d}.mp4"
        out_path = os.path.join(output_dir, fname)
        label = m.get("label") or m.get("type", "Highlight")
        mm, ss = int(t // 60), int(t % 60)
        log(f"Clip {i + 1}/{len(confirmed)}: {label} @ {mm}:{ss:02d}")

        try:
            _cut_clip(video_path, start, end, out_path, vertical=vertical)
        except subprocess.CalledProcessError as e:
            log(f"  cut failed: {e.stderr.decode()[:80]}")
            continue

        results.append({
            "index": i,
            "filename": fname,
            "clip_path": out_path,
            "peak_time": round(t, 1),
            "start": round(start, 1),
            "end": round(end, 1),
            "moment_type": m.get("type", "highlight"),
            "label": label,
            "excitement": m.get("excitement", 0),
        })

    log(f"{len(results)} clip(s) cut")

    # ── Step 4: Apply overlays (prediction banner + score) ─────────────────────
    want_prediction = bool(predicted_team and prediction_result)
    want_score      = bool(score)

    if results and (want_prediction or want_score):
        log("stage:Applying overlays...")
        try:
            from overlays import (
                make_prediction_banner, make_score_banner,
                apply_overlays, video_wh,
            )

            # Probe dimensions from the first clip
            vw, vh = video_wh(results[0]["clip_path"])
            top_h  = max(180, int(min(vw, vh) * 0.20))
            bot_h  = max(80,  int(min(vw, vh) * 0.10))

            top_img = make_prediction_banner(
                vw, top_h,
                predicted_team=predicted_team,
                result=prediction_result,
                win_prob=win_probability,
                confidence=confidence,
                model_accuracy=model_accuracy,
            ) if want_prediction else None

            bot_img = make_score_banner(vw, bot_h, score) if want_score else None

            for r in results:
                raw_path = r["clip_path"]
                ov_path  = raw_path.replace(".mp4", "_ov.mp4")
                try:
                    apply_overlays(raw_path, ov_path, top_img, bot_img, output_dir)
                    os.replace(ov_path, raw_path)   # swap in place
                    log(f"  Overlays applied → {r['filename']}")
                except Exception as e:
                    log(f"  Overlay failed for {r['filename']}: {e}")

        except Exception as e:
            log(f"Overlay step skipped: {e}")

    # ── Step 5: Assemble combined reel ─────────────────────────────────────────
    reel_path = None
    if results:
        log("stage:Assembling highlight reel...")
        reel_path = os.path.join(output_dir, "highlight_reel.mp4")
        try:
            assemble_highlight_reel(
                [r["clip_path"] for r in results],
                reel_path,
                progress_cb=log,
            )
        except Exception as e:
            log(f"Reel assembly failed: {e}")
            reel_path = None

    log(f"Done — {len(results)} clip(s) + reel ready")
    return {"clips": results, "reel_path": reel_path}
