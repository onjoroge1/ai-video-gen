"""Spec-§4 thumbnail for the HotD S3E3 explainer.

Spec asks for exactly three dominant elements -- (1) Rhaenyra uneasy on the Iron Throne,
(2) an empty gold chest in the foreground, (3) Ormund and the false Daeron as a *small*
secondary threat -- and warns that adding more destroys the hierarchy.

IP-safe reading of element 1: a single small DISTANT SILHOUETTE on the throne. No face, no
likeness, original artwork. Element 3 becomes two small heraldic marks (the Hightower beacon
and the cracked decoy mask) rather than character art.

Title-thumbnail contract: "She possesses the throne but not the machinery of government."

Run: /opt/homebrew/bin/python3 hotd_thumbnail.py
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

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

import board_pipeline as bp
import explainer_pipeline as ep

PACK = "house-of-dragons/house_of_the_dragon_s3e3_complete_asset_pack/images"
EL = f"{PACK}/generated/thumb_elements"
OUT = f"{PACK}/thumbnail/08_thumbnail_she_won_now_what.png"
TW, TH = 1280, 720

ELEMENTS = {
    "throne_lone_figure": (
        "Cinematic matte-painting illustration, painterly, muted desaturated palette. A vast "
        "dark stone throne hall. An immense jagged throne of blackened welded blades stands on "
        "a raised dais, lit from one high window. A single small distant figure sits on it, "
        "seen from far away in full silhouette, no visible face, no discernible features, "
        "dwarfed by the empty hall. Dramatic hard shaft of cold light, deep shadow. No text, "
        "no logos, original artwork not resembling any film or television production."),
    "empty_chest": (
        "Cinematic still life, painterly, dramatic low torchlight on a pure black background. "
        "One heavy iron-bound wooden chest lying open and completely empty, lid thrown back, "
        "three or four gold coins spilled on dark flagstones beside it. Nothing else in frame. "
        "No people, no text, no logos."),
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


def _sigil(name, size, tint):
    p = f"{PACK}/generated/sigils/sig_{name}.png"
    em = Image.open(p).convert("RGB").resize((size, size), Image.LANCZOS)
    mask = em.convert("L").point(lambda v: min(255, int(v * 1.3)))
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(Image.new("RGB", (size, size), tint), (0, 0), mask)
    return out


def build():
    im = _cover(f"{EL}/throne_lone_figure.png", TW, TH).convert("RGBA")

    # ELEMENT 2 -- the empty chest, foreground bottom-RIGHT (bottom-left belongs to the title).
    # A luminance key destroys it: the wood sits at L~40-70, barely above the black background,
    # so keying leaves it near-transparent. Both plates are near-black at the bottom, so a
    # feathered rectangular blend merges them invisibly instead.
    cw = 620
    ch = Image.open(f"{EL}/empty_chest.png").convert("RGB")
    ch = ch.resize((cw, int(cw * ch.height / ch.width)), Image.LANCZOS)
    ch = ImageEnhance.Brightness(ch).enhance(1.18)
    fe = 86
    mask = Image.new("L", ch.size, 0)
    ImageDraw.Draw(mask).rectangle([fe, fe, ch.width - fe, ch.height - fe], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(fe / 2.2))
    layer = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    layer.paste(ch.convert("RGBA"), (TW - cw + 40, TH - ch.height + 60), mask)
    im = Image.alpha_composite(im, layer)

    # darken the right third so the small threat marks and the title read
    sc = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sc)
    for y in range(TH):
        sd.line([(0, y), (TW, y)], fill=(3, 4, 7, int(150 * min(1.0, max(0, y - 300) / 260))))
    im = Image.alpha_composite(im, sc)

    d = ImageDraw.Draw(im)

    # ELEMENT 3 -- the secondary threat, deliberately small: beacon + cracked decoy mask
    im.alpha_composite(_sigil("hightower", 108, (214, 176, 96)), (TW - 250, 44))
    im.alpha_composite(_sigil("decoy", 108, (196, 74, 66)), (TW - 128, 44))
    d.text((TW - 250, 160), "ORMUND  ·  THE DECOY", font=bp._F(bp._ARIAL, 19), fill=(198, 184, 160))

    # title
    f1 = bp._F(bp._COPPER, 104)
    f2 = bp._F(bp._COPPER, 118)
    for dx, dy in ((4, 5), (-3, 4), (3, -3)):
        d.text((62 + dx, TH - 268 + dy), "SHE WON…", font=f1, fill=(0, 0, 0, 210))
        d.text((62 + dx, TH - 156 + dy), "NOW WHAT?", font=f2, fill=(0, 0, 0, 220))
    d.text((62, TH - 268), "SHE WON…", font=f1, fill=(236, 228, 212))
    d.text((62, TH - 156), "NOW WHAT?", font=f2, fill=(226, 186, 96))
    d.rectangle([62, TH - 292, 250, TH - 286], fill=(226, 186, 96))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    im.convert("RGB").save(OUT, quality=95)
    print(f"  thumbnail -> {OUT}  {im.size}")
    return OUT


if __name__ == "__main__":
    gen()
    build()
