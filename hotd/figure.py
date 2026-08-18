"""Place a supplied character portrait in a shot, as a framed dossier panel.

WHY A PANEL AND NOT A CUT-OUT
Keying these portraits off their studio sweep does not work, and this was established by measurement
rather than taste. The sweep is radial, so a flat threshold leaves a grey halo; a per-row estimate
reads the dark corners and keeps the bright centre; a fitted quadratic surface gets most of it but
leaves ragged patches where the sweep brightens behind a head. Sweeping the threshold showed the real
problem: at tol 22 Addam of Hull keeps a grey arch, and by tol 34 his blue-grey robe starts
perforating, because his robe IS the backdrop's tone. Subject and background overlap in colour, so no
single threshold exists. Aemond survives any threshold only because black is far from grey.

A framed panel sidesteps the matte entirely: the portrait is presented as a portrait. It reads as
deliberate design rather than a failed key, it is identical in quality for all twenty images and for
any future ones, and it cannot silently eat a costume.

If portraits are ever supplied WITH alpha, `hotd.portrait.cut` becomes usable and the figure can stand
in the scene properly. That is the upgrade path, and it needs no change here.
"""
from __future__ import annotations
import os

from PIL import Image, ImageDraw, ImageFilter

import board_pipeline as bp

W, H = 1920, 1080
GOLD = (214, 176, 96)


