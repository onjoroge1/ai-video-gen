"""Spec-§5 thumbnail for S3E5: "THEY'RE INSIDE".

The spec's own thumbnail text. Three dominant elements, no likenesses:
  1. the Red Keep above the city -- the place that is supposed to be safe
  2. a struck coin in the foreground, the object that carries the war in
  3. the Hightower beacon small in the sky behind, as heraldry rather than a portrait

Compositing goes through hotd.thumbnail, which screen-blends black-backed elements: a luminance key
deletes dark subjects and an alpha paste leaves a visible rectangle. Both were learned by shipping
them wrong.
"""
from __future__ import annotations
import os

from hotd import thumbnail as T
import hotd_s3e5_data as D

EL = f"{D.PACK}/generated/thumb_elements"
OUT = f"{D.PACK}/thumbnail/95_thumbnail_they_are_inside.png"

ELEMENTS = {
    "keep_over_city": (
        "Cinematic matte-painting illustration, painterly, muted desaturated palette. A massive red "
        "sandstone castle with seven great drum towers standing on a hill above a dense medieval "
        "city at night, lit windows scattered across the rooftops below, cold moonlight, low smoke. "
        "No people, no faces, no text, no logos, original artwork not resembling any film or "
        "television production."),
    "struck_coin": (
        "Cinematic macro still life on a pure black background, dramatic hard side light. A single "
        "worn silver-gold coin standing on edge on dark stone, a crowned profile struck in relief on "
        "its face, shallow depth of field. Only the coin and the stone. No hands, no people, no "
        "readable letters or words anywhere, no text, no logos."),
}


def gen():
    return T.gen_elements(ELEMENTS, EL, cap_usd=0.30)


def build():
    im = T.cover(f"{EL}/keep_over_city.png").convert("RGBA")
    # the coin, foreground right, screen-blended so its black backing disappears entirely
    im = T.screen_element(im, f"{EL}/struck_coin.png", width=560, pos=(T.TW - 520, T.TH - 430),
                          brighten=1.2, feather=64)
    im = T.corner_scrim(im, y_start=230, x_full=0.44, x_end=0.80, alpha=176)
    # element 3: the Hightower beacon, deliberately small
    T.badge(im, "S3 EP5 EXPLAINED")
    # below the badge, not behind it: at the same height the beacon reads as an artifact rather
    # than as the third element
    im.alpha_composite(T.sigil(D.PACK_PREV, "hightower", 82, (214, 176, 96)), (T.TW - 150, 104))
    T.title(im, ["THEY'RE", "INSIDE"], size=132)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    im.convert("RGB").save(OUT, quality=95)
    return OUT


if __name__ == "__main__":
    gen()
    p = build()
    print(f"  thumbnail -> {p}")
    print(f"  legibility: {T.contrast_report(p)}")
