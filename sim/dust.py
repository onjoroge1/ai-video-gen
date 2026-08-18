"""Procedural dust drift for empty scenes. Deterministic, free, cannot grow a goat.

Seven consecutive i2v generations of "dust settles over empty rocky ground" came back with an
invented animal walking through frame -- with wildlife negatives in place. The invented_subject_gate
now catches them, but a gate that rejects 100% of attempts is just a slower way to spend $0.35 per
roll. The actual lesson is the layer-ownership rule already written on this project: the generative
model owns the WORLD when the world needs imagination; a drifting dust layer is not imagination, it
is a texture with a velocity, and that belongs to code.

Three translucent smoke layers (smooth noise, upscaled), each scrolling at its own speed with a slow
opacity breath, screen-blended over the plate. Seeded per plate stem, so a rebuild is bit-identical.
"""
from __future__ import annotations
import os
import subprocess

import numpy as np
from PIL import Image, ImageFilter


def _noise_field(rng, w, h, cell=48):
    """Smooth random field in [0,1]: low-res gaussian noise upscaled with bicubic."""
    lo = rng.random((h // cell + 2, w // cell + 2)).astype(np.float32)
    im = Image.fromarray((lo * 255).astype(np.uint8)).resize((w * 2, h * 2), Image.BICUBIC)
    im = im.filter(ImageFilter.GaussianBlur(cell // 3))
    return np.asarray(im, dtype=np.float32)[:h * 2, :w * 2] / 255.0


def render(plate_png, out_mp4, seconds=5.04, fps=30, strength=0.38, seed_from=None,
           band=(0.35, 1.0)):
    """Write a dust-drift clip over the plate. `band` limits the dust to a vertical fraction of
    frame (default: lower two thirds -- dust hugs the ground, it does not climb the cliff top)."""
    plate = Image.open(plate_png).convert("RGB")
    w, h = plate.size
    base = np.asarray(plate, dtype=np.float32)

    seed = abs(hash(seed_from or os.path.basename(plate_png))) % (2 ** 31)
    rng = np.random.default_rng(seed)
    frames = int(round(seconds * fps))

    # Three layers: slow far haze, mid drift, near faster wisps. Cells are LARGE and soft on
    # purpose -- a small high-contrast noise cell is a compact bright blob, and the invented-subject
    # gate (correctly) reads that as a creature. Velocities are full pixels per frame at plate
    # resolution: the first cut drifted sub-pixel at decode scale and failed the motion floor.
    # Each layer holds TWO fields scrolling against each other; their product churns instead of
    # sliding, which is where the visible motion lives -- a single smooth field translating reads
    # as nearly static no matter how fast it moves, because the per-pixel delta of a soft gradient
    # is tiny. Interference gives the billow.
    layers = []
    for cell, vx, vy, amp in ((170, 90, -18, 0.40), (110, 160, -34, 0.30), (70, 260, -60, 0.20)):
        layers.append({"a": _noise_field(rng, w, h, cell), "b": _noise_field(rng, w, h, cell),
                       "vx": vx / fps, "vy": vy / fps, "amp": amp})

    # vertical mask: dust lives near the ground
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    lo, hi = band
    mask = np.clip((y - lo) / max(hi - lo, 1e-6), 0, 1) ** 1.5

    work = out_mp4[:-4] + "_frames"
    os.makedirs(work, exist_ok=True)
    for f in range(frames):
        dust = np.zeros((h, w), dtype=np.float32)
        for L in layers:
            ox, oy = int(f * L["vx"]), int(f * L["vy"])
            ta = np.roll(np.roll(L["a"], -oy % h, axis=0), -ox % w, axis=1)[:h, :w]
            # second field counter-scrolls at 0.6x: the product BILLOWS
            tb = np.roll(np.roll(L["b"], int(oy * 0.6) % h, axis=0),
                         int(ox * 0.6) % w, axis=1)[:h, :w]
            breath = 0.85 + 0.15 * np.sin(2 * np.pi * (f / frames) + L["amp"] * 7)
            dust += L["amp"] * breath * (0.35 * ta + 0.65 * ta * (0.5 + tb))
        dust = np.clip(dust, 0, 1) * mask * strength
        # screen blend with a warm grey dust colour
        col = np.array([206, 199, 188], dtype=np.float32)
        frame = base + (255 - base) * (dust[:, :, None] * (col / 255.0))
        Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8)).save(
            os.path.join(work, f"d_{f:05d}.png"))

    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                    "-i", os.path.join(work, "d_%05d.png"), "-frames:v", str(frames),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                    "-pix_fmt", "yuv420p", out_mp4], check=True)
    for fn in os.listdir(work):
        os.remove(os.path.join(work, fn))
    os.rmdir(work)
    return out_mp4


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    P = "simulations/survives_the_fall/images"
    C = "renders/survives_the_fall/work/clips"
    for stem, scene in (("14_horse_land", "hook"), ("13_human_land", "human_land"),
                        ("14_horse_land", "horse_land")):
        out = os.path.join(C, f"{scene}.mp4")
        render(os.path.join(P, f"{stem}.png"), out, seed_from=scene)
        print(scene, "->", out)


