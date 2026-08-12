"""HotD S3E3 asset generator — heraldic character cards + infographics, code-drawn.

Why code-drawn and heraldic (not portraits):
  * These are characters from a copyrighted show played by identifiable actors. The S3E2 video was
    deliberately IP-safe and we keep that posture. The spec's own consistency rules agree:
    "Prefer original stylized visuals and diagrams over continuous episode footage" and
    "Use one portrait-card template for every character."
  * A politics-explainer cares about FACTION / ROLE / STATUS, not a face. A heraldic card carries more
    information per frame than a portrait would.
  * Code-drawn means $0, pixel-consistent across all cards, and instantly re-renderable when a status
    changes (e.g. Tyland must read "presumed dead by the court", never "dead").

Palette + glyph helpers are imported from board_pipeline so these cards match the state-board look.
Run: /opt/homebrew/bin/python3 hotd_assets.py
"""
from __future__ import annotations
import os

from PIL import Image, ImageDraw, ImageFilter

import board_pipeline as BP

W, H = 1920, 1080
OUT = "house-of-dragons/house_of_the_dragon_s3e3_complete_asset_pack/images/generated"
SIG_GEN = f"{OUT}/sigils"   # generated heraldic emblems (gold on black); see hotd_gen_assets.py
# Later episodes add their own emblems in their own pack. Cards resolve a sigil against every
# registered directory, so an episode reuses earlier heraldry and only generates what is new.
SIG_DIRS = [SIG_GEN]


def register_sigil_dir(path):
    if path not in SIG_DIRS:
        SIG_DIRS.insert(0, path)


def find_sigil(name):
    for d in SIG_DIRS:
        p = os.path.join(d, f"sig_{name}.png")
        if os.path.exists(p):
            return p
    return None

# Faction palettes — spec §9: "black/red-gold accents for Team Black and muted green-gold for
# Hightower forces". Neutral factions get steel so they read as unaligned.
CRIMSON = (168, 46, 46)
FACTION = {
    "black":   {"label": "TEAM BLACK",    "accent": BP.GOLD,  "edge": CRIMSON,       "bg": (10, 9, 12)},
    "green":   {"label": "TEAM GREEN",    "accent": (176, 168, 104), "edge": (86, 104, 74), "bg": (11, 14, 11)},
    "faith":   {"label": "THE FAITH",     "accent": (226, 214, 178), "edge": (150, 140, 110), "bg": (13, 13, 15)},
    "neutral": {"label": "UNALIGNED",     "accent": BP.STEEL, "edge": (90, 104, 120), "bg": (10, 12, 15)},
}
TONE = {"key": BP.GOLD, "bad": BP.RED, "good": BP.GREEN, "neutral": BP.STEEL, "dead": BP.RED}
# All faction plates are near-black (10,9,12 .. 13,13,15), so one dark value works for "cut back to
# background" details inside a sigil (e.g. a dragon's jaw gap) without threading the bg through.
FACTION_BG_HINT = (11, 12, 13)


# ---------------------------------------------------------------------------------------------------
# sigil glyphs — abstract heraldry, no likenesses
def sig_targaryen(d, cx, cy, s, col):
    """Three-headed dragon as a HERALDIC DEVICE: three necks fanning from one base, each ending in a
    wedge head with an open jaw. Overlaying three side-profile dragons read as abstract clutter; a
    symmetrical fan reads instantly as 'three heads' and is also further from any screen likeness."""
    import math
    base = (cx, cy + s * 0.86)
    for ang, ln in ((-58, 0.96), (-90, 1.12), (-122, 0.96)):
        a = math.radians(ang)
        hx, hy = cx + math.cos(a) * s * ln, base[1] + math.sin(a) * s * ln
        # neck: tapered wedge from base to head
        nx, ny = math.cos(a + math.pi / 2), math.sin(a + math.pi / 2)
        d.polygon([(base[0] + nx * s * 0.15, base[1] + ny * s * 0.15),
                   (base[0] - nx * s * 0.15, base[1] - ny * s * 0.15),
                   (hx - nx * s * 0.07, hy - ny * s * 0.07),
                   (hx + nx * s * 0.07, hy + ny * s * 0.07)], fill=col)
        # head: snout wedge + open jaw
        fx, fy = math.cos(a), math.sin(a)
        tipx, tipy = hx + fx * s * 0.34, hy + fy * s * 0.34
        d.polygon([(hx + nx * s * 0.16, hy + ny * s * 0.16),
                   (hx - nx * s * 0.16, hy - ny * s * 0.16),
                   (tipx, tipy)], fill=col)
        d.line([(hx - nx * s * 0.13, hy - ny * s * 0.13), (tipx - fx * s * 0.02, tipy - fy * s * 0.02)],
               fill=FACTION_BG_HINT, width=max(2, int(s * 0.045)))          # jaw gap
    # wings implied by two swept arcs behind the necks
    d.arc([cx - s * 1.30, cy - s * 0.30, cx + s * 0.02, cy + s * 1.02], 200, 330, fill=col, width=max(2, int(s * 0.05)))
    d.arc([cx - s * 0.02, cy - s * 0.30, cx + s * 1.30, cy + s * 1.02], 210, 340, fill=col, width=max(2, int(s * 0.05)))
    d.ellipse([base[0] - s * 0.13, base[1] - s * 0.13, base[0] + s * 0.13, base[1] + s * 0.13], fill=col)


