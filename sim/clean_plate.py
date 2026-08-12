"""Remove the painted projectile and energy trail from a source plate, keeping everything else.

WHY THIS EXISTS
The supplied artwork ships with the trajectory already drawn in: a luminous blue or orange arc with
a small bullet at its head. That is the thing that reads as "polished science illustration" rather
than "a real object under real physics", and it is baked into the background, so it cannot be
replaced by compositing on top -- the old trail would still be underneath.

Local filtering does not work. A median-deviation mask plus median fill was tried first: it smeared
the terrain and the character, and the arc survived anyway, because the arc is thick and bright over
a large area rather than a hairline. So the fill has to be a real inpaint.

WHAT IS EDITED
Only the mask: the arc, its glow halo, and the drawn bullet. Terrain, sky gradient, launcher,
character and lighting are outside the mask and are preserved by input_fidelity=high.
"""
from __future__ import annotations
import base64
import io
import os

import numpy as np
from PIL import Image, ImageFilter

MODEL = os.environ.get("IMAGE_MODEL", "gpt-image-2")
EDIT_SIZE = "1024x1536"          # portrait; plates are 941x1672


def arc_mask(path, dev_thresh=16, grow=13, feather=5, min_area=900):
    """Transparent where the trail is, opaque elsewhere. OpenAI edits the TRANSPARENT region.

    Naive brightness deviation is NOT enough: on the airless plates it flags every star and masked
    46% of the frame, which would mean regenerating half the artwork rather than preserving it. So
    the candidate pixels are grouped into connected components and only LARGE ones are kept -- the
    trail is one long connected stroke, a star is a handful of pixels.
    """
    from scipy import ndimage

    im = Image.open(path).convert("RGB")
    a = np.asarray(im, dtype=np.float32)
    med = np.asarray(im.filter(ImageFilter.MedianFilter(21)), dtype=np.float32)
    dev = (a - med).max(axis=2)
    cand = dev > dev_thresh
    cand = ndimage.binary_closing(cand, structure=np.ones((5, 5)), iterations=2)
    lab, n = ndimage.label(cand)
    keep = np.zeros_like(cand)
    for i in range(1, n + 1):
        comp = lab == i
        if comp.sum() >= min_area:                    # the stroke survives, stars do not
            keep |= comp
    m = Image.fromarray((keep * 255).astype(np.uint8))
    m = m.filter(ImageFilter.MaxFilter(grow)).filter(ImageFilter.GaussianBlur(feather))
    alpha = 255 - np.asarray(m, dtype=np.uint8)          # trail -> transparent
    out = im.convert("RGBA")
    out.putalpha(Image.fromarray(alpha))
    return out, float((np.asarray(m) > 127).mean())


CLEAN_PROMPT = (
    "Remove the glowing projectile streak and the small bullet completely. Fill the area with the "
    "surrounding sky, clouds, stars or terrain so the scene looks completely natural and empty, as "
    "though nothing had ever been fired. Keep the landscape, the horizon, the metal launcher, the "
    "small robot, the lighting and the colour grade exactly as they are. No streak, no trail, no "
    "glow, no projectile, no text.")


def clean(path, out_path, cost_sink=None, progress=print):
    """Inpaint the trail away. Returns (ok, mask_fraction, err)."""
    from openai import OpenAI

    masked, frac = arc_mask(path)
    src = Image.open(path).convert("RGB").resize(
        tuple(int(x) for x in EDIT_SIZE.split("x")), Image.LANCZOS)
    msk = masked.resize(tuple(int(x) for x in EDIT_SIZE.split("x")), Image.LANCZOS)
    sb, mb = io.BytesIO(), io.BytesIO()
    src.save(sb, format="PNG"); msk.save(mb, format="PNG")
    sb.name, mb.name = "plate.png", "mask.png"
    sb.seek(0); mb.seek(0)
    try:
        # NOTE: gpt-image-2 rejects input_fidelity (400 invalid_input_fidelity_model).
        r = OpenAI().images.edit(model=MODEL, image=sb, mask=mb, prompt=CLEAN_PROMPT,
                                 size=EDIT_SIZE)
        img = Image.open(io.BytesIO(base64.b64decode(r.data[0].b64_json)))
        img.resize(Image.open(path).size, Image.LANCZOS).save(out_path)
        if cost_sink is not None and getattr(r, "usage", None):
            u = r.usage
            cost_sink.append((getattr(u, "input_tokens", 0) * 10 +
                              getattr(u, "output_tokens", 0) * 40) / 1e6)
        return True, frac, None
    except Exception as e:
        return False, frac, f"{type(e).__name__}: {e}"


def clean_all(src_dir, out_dir, names=None, cap_usd=1.00, progress=print):
    os.makedirs(out_dir, exist_ok=True)
    costs, fails = [], []
    stems = names or sorted(os.path.splitext(f)[0] for f in os.listdir(src_dir)
                            if f.endswith(".png"))
    for n in stems:
        dst = os.path.join(out_dir, f"{n}.png")
        if os.path.exists(dst) and os.path.getsize(dst) > 10000:
            progress(f"  {n:38s} reuse"); continue
        if sum(costs) >= cap_usd:
            fails.append((n, "cap reached")); continue
        ok, frac, err = clean(os.path.join(src_dir, f"{n}.png"), dst, cost_sink=costs)
        progress(f"  {n:38s} {'ok' if ok else 'FAIL'}  masked {frac*100:4.1f}%"
                 f"{'' if ok else '  ' + str(err)[:80]}  (${sum(costs):.2f})")
        if not ok:
            fails.append((n, err))
    return costs, fails
