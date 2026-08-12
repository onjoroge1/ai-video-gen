"""Animate the INFORMATION: turn a static diagram into a build that lands one claim at a time.

WHY THIS AND NOT MORE AMBIENT MOTION
Everything we have measured says attention follows semantic change, not pixel movement:

  * S3E2 failed at 1.7% moving frames, and the fix that worked was not adding motion -- it was
    changing the IMAGE every ~6 seconds.
  * The bespoke short DID have motion (2D overlays on held frames) and still read as "a still image
    from 0.17 seconds", because nothing new was being said.
  * Our own sequence-compiler note: "semantic state-change every 1.5-2.5s -- a cut alone does NOT
    count."
  * The S3E5 spec's own pattern-interrupt list is ten items long and every single one is an
    information change (map, canon label, state card, power-board update, before-and-after identity
    graphic, split screen, scoreboard...). Not one is an atmosphere effect.

A generated ambient clip raises the floor -- a held shot stops looking dead. It does not create
forward pull, it costs about $0.30 a shot, and only about 60% of them come back usable. A diagram
that assembles itself in time with the narration costs nothing, is deterministic, cannot violate the
IP posture, and IS the semantic change.

HOW IT WORKS WITHOUT REWRITING EVERY DIAGRAM
Rather than parameterising a dozen drawing functions, the reveal is derived from the finished PNG:
rows carrying ink are grouped into content BANDS (a title, a row of a table, a column block), and
the bands are revealed cumulatively with a soft leading edge. Each band arriving is one new claim.
The complete diagram then holds for the tail so it can be read as a whole.
"""
from __future__ import annotations
import os
import subprocess

import numpy as np
from PIL import Image

HOLD_TAIL = 0.34          # fraction of the shot showing the finished diagram
EDGE_SOFT = 26            # px of feather on the leading edge
MIN_BAND_PX = 14          # ignore hairlines and rule separators
GAP_PX = 9                # blank rows needed to split two bands


def content_bands(png, bg_tol=14, min_band=MIN_BAND_PX, gap=GAP_PX, margin=0.03):
    """Rows of the image that carry ink, grouped into bands. Deterministic, no drawing-code changes.

    The plate background is near-black and close to uniform, so 'ink' is any row whose spread of
    luma rises meaningfully above the frame's own floor.
    """
    a = np.asarray(Image.open(png).convert("L"), dtype=np.int16)
    h, w = a.shape
    x0, x1 = int(w * margin), int(w * (1 - margin))
    strip = a[:, x0:x1]
    floor = np.percentile(strip, 20)
    ink = ((strip - floor) > bg_tol).sum(axis=1)
    thresh = max(6, int(0.004 * (x1 - x0)))
    rows = ink > thresh

    bands, start, blank = [], None, 0
    for y in range(h):
        if rows[y]:
            if start is None:
                start = y
            blank = 0
        elif start is not None:
            blank += 1
            if blank >= gap:
                if y - blank - start >= min_band:
                    bands.append((start, y - blank))
                start, blank = None, 0
    if start is not None and h - start >= min_band:
        bands.append((start, h))
    return bands


SEC_PER_BEAT = 1.9        # our own rule: a semantic change every 1.5-2.5s. Faster than that and
                          # the claim lands before it can be read, which is not retention, it is noise.
MIN_BEATS, MAX_BEATS = 2, 6


