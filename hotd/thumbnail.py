"""Thumbnail compositor, shared across episodes.

Both per-episode thumbnail scripts were ~50% identical and each re-derived the same compositing
lessons the hard way. The two that matter, learned by getting them wrong:

  * DO NOT luminance-key a generated element onto a plate. Dark subjects (weathered wood, blued
    steel) sit only just above the black background, so a key deletes the subject and keeps nothing.
  * DO NOT alpha-paste a black-backed element either, feathered or not: the plate's dark corners
    leave a visible rectangle wherever the background behind is brighter. SCREEN-blend instead --
    black contributes nothing, so the element adds its own light and its backing simply disappears.

Text scrims ramp on BOTH axes; a scrim with a hard right edge is visible against a bright sky.
"""
from __future__ import annotations
import os

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

import board_pipeline as bp

TW, TH = 1280, 720


def gen_elements(elements, outdir, cap_usd=0.5, size="1536x1024", progress=print):
    """Generate the thumbnail's photographic elements, with a spend cap."""
    from hotd.generate import Ledger

    os.makedirs(outdir, exist_ok=True)
    led = Ledger(cap_usd)
    import explainer_pipeline as ep
    for name, prompt in elements.items():
        p = os.path.join(outdir, f"{name}.png")
        if os.path.exists(p) and os.path.getsize(p) > 0:
            progress(f"  {name:24s} reuse"); continue
        led.check()
        ep.generate_image(prompt, p, cost_sink=led.costs, size=size)
        progress(f"  {name:24s} ok")
    progress(f"  element spend: ${led.spent:.3f}")
    return led


def cover(path, w=TW, h=TH):
    im = Image.open(path).convert("RGB")
    s = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * s + 0.5), int(im.height * s + 0.5)), Image.LANCZOS)
    return im.crop(((im.width - w) // 2, (im.height - h) // 2,
                    (im.width - w) // 2 + w, (im.height - h) // 2 + h))


def screen_element(base_rgba, element_path, width, pos, brighten=1.14, feather=70):
    """Add a black-backed element by SCREEN blend, confined to a soft ellipse. No edges, ever."""
    el = Image.open(element_path).convert("RGB")
    el = el.resize((width, int(width * el.height / el.width)), Image.LANCZOS)
    el = ImageEnhance.Brightness(el).enhance(brighten)
    x, y = pos
    plate = Image.new("RGB", base_rgba.size, (0, 0, 0))
    plate.paste(el, (x, y))
    keep = Image.new("L", base_rgba.size, 0)
    ImageDraw.Draw(keep).ellipse([x - int(width * 0.06), y + int(el.height * 0.06),
                                  x + int(width * 1.06), y + int(el.height * 1.18)], fill=255)
    plate = Image.composite(plate, Image.new("RGB", base_rgba.size, (0, 0, 0)),
                            keep.filter(ImageFilter.GaussianBlur(feather)))
    return Image.merge("RGBA", (*ImageChops.screen(base_rgba.convert("RGB"), plate).split(),
                                base_rgba.split()[3]))


def corner_scrim(im, y_start=250, x_full=0.42, x_end=0.78, alpha=170):
    sc = Image.new("RGBA", im.size, (0, 0, 0, 0))
    px = sc.load()
    w, h = im.size
    for y in range(y_start, h):
        ay = min(1.0, (y - y_start) / 240.0)
        for x in range(0, int(w * x_end)):
            ax = 1.0 if x < w * x_full else max(0.0, 1.0 - (x - w * x_full) / (w * (x_end - x_full)))
            a = int(alpha * ay * ax)
            if a:
                px[x, y] = (3, 4, 7, a)
    return Image.alpha_composite(im, sc)


def title(im, lines, size=128, x=60, bottom_pad=150, accent=(226, 186, 96),
          light=(236, 228, 212)):
    d = ImageDraw.Draw(im)
    f = bp._F(bp._COPPER, size)
    n = len(lines)
    for i, ln in enumerate(lines):
        y = im.height - bottom_pad - (n - 1 - i) * int(size * 0.92)
        for dx, dy in ((5, 6), (-4, 5), (4, -4)):
            d.text((x + dx, y + dy), ln, font=f, fill=(0, 0, 0, 215))
        d.text((x, y), ln, font=f, fill=accent if i == n - 1 else light)
    top = im.height - bottom_pad - (n - 1) * int(size * 0.92)
    d.rectangle([x, top - 28, x + 190, top - 22], fill=accent)
    return im


def badge(im, text, size=22):
    d = ImageDraw.Draw(im)
    f = bp._F(bp._ARIAL, size)
    w = d.textlength(text, font=f)
    d.rounded_rectangle([im.width - w - 78, 36, im.width - 36, 36 + size * 2.1], radius=8,
                        fill=(10, 12, 18, 232), outline=bp.GOLD, width=2)
    d.text((im.width - w - 57, 48), text, font=f, fill=bp.GOLD)
    return im


def sigil(pack, name, size, tint):
    from hotd import assets as A
    p = A.find_sigil(pack, name)
    em = Image.open(p).convert("RGB").resize((size, size), Image.LANCZOS)
    mask = em.convert("L").point(lambda v: min(255, int(v * 1.3)))
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(Image.new("RGB", (size, size), tint), (0, 0), mask)
    return out


def contrast_report(path):
    """Cheap legibility check: the title region must be dark enough for light text."""
    import numpy as np
    im = Image.open(path).convert("L")
    a = np.asarray(im, dtype=float)
    h, w = a.shape
    region = a[int(h * 0.62):, :int(w * 0.45)]
    return {"title_region_mean_luma": round(float(region.mean()), 1),
            "ok_for_light_text": bool(region.mean() < 90)}
