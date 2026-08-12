"""Spec-§4 thumbnail for the HotD S3E4 explainer.

§4 asks for three dominant elements: Ormund in the foreground with a threatening expression,
Daeron holding a bloodied sword and visibly conflicted, and Tessarion or occupied Tumbleton behind.
Two of those three are faces, and we do not use likenesses.

IP-safe substitution that keeps the same MEANING:
  1. the bloodied sword, held point-down in an armoured hand -- the killing, and the fact that it
     was performed rather than chosen. No face.
  2. the Hightower beacon burning above -- Ormund, as heraldry rather than portrait.
  3. the occupied town below -- Tumbleton.
Plus the §4 badge. Title text is the recommended "A NEW KING?".

Title-thumbnail contract: why is Ormund preparing Daeron to replace his brothers, and what did the
execution accomplish?

Run: /opt/homebrew/bin/python3 hotd_s3e4_thumbnail.py
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
for _l in open(".env", encoding="utf8"):
    _l = _l.strip()
    if _l and not _l.startswith("#") and "=" in _l:
        _k, _, _v = _l.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip())

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

import board_pipeline as bp
import explainer_pipeline as ep

PACK = "house-of-dragons/house_of_the_dragon_s3e4_complete_asset_pack/images"
EL = f"{PACK}/generated/thumb_elements"
OUT = f"{PACK}/thumbnail/90_thumbnail_a_new_king.png"
TW, TH = 1280, 720

ELEMENTS = {
    "occupied_town_dusk": (
        "Cinematic matte-painting illustration, painterly, muted desaturated palette. A small "
        "medieval river town seen from a low hill at dusk, ringed by an army's campfires and tents, "
        "banners on the walls, smoke rising, cold storm light breaking behind a tall stone watchtower "
        "with a beacon burning at its summit. No people in the foreground, no faces, no text, no "
        "logos, original artwork not resembling any film or television production."),
    "bloodied_sword": (
        "Cinematic still life, painterly, dramatic hard side light on a pure black background. A "
        "single medieval longsword held point-downward in one armoured gauntlet, the blade wet and "
        "dark with blood along its lower half. Only the gauntlet and forearm are visible, cropped at "
        "the elbow. No face, no person, no head, no body, no text, no logos."),
}


def gen():
    os.makedirs(EL, exist_ok=True)
    costs = []
    for name, prompt in ELEMENTS.items():
        p = f"{EL}/{name}.png"
        if os.path.exists(p) and os.path.getsize(p) > 0:
            print(f"  {name:20s} reuse"); continue
        ep.generate_image(prompt, p, cost_sink=costs, size="1536x1024")
        print(f"  {name:20s} ok")
    print(f"  element spend: ${sum(costs):.3f}")
    return costs


def _cover(path, w, h):
    im = Image.open(path).convert("RGB")
    s = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * s + 0.5), int(im.height * s + 0.5)), Image.LANCZOS)
    return im.crop(((im.width - w) // 2, (im.height - h) // 2,
                    (im.width - w) // 2 + w, (im.height - h) // 2 + h))


def build():
    im = _cover(f"{EL}/occupied_town_dusk.png", TW, TH).convert("RGBA")

    # ELEMENT 1 -- the sword, foreground right. Both plates are near-black in the shadows, so a
    # feathered blend merges them; a luminance key would erase the dark steel entirely.
    sw = 660
    s = Image.open(f"{EL}/bloodied_sword.png").convert("RGB")
    s = s.resize((sw, int(sw * s.height / s.width)), Image.LANCZOS)
    s = ImageEnhance.Brightness(s).enhance(1.14)
    # Any alpha paste of a black-backed plate leaves an edge somewhere. SCREEN cannot: black
    # contributes nothing, so the sword adds its own light and the plate simply disappears.
    plate = Image.new("RGB", (TW, TH), (0, 0, 0))
    plate.paste(s, (TW - sw + 40, TH - s.height + 52))
    keep = Image.new("L", (TW, TH), 0)
    ImageDraw.Draw(keep).ellipse([TW - sw - 10, TH - s.height + 90, TW + 60, TH + 120], fill=255)
    plate = Image.composite(plate, Image.new("RGB", (TW, TH), (0, 0, 0)),
                            keep.filter(ImageFilter.GaussianBlur(70)))
    im = Image.merge("RGBA", (*ImageChops.screen(im.convert("RGB"), plate).split(),
                              im.split()[3]))

    # bottom-left scrim for the title -- ramped on BOTH axes; a hard right edge is visible
    # against the bright sky
    sc = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    sp = sc.load()
    for y in range(250, TH):
        ay = min(1.0, (y - 250) / 240.0)
        for x in range(0, int(TW * 0.78)):
            ax = 1.0 if x < TW * 0.42 else max(0.0, 1.0 - (x - TW * 0.42) / (TW * 0.36))
            a = int(170 * ay * ax)
            if a:
                sp[x, y] = (3, 4, 7, a)
    im = Image.alpha_composite(im, sc)

    d = ImageDraw.Draw(im)

    # §4 badge
    bf = bp._F(bp._ARIAL, 22)
    bw = d.textlength("S3 EP4 EXPLAINED", font=bf)
    d.rounded_rectangle([TW - bw - 78, 36, TW - 36, 82], radius=8,
                        fill=(10, 12, 18, 232), outline=bp.GOLD, width=2)
    d.text((TW - bw - 57, 48), "S3 EP4 EXPLAINED", font=bf, fill=bp.GOLD)

    # title
    f1 = bp._F(bp._COPPER, 128)
    for dx, dy in ((5, 6), (-4, 5), (4, -4)):
        d.text((60 + dx, TH - 268 + dy), "A NEW", font=f1, fill=(0, 0, 0, 215))
        d.text((60 + dx, TH - 150 + dy), "KING?", font=f1, fill=(0, 0, 0, 220))
    d.text((60, TH - 268), "A NEW", font=f1, fill=(236, 228, 212))
    d.text((60, TH - 150), "KING?", font=f1, fill=(226, 186, 96))
    d.rectangle([60, TH - 296, 250, TH - 290], fill=(226, 186, 96))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    im.convert("RGB").save(OUT, quality=95)
    print(f"  thumbnail -> {OUT}  {im.size}")
    return OUT


if __name__ == "__main__":
    gen()
    build()
