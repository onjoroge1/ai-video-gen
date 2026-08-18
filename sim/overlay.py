"""Code-drawn overlay for simulation scenes: comparison chips, on-screen text, captions.

This replaces the HotD state rail. A simulation's persistent UI is not a faction board -- it is the
CONTROL PANEL of the experiment: which world this is, and the two variables that decide the outcome.
Keeping those on screen is what lets a viewer compare shot four against shot two without rewinding.

All drawn in code: free, deterministic, identical every render, and immune to the generator inventing
lettering (Kling and gpt-image both do, which is why every i2v prompt bans text).
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

import board_pipeline as BP

GOLD = (232, 205, 148)
WHITE = (242, 240, 236)
DIM = (150, 156, 166)
PANEL = (10, 12, 18, 214)


def _fit(d, text, font_fn, size, max_w):
    """Shrink until it fits: a chip that overflows its own pill is worse than a smaller chip."""
    while size > 14:
        f = font_fn(size)
        if d.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return font_fn(14)


def chips(ov, texts, W, H, y=None):
    """Two stacked pills, top-left: the world, and the variables that decide the outcome."""
    if not texts:
        return
    d = ImageDraw.Draw(ov)
    x, y = 54, y if y is not None else 132
    for i, t in enumerate(texts):
        big = i == 0
        size = 58 if big else 34
        f = _fit(d, t, lambda s: BP._F(BP._COPPER if big else BP._ARIAL_B, s), size, W - 160)
        tw = d.textlength(t, font=f)
        h = (f.size + 26)
        d.rounded_rectangle([x, y, x + tw + 46, y + h], radius=10,
                            fill=PANEL, outline=GOLD if big else (70, 76, 88), width=2)
        d.text((x + 23, y + 12), t, font=f, fill=GOLD if big else WHITE)
        y += h + 12


def onscreen(ov, text, W, H):
    """The spec's large burned-in beat text. Centred, with a scrim so it reads over any sky."""
    if not text:
        return
    d = ImageDraw.Draw(ov)
    words, lines, cur = text.split(), [], ""
    f = BP._F(BP._COPPER, 92)
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) > W - 150 and cur:
            lines.append(cur); cur = w
        else:
            cur = t
    lines.append(cur)
    while any(d.textlength(l, font=f) > W - 150 for l in lines) and f.size > 40:
        f = BP._F(BP._COPPER, f.size - 6)
    lh = f.size + 18
    top = int(H * 0.40) - lh * len(lines) // 2
    sc = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sc)
    sd.rounded_rectangle([40, top - 40, W - 40, top + lh * len(lines) + 28], radius=22,
                         fill=(4, 5, 9, 168))
    ov.alpha_composite(sc.filter(ImageFilter.GaussianBlur(18)))
    d = ImageDraw.Draw(ov)
    for i, l in enumerate(lines):
        tw = d.textlength(l, font=f)
        d.text(((W - tw) / 2, top + i * lh), l, font=f, fill=WHITE)


def caption(ov, text, W, H):
    """Burned-in narration caption, lower third. Shorts are watched muted."""
    if not text:
        return
    d = ImageDraw.Draw(ov)
    f = BP._F(BP._ARIAL_B, 46)
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) > W - 130 and cur:
            lines.append(cur); cur = w
        else:
            cur = t
    lines.append(cur)
    lines = lines[:3]
    lh = 60
    # 0.78, not 0.855: the Shorts progress bar and title sit in the bottom ~15%, and the landing
    # action in a fall video is by definition at the bottom of frame. The box also hugs the text
    # now instead of running wall to wall -- a full-width slab was blanketing feet and impact zones.
    bottom = int(H * 0.78)
    top = bottom - lh * len(lines)
    widest = max(d.textlength(l, font=f) for l in lines)
    x0 = max(44, int((W - widest) / 2) - 34)
    sc = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sc).rounded_rectangle([x0, top - 26, W - x0, bottom + 20], radius=18,
                                         fill=(4, 5, 9, 186))
    ov.alpha_composite(sc.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(ov)
    for i, l in enumerate(lines):
        tw = d.textlength(l, font=f)
        d.text(((W - tw) / 2, top + i * lh), l, font=f, fill=WHITE)


def build(scene, W, H, out, with_caption=True):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    chips(ov, scene.chips, W, H)
    onscreen(ov, scene.onscreen, W, H)
    if with_caption:
        caption(ov, scene.narration, W, H)
    ov.save(out)
    return out
