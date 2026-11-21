"""Bring a built Short's voice to the feed level (-14 LUFS, -1.5 dBTP) with one fixed gain after a compressor and limiter.

    python3 scripts/fg_loudness.py <short folder> [...]

Why (2026-11-06 comparison): breakout Shorts measured -13 to -16 LUFS; ours ship at about -24.
Chain per the 10-01 audio lessons: compressor + limiter so TTS peaks fit. ffmpeg's alimiter auto-levels
(level=true), which made a two-pass loudnorm fall back to dynamic, so the gain is applied once, fixed.
Keeps the original as short_quiet.mp4; video is stream-copied.
"""
import json, os, re, shutil, subprocess, sys

PRE = "acompressor=threshold=-24dB:ratio=3:attack=5:release=80,alimiter=limit=0.18"
TARGET = "I=-14:TP=-1.5:LRA=20"


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise SystemExit(p.stderr[-800:])
    return p.stderr


def measure(path):
    out = run(["ffmpeg", "-nostdin", "-i", path, "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"])
    i = re.findall(r"I:\s*(-?[\d.]+) LUFS", out)[-1]
    tp = re.findall(r"Peak:\s*(-?[\d.]+) dBFS", out)[-1]
    return float(i), float(tp)


def fix(folder):
    """Compressor + limiter (its auto make-up lifts peaks to ~-0.8 dBTP), measure the result on the full
    decode, then ONE fixed volume change to -14 LUFS. Fixed gain cannot pump. Refused unless the
    final measure is within 0.6 LU of target and the peak is at or under -1.0 dBFS."""
    src = os.path.join(folder, "short.mp4")
    quiet = os.path.join(folder, "short_quiet.mp4")
    # A rebuild writes a new short.mp4 (still un-normalised, so it lacks our package.json stamp): take it as the source.
    stamped = "premise batch" in json.dumps(json.load(open(os.path.join(folder, "package.json"))).get("loudness", {})) \
        if os.path.isfile(os.path.join(folder, "package.json")) else False
    if not os.path.isfile(quiet) or not stamped:
        shutil.copy2(src, quiet)
    chain = f"{PRE},aresample=48000"
    tmp0 = os.path.join(folder, "_limited.wav")
    run(["ffmpeg", "-nostdin", "-y", "-i", quiet, "-vn", "-af", chain, tmp0])
    i0, _ = measure(tmp0)
    gain = -14.0 - i0
    tmp = os.path.join(folder, "short_loud.mp4")
    run(["ffmpeg", "-nostdin", "-y", "-i", quiet, "-i", tmp0, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
         "-af", f"volume={gain:.2f}dB", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", tmp])
    os.remove(tmp0)
    i, tp = measure(tmp)
    if abs(i + 14.0) > 0.6 or tp > -1.0:
        os.remove(tmp)
        raise SystemExit(f"{folder}: result {i} LUFS / peak {tp} dBFS outside target; not shipping")
    os.replace(tmp, src)
    pk = os.path.join(folder, "package.json")
    if os.path.isfile(pk):
        d = json.load(open(pk))
        d["loudness"] = {"lufs": i, "true_peak": tp, "normalised": f"compressor+limiter, fixed gain {gain:+.2f} dB (premise batch)"}
        json.dump(d, open(pk, "w"), indent=1, ensure_ascii=False)
    print(f"{os.path.basename(folder)}: gain {gain:+.2f} dB -> {i} LUFS, peak {tp} dBFS")


for f in sys.argv[1:]:
    fix(f)
