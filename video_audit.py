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
# --------------------------------------------------------------------------------------------
# PER-SHOT gate, for slow-drift formats (Ken-Burns explainers, long-form).
#
# max_static_run above is the right primary gate for ACTION i2v, and it is useless here. Measured
# on renders/hotd_s3e3/hotd_s3e3.mp4: it reports a 203-frame "static run" on shots that provably
# move -- the same clip displaces >=25px and 16.9 mean |diff| between its first and last frame. The
# reason is arithmetic, not a bug: a 5.5% zoom spread over 208 frames is ~0.12px/frame, so the
# per-frame difference is subpixel and sits under any usable threshold. A gate that cannot tell a
# slow push from a freeze cannot be used to certify either.
#
# So measure DISPLACEMENT PER SHOT instead: first frame vs last frame of each shot. That is the
# quantity a viewer actually perceives over a 6-second hold, and it discriminates cleanly (a frozen
# shot scores ~0, a drifting shot scores >10).
DEFAULT_MIN_SHOT_DISPLACEMENT = 3.0


def shot_motion_gate(path: str,
                     shot_frames: list,
                     min_displacement: float = DEFAULT_MIN_SHOT_DISPLACEMENT,
                     w: int = 340, h: int = 192,
                     exclude: list | None = None) -> dict:
    """Assert no SHOT is a still. `shot_frames` is the per-shot frame count, in order.

    `exclude` optionally gives, per shot, a list of normalised (x0, y0, x1, y1) boxes to IGNORE when
    measuring. This matters because the format deliberately holds part of the frame still: a
    character card is a static overlay and only the plate behind it drifts ("stable UI, moving art").
    Measuring the whole frame therefore penalises the design -- measured on a real render, plate
    shots median 23.8 and card shots 5.1, not because cards are broken but because most of their
    frame is meant to be motionless. Excluding the static overlay measures the quantity the gate
    actually means: does the moving part move?

    Returns per-shot first-vs-last displacement plus a pass/fail.
    """
    g = _decode_gray(path, w, h).astype(np.int16)
    shots, i = [], 0
    for k, n in enumerate(shot_frames):
        a, b = i, min(i + int(n), len(g)) - 1
        if b > a:
            diff = np.abs(g[a] - g[b]).astype(float)
            mask = np.ones_like(diff, dtype=bool)
            for (x0, y0, x1, y1) in (exclude[k] if exclude and k < len(exclude) else []):
                mask[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)] = False
            d = float(diff[mask].mean()) if mask.any() else float(diff.mean())
            shots.append({"shot": k, "first_frame": a, "frames": int(n),
                          "displacement": round(d, 2),
                          "measured_frac": round(float(mask.mean()), 3)})
        i += int(n)
    frozen = [s for s in shots if s["displacement"] < min_displacement]
    ds = [s["displacement"] for s in shots] or [0.0]
    return {"shots": shots, "frozen": frozen, "passed": not frozen,
            "n_shots": len(shots), "decoded_frames": int(len(g)),
            "min_displacement": round(min(ds), 2),
            "median_displacement": round(float(np.median(ds)), 2),
            "threshold": min_displacement}


def shot_gate_selftest(drifting_clip: str, tmpdir: str) -> bool:
    """Anti-theater check: the gate must FAIL a synthetic frozen shot and PASS a real drifting one.

    Two gates in this repo have previously reported green while measuring the wrong quantity, so no
    gate ships without a paired demonstration that it discriminates.
    """
    import os
    os.makedirs(tmpdir, exist_ok=True)
    still = os.path.join(tmpdir, "_selftest_frozen.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", drifting_clip, "-vf", "select=eq(n\\,0)",
                    "-frames:v", "1", os.path.join(tmpdir, "_f0.png")], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", "30",
                    "-i", os.path.join(tmpdir, "_f0.png"), "-frames:v", "180",
                    "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", still], check=True)
    n_drift = int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                 "-show_entries", "stream=nb_frames", "-of", "csv=p=0",
                                 drifting_clip], capture_output=True, text=True).stdout.strip())
    bad = shot_motion_gate(still, [180])
    good = shot_motion_gate(drifting_clip, [n_drift])
    ok = (not bad["passed"]) and good["passed"]
    print(f"  frozen 180f synthetic : displacement={bad['min_displacement']:6.2f}  "
          f"{'FAIL (correct)' if not bad['passed'] else 'PASS (WRONG)'}")
    print(f"  real drifting shot    : displacement={good['min_displacement']:6.2f}  "
          f"{'PASS (correct)' if good['passed'] else 'FAIL (WRONG)'}")
    print(f"  shot gate discriminates: {ok}")
    return ok


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


