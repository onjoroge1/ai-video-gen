"""POST-RENDER video audit — the gate the pipeline never had.

Every existing quality gate fires on the SCRIPT or on a SINGLE frame. Nothing ever looked at the
finished MP4, which is how a 619-frame short with 10% real motion passed every check and shipped as a
slideshow. This module measures the assembled video.

Design rules learned the hard way:
  * Name each metric after what it LITERALLY measures, not what we hope it implies. (A previous gate
    called `n_bolts` actually counted bright blobs — it counted signage and passed at 12.)
  * Report the numbers alongside the verdict so a human can sanity-check the threshold.
  * Calibrate thresholds against KNOWN-GOOD and KNOWN-BAD renders, not intuition (see selftest()).

Decoding is a single ffmpeg rawvideo pipe at low resolution — no temp PNGs, ~1s for a 20s short.
"""
from __future__ import annotations
import json
import subprocess
from dataclasses import dataclass, asdict

import numpy as np

# ---------------------------------------------------------------------------------------------------
# CALIBRATION (measured, not guessed — see the table below). Mean inter-frame |diff| at 192x340 gray:
#
#   video                    median   frames>0.25   LONGEST HELD RUN
#   BAD  oxygen master        0.235       49%            60f   <- 5 of 6 beats are held frames
#   BAD  oxygen final         0.240       50%            60f
#   GOOD A1 (paid i2v)        0.529       78%             1f
#   GOOD A2 (paid i2v)        0.660       68%            11f
#   ~    A3 (paid i2v)        0.176       39%            31f   <- has a DOCUMENTED frozen 0.5s+ tail
#
# Two lessons, both the opposite of my first attempt:
#  1. A threshold of 1.0 was ABOVE the real signal (~0.4-0.6) and failed everything, including clips
#     with obvious motion. These shorts are dark with a small subject, so global means stay low.
#  2. `frac_moving` does NOT discriminate here: A3 (39%) scores WORSE than the bad master (49%),
#     because the master's hard cuts spike the mean while its held frames sit near zero. It is REPORTED
#     for humans but must not be the primary gate.
# The reliable signal is the LONGEST HELD RUN: a slideshow parks on frames; generated motion never does.
MOVING_THRESHOLD = float(0.25)
DECODE_W, DECODE_H = 192, 340         # ~9:16; 96x170 washed localized subject motion out entirely
DEFAULT_MAX_STATIC_RUN = 12           # PRIMARY gate. Editorial rule: nothing held >12f (0.4s) unless a
                                      # meter/light/character/camera/environment state is changing.
DEFAULT_MIN_MOVING_FRAC = 0.25        # BACKSTOP only (catches a fully frozen render), NOT the real test


@dataclass
class MotionReport:
    path: str
    frames: int
    fps: float
    duration_s: float
    frac_moving: float                # share of frames whose diff from the previous frame > threshold
    mean_motion: float                # mean inter-frame diff across the whole video
    median_motion: float
    max_static_run: int               # longest consecutive run of non-moving frames
    static_run_start_frame: int       # where that run begins (so a human can go look at it)
    moving_threshold: float
    passed: bool
    failures: list                    # human-readable reasons; empty when passed

    def as_dict(self) -> dict:
        return asdict(self)


