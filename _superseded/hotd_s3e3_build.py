"""Build the House of the Dragon S3E3 explainer (long-form 1920x1080).

The S3E2 video was one still card for 11 minutes (measured: 1.7% moving frames, longest
held run 1184 frames). The fix the user asked for -- "more changing images based on the
story" -- is implemented here as:

  * 26 narration segments -> a PLAYLIST of 3-6 visuals each (~119 total, one visual every
    ~6.5s). The changing element is the ART, not a caption.
  * every visual drifts with a DURATION-AWARE zoompan rate (step = 0.05/frames), so a 9s
    shot drifts as slowly as a 4s shot instead of hitting the zoom ceiling and freezing --
    the exact defect that made quiz cards look like stills.
  * an always-on state rail (board_pipeline.render_board) over location plates and character
    cards, advancing through 6 authored states; INFOGRAPHICS play full-bleed without the rail
    (they are their own information display) which also buys visual variety.
  * hard cuts (concat demuxer, stream copy) -- no 0.5s crossfade mush.

IP posture: no likenesses, no episode footage. Characters are heraldic text cards, locations
are original matte paintings, everything else is code-drawn diagrams.

Run: /opt/homebrew/bin/python3 hotd_s3e3_build.py
"""
from __future__ import annotations
import glob
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
for _l in open(".env", encoding="utf8"):
    _l = _l.strip()
    if _l and not _l.startswith("#") and "=" in _l:
        _k, _, _v = _l.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip())

from PIL import Image, ImageDraw, ImageFilter

import board_pipeline as bp
import explainer_pipeline as ep

W, H, FPS = 1920, 1080, 30
PACK = "house-of-dragons/house_of_the_dragon_s3e3_complete_asset_pack/images"
OUT = "renders/hotd_s3e3"
WORK = f"{OUT}/work"
CONTENT_W = 1086          # rail scrim begins at x=1086; art must stay left of it
VOICE = "echo"
SEG_GAP = 0.35            # silence between segments (breathing room at every hard cut)


# ----------------------------------------------------------------------------- assets
def _index():
    ix = {}
    for p in glob.glob(f"{PACK}/**/*.png", recursive=True):
        b = os.path.basename(p)[:-4]
        if b.startswith("_"):
            continue
        ix[b] = p
    return ix


IX = _index()


def A(name):
    if name not in IX:
        raise KeyError(f"asset not found: {name}")
    return IX[name]


# ----------------------------------------------------------------------------- rail states
def _chip(name, role, tag, tone):
    return {"name": name, "role": role, "tag": tag, "tone": tone}


_BASE_SUB = "House of the Dragon · S3E3"

