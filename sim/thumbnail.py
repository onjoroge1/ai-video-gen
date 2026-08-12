"""Thumbnails for simulations, drawn from a plate the video already paid for.

No generation call. The most striking frame of a simulation is one of its own plates -- generating a
separate hero image costs money, risks a different-looking subject than the video, and is the exact
identity drift the CONTINUITY block exists to prevent.

Which plate: the scene whose chip carries the PAYOFF, not the control. A thumbnail of Earth on a
video about six worlds promises the boring one. `hero` defaults to the first scene the direction
opened on, which for a parallel experiment is the surprise by construction.

Text comes from the scene's own `onscreen` string, so the thumbnail and the first seconds of the
video make the same promise -- the title/thumbnail contract, enforced by reusing the string rather
than by writing it twice.
"""
from __future__ import annotations
import os

from PIL import Image

from hotd import thumbnail as T


def _pick(sim, hero=None):
    """(plate_path, lines) for the thumbnail."""
    by_id = {s.id: s for s in sim.scenes}
    sc = by_id.get(hero) if hero else None
    if sc is None:
        # first scene carrying on-screen text; the opener of a parallel experiment is the surprise
        sc = next((s for s in sim.scenes if (s.onscreen or "").strip()), sim.scenes[0])
    txt = (sc.onscreen or sim.title or "").strip()
    words = txt.split()
    if len(words) > 3:
        mid = (len(words) + 1) // 2
        lines = [" ".join(words[:mid]), " ".join(words[mid:])]
    else:
        lines = [txt] if txt else [sim.title]
    return sim.asset(sc.image), [l.upper() for l in lines if l], sc


def _smart_cover(path, w=T.TW, h=T.TH):
    """Crop a portrait plate to 16:9 around the SUBJECT, not the geometric centre.

    hotd.thumbnail.cover centre-crops, which is right for a landscape source and wrong for a 9:16
    plate: the first fly thumbnail was a rectangle of empty orange sky because the drone sat high in
    frame and the centre of the picture was haze. Choose the window with the most edge energy --
    a cheap saliency proxy that finds the drone, the glass, the hands.
    """
    import numpy as np
    from PIL import ImageFilter

    im = Image.open(path).convert("RGB")
    if im.width / im.height >= w / h:                 # already landscape enough
        return T.cover(path, w, h)
    win = int(im.width * h / w)                       # height of a 16:9 window at full width
    if win >= im.height:
        return T.cover(path, w, h)
    edges = np.asarray(im.convert("L").filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    rows = edges.mean(axis=1)
    cs = np.concatenate([[0.0], np.cumsum(rows)])
    best, top = -1.0, 0
    for y in range(0, im.height - win + 1, 8):
        e = cs[y + win] - cs[y]
        if e > best:
            best, top = e, y
    return im.crop((0, top, im.width, top + win)).resize((w, h), Image.LANCZOS)


def build(sim, out=None, hero=None, badge=None, size=140, progress=print):
    """Write a 1280x720 thumbnail beside the render. Free, deterministic, no provider call."""
    plate, lines, sc = _pick(sim, hero)
    im = _smart_cover(plate).convert("RGBA")
    # scrim under the text only, so the plate still reads as the picture
    im = T.corner_scrim(im, y_start=int(T.TH * 0.34), x_full=0.50, x_end=0.86, alpha=178)
    T.title(im, lines, size=size)
    if badge:
        T.badge(im, badge)
    out = out or os.path.join(sim.out, "thumbnail.jpg")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    im.convert("RGB").save(out, quality=94)
    rep = T.contrast_report(out)
    progress(f"  thumbnail <- {sc.id} ({os.path.basename(plate)}) {lines} -> {out}")
    progress(f"  legibility: {rep}")
    if not rep.get("ok_for_light_text"):
        progress("  WARNING: title region is bright; light text may not read at phone size")
    return {"path": out, "from_scene": sc.id, "lines": lines, "contrast": rep}