def _probe_fps(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip()
    try:
        num, _, den = out.partition("/")
        return float(num) / float(den or 1)
    except Exception:
        return 30.0


def _decode_gray(path: str, w: int = DECODE_W, h: int = DECODE_H) -> np.ndarray:
    """Decode the whole video to a (frames, h, w) uint8 array of luma via one ffmpeg pipe."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={w}:{h}",
         "-pix_fmt", "gray", "-f", "rawvideo", "-"],
        capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg decode failed for {path}: {proc.stderr[:200].decode('utf8','replace')}")
    buf = np.frombuffer(proc.stdout, dtype=np.uint8)
    n = buf.size // (w * h)
    if n == 0:
        raise RuntimeError(f"no frames decoded from {path}")
    return buf[: n * w * h].reshape(n, h, w)


def measure_motion(path: str, moving_threshold: float = MOVING_THRESHOLD) -> dict:
    """Measure inter-frame motion. Pure measurement — no pass/fail opinion."""
    g = _decode_gray(path).astype(np.int16)
    if len(g) < 2:
        return {"frames": len(g), "diffs": np.zeros(0), "frac_moving": 0.0,
                "mean_motion": 0.0, "median_motion": 0.0, "max_static_run": len(g),
                "static_run_start_frame": 0}
    diffs = np.abs(np.diff(g, axis=0)).mean(axis=(1, 2))     # one value per frame transition
    moving = diffs > moving_threshold
    # longest run of NON-moving transitions, and where it starts
    best_run = run = 0
    best_start = start = 0
    for i, m in enumerate(moving):
        if not m:
            if run == 0:
                start = i
            run += 1
            if run > best_run:
                best_run, best_start = run, start
        else:
            run = 0
    return {"frames": int(len(g)), "diffs": diffs,
            "frac_moving": float(moving.mean()),
            "mean_motion": float(diffs.mean()),
            "median_motion": float(np.median(diffs)),
            "max_static_run": int(best_run),
            "static_run_start_frame": int(best_start)}


def motion_density_gate(path: str,
                        min_moving_frac: float = DEFAULT_MIN_MOVING_FRAC,
                        max_static_run: int = DEFAULT_MAX_STATIC_RUN,
                        moving_threshold: float = MOVING_THRESHOLD) -> MotionReport:
    """Gate an ASSEMBLED video on how much of it actually moves.

    Two independent failure modes, because they catch different things:
      frac_moving   — a video can be 'mostly still with a couple of animated beats' (the slideshow).
      max_static_run— a video can average fine yet park on one held frame for 3 seconds.
    """
    m = measure_motion(path, moving_threshold)
    fps = _probe_fps(path)
    failures = []
    # PRIMARY: held stretches. This is the metric that actually discriminates (see CALIBRATION).
    if m["max_static_run"] > max_static_run:
        failures.append(
            f"held for {m['max_static_run']} frames ({m['max_static_run']/max(fps,1):.1f}s) starting at "
            f"frame {m['static_run_start_frame']} — max allowed {max_static_run} "
            f"({max_static_run/max(fps,1):.1f}s). This is what makes a render read as a slideshow.")
    # BACKSTOP: an essentially frozen video. Deliberately loose — frac_moving is unreliable on dark
    # footage with a small subject, so it only catches the extreme case.
    if m["frac_moving"] < min_moving_frac:
        failures.append(
            f"only {m['frac_moving']*100:.0f}% of frames change at all "
            f"(backstop floor {min_moving_frac*100:.0f}%) — near-frozen render")
    return MotionReport(
        path=path, frames=m["frames"], fps=round(fps, 3),
        duration_s=round(m["frames"] / max(fps, 1), 3),
        frac_moving=round(m["frac_moving"], 4),
        mean_motion=round(m["mean_motion"], 3),
        median_motion=round(m["median_motion"], 3),
        max_static_run=m["max_static_run"],
        static_run_start_frame=m["static_run_start_frame"],
        moving_threshold=moving_threshold,
        passed=not failures, failures=failures)


# --------------------------------------------------------------------------------------------------
# ANTI-THEATER SELF-TEST. A gate nobody has validated is decoration. This asserts the gate REJECTS a
# render we know is bad and ACCEPTS one we know is good. Run it whenever the thresholds change.
_AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"
# (path, expect_pass, why)
REFERENCES = [
    (f"{_AT}/master/oxygen_master_619f.mp4", False,
     "619-frame oxygen master: 5 of 6 beats are held frames with 2D overlays (the render you rejected)"),
    (f"{_AT}/final/oxygen_final_1080x1920.mp4", False,
     "same master with narration/captions muxed — audio cannot fix a static picture"),
    (f"{_AT}/a1_accepted/A1_final_primitive.mp4", True,
     "paid Kling i2v: continuous forward hover-launch"),
    (f"{_AT}/a2_accepted/A2_production_primitive.mp4", True,
     "paid Kling i2v: continuous effortful approach"),
]
# NOTE 1: assembled/A1_A2_A3_sequence.mp4 was the obvious reference but is TRUNCATED on disk (reads
# fully, yet has no moov atom -> whatever wrote it was killed before finalizing). Excluded.
# NOTE 2: A3_production_primitive.mp4 is deliberately NOT a reference: it ends in a documented frozen
# "clean-hold" tail (~1s), so it legitimately trips the held-run gate. Keeping it out avoids encoding a
# known exception into the calibration.


def selftest() -> bool:
    import os
    ok = True
    for path, expect_pass, why in REFERENCES:
        if not os.path.exists(path):
            print(f"  SKIP (missing): {path}")
            continue
        r = motion_density_gate(path)
        verdict = "PASS" if r.passed else "FAIL"
        good = (r.passed == expect_pass)
        ok &= good
        print(f"  [{'ok ' if good else 'BAD'}] {verdict:4s} (expected {'PASS' if expect_pass else 'FAIL'})  "
              f"{r.frac_moving*100:5.1f}% moving  mean {r.mean_motion:6.2f}  "
              f"max_hold {r.max_static_run:3d}f  {os.path.basename(path)}")
        print(f"        {why}")
        for f in r.failures:
            print(f"        -> {f}")
    print(f"  selftest: {'PASS — the gate discriminates' if ok else 'FAIL — thresholds do not discriminate'}")
    return ok


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        raise SystemExit(0 if selftest() else 1)
    for p in sys.argv[1:]:
        print(json.dumps(motion_density_gate(p).as_dict(), indent=2))