def sig_hightower(d, cx, cy, s, col):
    """Stepped tower with a beacon flame."""
    w = s * 0.44
    for i, (hh, ww) in enumerate(((1.05, 1.0), (0.72, 0.82), (0.42, 0.66))):
        d.rectangle([cx - w * ww, cy + s * 0.55 - s * hh, cx + w * ww, cy + s * 0.60 - s * hh + s * 0.34],
                    outline=col, width=4)
    d.polygon([(cx, cy - s * 0.92), (cx + s * 0.20, cy - s * 0.52),
               (cx, cy - s * 0.62), (cx - s * 0.20, cy - s * 0.52)], fill=col)


def sig_velaryon(d, cx, cy, s, col):
    """Seahorse, reduced to a spiral-tailed arc."""
    d.arc([cx - s * 0.55, cy - s * 0.95, cx + s * 0.55, cy + s * 0.25], 200, 20, fill=col, width=5)
    d.arc([cx - s * 0.42, cy - s * 0.15, cx + s * 0.30, cy + s * 0.85], 250, 130, fill=col, width=5)
    d.arc([cx - s * 0.12, cy + s * 0.35, cx + s * 0.34, cy + s * 0.92], 200, 60, fill=col, width=4)
    d.ellipse([cx + s * 0.26, cy - s * 0.86, cx + s * 0.44, cy - s * 0.68], fill=col)


def sig_seven(d, cx, cy, s, col):
    """Seven-pointed star of the Faith."""
    import math
    r_out, r_in = s * 0.92, s * 0.40
    pts = []
    for i in range(14):
        a = -math.pi / 2 + i * math.pi / 7
        r = r_out if i % 2 == 0 else r_in
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    d.polygon(pts, outline=col, width=4)


def sig_whisper(d, cx, cy, s, col):
    """Mistress of Whispers — a masked face reduced to a keyhole + three sound arcs."""
    d.ellipse([cx - s * 0.46, cy - s * 0.78, cx + s * 0.46, cy + s * 0.30], outline=col, width=4)
    d.polygon([(cx - s * 0.30, cy + s * 0.28), (cx + s * 0.30, cy + s * 0.28),
               (cx, cy + s * 0.86)], outline=col, width=4)
    for i, r in enumerate((0.42, 0.62, 0.82)):
        d.arc([cx + s * 0.50, cy - s * r, cx + s * (0.50 + r * 1.5), cy + s * r], -55, 55, fill=col, width=3)


def sig_decoy(d, cx, cy, s, col):
    """The false Daeron. Deliberately NOT a dragon — spec §9: never depict the decoy as the real
    prince. An empty mask with a broken outline reads 'impostor' at a glance."""
    d.ellipse([cx - s * 0.62, cy - s * 0.78, cx + s * 0.62, cy + s * 0.62], outline=col, width=4)
    for ex in (-0.26, 0.26):                                   # hollow eyes
        d.ellipse([cx + s * ex - s * 0.13, cy - s * 0.28, cx + s * ex + s * 0.13, cy - s * 0.04], fill=col)
    d.line([(cx - s * 0.86, cy + s * 0.86), (cx + s * 0.86, cy - s * 0.98)], fill=BP.RED, width=6)


def sig_generic(d, cx, cy, s, col):
    """Neutral mark for a house or figure with no drawn heraldry -- a plain lozenge and bar.

    Later episodes introduce characters whose emblems are generated files, not code. If the emblem
    is missing (still generating, or a commoner with no arms at all) the card must still render:
    a missing sigil is a cosmetic gap, not a reason to fail the whole asset build.
    """
    d.polygon([(cx, cy - s * 0.82), (cx + s * 0.58, cy), (cx, cy + s * 0.82), (cx - s * 0.58, cy)],
              outline=col, width=6)
    d.line([(cx - s * 0.30, cy), (cx + s * 0.30, cy)], fill=col, width=6)


SIGILS = {"targaryen": sig_targaryen, "hightower": sig_hightower, "velaryon": sig_velaryon,
          "seven": sig_seven, "whisper": sig_whisper, "decoy": sig_decoy,
          "generic": sig_generic}


# ---------------------------------------------------------------------------------------------------
def _bg(faction):
    """Vignetted parchment-dark plate with a faint faction wash."""
    f = FACTION[faction]
    im = Image.new("RGB", (W, H), f["bg"])
    d = ImageDraw.Draw(im, "RGBA")
    for i in range(0, H, 4):                                   # subtle horizontal weave
        d.line([(0, i), (W, i)], fill=(255, 255, 255, 4))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W * 0.18, -H * 0.35, W * 0.82, H * 1.05], fill=tuple(int(c * 0.30) for c in f["edge"]))
    glow = glow.filter(ImageFilter.GaussianBlur(190))
    return Image.blend(im, Image.blend(im, glow, 0.55), 0.85)


