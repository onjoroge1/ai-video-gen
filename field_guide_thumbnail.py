"""The Can't Undo Field Guide thumbnail overlay: a two-line headline and a "YOU" arrow.

Operator, 2026-11-05. The agreed grammar, after a cream specimen-card version was rejected as not
striking enough: ONE giant animal in the film's own painted style, a tiny person the viewer reads
as themselves (marked "YOU" with a curved arrow), and a two-word headline about what can't be
undone ("WRONG OCEAN"), white over orange, in calm space the picture leaves for it. It borrows
Depth Theory's scale-and-you idea, not their black-and-white etching look.

The picture is drawn by the image model (or taken from the film); the words and the arrow are
drawn here so they never garble and stay identical from film to film. No provider is called.
"""
from __future__ import annotations

import math
import os
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 720
WHITE = (255, 255, 255)
ORANGE = (255, 138, 40)
STROKE = (12, 14, 20)
HEADLINE_MAX_CHARS = 14          # per line: two short words stay huge at feed size

_SUP = "/System/Library/Fonts/Supplemental/"
_FONTS = (_SUP + "Arial Black.ttf", _SUP + "Impact.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def _font(size: int):
    for path in _FONTS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def headline_lines(text: str) -> list[str]:
    """Two words (or two short phrases split on '/'), one per line: WRONG / OCEAN."""
    clean = re.sub(r"\s+", " ", (text or "").strip().upper())
    parts = [p.strip() for p in clean.split("/")] if "/" in clean else clean.split(" ")
    if len(parts) != 2 or not all(parts) or any(len(p) > HEADLINE_MAX_CHARS for p in parts) \
            or any(c in clean for c in ':?"\n'):
        raise ValueError(f"headline must be two words or 'A / B', each <= {HEADLINE_MAX_CHARS} chars: {text!r}")
    return parts


def _cover(img: Image.Image, focus_y: float) -> Image.Image:
    """Scale to cover 1280x720; keep full width, crop vertically around focus_y (0-1)."""
    scale = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left = (img.width - W) // 2
    top = min(max(round(focus_y * img.height - H / 2), 0), img.height - H)
    return img.crop((left, top, left + W, top + H))


def _text(base: Image.Image, xy, s: str, font, fill, stroke: int) -> None:
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((xy[0] + 6, xy[1] + 8), s, font=font, fill=(0, 0, 0, 170),
                                stroke_width=stroke, stroke_fill=(0, 0, 0, 170))
    base.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(7)))
    ImageDraw.Draw(base).text(xy, s, font=font, fill=fill, stroke_width=stroke, stroke_fill=STROKE)


def _arrow(base: Image.Image, p0, p2) -> None:
    """A white curved arrow with a dark outline from p0 (by the label) to p2 (the person)."""
    d = ImageDraw.Draw(base)
    p1 = (p0[0] + 0.45 * (p2[0] - p0[0]) + 40, p0[1])
    pts = [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
            (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])
           for t in (i / 40 for i in range(41))]
    d.line(pts, fill=STROKE, width=13, joint="curve")
    d.line(pts, fill=WHITE, width=6, joint="curve")
    ang = math.atan2(p2[1] - pts[-4][1], p2[0] - pts[-4][0])
    for colour, extra in ((STROKE, 8), (WHITE, 0)):
        length = 24 + extra
        d.polygon([p2,
                   (p2[0] - length * math.cos(ang - 0.5), p2[1] - length * math.sin(ang - 0.5)),
                   (p2[0] - length * math.cos(ang + 0.5), p2[1] - length * math.sin(ang + 0.5))],
                  fill=colour)


def compose(picture: str, out_path: str, *, headline: str, you_at: tuple[float, float] | None,
            side: str = "left", focus_y: float = 0.5) -> str:
    """Overlay the headline (top-left or top-right) and, when you_at is given, a "YOU" arrow.

    you_at is the person's position as 0-1 fractions of the 1280x720 output; the label sits
    below-left of them and the arrow curves up to them.
    """
    top, bottom = headline_lines(headline)
    base = _cover(Image.open(picture).convert("RGB"), focus_y).convert("RGBA")
    size = 128
    font = _font(size)
    draw = ImageDraw.Draw(base)
    while max(draw.textbbox((0, 0), s, font=font, stroke_width=10)[2] for s in (top, bottom)) > 640 \
            and size > 72:
        size -= 6
        font = _font(size)
    gap = round(size * 1.14)
    for i, (line, colour) in enumerate(((top, WHITE), (bottom, ORANGE))):
        width = draw.textbbox((0, 0), line, font=font, stroke_width=10)[2]
        x = 40 if side == "left" else W - 40 - width
        _text(base, (x, 22 + i * gap), line, font, colour, stroke=10)
    if you_at is not None:
        px, py = you_at[0] * W, you_at[1] * H
        label_font = _font(46)
        lx, ly = max(px - 150, 16), min(py + 95, H - 70)
        _text(base, (lx, ly), "YOU", label_font, WHITE, stroke=6)
        _arrow(base, (lx + 120, ly + 22), (px + 4, py + 26))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    base.convert("RGB").save(out_path, quality=93)
    return out_path
