"""Shared card and diagram primitives.

The card template, faction palette, tone vocabulary, sigil glyphs and the diagram helpers
(_plate/_bar/_chain/_map_canvas/_pin/_legend) live in hotd_assets.py, which is a genuine shared
library rather than a duplicate. This module is the package-facing surface: it re-exports those
primitives and adds the multi-pack helpers, so episode modules import from `hotd.assets` and never
reach into the legacy module directly.
"""
from __future__ import annotations
import os

import hotd_assets as _HA

# card + palette
character_card = _HA.character_card
FACTION = _HA.FACTION
TONE = _HA.TONE
SIGILS = _HA.SIGILS
W, H = _HA.W, _HA.H

# diagram helpers
plate = _HA._plate
bar = _HA._bar
chain = _HA._chain
map_canvas = _HA._map_canvas
pin = _HA._pin
legend = _HA._legend
MAP_PTS = _HA.MAP_PTS


def register_pack(pack_images_dir):
    """Let cards resolve emblems from this pack in addition to any already registered."""
    _HA.register_sigil_dir(os.path.join(pack_images_dir, "generated", "sigils"))


def find_sigil(pack_images_dir, name):
    register_pack(pack_images_dir)
    p = _HA.find_sigil(name)
    if not p:
        raise FileNotFoundError(f"no emblem sig_{name}.png in any registered pack")
    return p


def wrap(text, n):
    """Word wrap for narrow diagram columns; hotd_assets has no wrap helper."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if len(t) > n and cur:
            lines.append(cur); cur = w
        else:
            cur = t
    lines.append(cur)
    return lines


def build_cards(rows, outdir, kind="character"):
    """rows: (name, faction, role, status, tone, sigil, stem, note). Every card is code-drawn and
    free, so an episode restates every returning character's status rather than reusing a card that
    says something that was true last episode."""
    os.makedirs(outdir, exist_ok=True)
    made = []
    for r in rows:
        name, fac, role, status, tone, sig, stem, note = r
        character_card(name, fac, role, status, tone, sig, os.path.join(outdir, f"{stem}.png"), note)
        made.append(stem)
    return made


def build_dragon_cards(rows, outdir):
    """rows: (name, faction, role, status, tone, stem). Falls back to the house sigil when a dragon
    emblem has not been generated."""
    os.makedirs(outdir, exist_ok=True)
    made = []
    for name, fac, role, status, tone, stem in rows:
        sig = f"dragon_{name.lower()}" if _HA.find_sigil(f"dragon_{name.lower()}") else "targaryen"
        character_card(name, fac, role, status, tone, sig,
                       os.path.join(outdir, f"{stem}.png"), "DRAGON")
        made.append(stem)
    return made


def build_diagrams(diagrams, outdir):
    """diagrams: [(stem, fn)] where fn(out_path) draws it. A diagram that raises is collected, not
    swallowed -- a silently missing diagram surfaced much later as a blank shot."""
    os.makedirs(outdir, exist_ok=True)
    made, failed = [], []
    for stem, fn in diagrams:
        try:
            fn(os.path.join(outdir, f"{stem}.png"))
            made.append(stem)
        except Exception as e:
            failed.append((stem, f"{type(e).__name__}: {e}"))
    if failed:
        raise RuntimeError("diagram(s) failed to draw: " +
                           "; ".join(f"{s}: {e}" for s, e in failed))
    return made


def overflow_check(outdir, stems, canvas=(W, H)):
    """Assert every diagram fits its canvas. Layout was previously verified only by eye."""
    from PIL import Image
    bad = []
    for s in stems:
        p = os.path.join(outdir, f"{s}.png")
        if not os.path.exists(p):
            bad.append((s, "missing")); continue
        im = Image.open(p)
        if im.size != tuple(canvas):
            bad.append((s, f"{im.size} != {canvas}"))
    if bad:
        raise RuntimeError(f"diagram canvas problems: {bad}")
    return True