def character_card(name, faction, role, status, tone, sigil, out, note=""):
    """One card template for every character (spec §9)."""
    f = FACTION[faction]
    im = _bg(faction)
    d = ImageDraw.Draw(im, "RGBA")
    acc, edge = f["accent"], f["edge"]

    # frame + corner brackets
    d.rectangle([54, 54, W - 54, H - 54], outline=acc, width=3)
    for (cx, cy, sx, sy) in ((54, 54, 1, 1), (W - 54, 54, -1, 1), (54, H - 54, 1, -1), (W - 54, H - 54, -1, -1)):
        d.line([(cx, cy + 96 * sy), (cx, cy), (cx + 96 * sx, cy)], fill=edge, width=9)

    # faction ribbon
    fl = f["label"]
    fnt_f = BP._F(BP._COPPER, 30)
    fw = BP._tw(d, fl, fnt_f) + len(fl) * 6 + 64
    d.rectangle([54, 54, 54 + fw, 122], fill=(*edge, 220))
    BP._track(d, (86, 70), fl, fnt_f, BP.WHITE, tr=6)

    # sigil — prefer the GENERATED emblem (gold on pure black), tinted to the faction accent.
    # Keying is trivial because the source is an emblem on true black: luminance IS the coverage mask,
    # so no alpha extraction is needed (the trap that ate days on the Bolt work).
    gp = find_sigil(sigil)
    if gp:
        em = Image.open(gp).convert("RGB").resize((430, 430), Image.LANCZOS)
        mask = em.convert("L").point(lambda v: min(255, int(v * 1.25)))     # slight lift, keeps edges
        tint = Image.new("RGB", em.size, acc)
        im.paste(tint, (W // 2 - 215, 430 - 215), mask)
    else:
        SIGILS.get(sigil, sig_generic)(d, W // 2, 430, 200, acc)          # code-drawn fallback

    # name
    fnt_n = BP._F(BP._COPPER, 104)
    nm = name.upper()
    nw = BP._tw(d, nm, fnt_n) + len(nm) * 10
    BP._track(d, ((W - nw) // 2, 640), nm, fnt_n, BP.WHITE, tr=10)
    d.line([(W // 2 - nw // 2, 776), (W // 2 + nw // 2, 776)], fill=acc, width=2)

    # role
    fnt_r = BP._F(BP._GEO_B, 44)
    d.text(((W - BP._tw(d, role, fnt_r)) // 2, 806), role, font=fnt_r, fill=BP.MUTE)

    # status chip — the line the spec actually cares about
    fnt_s = BP._F(BP._ARIAL_B, 40)
    st = status.upper()
    sw = BP._tw(d, st, fnt_s) + len(st) * 3
    col = TONE[tone]
    x0 = (W - (sw + 76)) // 2
    d.rounded_rectangle([x0, 884, x0 + sw + 76, 960], radius=14, fill=(*BP.CHIP[:3], 240), outline=col, width=3)
    BP._track(d, (x0 + 38, 897), st, fnt_s, col, tr=3)

    if note:
        fnt_x = BP._F(BP._ARIAL, 26)
        d.text(((W - BP._tw(d, note, fnt_x)) // 2, 984), note, font=fnt_x, fill=(120, 126, 136))
    im.save(out)
    return out


# 11 of the spec's 18-asset minimum set. Status wording follows spec §9 exactly:
# "missing", "decoy", "unknown rider", "presumed dead by the court".
CHARACTERS = [
    ("Rhaenyra Targaryen", "black", "Queen on the Iron Throne", "crowned · not anointed", "key",
     "targaryen", "01_char_rhaenyra", "Holds the symbol of rule; the Faith withholds legitimacy"),
    ("Daemon Targaryen", "black", "Prince Consort · rides Caraxes", "argues rule through fear", "neutral",
     "targaryen", "02_char_daemon", "Ormund's false surrender answered with force"),
    ("Ormund Hightower", "green", "Lord of Oldtown", "false surrender", "bad",
     "hightower", "03_char_ormund", "Claimed retreat to Oldtown; struck Tumbleton instead"),
    ("Daeron Targaryen", "green", "The real prince · rides Tessarion", "at large with Ormund", "bad",
     "targaryen", "04_char_daeron_real", "Tessarion remains with Hightower forces"),
    ("The False Daeron", "green", "Captive impostor", "decoy · not the prince", "bad",
     "decoy", "05_char_daeron_false", "Exposed by Alicent; never the real prince"),
    ("Alicent Hightower", "green", "Prisoner · unwilling adviser", "captive · exposed the decoy", "neutral",
     "hightower", "06_char_alicent", "Surrender terms rewritten by Rhaenyra"),
    ("Corlys Velaryon", "black", "Lord of the Tides", "demands his sons acknowledged", "neutral",
     "velaryon", "07_char_corlys", "Legitimisation dispute over Addam and Alyn of Hull"),
    ("Mysaria", "black", "Mistress of Whispers", "reads the smallfolk", "good",
     "whisper", "08_char_mysaria", "Public opinion as an instrument of rule"),
    ("High Septon Balman", "faith", "Voice of the Faith", "withholds legitimacy", "bad",
     "seven", "09_char_high_septon", "Refuses to anoint while a rival king lives"),
    ("Aegon II Targaryen", "green", "Rival king", "missing", "bad",
     "targaryen", "10_char_aegon_ii_missing", "His survival blocks the Faith's recognition"),
    ("Aemond Targaryen", "green", "Military threat · Vhagar", "missing", "bad",
     "targaryen", "11_char_aemond_missing", "Vhagar unaccounted for from Rhaenyra's view"),
    # --- newly knighted dragonriders (Team Black) ---
    ("Addam of Hull", "black", "Knighted dragonrider · Seasmoke", "raised by Rhaenyra", "good",
     "velaryon", "19_char_addam_of_hull", "Corlys asks that he be acknowledged a Velaryon"),
    ("Alyn of Hull", "black", "Proposed Velaryon heir", "claim unresolved", "neutral",
     "velaryon", "20_char_alyn_of_hull", "The other son at the centre of Corlys's request"),
    ("Hugh Hammer", "black", "Knighted dragonrider · Vermithor", "makes household requests", "neutral",
     "targaryen", "21_char_hugh_hammer", "Elevated from smallfolk to sworn sword"),
    ("Ulf White", "black", "Knighted dragonrider · Silverwing", "newly elevated", "neutral",
     "targaryen", "22_char_ulf_white", "Elevated from smallfolk to sworn sword"),
    # --- supporting ---
    ("Helaena Targaryen", "green", "Prisoner with Alicent", "captive", "neutral",
     "targaryen", "23_char_helaena", "Held in the Red Keep alongside her mother"),
    ("Torrhen Manderly", "black", "Northern lord at council", "challenges the food plan", "neutral",
     "seven", "24_char_torrhen_manderly", "Questions whether seizing stores can hold"),
    ("Tyland Lannister", "green", "Master of coin · the treasury", "presumed dead by the court", "dead",
     "hightower", "25_char_tyland_lannister", "SPEC NOTE: later episodes reveal he survived the Gullet"),
    ("Rhaena Targaryen", "neutral", "Rides Sheepstealer", "unknown rider", "neutral",
     "targaryen", "26_char_rhaena", "Her claim is NOT known to Rhaenyra's government"),
    # --- memory / family context ---
    ("Viserys I Targaryen", "neutral", "The late king", "memory · governing ideal", "neutral",
     "targaryen", "27_char_viserys_memory", "Rhaenyra's model of rule by council and law"),
    ("Queen Aemma Arryn", "neutral", "Rhaenyra's mother", "memory", "neutral",
     "targaryen", "28_char_aemma_memory", "Invoked in Rhaenyra's grief"),
    ("Jacaerys Velaryon", "black", "Rhaenyra's heir", "killed at the Gullet", "dead",
     "velaryon", "29_char_jacaerys_memorial", "Grief and the parentage dispute"),
    ("Lucerys Velaryon", "black", "Rhaenyra's son", "killed before the war turned", "dead",
     "velaryon", "30_char_lucerys_memorial", "Family-loss context"),
    ("Joffrey Velaryon", "black", "Rhaenyra's son", "parentage disputed", "neutral",
     "velaryon", "31_char_joffrey", "At the centre of the legitimacy question"),
    ("Laenor Velaryon", "black", "Legal father of Rhaenyra's sons", "memory", "neutral",
     "velaryon", "32_char_laenor", "Accepted the boys as his own"),
    ("Princess Rhaenys Targaryen", "black", "The Queen Who Never Was", "killed at Rook's Rest", "dead",
     "targaryen", "33_char_rhaenys", "Corlys's wife; sacrifice context"),
    ("Laena Velaryon", "black", "Corlys and Rhaenys's daughter", "memory", "neutral",
     "velaryon", "34_char_laena", "Family diagram context"),
    ("Otto Hightower", "green", "Former Hand", "burial request · treasury", "neutral",
     "hightower", "35_char_otto_memorial", "Named in the treasury and burial threads"),
]

# ---------------------------------------------------------------------------------------------------
# DRAGONS. Same card grammar, but the status line carries the RIDER and whether the regime knows.
# Spec §9: Tessarion must never sit in Team Black's possession; Sheepstealer's rider must read
# "unknown rider", never "Rhaena".
DRAGONS = [
    ("Syrax",        "black",   "Rhaenyra's mount",      "ridden · at King's Landing", "key",     "36_dragon_syrax"),
    ("Caraxes",      "black",   "Daemon's mount",        "ridden · in the field",      "key",     "37_dragon_caraxes"),
    ("Vermithor",    "black",   "Hugh Hammer's mount",   "newly claimed",              "good",    "38_dragon_vermithor"),
    ("Silverwing",   "black",   "Ulf White's mount",     "newly claimed",              "good",    "39_dragon_silverwing"),
    ("Seasmoke",     "black",   "Addam of Hull's mount", "newly claimed",              "good",    "40_dragon_seasmoke"),
    ("Sheepstealer", "neutral", "Rider unknown to the court", "unknown rider",         "neutral", "41_dragon_sheepstealer"),
    ("Tessarion",    "green",   "Daeron's mount",        "with Hightower forces",      "bad",     "42_dragon_tessarion"),
    ("Vhagar",       "green",   "Aemond's mount",        "missing",                    "bad",     "43_dragon_vhagar_missing"),
]


def build_dragons():
    os.makedirs(OUT, exist_ok=True)
    made = []
    for name, fac, role, status, tone, stem in DRAGONS:
        p = os.path.join(OUT, f"{stem}.png")
        # a generated per-dragon emblem if present, else the house dragon device
        sig = f"dragon_{name.lower()}" if find_sigil(f"dragon_{name.lower()}") else "targaryen"
        character_card(name, fac, role, status, tone, sig, p, note="DRAGON")
        made.append(p)
    return made


def build_characters():
    os.makedirs(OUT, exist_ok=True)
    made = []
    for name, fac, role, status, tone, sig, stem, note in CHARACTERS:
        p = os.path.join(OUT, f"{stem}.png")
        character_card(name, fac, role, status, tone, sig, p, note)
        made.append(p)
    return made


if __name__ == "__main__":
    ps = build_characters()
    print(f"{len(ps)} heraldic character cards -> {OUT}")
    for p in ps:
        print("  ", os.path.basename(p))


# ---------------------------------------------------------------------------------------------------
# INFOGRAPHICS (#17, #18 of the minimum set). Deliberately CODE-DRAWN: a diagram needs exact labels and
# correct relative geography, and a generated image will hallucinate both.
MAP_BASE = ("house-of-dragons/house_of_the_dragon_s3e3_complete_asset_pack/images/"
            "maps_and_locations/01_westeros_map.png")
# Normalised coordinates read off the SUPPLIED map (1672x941). Annotating the real map beats inventing
# geography: my first attempt drew arbitrary nodes joined by a line, which implied a coastline/route
# that does not exist. Tumbleton is not labelled on the base map; it sits in the Reach between
# Highgarden and King's Landing, so it is placed there and drawn as an ADDED pin, not a base label.
MAP_PTS = {
    "KING'S LANDING": (0.634, 0.574), "HARRENHAL": (0.553, 0.445), "OLDTOWN": (0.362, 0.798),
    "HIGHGARDEN": (0.421, 0.723), "THE EYRIE": (0.665, 0.290), "DRAGONSTONE": (0.762, 0.522),
    "TUMBLETON": (0.530, 0.660),
}


# Crop window over the supplied map: drops its own title/legend panel on the left so our annotations
# and legend are not fighting it for space. Chosen to land on a 16:9 crop of the landmass.
CROP = (0.260, 0.121, 1.0, 0.860)          # x0, y0, x1, y1 (normalised on the source map)


def _map_canvas(title, subtitle=""):
    """The supplied Westeros map, cropped to the landmass and dimmed, with a title bar."""
    src = Image.open(MAP_BASE).convert("RGB")
    sw, sh = src.size
    base = src.crop((int(CROP[0] * sw), int(CROP[1] * sh), int(CROP[2] * sw), int(CROP[3] * sh)))
    base = base.resize((W, H), Image.LANCZOS)
    dark = Image.new("RGB", (W, H), (6, 8, 12))
    im = Image.blend(base, dark, 0.42)                       # dim so annotations read on top
    d = ImageDraw.Draw(im, "RGBA")
    d.rectangle([0, 0, W, 128], fill=(8, 10, 14, 226))
    BP._track(d, (64, 42), title.upper(), BP._F(BP._COPPER, 42), BP.GOLD, tr=6)
    if subtitle:
        d.text((64, 96), subtitle, font=BP._F(BP._ARIAL, 26), fill=(186, 192, 200))
    d.line([(0, 128), (W, 128)], fill=BP.GOLD, width=3)
    return im, d


def _xy(key):
    """Source-map normalised point -> pixel inside the cropped canvas."""
    nx, ny = MAP_PTS[key]
    return (int((nx - CROP[0]) / (CROP[2] - CROP[0]) * W),
            int((ny - CROP[1]) / (CROP[3] - CROP[1]) * H))


def _pin(d, key, label, col, side="right", ring=True):
    x, y = _xy(key)
    if ring:
        for r, a in ((46, 90), (34, 150)):
            d.ellipse([x - r, y - r, x + r, y + r], outline=(*col, a), width=4)
    d.ellipse([x - 13, y - 13, x + 13, y + 13], fill=col, outline=BP.WHITE, width=3)
    fnt = BP._F(BP._ARIAL_B, 32)
    tw = BP._tw(d, label, fnt)
    lx = x + 30 if side == "right" else x - 30 - tw
    d.rounded_rectangle([lx - 12, y - 24, lx + tw + 12, y + 22], radius=9, fill=(8, 10, 14, 238),
                        outline=(*col, 200), width=2)
    d.text((lx, y - 18), label, font=fnt, fill=BP.WHITE)


def _legend(d, rows):
    """Top-right. The first version sat bottom-left and covered the Oldtown pin and a route label."""
    fnt = BP._F(BP._ARIAL, 27)
    wid = max(BP._tw(d, t, fnt) for t, _ in rows) + 108
    x0, y0 = W - 56 - wid, 168
    d.rounded_rectangle([x0, y0 - 18, x0 + wid, y0 + 42 * len(rows) + 8], radius=12,
                        fill=(8, 10, 14, 236), outline=(*BP.GOLD, 170), width=2)
    for i, (t, c) in enumerate(rows):
        yy = y0 + i * 42
        d.ellipse([x0 + 22, yy + 8, x0 + 38, yy + 24], fill=c)
        d.text((x0 + 56, yy), t, font=fnt, fill=(212, 216, 222))


def graphic_strategic_map(out):
    im, d = _map_canvas("Episode 3 — the strategic picture",
                        "Rhaenyra holds the capital; her enemies are unlocated")
    _pin(d, "KING'S LANDING", "KING'S LANDING — taken", BP.GOLD)
    _pin(d, "TUMBLETON", "TUMBLETON — struck", BP.RED, side="left")
    _pin(d, "OLDTOWN", "OLDTOWN — claimed retreat", BP.STEEL, side="right")
    _pin(d, "HARRENHAL", "HARRENHAL — bounty", (150, 170, 192), side="left", ring=False)
    _pin(d, "THE EYRIE", "THE VALE — refuge", (150, 170, 192), side="left", ring=False)
    _legend(d, [("Rhaenyra holds the throne — not the war", BP.GOLD),
                ("Ormund's real target; civilians trapped", BP.RED),
                ("Aegon II and Aemond: location unknown", (196, 128, 128)),
                ("SHOW CONFIRMED — Episode 3", BP.STEEL)])
    im.save(out); return out


def graphic_deception_route(out):
    im, d = _map_canvas("Ormund's deception", "The retreat was announced. The attack went elsewhere.")
    P = _xy
    hx, hy = P("HIGHGARDEN")            # Hightower host in the Reach
    ox, oy = P("OLDTOWN")               # claimed destination
    tx, ty = P("TUMBLETON")             # actual target
    for t in range(0, 100, 5):          # claimed: dashed steel
        a = (hx + (ox - hx) * t / 100, hy + (oy - hy) * t / 100)
        b = (hx + (ox - hx) * (t + 2.6) / 100, hy + (oy - hy) * (t + 2.6) / 100)
        d.line([a, b], fill=BP.STEEL, width=6)
    d.line([(hx, hy), (tx, ty)], fill=BP.RED, width=9)      # actual: solid red
    # labels placed AWAY from both lines (the first version collided with the node label)
    # RIGHT of the dashed route (both its pins sit bottom-left), clamped inside the frame — pushing it
    # left ran it off-canvas and overlapping the pins hid it behind their label plates.
    d.text((max(70, min(W - 460, ox + 300)), min(H - 64, oy - 12)), "CLAIMED RETREAT",
           font=BP._F(BP._ARIAL_B, 34), fill=BP.STEEL)
    d.text((tx + 70, ty + 34), "ACTUAL ATTACK", font=BP._F(BP._ARIAL_B, 34), fill=BP.RED)
    _pin(d, "HIGHGARDEN", "HIGHTOWER HOST", (150, 170, 116), side="left", ring=False)
    _pin(d, "OLDTOWN", "OLDTOWN", BP.STEEL, side="right", ring=False)
    _pin(d, "TUMBLETON", "TUMBLETON", BP.RED, side="left")
    _legend(d, [("Announced: withdrawal to Oldtown", BP.STEEL),
                ("Actual: assault on Tumbleton", BP.RED),
                ("SHOW CONFIRMED — Episode 3", BP.GOLD)])
    im.save(out); return out


def build_infographics():
    os.makedirs(OUT, exist_ok=True)
    return [graphic_strategic_map(os.path.join(OUT, "17_graphic_strategic_map.png")),
            graphic_deception_route(os.path.join(OUT, "18_graphic_ormund_deception_route.png"))]


# ---------------------------------------------------------------------------------------------------
# INFOGRAPHICS (the remaining 7 of manifest §7). All code-drawn: these carry exact labels, numbers and
# causal order, which a generated image would invent.
def _plate(title, subtitle="", label="SHOW CONFIRMED — Episode 3"):
    im = Image.new("RGB", (W, H), (9, 11, 14))
    d = ImageDraw.Draw(im, "RGBA")
    for i in range(0, H, 4):
        d.line([(0, i), (W, i)], fill=(255, 255, 255, 4))
    d.rectangle([48, 48, W - 48, H - 48], outline=BP.GOLD, width=3)
    BP._track(d, (84, 72), title.upper(), BP._F(BP._COPPER, 40), BP.GOLD, tr=6)
    if subtitle:
        d.text((84, 130), subtitle, font=BP._F(BP._ARIAL, 28), fill=(188, 194, 202))
    d.line([(84, 176), (W - 84, 176)], fill=BP.GOLD, width=2)
    if label:
        d.text((84, H - 96), label, font=BP._F(BP._ARIAL_B, 24), fill=BP.GOLD)
    return im, d


def _bar(d, x, y, w, frac, col, h=30):
    d.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=(26, 30, 38, 255))
    if frac > 0:
        d.rounded_rectangle([x, y, x + max(10, int(w * frac)), y + h], radius=8, fill=col)
    d.rounded_rectangle([x, y, x + w, y + h], radius=8, outline=(70, 78, 90), width=2)


def graphic_government_dashboard(out):
    im, d = _plate("Rhaenyra's government — what she actually controls",
                   "Holding the capital is not the same as holding power")
    rows = [("GOLD / TREASURY", 0.06, BP.RED, "empty — the crown has no money"),
            ("FOOD SUPPLY", 0.22, BP.RED, "blockade + hoarding; relief is temporary"),
            ("THE FAITH", 0.10, BP.RED, "will not anoint while a rival king lives"),
            ("PUBLIC SUPPORT", 0.55, BP.GOLD, "petitions heard; goodwill is fragile"),
            ("MILITARY / DRAGONS", 0.78, BP.GREEN, "strongest instrument she holds"),
            ("INTELLIGENCE", 0.30, BP.RED, "enemies unlocated"),
            ("ALLIES", 0.48, BP.GOLD, "Velaryon support has a price")]
    fnt_l, fnt_n = BP._F(BP._ARIAL_B, 30), BP._F(BP._ARIAL, 25)
    for i, (lab, frac, col, note) in enumerate(rows):
        y = 236 + i * 96
        d.text((92, y), lab, font=fnt_l, fill=BP.WHITE)
        _bar(d, 470, y - 2, 620, frac, col)
        d.text((1128, y + 2), note, font=fnt_n, fill=(178, 184, 192))
    im.save(out); return out


def graphic_three_powers(out):
    im, d = _plate("Three forms of power", "The episode separates them — and she only has one")
    cols = [("COERCIVE POWER", "Dragons and swords.\nShe has the most of this.", BP.GREEN, "STRONG"),
            ("INSTITUTIONAL\nLEGITIMACY", "Anointing, recognition, law.\nThe Faith withholds it.", BP.RED, "BLOCKED"),
            ("ADMINISTRATIVE\nCAPACITY", "Gold, food, records, officials.\nThe treasury is empty.", BP.RED, "HOLLOW")]
    for i, (t, body, col, verdict) in enumerate(cols):
        x = 130 + i * 560
        d.rounded_rectangle([x, 240, x + 480, 760], radius=16, fill=(14, 17, 22, 240), outline=col, width=3)
        yy = 276
        for line in t.split("\n"):
            BP._track(d, (x + 34, yy), line, BP._F(BP._COPPER, 32), BP.WHITE, tr=3); yy += 44
        yy += 18
        for line in body.split("\n"):
            d.text((x + 34, yy), line, font=BP._F(BP._ARIAL, 26), fill=(184, 190, 198)); yy += 38
        d.rounded_rectangle([x + 34, 668, x + 34 + 200, 720], radius=10, fill=(*BP.CHIP[:3], 240), outline=col, width=3)
        BP._track(d, (x + 56, 682), verdict, BP._F(BP._ARIAL_B, 30), col, tr=3)
    d.text((130, 800), "Rhaenyra wins the city with power 1 and cannot govern it without powers 2 and 3.",
           font=BP._F(BP._ARIAL, 28), fill=(200, 206, 214))
    im.save(out); return out


def graphic_false_daeron_id(out):
    im, d = _plate("The captive is not the prince", "Alicent identifies the decoy", "SHOW CONFIRMED — Episode 3")
    for i, (lab, val, col) in enumerate([("PRESENTED AS", "Prince Daeron Targaryen", BP.STEEL),
                                         ("ACTUALLY", "an impostor — a decoy", BP.RED),
                                         ("EXPOSED BY", "Alicent Hightower", BP.GOLD),
                                         ("REAL DAERON", "at large with Ormund; rides Tessarion", BP.RED),
                                         ("STRATEGIC USE", "a false bargaining chip", BP.STEEL)]):
        y = 250 + i * 104
        d.text((104, y), lab, font=BP._F(BP._ARIAL_B, 26), fill=(140, 146, 156))
        d.text((104, y + 36), val, font=BP._F(BP._GEO_B, 38), fill=col)
        d.line([(104, y + 88), (W - 104, y + 88)], fill=(48, 54, 64), width=2)
    gp = os.path.join(SIG_GEN, "sig_decoy.png")
    if os.path.exists(gp):
        em = Image.open(gp).convert("RGB").resize((300, 300), Image.LANCZOS)
        im.paste(Image.new("RGB", em.size, BP.RED), (W - 420, 300), em.convert("L"))
    im.save(out); return out


def _chain(d, steps, y=430):
    fnt = BP._F(BP._ARIAL_B, 26)
    n = len(steps); bw = (W - 200 - (n - 1) * 46) // n
    for i, (t, col) in enumerate(steps):
        x = 100 + i * (bw + 46)
        d.rounded_rectangle([x, y, x + bw, y + 190], radius=14, fill=(14, 17, 22, 242), outline=col, width=3)
        yy = y + 34
        for line in t.split("\n"):
            tw = BP._tw(d, line, fnt)
            d.text((x + (bw - tw) // 2, yy), line, font=fnt, fill=BP.WHITE); yy += 36
        if i < n - 1:
            ax = x + bw + 8
            d.polygon([(ax, y + 82), (ax, y + 108), (ax + 28, y + 95)], fill=BP.GOLD)


def graphic_rat_banquet_chain(out):
    im, d = _plate("The rat banquet", "Why nobles were served vermin — the causal chain")
    _chain(d, [("BLOCKADE\ncuts supply", BP.RED), ("NOBLES\nHOARD FOOD", BP.RED),
               ("CITY\nSHORTAGE", BP.RED), ("GOLD CLOAKS\nRAID STORES", BP.GOLD),
               ("RELIEF —\nTEMPORARY", BP.GREEN)])
    d.text((100, 700), "The banquet is a demonstration, not a solution: it shames the hoarders and feeds the city once.",
           font=BP._F(BP._ARIAL, 28), fill=(196, 202, 210))
    d.text((100, 748), "Torrhen Manderly's objection stands — seizure cannot be repeated indefinitely.",
           font=BP._F(BP._ARIAL, 28), fill=(150, 157, 166))
    im.save(out); return out


def graphic_daemon_vs_rhaenyra(out):
    im, d = _plate("Two theories of rule", "Daemon argues fear. Rhaenyra argues institutions.")
    for i, (who, sub, pts, col) in enumerate([
            ("DAEMON", "rule through fear", ["Answer deception with force",
                                             "Make an example of Tumbleton",
                                             "Obedience now, legitimacy later"], BP.RED),
            ("RHAENYRA", "rule through institutions", ["Hear petitions; be seen to be just",
                                                       "Seek anointing and recognition",
                                                       "Feed the city, then hold it"], BP.GOLD)]):
        x = 110 + i * 900
        d.rounded_rectangle([x, 236, x + 800, 720], radius=16, fill=(14, 17, 22, 240), outline=col, width=3)
        BP._track(d, (x + 36, 272), who, BP._F(BP._COPPER, 46), BP.WHITE, tr=5)
        d.text((x + 36, 336), sub, font=BP._F(BP._ARIAL, 28), fill=col)
        for k, t in enumerate(pts):
            yy = 404 + k * 78
            d.ellipse([x + 40, yy + 10, x + 56, yy + 26], fill=col)
            d.text((x + 78, yy), t, font=BP._F(BP._ARIAL, 27), fill=(196, 202, 210))
    d.text((110, 760), "INTERPRETATION — the episode stages the argument; it does not declare a winner.",
           font=BP._F(BP._ARIAL_B, 26), fill=BP.STEEL)
    im.save(out); return out


def graphic_show_vs_book(out):
    im, d = _plate("Show vs book", "The adaptation reorders and compresses — label them separately",
                   "SHOW CHANGE / BOOK CONFIRMED")
    for i, (lane, col, rows) in enumerate([
            ("TELEVISION", BP.GOLD, ["Rhaenyra takes King's Landing", "Ormund fakes a retreat",
                                     "A decoy Daeron is captured", "The Faith refuses to anoint"]),
            ("FIRE & BLOOD", BP.STEEL, ["The book records a different order", "Tumbleton falls in its own chapter",
                                        "No direct equivalent to the decoy", "Testimony conflicts by source"])]):
        y = 250 + i * 300
        BP._track(d, (100, y), lane, BP._F(BP._COPPER, 34), col, tr=4)
        d.line([(100, y + 58), (W - 100, y + 58)], fill=col, width=3)
        for k, t in enumerate(rows):
            x = 110 + k * 430
            d.ellipse([x - 9, y + 49, x + 9, y + 67], fill=col, outline=BP.WHITE, width=2)
            d.text((x - 6, y + 86), t, font=BP._F(BP._ARIAL, 24), fill=(190, 196, 204))
    d.text((100, 860), "The book is an in-universe history compiled from conflicting sources — not a camera record.",
           font=BP._F(BP._ARIAL, 27), fill=(150, 157, 166))
    im.save(out); return out


def graphic_winner_scoreboard(out):
    im, d = _plate("Who actually won Episode 3?", "Tactical gain is not strategic gain")
    rows = [("TACTICAL GAIN", "RHAENYRA", "holds the capital, the throne, the city's goodwill", BP.GREEN),
            ("STRATEGIC GAIN", "THE HIGHTOWERS", "the real army struck Tumbleton; Daeron is free", BP.RED),
            ("HER WEAKNESS", "LEGITIMACY + GOLD", "unanointed, unfunded, enemies unlocated", BP.RED),
            ("THE OPEN QUESTION", "CAN SHE GOVERN?", "force took the city; administration must keep it", BP.GOLD)]
    for i, (lab, who, why, col) in enumerate(rows):
        y = 246 + i * 150
        d.rounded_rectangle([96, y, W - 96, y + 122], radius=14, fill=(14, 17, 22, 240), outline=col, width=3)
        d.text((128, y + 18), lab, font=BP._F(BP._ARIAL_B, 25), fill=(140, 146, 156))
        BP._track(d, (128, y + 54), who, BP._F(BP._COPPER, 38), col, tr=4)
        d.text((760, y + 48), why, font=BP._F(BP._ARIAL, 27), fill=(196, 202, 210))
    im.save(out); return out


def build_more_infographics():
    os.makedirs(OUT, exist_ok=True)
    return [graphic_government_dashboard(os.path.join(OUT, "44_graphic_government_dashboard.png")),
            graphic_three_powers(os.path.join(OUT, "45_graphic_three_forms_of_power.png")),
            graphic_false_daeron_id(os.path.join(OUT, "46_graphic_false_daeron_identity.png")),
            graphic_rat_banquet_chain(os.path.join(OUT, "47_graphic_rat_banquet_causal_chain.png")),
            graphic_daemon_vs_rhaenyra(os.path.join(OUT, "48_graphic_daemon_vs_rhaenyra_rule.png")),
            graphic_show_vs_book(os.path.join(OUT, "49_graphic_show_vs_book.png")),
            graphic_winner_scoreboard(os.path.join(OUT, "50_graphic_winner_scoreboard.png"))]


def build_all():
    return build_characters() + build_dragons() + build_infographics() + build_more_infographics()