# Roles/tags are kept short on purpose: the chip lays the tag pill out on the same row as the
# role, so long strings ellipsise the role away ("Whisperers" -> "Whisp...").
STATES = {
    "open": {
        "title": "STATE OF THE WAR", "subtitle": _BASE_SUB,
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            _chip("Rhaenyra", "Queen", "THRONE TAKEN", "key"),
            _chip("Daemon", "Consort", "IN THE FIELD", "good"),
            _chip("Mysaria", "Whisperers", "NETWORK LIVE", "good"),
            _chip("Corlys", "Hand", "SERVING", "neutral")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            _chip("Aegon II", "Deposed", "MISSING", "bad"),
            _chip("Aemond", "Vhagar", "MISSING", "bad"),
            _chip("Alicent", "Dowager", "CONFINED", "bad"),
            _chip("Ormund", "Hightower", "IN THE REACH", "neutral")]},
        "control": {"label": "KING'S LANDING", "held_by": "blacks",
                    "text": "Throne held. Nothing else settled."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 1 · The morning after victory",
        "changed": ["Rhaenyra", "control"]},
    "treasury": {
        "title": "STATE OF THE WAR", "subtitle": _BASE_SUB,
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            _chip("Rhaenyra", "Queen", "UNANOINTED", "neutral"),
            _chip("Treasury", "Crown coin", "EMPTY", "bad"),
            _chip("Food", "The capital", "CRITICAL", "bad"),
            _chip("Mysaria", "Whisperers", "NETWORK LIVE", "good")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            _chip("Tyland", "Coin", "PRESUMED DEAD", "dead"),
            _chip("High Septon", "The Faith", "WITHHOLDING", "bad"),
            _chip("Aegon II", "Deposed", "MISSING", "bad"),
            _chip("Aemond", "Vhagar", "MISSING", "bad")]},
        "control": {"label": "THE CAPITAL", "held_by": "contested",
                    "text": "Held by force. Not yet governed."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 2 · What victory did not deliver",
        "changed": ["Treasury", "Food", "High Septon", "control"]},
    "field": {
        "title": "THE FIELD", "subtitle": _BASE_SUB + " · the Reach",
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            _chip("Daemon", "Consort", "TERMS GIVEN", "good"),
            _chip("Caraxes", "Dragon", "IN THE AIR", "good"),
            _chip("Hostage", "Claimed heir", "SECURED", "key"),
            _chip("Reach army", "Hightower", "DISBANDING", "good")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            _chip("Ormund", "Hightower", "KNELT", "neutral"),
            _chip("Daeron", "Prince", "UNVERIFIED", "bad"),
            _chip("Tessarion", "Dragon", "WITH HOST", "bad"),
            _chip("Oldtown", "The seat", "UNTOUCHED", "neutral")]},
        "control": {"label": "THE REACH ROAD", "held_by": "contested",
                    "text": "A surrender accepted before it was verified."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 3 · Defeated by information",
        "changed": ["Daemon", "Ormund", "Hostage", "Daeron"]},
    "court": {
        "title": "THE COURT", "subtitle": _BASE_SUB + " · King's Landing",
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            _chip("Rhaenyra", "Queen", "GOVERNING", "key"),
            _chip("Corlys", "Hand", "PRESSING", "neutral"),
            _chip("Mysaria", "Whisperers", "ESSENTIAL", "good"),
            _chip("New knights", "Three riders", "OWED", "neutral")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            _chip("Alicent", "Dowager", "USEFUL", "neutral"),
            _chip("Helaena", "Confined", "HELD", "bad"),
            _chip("High Septon", "The Faith", "WITHHOLDING", "bad"),
            _chip("Smallfolk", "The city", "HUNGRY", "bad")]},
        "control": {"label": "LEGITIMACY", "held_by": "contested",
                    "text": "Every ally is also an invoice."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 4 · The price of every ally",
        "changed": ["Corlys", "Alicent", "New knights", "Smallfolk"]},
    "decoy": {
        "title": "THE DECEPTION", "subtitle": _BASE_SUB + " · Tumbleton",
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            _chip("Rhaenyra", "Queen", "MISINFORMED", "bad"),
            _chip("Daemon", "Sent away", "THE VALE", "neutral"),
            _chip("Hostage", "Not Daeron", "A DECOY", "bad"),
            _chip("Syrax", "Dragon", "GROUNDED", "neutral")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            _chip("Ormund", "Hightower", "AT TUMBLETON", "good"),
            _chip("Tumbleton", "River town", "TAKEN", "good"),
            _chip("Daeron", "Prince", "UNKNOWN", "good"),
            _chip("Tessarion", "Dragon", "WITH HOST", "good")]},
        "control": {"label": "TUMBLETON", "held_by": "greens",
                    "text": "A road nobody was watching."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 5 · What the decoy bought",
        "changed": ["Ormund", "Tumbleton", "Hostage", "Rhaenyra", "control"]},
    "final": {
        "title": "END OF EPISODE", "subtitle": _BASE_SUB,
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            _chip("Force", "Dragons", "HELD", "good"),
            _chip("Legitimacy", "The oil", "WITHHELD", "bad"),
            _chip("Governing", "Coin, grain", "MISSING", "bad"),
            _chip("Mysaria", "Whisperers", "QUIET WINNER", "key")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            _chip("Ormund", "Hightower", "EP. WINNER", "good"),
            _chip("Alicent", "Dowager", "STILL USEFUL", "neutral"),
            _chip("Aegon II", "Deposed", "STILL MISSING", "bad"),
            _chip("Aemond", "Vhagar", "STILL MISSING", "bad")]},
        "control": {"label": "THE THRONE", "held_by": "blacks",
                    "text": "One of three forms of power. Only one."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 6 · Ruling begins after victory",
        "changed": ["Legitimacy", "Governing", "Mysaria", "Ormund"]},
}