def plan(png, frames, fps=30, hold_tail=HOLD_TAIL, sec_per_beat=SEC_PER_BEAT):
    """When each band should land. Returns [(band, appear_frame)] plus the hold point.

    Beat COUNT comes from the shot's length, not from how many bands the diagram happens to have:
    a 7s shot carries three or four claims, not eight. Extra bands are merged into their neighbours.
    """
    bands = content_bands(png)
    build_s = frames * (1 - hold_tail) / fps
    max_bands = max(MIN_BEATS, min(MAX_BEATS, int(round(build_s / sec_per_beat))))
    if len(bands) > max_bands:                     # merge neighbours so beats stay readable
        step = len(bands) / max_bands
        merged = []
        for i in range(max_bands):
            grp = bands[int(i * step):int((i + 1) * step)] or [bands[min(i, len(bands) - 1)]]
            merged.append((grp[0][0], grp[-1][1]))
        bands = merged
    if not bands:
        return [], frames
    build_frames = max(1, int(frames * (1 - hold_tail)))
    per = max(1, build_frames // len(bands))
    return [(b, min(i * per, build_frames - 1)) for i, b in enumerate(bands)], build_frames


def render(png, out_mp4, frames, fps=30, hold_tail=HOLD_TAIL, work=None):
    """Write a clip in which the diagram assembles band by band, then holds complete.

    Returns a report, including the number of beats -- which is the number of distinct moments of
    new information the shot delivers.
    """
    sched, build_frames = plan(png, frames, fps, hold_tail)
    if not sched:
        return {"beats": 0, "rendered": False, "reason": "no content bands found"}

    src = Image.open(png).convert("RGB")
    w, h = src.size
    work = work or (os.path.splitext(out_mp4)[0] + "_frames")
    os.makedirs(work, exist_ok=True)

    base = np.asarray(src, dtype=np.float32)
    dim = (base * 0.10).astype(np.float32)          # unrevealed content sits dark, not absent

    written = 0
    for f in range(frames):
        mask = np.zeros((h, w), dtype=np.float32)
        for (y0, y1), appear in sched:
            if f >= appear:
                grow = min(1.0, (f - appear + 1) / max(EDGE_SOFT / 2.0, 1))
                yy = int(y0 + (y1 - y0) * grow)
                mask[y0:max(yy, y0 + 1), :] = 1.0
                soft = slice(max(yy - EDGE_SOFT, y0), min(yy + EDGE_SOFT, y1))
                if soft.stop > soft.start:
                    ramp = np.linspace(1.0, 0.0, soft.stop - soft.start, dtype=np.float32)
                    mask[soft, :] = np.maximum(mask[soft, :], ramp[:, None])
        m = mask[:, :, None]
        frame = (base * m + dim * (1.0 - m)).astype(np.uint8)
        Image.fromarray(frame).save(os.path.join(work, f"f_{f:05d}.png"))
        written += 1

    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                    "-i", os.path.join(work, "f_%05d.png"),
                    "-frames:v", str(frames), "-c:v", "libx264", "-preset", "medium",
                    "-crf", "19", "-pix_fmt", "yuv420p", out_mp4], check=True)
    for f in os.listdir(work):
        os.remove(os.path.join(work, f))
    os.rmdir(work)
    return {"beats": len(sched), "frames": written, "build_frames": build_frames,
            "hold_frames": frames - build_frames, "rendered": True,
            "beat_every_s": round(build_frames / fps / max(len(sched), 1), 2)}


def build_for_episode(ep, playlists, script, fps=30, progress=print):
    """Render a reveal clip for every diagram shot. Free, deterministic, no provider involved."""
    seg = {s["id"]: s for s in script["segments"]}
    outdir = os.path.join(ep.work, "reveals")
    os.makedirs(outdir, exist_ok=True)
    made, skipped = {}, []
    for sid, shots in playlists.items():
        if sid not in seg:
            continue
        n = len(shots)
        total = int(round(seg[sid]["target_s"] * fps))
        per = total // max(n, 1)
        for k, it in enumerate(shots):
            if it[0] != "full":
                continue
            key = f"{sid}#{k}"
            out = os.path.join(outdir, f"{key.replace('#', '_')}.mp4")
            if os.path.exists(out) and os.path.getsize(out) > 10000:
                made[key] = out
                continue
            r = render(ep.asset(it[1]), out, per, fps)
            if r["rendered"]:
                made[key] = out
                progress(f"  {key:34s} {r['beats']} beats, one every {r['beat_every_s']}s")
            else:
                skipped.append((key, r.get("reason")))
    return {"clips": made, "skipped": skipped}
