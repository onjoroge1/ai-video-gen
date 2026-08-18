"""Put the reference figure under the SCENE's light before the generator ever sees him.

THE FAILURE THIS PREVENTS (negative validation, class 2 -- the biggest one):
Reference conditioning imports the reference image's lighting along with its wardrobe. Our
human-model.png is a studio shot -- neutral key, white fill -- so every plate built from it put a
studio-lit man into worlds where every photon is orange (Titan), sulfur yellow (Venus) or hard and
shadow-casting (Mars). Three independent review lenses called it the single strongest compositing
tell. Prompt language alone does not beat the reference: the pixels win.

So the reference itself is graded per world before it is passed to gpt-image-2: pushed toward the
scene's ambient colour, contrast bent toward its light quality, and handed over already belonging
to that world. The INTEGRATION_RULE text in the plate prompt then asks for the contact shadow; the
graded reference stops the prompt having to fight the pixels about colour.

Deterministic, free, cached by content: same reference + same ambient -> same file.
"""
from __future__ import annotations
import hashlib
import os

from PIL import Image, ImageEnhance

# Named ambients, so scene data declares intent ("titan_haze") rather than RGB soup. Each entry:
# (tint RGB, tint strength 0..1, contrast, brightness). Strengths are deliberately strong -- a
# subtle grade loses to the generator's prior for clean studio light; we are re-lighting, not
# tinting a thumbnail.
AMBIENTS = {
    "titan_haze":   ((255, 147, 41), 0.45, 0.94, 0.82),   # deep orange overcast, dim
    "venus_sulfur": ((234, 200, 96), 0.42, 0.90, 0.88),   # sealed yellow softbox
    "mars_sun":     ((255, 178, 128), 0.30, 1.12, 1.05),  # hard salmon daylight
    "earth_storm":  ((160, 172, 190), 0.30, 0.92, 0.80),  # cool grey backlit overcast
    "moon_sun":     ((240, 240, 245), 0.12, 1.20, 1.05),  # airless hard white
    "neutral":      ((255, 255, 255), 0.0, 1.0, 1.0),
}


def graded_reference(ref_path, ambient, out_dir):
    """Return the path of `ref_path` graded to the named ambient, writing it if not cached.

    The cache key includes the source file's bytes and the ambient parameters, so editing the
    reference or tuning an ambient invalidates stale grades instead of silently reusing them.
    """
    if ambient not in AMBIENTS:
        raise KeyError(f"unknown ambient {ambient!r}; have {sorted(AMBIENTS)}")
    tint, strength, contrast, bright = AMBIENTS[ambient]
    if strength == 0.0:
        return ref_path

    h = hashlib.sha1()
    h.update(open(ref_path, "rb").read())
    h.update(repr(AMBIENTS[ambient]).encode())
    stem = os.path.splitext(os.path.basename(ref_path))[0]
    out = os.path.join(out_dir, f"{stem}_{ambient}_{h.hexdigest()[:10]}.png")
    if os.path.exists(out):
        return out

    os.makedirs(out_dir, exist_ok=True)
    im = Image.open(ref_path).convert("RGB")
    overlay = Image.new("RGB", im.size, tint)
    im = Image.blend(im, overlay, strength)
    im = ImageEnhance.Contrast(im).enhance(contrast)
    im = ImageEnhance.Brightness(im).enhance(bright)
    im.save(out)
    return out


def references_for(sim, base_refs, out_dir=None):
    """Per-plate-stem reference map from scene ambients. -> {stem: [paths]} or None.

    Scenes declare `Scene.ambient` (a key into AMBIENTS) or inherit meta["ambient"]. Plates whose
    scene declares nothing get the base references untouched -- explicitly, so a missing ambient is
    a visible choice in the data file rather than a silent neutral.
    """
    if not base_refs:
        return None
    out_dir = out_dir or os.path.join(sim.work, "graded_refs")
    default = (sim.meta or {}).get("ambient")
    by_stem = {}
    for sc in sim.scenes:
        amb = getattr(sc, "ambient", "") or default
        if amb:
            by_stem[sc.image] = [graded_reference(r, amb, out_dir) for r in base_refs]
        else:
            by_stem[sc.image] = list(base_refs)
    return by_stem