# ----------------------------------------------------------------------------- playlists
# (type, ...) per visual.  card/cards carry their own background plate.
# INVARIANT: no segment opens on "full"/"map" -- those are self-titled diagrams, so the
# segment caption has nowhere to go without double-titling. Open on a plate or a card, THEN
# cut to the diagram. That is better editing anyway: establish the scene, then explain it.
P = {
    "cold_open": [("plate", "13_loc_iron_throne_room"),
                  ("plate", "14_loc_empty_treasury"),
                  ("card", "09_char_high_septon", "13_loc_iron_throne_room"),
                  ("card", "05_char_daeron_false", "16_loc_tumbleton_occupied"),
                  ("full", "18_graphic_ormund_deception_route")],
    "board": [("plate", "12_loc_kings_landing"),
              ("full", "44_graphic_government_dashboard"),
              ("cards", ["10_char_aegon_ii_missing", "11_char_aemond_missing"], "51_loc_red_keep"),
              ("card", "43_dragon_vhagar_missing", "55_loc_harrenhal"),
              ("plate", "53_loc_the_reach_farmland")],
    "ormund_a": [("plate", "53_loc_the_reach_farmland"),
                 ("card", "37_dragon_caraxes", "53_loc_the_reach_farmland"),
                 ("card", "02_char_daemon", "53_loc_the_reach_farmland"),
                 ("card", "03_char_ormund", "52_loc_oldtown_hightower"),
                 ("plate", "52_loc_oldtown_hightower")],
    "ormund_b": [("plate", "52_loc_oldtown_hightower"),
                 ("full", "18_graphic_ormund_deception_route"),
                 ("card", "05_char_daeron_false", "16_loc_tumbleton_occupied"),
                 ("card", "03_char_ormund", "53_loc_the_reach_farmland"),
                 ("map", "01_westeros_map"),
                 ("plate", "16_loc_tumbleton_occupied")],
    "first_day_a": [("plate", "59_loc_small_council_chamber"),
                    ("plate", "14_loc_empty_treasury"),
                    ("card", "25_char_tyland_lannister", "14_loc_empty_treasury"),
                    ("plate", "12_loc_kings_landing"),
                    ("full", "44_graphic_government_dashboard")],
    "first_day_b": [("card", "36_dragon_syrax", "13_loc_iron_throne_room"),
                    ("cards", ["10_char_aegon_ii_missing", "11_char_aemond_missing"], "55_loc_harrenhal"),
                    ("card", "41_dragon_sheepstealer", "57_loc_dragonstone"),
                    ("plate", "15_loc_rat_banquet_hall"),
                    ("plate", "14_loc_empty_treasury"),
                    ("full", "44_graphic_government_dashboard")],
    "faith_a": [("card", "09_char_high_septon", "51_loc_red_keep"),
                ("card", "01_char_rhaenyra", "13_loc_iron_throne_room"),
                ("plate", "12_loc_kings_landing")],
    "faith_b": [("card", "01_char_rhaenyra", "51_loc_red_keep"),
                ("full", "45_graphic_three_forms_of_power"),
                ("card", "09_char_high_septon", "12_loc_kings_landing"),
                ("plate", "51_loc_red_keep"),
                ("full", "45_graphic_three_forms_of_power")],
    "alicent_a": [("card", "06_char_alicent", "51_loc_red_keep"),
                  ("card", "23_char_helaena", "51_loc_red_keep"),
                  ("plate", "51_loc_red_keep"),
                  ("card", "11_char_aemond_missing", "55_loc_harrenhal"),
                  ("card", "43_dragon_vhagar_missing", "56_loc_riverlands")],
    "alicent_b": [("plate", "51_loc_red_keep"),
                  ("cards", ["06_char_alicent", "01_char_rhaenyra"], "51_loc_red_keep"),
                  ("card", "06_char_alicent", "59_loc_small_council_chamber"),
                  ("card", "08_char_mysaria", "12_loc_kings_landing"),
                  ("plate", "59_loc_small_council_chamber")],
    "corlys_a": [("card", "07_char_corlys", "57_loc_dragonstone"),
                 ("cards", ["19_char_addam_of_hull", "20_char_alyn_of_hull"], "58_loc_the_gullet"),
                 ("cards", ["32_char_laenor", "33_char_rhaenys"], "57_loc_dragonstone"),
                 ("full", "06_targaryen_family_tree")],
    "corlys_b": [("card", "07_char_corlys", "57_loc_dragonstone"),
                 ("cards", ["19_char_addam_of_hull", "20_char_alyn_of_hull"], "58_loc_the_gullet"),
                 ("cards", ["29_char_jacaerys_memorial", "30_char_lucerys_memorial"], "57_loc_dragonstone"),
                 ("card", "31_char_joffrey", "57_loc_dragonstone"),
                 ("full", "45_graphic_three_forms_of_power")],
    "smallfolk_a": [("plate", "60_loc_petition_hall"),
                    ("cards", ["21_char_hugh_hammer", "22_char_ulf_white"], "13_loc_iron_throne_room"),
                    ("card", "19_char_addam_of_hull", "13_loc_iron_throne_room"),
                    ("plate", "13_loc_iron_throne_room")],
    "smallfolk_b": [("plate", "15_loc_rat_banquet_hall"),
                    ("full", "47_graphic_rat_banquet_causal_chain"),
                    ("plate", "61_loc_food_distribution"),
                    ("plate", "12_loc_kings_landing")],
    "smallfolk_c": [("plate", "61_loc_food_distribution"),
                    ("full", "47_graphic_rat_banquet_causal_chain"),
                    ("plate", "58_loc_the_gullet"),
                    ("plate", "56_loc_riverlands"),
                    ("card", "08_char_mysaria", "60_loc_petition_hall")],
    "philosophy_a": [("card", "02_char_daemon", "53_loc_the_reach_farmland"),
                     ("full", "48_graphic_daemon_vs_rhaenyra_rule"),
                     ("card", "01_char_rhaenyra", "13_loc_iron_throne_room"),
                     ("full", "48_graphic_daemon_vs_rhaenyra_rule")],
    "philosophy_b": [("card", "02_char_daemon", "54_loc_vale_of_arryn"),
                     ("full", "17_graphic_strategic_map"),
                     ("plate", "54_loc_vale_of_arryn"),
                     ("card", "41_dragon_sheepstealer", "54_loc_vale_of_arryn"),
                     ("map", "01_westeros_map")],
    "false_daeron_a": [("card", "06_char_alicent", "51_loc_red_keep"),
                       ("card", "05_char_daeron_false", "51_loc_red_keep"),
                       ("full", "46_graphic_false_daeron_identity"),
                       ("card", "04_char_daeron_real", "52_loc_oldtown_hightower"),
                       ("plate", "51_loc_red_keep")],
    "false_daeron_b": [("card", "03_char_ormund", "16_loc_tumbleton_occupied"),
                       ("full", "46_graphic_false_daeron_identity"),
                       ("plate", "16_loc_tumbleton_occupied"),
                       ("full", "18_graphic_ormund_deception_route"),
                       ("plate", "53_loc_the_reach_farmland")],
    "tumbleton_a": [("plate", "16_loc_tumbleton_occupied"),
                    ("full", "18_graphic_ormund_deception_route"),
                    ("full", "17_graphic_strategic_map")],
    "tumbleton_b": [("card", "01_char_rhaenyra", "13_loc_iron_throne_room"),
                    ("card", "36_dragon_syrax", "12_loc_kings_landing"),
                    ("full", "45_graphic_three_forms_of_power"),
                    ("plate", "13_loc_iron_throne_room"),
                    ("full", "44_graphic_government_dashboard")],
    "book_a": [("plate", "53_loc_the_reach_farmland"),
               ("full", "49_graphic_show_vs_book"),
               ("card", "03_char_ormund", "52_loc_oldtown_hightower"),
               ("full", "49_graphic_show_vs_book")],
    "book_b": [("card", "07_char_corlys", "57_loc_dragonstone"),
               ("full", "49_graphic_show_vs_book"),
               ("cards", ["19_char_addam_of_hull", "20_char_alyn_of_hull"], "58_loc_the_gullet"),
               ("plate", "57_loc_dragonstone"),
               ("full", "49_graphic_show_vs_book")],
    "scoreboard_a": [("card", "01_char_rhaenyra", "13_loc_iron_throne_room"),
                     ("full", "50_graphic_winner_scoreboard"),
                     ("card", "03_char_ormund", "16_loc_tumbleton_occupied"),
                     ("card", "02_char_daemon", "54_loc_vale_of_arryn")],
    "scoreboard_b": [("card", "06_char_alicent", "51_loc_red_keep"),
                     ("full", "50_graphic_winner_scoreboard"),
                     ("card", "07_char_corlys", "57_loc_dragonstone"),
                     ("card", "08_char_mysaria", "12_loc_kings_landing")],
    "conclusion": [("plate", "13_loc_iron_throne_room"),
                   ("full", "45_graphic_three_forms_of_power"),
                   ("card", "01_char_rhaenyra", "13_loc_iron_throne_room")],
}