def _cover(path, w, h):
    im = Image.open(path).convert("RGB")
    s = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * s + 0.5), int(im.height * s + 0.5)), Image.LANCZOS)
    return im.crop(((im.width - w) // 2, (im.height - h) // 2,
                    (im.width - w) // 2 + w, (im.height - h) // 2 + h))


def panel(portrait_path, box, radius=18, border=GOLD, anchor="top"):
    """The subject inside a rounded panel with a hairline border and a soft drop shadow.

    `anchor` decides the vertical crop. People are cropped from the TOP, because the face is what
    identifies them and these are full-body sources. Dragons are cropped CENTRE: they are landscape
    subjects in a square frame, and a top crop cuts the body off below the neck.
    """
    x0, y0, x1, y1 = box
    pw, ph = x1 - x0, y1 - y0
    src = Image.open(portrait_path).convert("RGB")
    s = max(pw / src.width, ph / src.height)
    src = src.resize((int(src.width * s + 0.5), int(src.height * s + 0.5)), Image.LANCZOS)
    left = (src.width - pw) // 2
    top = 0 if anchor == "top" else max(0, (src.height - ph) // 2)
    src = src.crop((left, top, left + pw, top + ph))

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, pw - 1, ph - 1], radius=radius, fill=255)

    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([x0 + 12, y0 + 18, x1 + 14, y1 + 20],
                                         radius=radius, fill=(0, 0, 0, 165))
    layer.alpha_composite(sh.filter(ImageFilter.GaussianBlur(22)))
    layer.paste(src.convert("RGBA"), (x0, y0), mask)
    ImageDraw.Draw(layer).rounded_rectangle([x0, y0, x1, y1], radius=radius,
                                            outline=border, width=2)
    return layer


def name_plate(im, cx, y, name, role, status, tone=(196, 74, 66), scale=1.0):
    d = ImageDraw.Draw(im)
    s = lambda n: max(13, int(n * scale))
    f1, f2, f3 = bp._F(bp._COPPER, s(56)), bp._F(bp._ARIAL, s(26)), bp._F(bp._ARIAL_B, s(25))
    if scale != 1.0:
        return _name_plate_scaled(d, cx, y, name, role, status, tone, f1, f2, f3, scale)
    tw = d.textlength(name.upper(), font=f1)
    d.text((cx - tw / 2, y), name.upper(), font=f1, fill=(240, 232, 216))
    tw = d.textlength(role, font=f2)
    d.text((cx - tw / 2, y + 68), role, font=f2, fill=(186, 192, 200))
    sw = d.textlength(status.upper(), font=f3)
    d.rounded_rectangle([cx - sw / 2 - 20, y + 108, cx + sw / 2 + 20, y + 150],
                        radius=8, fill=(10, 12, 18, 232), outline=tone, width=2)
    d.text((cx - sw / 2, y + 116), status.upper(), font=f3, fill=tone)
    return im


_TITLES = {"ser", "grand", "maester", "lord", "lady", "prince", "princess", "king", "queen"}


def short_name(name):
    """The name a viewer needs under a narrow panel: no truncation, no title.

    Truncating produced "ALICENT HIGHTO…" and "HELAENA TARGA…" side by side, which reads as a layout
    bug. A given name identifies these characters unambiguously; where the first word is a title, the
    surname does ("Ser Luthor Largent" -> LARGENT, "Grand Maester Orwyle" -> ORWYLE).
    """
    parts = [p for p in name.replace("'s", "").split() if p]
    if not parts:
        return name
    return parts[-1] if parts[0].lower() in _TITLES else parts[0]


def _name_plate_scaled(d, cx, y, name, role, status, tone, f1, f2, f3, scale):
    """The plate at a smaller size, for an ensemble where each panel is narrower.

    Line positions come from the FONTS, not from scaled pixel constants. Scaling the constants put the
    role text underneath the status pill at three panels wide, because the type shrank faster than the
    offsets did.
    """
    def line_h(f, pad):
        return int(f.size * pad)
    nm = short_name(name).upper()
    tw = d.textlength(nm, font=f1)
    d.text((cx - tw / 2, y), nm, font=f1, fill=(240, 232, 216))
    ry = y + line_h(f1, 1.32)
    rl, lim = role, int(430 * scale) + 70
    while len(rl) > 6 and d.textlength(rl, font=f2) > lim:
        rl = rl.rsplit(" ", 1)[0]
    tw = d.textlength(rl, font=f2)
    d.text((cx - tw / 2, ry), rl, font=f2, fill=(186, 192, 200))
    sy = ry + line_h(f2, 1.75)
    stt = status.upper()
    while len(stt) > 6 and d.textlength(stt, font=f3) > lim:
        stt = stt.rsplit(" ", 1)[0]
    sw = d.textlength(stt, font=f3)
    pad, h = max(10, int(20 * scale)), int(f3.size * 1.7)
    d.rounded_rectangle([cx - sw / 2 - pad, sy, cx + sw / 2 + pad, sy + h],
                        radius=8, fill=(10, 12, 18, 232), outline=tone, width=2)
    d.text((cx - sw / 2, sy + int(h * 0.22)), stt, font=f3, fill=tone)


# Three narrow panels need a taller crop than two wide ones, or the row floats in the upper half of
# the picture area with the plate empty beneath it.
ENSEMBLE_ASPECT = {1: 0.85, 2: 0.85, 3: 0.62}


def ensemble_boxes(n, x0=920, x1=1816, top=262, gap=24):
    """Boxes for n side-by-side portraits inside the picture area right of the rail.

    Every panel is identical in size: an ensemble exists to say "these people are being discussed
    together", and a dominant panel would contradict that.
    """
    span = x1 - x0
    w = (span - gap * (n - 1)) // n
    h = int(w / ENSEMBLE_ASPECT.get(n, 0.85))
    return [(x0 + i * (w + gap), top, x0 + i * (w + gap) + w, top + h) for i in range(n)]


def build_overlay_ensemble(out, rail_png, people, caption=None, canon=None):
    """Two or three portraits sharing the frame, each with its own name plate and status pill.

    Reached when the narration discusses several people in the same breath. Choosing one of them would
    be wrong about the others, and the measurement that motivated this found 21 such moments in a
    single episode.
    """
    n = min(len(people), 3)
    boxes = ensemble_boxes(n)
    scale = (boxes[0][2] - boxes[0][0]) / float(PORTRAIT_BOX[2] - PORTRAIT_BOX[0])
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for fg, box in zip(people[:n], boxes):
        # a dragon is a landscape subject: a top crop cuts it off below the neck
        ov.alpha_composite(panel(fg["portrait"], box,
                                 anchor=ANCHORS.get(fg.get("shape", "tall"), "top")))
    for fg, box in zip(people[:n], boxes):
        name_plate(ov, (box[0] + box[2]) // 2, box[3] + 20,
                   fg["name"], fg["role"], fg["status"],
                   tone=fg.get("tone", (196, 74, 66)), scale=scale)
    if rail_png:
        ov.alpha_composite(Image.open(rail_png).convert("RGBA"))
    if caption:
        caption_block(ov, PIC_X0, 84, caption, canon or "", content_right=PIC_X1)
    ov.save(out)
    return out


def caption_block(im, x, y, caption, canon, content_right=W):
    """Caption and canon chip, wrapped to the picture area right of a left-hand rail."""
    d = ImageDraw.Draw(im)
    f = bp._F(bp._COPPER, 50)
    lines, cur = [], ""
    for word in caption.split():
        t = (cur + " " + word).strip()
        if d.textlength(t, font=f) > (content_right - x - 60) and cur:
            lines.append(cur); cur = word
        else:
            cur = t
    lines.append(cur)
    d.rectangle([x - 26, y, x - 22, y + 62 * len(lines)], fill=GOLD)
    for i, ln in enumerate(lines):
        d.text((x, y + 62 * i), ln, font=f, fill=(240, 232, 216))
    cy = y + 62 * len(lines) + 16
    cf = bp._F(bp._ARIAL, 19)
    cw = d.textlength(canon, font=cf)
    d.rounded_rectangle([x, cy, x + cw + 34, cy + 34], radius=6,
                        fill=(10, 12, 18, 225), outline=GOLD, width=1)
    d.text((x + 17, cy + 8), canon, font=cf, fill=GOLD)
    return im


# The picture area sits right of the 860px left rail. The caption runs ACROSS the top of that area,
# not in the gutter beside the panel: boxed into the gutter it wrapped to four lines.
PIC_X0, PIC_X1 = 900, 1836
PORTRAIT_BOX = (1096, 250, 1640, 890)        # tall: a standing figure
CREATURE_BOX = (952, 300, 1788, 796)         # wide: a dragon is a landscape subject
BOXES = {"tall": PORTRAIT_BOX, "wide": CREATURE_BOX}
ANCHORS = {"tall": "top", "wide": "center"}


def build_bg(plate_path, out, dim=0.34):
    """Location plate, darkened so the panel and the rail both read over it."""
    bgw, bgh = int(W * 1.15), int(H * 1.15)
    im = _cover(plate_path, bgw, bgh)
    im = Image.blend(im, Image.new("RGB", (bgw, bgh), (6, 7, 11)), dim)
    im.save(out)
    return out


def build_overlay(out, rail_png, portrait_path, name, role, status,
                  caption=None, canon=None, shape="tall", box=None, tone=(196, 74, 66)):
    box = box or BOXES.get(shape, PORTRAIT_BOX)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov.alpha_composite(panel(portrait_path, box, anchor=ANCHORS.get(shape, "top")))
    name_plate(ov, (box[0] + box[2]) // 2, box[3] + 26, name, role, status, tone=tone)
    if rail_png:
        ov.alpha_composite(Image.open(rail_png).convert("RGBA"))
    if caption:
        caption_block(ov, PIC_X0, 84, caption, canon or "", content_right=PIC_X1)
    ov.save(out)
    return out