# --------------------------------------------------------------------------------------------
# PICTURE-REGION freeze gate.
#
# Why a separate gate: the whole-frame metrics above are masked by any moving overlay. A long-form
# render with a frozen picture and a live caption band measured "one 1.6s freeze" whole-frame, while
# the PICTURE alone was frozen for up to 3.97s at a stretch and 75% still. The caption was doing the
# moving that the gate credited to the image.
#
# So: crop the caption band away and measure only the part of the frame the viewer calls "the
# video". Calibrated against a known-bad (tpad=clone freeze) and known-good (ping-pong loop) pair --
# 16.97s vs 0.13s longest freeze on the same source clip over the same 22s scene.
DEFAULT_MAX_PICTURE_FREEZE_S = 1.2
CAPTION_BAND_FRAC = 0.22          # bottom of frame excluded; captions live here


def picture_freeze_gate(path, max_freeze_s=DEFAULT_MAX_PICTURE_FREEZE_S,
                        caption_frac=CAPTION_BAND_FRAC, threshold=MOVING_THRESHOLD, w=240, h=135):
    """Longest stretch where the PICTURE (frame minus caption band) does not change."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path,
         "-vf", f"crop=iw:ih*{1-caption_frac:.3f}:0:0,scale={w}:{h}",
         "-pix_fmt", "gray", "-f", "rawvideo", "-"], capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"decode failed: {proc.stderr[:180].decode('utf8','replace')}")
    buf = np.frombuffer(proc.stdout, dtype=np.uint8)
    n = buf.size // (w * h)
    if n < 2:
        return {"passed": False, "reason": "too few frames"}
    g = buf[: n * w * h].reshape(n, h, w).astype(np.int16)
    d = np.abs(np.diff(g, axis=0)).mean(axis=(1, 2))
    fps = _probe_fps(path)
    still = d < threshold
    best = run = 0
    start = best_start = 0
    for i, x in enumerate(still):
        if x:
            if run == 0:
                start = i
            run += 1
            if run > best:
                best, best_start = run, start
        else:
            run = 0
    longest = best / max(fps, 1)
    return {"passed": longest <= max_freeze_s,
            "longest_picture_freeze_s": round(longest, 2),
            "at_s": round(best_start / max(fps, 1), 2),
            "still_frac": round(float(still.mean()), 3),
            "mean_motion": round(float(d.mean()), 3),
            "cap_s": max_freeze_s,
            "measures": "longest run with no change in the frame ABOVE the caption band"}


def invented_subject_gate(clip, plate, bright_delta=30, min_frac=0.003, max_frac=0.45,
                          min_fill=0.45, thresh=0.2, samples=16):
    """Detect a subject the i2v model INVENTED in a scene whose plate is empty.

    Born from a mountain goat: four consecutive generations of "empty rocky ground, dust settling"
    came back with a goat walking through frame -- over a HORSE label, behind the closing claim --
    and one shipped. A negative prompt did not stop it (4/4 with wildlife negatives in place), and
    no text check can see pixels, so this measures instead: a compact bright blob present in the
    clip but absent from the plate. Drifting dust brightens DIFFUSELY and fails the compactness
    test; an animal is a tight filled region. Measured: goat clips 0.43-4.62, dust-only 0.00.

    The size window and sample count are calibrated by failure: the ceiling began at 15% of frame
    ("goat-sized") and a ninth goat materialised out of the dust LARGER than the ceiling, dead
    centre, passing untouched. The window now runs to 45% and sampling doubled -- a blob the size
    of half the frame is not scenery. Only meaningful for scenes that are SUPPOSED to be empty -- a legitimate subject in the plate
    moving through frame will also score. Callers gate on the scene's intent, not on every clip.
    """
    import subprocess
    import numpy as np
    from PIL import Image
    W, H = 180, 320
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", clip, "-vf",
                          f"scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    a = np.frombuffer(out, dtype=np.uint8)
    fr = a[:len(a) // (W * H) * (W * H)].reshape(-1, H, W).astype(np.float32)
    fr = fr[np.linspace(0, len(fr) - 1, min(samples, len(fr))).astype(int)]
    pl = np.asarray(Image.open(plate).convert("L").resize((W, H)), dtype=np.float32)
    worst, where = 0.0, None
    for fi, f in enumerate(fr):
        hot = ((f - pl) > bright_delta).astype(np.uint8)
        lab = np.zeros_like(hot, dtype=np.int32)
        cur = 0
        for y in range(H):
            for x in range(W):
                if hot[y, x] and not lab[y, x]:
                    cur += 1
                    stack, size, ys, xs = [(y, x)], 0, [], []
                    while stack:
                        cy, cx = stack.pop()
                        if not (0 <= cy < H and 0 <= cx < W) or not hot[cy, cx] or lab[cy, cx]:
                            continue
                        lab[cy, cx] = cur
                        size += 1
                        ys.append(cy); xs.append(cx)
                        stack += [(cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)]
                    frac = size / (W * H)
                    if min_frac < frac < max_frac:
                        fill = size / ((max(ys) - min(ys) + 1) * (max(xs) - min(xs) + 1))
                        if fill > min_fill:
                            score = frac * 100 * fill
                            if score > worst:
                                worst, where = score, {"frame": int(fi), "frac": round(frac, 4),
                                                       "fill": round(fill, 2)}
    return {"score": round(worst, 2), "threshold": thresh, "passed": worst < thresh,
            "detail": where}