SEG_STATE = {
    "cold_open": "open", "board": "open",
    "first_day_a": "treasury", "first_day_b": "treasury", "faith_a": "treasury", "faith_b": "treasury",
    "ormund_a": "field", "ormund_b": "field",
    "alicent_a": "court", "alicent_b": "court", "corlys_a": "court", "corlys_b": "court",
    "smallfolk_a": "court", "smallfolk_b": "court", "smallfolk_c": "court",
    "philosophy_a": "decoy", "philosophy_b": "decoy",
    "false_daeron_a": "decoy", "false_daeron_b": "decoy",
    "tumbleton_a": "decoy", "tumbleton_b": "decoy",
    "book_a": "final", "book_b": "final",
    "scoreboard_a": "final", "scoreboard_b": "final", "conclusion": "final",
}


# ----------------------------------------------------------------------------- image build
def _cover(path, w, h):
    im = Image.open(path).convert("RGB")
    s = max(w / im.width, h / im.height)
    im = im.resize((max(w, int(im.width * s + 0.5)), max(h, int(im.height * s + 0.5))), Image.LANCZOS)
    return im.crop(((im.width - w) // 2, (im.height - h) // 2,
                    (im.width - w) // 2 + w, (im.height - h) // 2 + h))


def _vignette(im, strength=0.55):
    w, h = im.size
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    d.ellipse([-w * 0.25, -h * 0.35, w * 1.25, h * 1.35], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(w // 8))
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(im, Image.blend(im, dark, strength), m)


# background is pre-scaled 1.15x so zoompan never reveals an edge
BGW, BGH = int(W * 1.15), int(H * 1.15)


DIAGRAM_FIT = 0.86        # keeps the whole diagram inside the frame at MAX zoom, not just at 1.0


def build_bg(kind, name, out):
    """Full-frame background plate (drifts under the static overlay)."""
    if kind in ("full", "map"):
        # A diagram's edge labels are the content, so it must survive the drift. The canvas is
        # 1.15x the frame and zoompan crops up to 5.5% more, so the diagram is fitted to 86%
        # of the canvas and floats on a blurred mat -- it grows slightly, never gets clipped.
        im = Image.open(A(name)).convert("RGB")
        s = min(BGW * DIAGRAM_FIT / im.width, BGH * DIAGRAM_FIT / im.height)
        r = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
        bg = _cover(A(name), BGW, BGH).filter(ImageFilter.GaussianBlur(44))
        bg = Image.blend(bg, Image.new("RGB", (BGW, BGH), (4, 5, 8)), 0.74)
        bg.paste(r, ((BGW - r.width) // 2, (BGH - r.height) // 2))
        im = bg
    elif kind == "plate":
        im = _vignette(_cover(A(name), BGW, BGH), 0.45)
    else:  # card / cards -> dim, blurred plate so the card reads as the subject
        im = _cover(A(name), BGW, BGH).filter(ImageFilter.GaussianBlur(14))
        im = Image.blend(im, Image.new("RGB", (BGW, BGH), (5, 6, 10)), 0.62)
        im = _vignette(im, 0.5)
    im.save(out)


def _paste_card(canvas, path, box_h, x, y):
    c = Image.open(path).convert("RGBA")
    s = box_h / c.height
    c = c.resize((int(c.width * s), box_h), Image.LANCZOS)
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle([x + 10, y + 14, x + c.width + 14, y + box_h + 16],
                                 fill=(0, 0, 0, 150))
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(16)))
    canvas.alpha_composite(c, (x, y))
    return c.width


def _canon_chip(d, label):
    f = bp._F(bp._ARIAL, 19)
    tw = d.textlength(label, font=f)
    x, y = 54, H - 62
    d.rounded_rectangle([x, y, x + tw + 34, y + 34], radius=6,
                        fill=(10, 12, 18, 225), outline=bp.GOLD, width=1)
    d.text((x + 17, y + 8), label, font=f, fill=bp.GOLD)


LINE_H, HEAD_BOTTOM = 66, H - 96


def _headline(ov, text):
    d = ImageDraw.Draw(ov)
    f = bp._F(bp._COPPER, 52)
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if d.textlength(t, font=f) > CONTENT_W - 140 and cur:
            lines.append(cur); cur = word
        else:
            cur = t
    lines.append(cur)
    # scrim so the headline reads over a bright plate
    sc = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sc)
    top = HEAD_BOTTOM - LINE_H * len(lines) - 60
    for y in range(top, H):
        a = int(190 * min(1.0, (y - top) / 150.0))
        sd.line([(0, y), (CONTENT_W + 60, y)], fill=(4, 5, 9, a))
    ov.alpha_composite(sc)
    d = ImageDraw.Draw(ov)
    y = HEAD_BOTTOM - LINE_H * len(lines)
    d.rectangle([54, y - 14, 58, y + LINE_H * len(lines) - 8], fill=bp.GOLD)
    for i, ln in enumerate(lines):
        d.text((84, y + LINE_H * i), ln, font=f, fill=(240, 232, 216, 255))


# Cards are 1920x1080 landscape compositions, so they are scaled into the 1086px content
# column left of the rail rather than pasted at native size (which ran under the rail).
CARD_W, CARD_Y = 1018, 155
PAIR_W, PAIR_Y1, PAIR_Y2 = 818, 55, 545


def build_overlay(kind, spec, out, rail_png=None, headline=None, canon=None):
    """Static RGBA overlay: cards + rail + captions. Never drifts (stable UI, moving art)."""
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if kind == "card":
        ch = int(CARD_W * H / W)
        # sit high when a caption occupies the lower third, otherwise centre -- a card parked high
        # over empty black reads as unfinished
        y = CARD_Y if headline else (H - ch) // 2
        _paste_card(ov, A(spec), ch, (CONTENT_W - CARD_W) // 2, y)
    elif kind == "cards":
        if headline:
            raise ValueError("a stacked pair leaves no room for the caption; open the segment "
                             "on a plate or a single card instead")
        h = int(PAIR_W * H / W)
        for n, y in zip(spec, (PAIR_Y1, PAIR_Y2)):
            _paste_card(ov, A(n), h, (CONTENT_W - PAIR_W) // 2, y)
    if rail_png:
        ov.alpha_composite(Image.open(rail_png).convert("RGBA"))
    if headline:
        _headline(ov, headline)
    if canon:
        _canon_chip(ImageDraw.Draw(ov), canon)
    ov.save(out)


# ----------------------------------------------------------------------------- render
def _drift_vf(idx, frames):
    """Duration-aware drift. A fixed per-frame step hits the zoom ceiling on long shots and
    the picture freezes -- the defect that made the quiz cards look like stills."""
    step = 0.055 / max(frames, 1)
    z_in = f"min(1.0+{step:.7f}*on,1.055)"
    z_out = f"max(1.055-{step:.7f}*on,1.0)"
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    pan = [(z_in, cx, cy), (z_out, cx, cy),
           (z_in, f"iw/2-(iw/zoom/2)+(on/{max(frames,1)})*90", cy),
           (z_in, f"iw/2-(iw/zoom/2)-(on/{max(frames,1)})*90", cy),
           (z_out, cx, f"ih/2-(ih/zoom/2)+(on/{max(frames,1)})*70"),
           (z_in, cx, f"ih/2-(ih/zoom/2)-(on/{max(frames,1)})*70")][idx % 6]
    return (f"zoompan=z='{pan[0]}':x='{pan[1]}':y='{pan[2]}':d=1:s={W}x{H}:fps={FPS},"
            f"trim=end_frame={frames}")


def render_visual(bg, ov, frames, idx, out):
    # The fade must happen BEFORE the rail composites, or the "always-on" state rail dips to
    # black at all 119 cuts and reads as a flicker. Art transitions; the rail stays locked.
    vf = (f"[0:v]{_drift_vf(idx, frames)},fade=t=in:st=0:d=0.12[b];"
          f"[b][1:v]overlay=0:0:format=auto,format=yuv420p[v]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-loop", "1", "-framerate", str(FPS), "-i", bg,
           "-loop", "1", "-framerate", str(FPS), "-i", ov,
           "-filter_complex", vf, "-map", "[v]",
           "-frames:v", str(frames), "-r", str(FPS),
           "-c:v", "libx264", "-preset", "medium", "-crf", "19",
           "-pix_fmt", "yuv420p", out]
    subprocess.run(cmd, check=True, capture_output=True)


_SELF_MTIME = os.path.getmtime(os.path.abspath(__file__))


def _fresh(p):
    """Reuse a rendered clip only if it postdates the current build script -- editing the
    renderer must invalidate every clip, or a partial rebuild silently ships mixed output."""
    return os.path.exists(p) and os.path.getsize(p) > 0 and os.path.getmtime(p) > _SELF_MTIME


def dur_of(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", p], capture_output=True, text=True)
    return float(r.stdout.strip())


def srt_time(t):
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def main():
    t0 = time.time()
    os.makedirs(WORK, exist_ok=True)
    script = json.load(open(f"{OUT}/script.json"))
    segs = script["segments"]
    missing = [s["id"] for s in segs if s["id"] not in P]
    if missing:
        raise SystemExit(f"no playlist for: {missing}")

    # 1. rail PNGs (one per authored state)
    rails = {}
    for k, st in STATES.items():
        p = f"{WORK}/rail_{k}.png"
        bp.render_board(st, p)
        rails[k] = p
    print(f"rails      : {len(rails)} states", flush=True)

    # 2. narration
    costs = []
    for i, s in enumerate(segs):
        p = f"{WORK}/vo_{i:02d}.mp3"
        if not (os.path.exists(p) and os.path.getsize(p) > 1000):
            ep.generate_tts(s["narration"], p, voice=VOICE)
        s["_vo"] = p
        s["_dur"] = dur_of(p)
    chars = sum(len(s["narration"]) for s in segs)
    tts_cost = chars / 1_000_000 * 30.0
    total_vo = sum(s["_dur"] for s in segs) + SEG_GAP * (len(segs) - 1)
    print(f"narration  : {len(segs)} segments, {chars} chars, {total_vo/60:.2f} min, ${tts_cost:.2f}")

    # 3. visuals
    clips, cuts, srt, t = [], [], [], 0.0
    vi = 0
    for si, s in enumerate(segs):
        pl = P[s["id"]]
        rail = rails[SEG_STATE[s["id"]]]
        n_f_total = int(round(s["_dur"] * FPS)) + int(round(SEG_GAP * FPS) if si < len(segs) - 1 else 0)
        per = [n_f_total // len(pl)] * len(pl)
        per[-1] += n_f_total - sum(per)
        # sentence-level SRT from character-proportional timing
        sents = [x.strip() for x in s["narration"].replace("? ", "?|").replace(". ", ".|")
                 .replace("! ", "!|").split("|") if x.strip()]
        ct = t
        for sent in sents:
            sd = s["_dur"] * len(sent) / max(len(s["narration"]), 1)
            srt.append((ct, ct + sd, sent)); ct += sd
        for k, item in enumerate(pl):
            kind = item[0]
            bgp, ovp = f"{WORK}/bg_{vi:03d}.png", f"{WORK}/ov_{vi:03d}.png"
            clip = f"{WORK}/c_{vi:03d}.mp4"
            src = item[1] if kind in ("plate", "full", "map") else item[-1]
            if _fresh(clip):
                clips.append(clip)
                cuts.append({"t": round(t, 2), "seg": s["id"], "kind": kind,
                             "asset": item[1] if isinstance(item[1], str) else "+".join(item[1]),
                             "frames": per[k]})
                t += per[k] / FPS
                vi += 1
                continue
            build_bg(kind, src, bgp)
            full_bleed = kind in ("full", "map")
            build_overlay(kind, item[1], ovp,
                          rail_png=None if full_bleed else rail,
                          headline=s["caption"] if k == 0 else None,
                          # code-drawn diagrams already carry their own canon footer
                          canon=None if full_bleed else s["canon"])
            render_visual(bgp, ovp, per[k], vi, clip)
            clips.append(clip)
            cuts.append({"t": round(t, 2), "seg": s["id"], "kind": kind,
                         "asset": item[1] if isinstance(item[1], str) else "+".join(item[1]),
                         "frames": per[k]})
            t += per[k] / FPS
            vi += 1
        print(f"  [{time.time()-t0:6.1f}s] {si+1:2d}/{len(segs)} {s['id']:16s} "
              f"{s['_dur']:5.1f}s -> {len(pl)} visuals", flush=True)

    # 4. hard-cut concat (stream copy: no crossfade mush, no re-encode)
    lst = f"{WORK}/concat.txt"
    with open(lst, "w") as f:
        for c in clips:
            f.write(f"file '{os.path.abspath(c)}'\n")
    silent = f"{WORK}/video_silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", silent], check=True)

    # 5. narration track with gaps, then 2-pass loudnorm to -14 LUFS / -1 dBTP
    parts = []
    for i, s in enumerate(segs):
        parts.append(s["_vo"])
        if i < len(segs) - 1:
            g = f"{WORK}/gap.wav"
            if not os.path.exists(g):
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                                "-i", f"anullsrc=r=44100:cl=mono", "-t", str(SEG_GAP), g], check=True)
            parts.append(g)
    ain = []
    for p in parts:
        ain += ["-i", p]
    fg = "".join(f"[{i}:a]aformat=sample_rates=44100:channel_layouts=mono[a{i}];"
                 for i in range(len(parts)))
    fg += "".join(f"[a{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[out]"
    vo = f"{WORK}/narration.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + ain +
                   ["-filter_complex", fg, "-map", "[out]", vo], check=True)
    m = subprocess.run(["ffmpeg", "-hide_banner", "-i", vo, "-af",
                        "loudnorm=I=-14:TP=-1:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    j = json.loads(m[m.rfind("{"):m.rfind("}") + 1])
    af = (f"loudnorm=I=-14:TP=-1:measured_I={j['input_i']}:measured_TP={j['input_tp']}"
          f":measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}"
          f":offset={j['target_offset']}:linear=true")
    final = f"{OUT}/hotd_s3e3.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", vo,
                    "-af", af, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart", final], check=True)

    # 6. SRT
    with open(f"{OUT}/hotd_s3e3.srt", "w", encoding="utf8") as f:
        for i, (a, b, txt) in enumerate(srt, 1):
            f.write(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{txt}\n\n")
    json.dump({"visuals": len(clips), "cuts": cuts,
               "tts_cost_usd": round(tts_cost, 3),
               "runtime_s": round(dur_of(final), 2)},
              open(f"{OUT}/build_report.json", "w"), indent=2)

    print(f"\nvideo      : {final}  {dur_of(final)/60:.2f} min")
    print(f"visuals    : {len(clips)}  (one every {dur_of(final)/len(clips):.1f}s)")
    print(f"spend      : ${tts_cost:.2f} (TTS only; every image was already generated)")
    print(f"wall clock : {(time.time()-t0)/60:.1f} min")
    return final


if __name__ == "__main__":
    main()
