"""The square-cube law, drawn rather than asserted.

The review's hardest structural criticism was that the payoff line -- mass grows faster than area --
was spoken over footage of an animal walking, so the one claim the whole video rests on was the only
claim with no picture. This is the picture: two cubes, one twice the size, with the face count and
the volume count made literal. Code-drawn, deterministic, free, and it cannot grow a goat.
"""
from __future__ import annotations
from PIL import Image, ImageDraw, ImageFont

W, H = 1024, 1536
BG = (16, 19, 24)
INK = (226, 230, 236)
DIM = (140, 146, 156)
TEAL = (64, 190, 180)
COPPER = (214, 160, 96)


def _font(size, bold=True):
    for name in (["/System/Library/Fonts/Supplemental/Arial Bold.ttf"] if bold else
                 ["/System/Library/Fonts/Supplemental/Arial.ttf"]):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _cube(d, x, y, s, col, fill_alpha=26):
    """Isometric-ish cube, side s, front face at (x, y)."""
    o = int(s * 0.42)                     # depth offset
    front = [(x, y), (x + s, y), (x + s, y + s), (x, y + s)]
    top = [(x, y), (x + o, y - o), (x + s + o, y - o), (x + s, y)]
    side = [(x + s, y), (x + s + o, y - o), (x + s + o, y + s - o), (x + s, y + s)]
    for face, shade in ((top, 40), (side, 20), (front, fill_alpha)):
        d.polygon(face, fill=(col[0], col[1], col[2], shade), outline=col, width=4)


def build(out_png):
    im = Image.new("RGB", (W, H), BG)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)

    d.text((W // 2, 130), "DOUBLE THE SIZE", font=_font(64), fill=INK, anchor="mm")

    # small cube
    s1, x1, y1 = 190, 150, 560
    _cube(d, x1, y1, s1, TEAL)
    d.text((x1 + s1 // 2, y1 + s1 + 58), "L", font=_font(48), fill=TEAL, anchor="mm")

    # big cube, side 2L
    s2, x2, y2 = 380, 490, 430
    _cube(d, x2, y2, s2, COPPER)
    d.text((x2 + s2 // 2, y2 + s2 + 58), "2L", font=_font(48), fill=COPPER, anchor="mm")

    rows = [
        ("SURFACE AREA", "x 4", TEAL, "drag holds you back"),
        ("MASS", "x 8", COPPER, "gravity pulls you down"),
    ]
    y = 1130
    for label, mult, col, note in rows:
        d.text((150, y), label, font=_font(40), fill=DIM, anchor="lm")
        d.text((620, y), mult, font=_font(76), fill=col, anchor="lm")
        d.text((150, y + 62), note, font=_font(31, bold=False), fill=DIM, anchor="lm")
        y += 170

    d.line([(150, 1105), (W - 150, 1105)], fill=(60, 66, 74), width=3)
    d.text((W // 2, 1475), "mass outruns area: bigger falls harder",
           font=_font(38), fill=INK, anchor="mm")

    im = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
    im.save(out_png)
    return out_png


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    print(build(os.path.join(here, "images", "15_sqcube.png")))
