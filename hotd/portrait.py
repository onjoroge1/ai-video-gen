"""Cut a supplied character portrait off its studio backdrop, cleanly.

The library portraits sit on a neutral grey sweep that is NOT flat -- it is brighter behind the
figure's head and falls off toward the corners. A single colour-distance threshold therefore keeps
part of the sweep and leaves a grey halo shaped like the vignette, which is exactly what the first
attempt produced. This is the same failure as keying the thumbnail chest off black: the background is
not one colour, so it cannot be removed with one number.

What also does not work: estimating the backdrop per ROW from the outer columns. Measured coverage
came out 0.35-0.71 (a figure should be ~0.20), because the sweep is RADIAL -- bright behind the head,
dark in the corners -- so an outer-column sample reads the dark corners and the bright centre then
registers as subject.

Method that works: fit the backdrop as a smooth SURFACE. Sample the border ring (excluding the bottom
edge, which the figure reaches), least-squares fit a quadratic in x and y per channel, evaluate it
over the whole frame, and key against that model. A smooth gradient is exactly what a low-order
polynomial represents well, and the figure -- which is not smooth -- falls out as residual.

`matte()` returns the cut-out RGBA plus a report. The report exists because a silent bad matte is
worse than a crash: coverage far outside 0.12-0.55 means the key failed and the caller should stop.
"""
from __future__ import annotations
import os

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

EDGE_COLS = 0.06          # fraction of width at each side used to sample the backdrop
TOL = 22.0                # colour distance from the local backdrop that counts as subject
FEATHER = 1.4
COVERAGE_OK = (0.08, 0.42)   # a full-body figure in a square frame measures ~0.15-0.30


def matte(path, tol=TOL, edge=EDGE_COLS, feather=FEATHER):
    im = Image.open(path).convert("RGB")
    a = np.asarray(im, dtype=np.float32)
    h, w, _ = a.shape
    k = max(4, int(w * edge))

    # --- fit the backdrop as a smooth quadratic surface from the border ring -------------------
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    xn, yn = xx / w, yy / h
    ring = np.zeros((h, w), dtype=bool)
    ring[:k, :] = True                    # top
    ring[:, :k] = True                    # left
    ring[:, w - k:] = True                # right
    ring[int(h * 0.72):, :] = False       # the figure reaches the bottom; never sample there
    basis = np.stack([np.ones_like(xn), xn, yn, xn * yn, xn ** 2, yn ** 2], axis=-1)
    B = basis[ring]                                        # (n, 6)
    model = np.empty_like(a)
    for c in range(3):
        coef, *_ = np.linalg.lstsq(B, a[..., c][ring], rcond=None)
        model[..., c] = basis @ coef
    dist = np.linalg.norm(a - model, axis=2)               # residual from the fitted sweep

    m = dist > tol
    m = ndimage.binary_opening(m, np.ones((3, 3)))         # kill speckle first
    m = ndimage.binary_closing(m, np.ones((7, 7)), iterations=2)
    lab, n = ndimage.label(m)
    if n:
        sizes = ndimage.sum(m, lab, range(1, n + 1))
        m = lab == (int(np.argmax(sizes)) + 1)             # the figure, not the sweep
    m = ndimage.binary_fill_holes(m)
    m = ndimage.binary_erosion(m, np.ones((3, 3)))         # pull in off the sweep edge

    coverage = float(m.mean())
    alpha = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(feather))
    out = im.convert("RGBA")
    out.putalpha(alpha)
    box = out.getbbox()
    out = out.crop(box) if box else out
    rep = {"coverage": round(coverage, 3), "bbox": box,
           "ok": COVERAGE_OK[0] <= coverage <= COVERAGE_OK[1]}
    return out, rep


def cut(path, target_h, cache_dir=None, **kw):
    """Matte and scale to target height. Caches the cut-out as a PNG with alpha."""
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        cp = os.path.join(cache_dir, os.path.basename(path))
        if os.path.exists(cp) and os.path.getsize(cp) > 0:
            im = Image.open(cp).convert("RGBA")
            s = target_h / im.height
            return im.resize((int(im.width * s), target_h), Image.LANCZOS), {"cached": True}
    im, rep = matte(path, **kw)
    if not rep["ok"]:
        raise RuntimeError(f"portrait matte failed for {path}: coverage {rep['coverage']} "
                           f"outside {COVERAGE_OK} -- the key kept backdrop or lost the figure")
    if cache_dir:
        im.save(os.path.join(cache_dir, os.path.basename(path)))
    s = target_h / im.height
    return im.resize((int(im.width * s), target_h), Image.LANCZOS), rep


def library_index(lib_dir):
    """slug -> path for every *-master.png in the supplied library."""
    out = {}
    for f in sorted(os.listdir(lib_dir)):
        if f.endswith("-master.png"):
            out[f[: -len("-master.png")]] = os.path.join(lib_dir, f)
    return out


def audit(lib_dir, cache_dir=None):
    """Matte every portrait and report coverage, so a bad key is found before any render."""
    rows = []
    for slug, p in library_index(lib_dir).items():
        try:
            _, rep = cut(p, 900, cache_dir=cache_dir)
            rows.append((slug, rep.get("coverage"), "ok" if rep.get("ok", True) else "SUSPECT"))
        except Exception as e:
            rows.append((slug, None, f"FAIL {e}"))
    return rows