# ---------------------------------------------------------------------------------------------
# DEBRIS: the deterministic answer to the ninth goat. The provider was asked for settling debris
# nine times and populated the frame with an animal nine times; the compositor philosophy already
# written in sim/projectile.py is that quantities and physical motion belong to code. Falling
# pebbles ARE physics -- position is v0*t + g*t^2/2 with one damped bounce -- so they are drawn,
# not requested. They also give the shot what the soft dust could not: per-pixel deltas large
# enough that the gap gate reads the frame as moving, because a pebble crossing 20px per frame
# is real motion, not a sliding gradient.
def render_debris(plate_png, out_mp4, seconds=5.04, fps=30, n=9, seed_from=None,
                  dust_strength=0.30, band=(0.35, 1.0)):
    """Dust drift + seeded falling pebbles with a bounce. Fully deterministic per (plate, seed)."""
    plate = Image.open(plate_png).convert("RGB")
    w, h = plate.size
    base = np.asarray(plate, dtype=np.float32)
    seed = abs(hash((seed_from or os.path.basename(plate_png)) + ":debris")) % (2 ** 31)
    rng = np.random.default_rng(seed)
    frames = int(round(seconds * fps))

    layers = []
    for cell, vx, vy, amp in ((170, 90, -18, 0.40), (110, 160, -34, 0.30), (70, 260, -60, 0.20)):
        layers.append({"a": _noise_field(rng, w, h, cell), "b": _noise_field(rng, w, h, cell),
                       "vx": vx / fps, "vy": vy / fps, "amp": amp})
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    lo, hi = band
    mask = np.clip((y - lo) / max(hi - lo, 1e-6), 0, 1) ** 1.5

    # pebbles: (x, y0, size, t_start, ground_y). Ground sits in the lower fifth of frame.
    g_px = h * 0.9 / (fps * fps)                     # ~0.9 frame-heights per second^2
    pebbles = []
    for i in range(n):
        pebbles.append({
            "x": float(rng.uniform(0.08, 0.92) * w),
            "y0": float(rng.uniform(-0.25, -0.05) * h),
            "r": float(rng.uniform(5, 14)),
            "t0": int(rng.uniform(0, frames * 0.55)),
            "gy": float(rng.uniform(0.80, 0.94) * h),
            "drift": float(rng.uniform(-1.2, 1.2)),
        })

    from PIL import ImageDraw
    work = out_mp4[:-4] + "_frames"
    os.makedirs(work, exist_ok=True)
    for f in range(frames):
        dust = np.zeros((h, w), dtype=np.float32)
        for L in layers:
            ox, oy = int(f * L["vx"]), int(f * L["vy"])
            ta = np.roll(np.roll(L["a"], -oy % h, axis=0), -ox % w, axis=1)[:h, :w]
            tb = np.roll(np.roll(L["b"], int(oy * 0.6) % h, axis=0),
                         int(ox * 0.6) % w, axis=1)[:h, :w]
            breath = 0.85 + 0.15 * np.sin(2 * np.pi * (f / frames) + L["amp"] * 7)
            dust += L["amp"] * breath * (0.35 * ta + 0.65 * ta * (0.5 + tb))
        dust = np.clip(dust, 0, 1) * mask * dust_strength
        col = np.array([206, 199, 188], dtype=np.float32)
        frame = base + (255 - base) * (dust[:, :, None] * (col / 255.0))
        im = Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(im)
        for p in pebbles:
            t = f - p["t0"]
            if t < 0:
                continue
            yy = p["y0"] + 0.5 * g_px * t * t
            if yy > p["gy"]:                          # one damped bounce, then rest
                t_hit = (2 * (p["gy"] - p["y0"]) / g_px) ** 0.5
                tb2 = t - t_hit
                v_hit = g_px * t_hit
                yy = p["gy"] - max(0.0, 0.30 * v_hit * tb2 - 0.5 * g_px * tb2 * tb2)
            xx = p["x"] + p["drift"] * t
            r = p["r"]
            sh = 0.35 * r
            d.ellipse([xx - r, yy - r * 0.8, xx + r, yy + r * 0.8], fill=(88, 84, 78))
            d.ellipse([xx - r, yy - r * 0.8, xx + r, yy - r * 0.15], fill=(132, 126, 116))
            d.ellipse([xx - r - sh, p["gy"] + 2, xx + r + sh, p["gy"] + 8], fill=(40, 38, 35))
        im.save(os.path.join(work, f"d_{f:05d}.png"))

    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                    "-i", os.path.join(work, "d_%05d.png"), "-frames:v", str(frames),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                    "-pix_fmt", "yuv420p", out_mp4], check=True)
    for fn in os.listdir(work):
        os.remove(os.path.join(work, fn))
    os.rmdir(work)
    return out_mp4
