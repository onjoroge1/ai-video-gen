"""Code-drawn S3E7 assets: the diagram set from the spec's §5 diagram specifications.

No character or dragon cards are built here. E7 draws its people from the supplied portrait library,
and the two cards it needs for people with no portrait -- Ulf White and Hugh Hammer -- already exist in
the E3 and E4 packs.

Each diagram is written as an ordered sequence of claims, because the reveal animation derives its
beats from bands of ink in the finished PNG: a diagram whose rows ARE its argument builds into that
argument. Nothing here depicts a real person.

Diagram A is the video's visual thesis and the spec is explicit about how it must read: the appointment
lane gets one-way arrows, the recognition lane gets two-way lines. That asymmetry is the argument, so
it is drawn rather than described.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import board_pipeline as BP
from hotd import assets as A

W, H = A.W, A.H
PACK = "house-of-dragons/house_of_the_dragon_s3e7_complete_asset_pack/images"
OUT = f"{PACK}/generated"
A.register_pack(PACK)

EP = "SHOW CONFIRMED — Episode 7"
INT = "INTERPRETATION — Episode 7"
BOOK = "BOOK ACCOUNT / SHOW CHANGE — Episode 7"
GOLD, IVORY, DIM = (214, 176, 96), (240, 232, 216), (150, 158, 168)
OXBLOOD, GREEN, PEARL = (196, 74, 66), (108, 148, 112), (196, 204, 214)

CHARACTERS: list = []          # portraits come from the supplied library
DRAGONS: list = []


def _plate(title, subtitle="", label=EP):
    return A.plate(title, subtitle, label)          # -> (Image, ImageDraw)


def _foot(d, text, y=None, col=(214, 200, 172)):
    d.text((104, y or (H - 168)), text, font=BP._F(BP._ARIAL, 29), fill=col)


def _arrow(d, x0, y, x1, col, width=3, both=False):
    """One-way for appointment, two-way for recognition. The spec calls this distinction the thesis."""
    d.line([(x0, y), (x1, y)], fill=col, width=width)
    hz = 13
    d.polygon([(x1, y), (x1 - hz, y - hz // 2 - 2), (x1 - hz, y + hz // 2 + 2)], fill=col)
    if both:
        d.polygon([(x0, y), (x0 + hz, y - hz // 2 - 2), (x0 + hz, y + hz // 2 + 2)], fill=col)


def _lane(d, y0, head, col, rows, both):
    d.rounded_rectangle([104, y0, W - 104, y0 + 300], radius=16,
                        fill=(14, 17, 22, 240), outline=col, width=3)
    BP._track(d, (132, y0 + 26), head, BP._F(BP._COPPER, 32), col, tr=3)
    for i, (left, right) in enumerate(rows):
        y = y0 + 104 + i * 56
        d.text((132, y - 14), left, font=BP._F(BP._ARIAL_B, 27), fill=IVORY)
        _arrow(d, 132 + 470, y, 132 + 470 + 190, col, both=both)
        d.text((132 + 700, y - 14), right, font=BP._F(BP._ARIAL_B, 27), fill=IVORY)


def g_recognition_vs_appointment(out):
    im, d = _plate("Appointed, or recognized", "The difference the episode keeps testing", INT)
    _lane(d, 232, "APPOINTED BY PEOPLE", OXBLOOD, [
        ("Queen", "assassin"),
        ("Lord", "promised title"),
        ("Ruler", "commanded prophecy"),
        ("Parent", "claimed protection"),
    ], both=False)
    _lane(d, 572, "RECOGNIZED BY DRAGONS", GOLD, [
        ("Aegon", "Sunfyre"),
        ("Rhaena", "Sheepstealer"),
        ("Helaena", "Dreamfyre"),
        ("Ulf", "Silverwing"),
    ], both=True)
    _foot(d, "One lane points one way. The other answers back.")
    im.save(out); return out


def g_four_dragon_collision(out):
    im, d = _plate("Four dragons, one river", "The Blue Fork contest")
    # scale-neutral markers; the spec requires the disclaimer, so it is drawn, not assumed
    rows = [("SYRAX", "Rhaenyra", "arrives to find Daemon", GOLD),
            ("SHEEPSTEALER", "Rhaena", "attacks Syrax", (168, 132, 92)),
            ("SEASMOKE", "Addam", "joins the fight", PEARL),
            ("CARAXES", "Daemon", "overwhelms the wild dragon", OXBLOOD)]
    for i, (dg, rider, act, col) in enumerate(rows):
        y = 250 + i * 118
        d.rounded_rectangle([104, y, W - 104, y + 96], radius=14,
                            fill=(13, 16, 21, 236), outline=col, width=2)
        d.ellipse([132, y + 30, 168, y + 66], fill=col)
        d.text((196, y + 16), dg, font=BP._F(BP._COPPER, 34), fill=col)
        d.text((196, y + 58), f"rider: {rider}", font=BP._F(BP._ARIAL, 24), fill=DIM)
        d.text((760, y + 34), act, font=BP._F(BP._ARIAL_B, 27), fill=IVORY)
    d.text((104, 726), "Caraxes ends the contest. Rhaenyra removes Rhaena.",
           font=BP._F(BP._GEO_B, 34), fill=IVORY)
    _foot(d, "RELATIVE POSITIONS, NOT LITERAL SCALE", y=H - 132, col=DIM)
    im.save(out); return out


def g_illegitimate_offer(out):
    im, d = _plate("A title he does not hold", "Driftmark, promised by its captor", INT)
    layers = [("CURRENT HOLDER", "Corlys Velaryon", "Lord of the Tides", GOLD),
              ("CAPTOR", "Ormund Hightower", "physical custody, no lawful grant", GREEN),
              ("PROMISED RECIPIENT", "Ulf White", "offered the office for allegiance", OXBLOOD)]
    for i, (role, who, note, col) in enumerate(layers):
        y = 262 + i * 152
        d.rounded_rectangle([104, y, W - 104, y + 126], radius=16,
                            fill=(14, 17, 22, 240), outline=col, width=3)
        BP._track(d, (132, y + 22), role, BP._F(BP._ARIAL_B, 24), col, tr=3)
        d.text((132, y + 58), who, font=BP._F(BP._COPPER, 38), fill=IVORY)
        d.text((760, y + 66), note, font=BP._F(BP._ARIAL, 26), fill=DIM)
    d.text((104, 736), "Control of a person is not lawful control of the title.",
           font=BP._F(BP._GEO_B, 36), fill=IVORY)

    im.save(out); return out


def g_corlys_three_panels(out):
    im, d = _plate("Man, message, vacancy", "One prisoner, three uses", INT)
    panels = [("A PRISONER", "alive in Green custody", GOLD),
              ("A MESSAGE", "the signet finger sent to Alyn", OXBLOOD),
              ("A VACANCY", "a title Ormund can promise", GREEN)]
    cw = (W - 208 - 48) // 3
    for i, (head, note, col) in enumerate(panels):
        x = 104 + i * (cw + 24)
        d.rounded_rectangle([x, 268, x + cw, 700], radius=16,
                            fill=(14, 17, 22, 240), outline=col, width=3)
        BP._track(d, (x + 26, 296), head, BP._F(BP._COPPER, 30), col, tr=3)
        d.line([(x + 26, 348), (x + cw - 26, 348)], fill=col, width=2)
        for k, line in enumerate(A.wrap(note, 22)):
            d.text((x + 26, 380 + k * 36), line, font=BP._F(BP._ARIAL, 27), fill=IVORY)
        d.text((x + 26, 640), f"{i + 1} of 3", font=BP._F(BP._ARIAL_B, 24), fill=DIM)
    _foot(d, "The symbols move. The history does not.")
    im.save(out); return out


def g_name_stripped(out):
    im, d = _plate("What is left of a king", "Aegon, layer by layer", INT)
    rows = [("A THRONE", "held by Rhaenyra", False),
            ("A CROWN", "gone", False),
            ("A COURT", "scattered", False),
            ("AN ARMY", "not present", False),
            ("A HEALTHY BODY", "broken at Rook's Rest", False),
            ("A NAME", "Aegon", True)]
    for i, (lab, val, keep) in enumerate(rows):
        y = 252 + i * 92
        col = GOLD if keep else (86, 92, 102)
        d.rounded_rectangle([104, y, W - 104, y + 74], radius=12,
                            fill=(15, 18, 23, 232), outline=col, width=3 if keep else 2)
        d.text((132, y + 20), lab, font=BP._F(BP._COPPER, 32), fill=IVORY if keep else DIM)
        d.text((760, y + 24), val, font=BP._F(BP._ARIAL_B, 28), fill=col)
        if not keep:
            d.line([(132, y + 40), (700, y + 40)], fill=(120, 60, 56), width=3)
    _foot(d, "The question the scene asks: does the name alone command anything?")
    im.save(out); return out


def g_helaena_triptych(out):
    im, d = _plate("Three futures, one witness", "What the visions ask of her")
    cols = [("MOTHER", "childbirth, and a newborn taken away", PEARL),
            ("WEAPON", "mounted on Dreamfyre before a mob", OXBLOOD),
            ("SURVIVOR", "a farm, her children, and snow", (150, 170, 190))]
    cw = (W - 208 - 48) // 3
    for i, (head, note, col) in enumerate(cols):
        x = 104 + i * (cw + 24)
        d.rounded_rectangle([x, 268, x + cw, 690], radius=16,
                            fill=(14, 17, 22, 240), outline=col, width=3)
        BP._track(d, (x + 26, 296), head, BP._F(BP._COPPER, 30), col, tr=3)
        d.line([(x + 26, 348), (x + cw - 26, 348)], fill=col, width=2)
        for k, line in enumerate(A.wrap(note, 22)):
            d.text((x + 26, 382 + k * 36), line, font=BP._F(BP._ARIAL, 27), fill=IVORY)
    d.text((104, 724), "Incompatible versions, not a schedule of events.",
           font=BP._F(BP._GEO_B, 34), fill=IVORY)
    _foot(d, "Visions. Not confirmed outcomes.", y=H - 132, col=DIM)
    im.save(out); return out


def g_winner_matrix(out):
    im, d = _plate("Who won the episode", "Scored only at the end of Episode 7")
    rows = [("TERRITORY", "Rhaenyra", GOLD),
            ("IMMEDIATE STRATEGIC SURPRISE", "Ormund", GREEN),
            ("RESTORED INDEPENDENT AGENCY", "Aegon and Sunfyre", (222, 176, 88)),
            ("INFORMATION WITHOUT FREEDOM", "Helaena", PEARL),
            ("HIGHEST EMERGING HUMAN RISK", "smallfolk at Tumbleton and the Dragonpit", OXBLOOD)]
    for i, (lab, who, col) in enumerate(rows):
        y = 258 + i * 104
        d.rounded_rectangle([104, y, W - 104, y + 84], radius=12,
                            fill=(14, 17, 22, 238), outline=col, width=2)
        BP._track(d, (132, y + 16), lab, BP._F(BP._ARIAL_B, 23), col, tr=3)
        d.text((132, y + 46), who, font=BP._F(BP._GEO_B, 32), fill=IVORY)
    _foot(d, "No prediction of the coming battle.")
    im.save(out); return out


def g_show_vs_book(out):
    im, d = _plate("Show versus book", "Four changes already visible on screen", BOOK)
    pairs = [("Sheepstealer is claimed by Nettles", "the bond is given to Rhaena, and Daemon hides it"),
             ("Ulf and Hugh change sides at Tumbleton", "Ormund cultivates Ulf's resentment first"),
             ("Sunfyre survives Rook's Rest, injured", "his return answers Aegon's declaration"),
             ("Helaena is Dreamfyre's rider", "the bond appears inside a possible future")]
    d.rounded_rectangle([104, 244, W // 2 - 12, 720], radius=16,
                        fill=(22, 20, 16, 240), outline=(178, 158, 118), width=3)
    d.rounded_rectangle([W // 2 + 12, 244, W - 104, 720], radius=16,
                        fill=(14, 19, 16, 240), outline=GREEN, width=3)
    BP._track(d, (132, 268), "BOOK ACCOUNT", BP._F(BP._COPPER, 30), (204, 186, 148), tr=3)
    BP._track(d, (W // 2 + 40, 268), "SHOW CHANGE", BP._F(BP._COPPER, 30), GREEN, tr=3)
    for i, (bk, sh) in enumerate(pairs):
        y = 336 + i * 96
        for k, line in enumerate(A.wrap(bk, 34)):
            d.text((132, y + k * 30), line, font=BP._F(BP._ARIAL, 24), fill=(226, 214, 190))
        for k, line in enumerate(A.wrap(sh, 34)):
            d.text((W // 2 + 40, y + k * 30), line, font=BP._F(BP._ARIAL, 24), fill=IVORY)
    _foot(d, "No outcomes beyond what Episode 7 already shows.", col=DIM)
    im.save(out); return out


DIAGRAMS = [
    ("70_graphic_recognition_vs_appointment", g_recognition_vs_appointment),
    ("71_graphic_four_dragon_collision", g_four_dragon_collision),
    ("72_graphic_illegitimate_offer", g_illegitimate_offer),
    ("73_graphic_corlys_three_panels", g_corlys_three_panels),
    ("74_graphic_name_stripped", g_name_stripped),
    ("75_graphic_helaena_triptych", g_helaena_triptych),
    ("76_graphic_winner_matrix", g_winner_matrix),
    ("77_graphic_show_vs_book", g_show_vs_book),
]


def build_all():
    os.makedirs(OUT, exist_ok=True)
    stems = A.build_diagrams(DIAGRAMS, OUT)
    A.overflow_check(OUT, stems)
    print(f"  diagrams   {len(stems)} (all {W}x{H})")


if __name__ == "__main__":
    build_all()


# ------------------------------------------------------------------------------ thumbnail
def build_thumbnail(out=None):
    """The spec's composition, built from library masters rather than generated.

    Aegon low and left, Sunfyre across the right two-thirds, and the rider-dragon bond line burning
    gold between them over an almost-black forest.

    The portraits are FRAMED, not cut out. Keying these masters off their studio sweep does not work --
    hotd.figure documents the measurement: subject and backdrop overlap in colour, so no single
    threshold exists, and pasting them raw leaves two grey rectangles that read as a broken export.
    Framing is the same treatment the video uses, so the thumbnail matches the product.

    NOT MET, and it cannot be met from these assets: the spec's accuracy locks require Sunfyre to show
    major battle scarring and facial asymmetry, and Aegon to show his current injuries and impaired
    posture. Both library masters are pristine. Rendering them as-is is the honest option; inventing
    scars is not. Closing that gap needs a damage-overlay asset or a new master.
    """
    from PIL import Image, ImageDraw, ImageFilter
    from hotd import figure as FIG
    from hotd import thumbnail as T

    LIB = "house-of-dragons/hotd-character-library/masters"
    out = out or f"{PACK}/thumbnail/90_thumbnail_he_still_knew_him.png"
    os.makedirs(os.path.dirname(out), exist_ok=True)

    base = T.cover(f"{OUT}/locations/82_loc_crownlands_forest.png")
    base = Image.blend(base.convert("RGB"), Image.new("RGB", base.size, (3, 4, 7)), 0.66)
    im = base.convert("RGBA")
    tw, th = im.size

    # Sunfyre gets the right two-thirds; Aegon a smaller panel left of him, both framed
    sun = (int(tw * 0.44), int(th * 0.06), int(tw * 0.97), int(th * 0.74))
    aeg = (int(tw * 0.05), int(th * 0.20), int(tw * 0.30), int(th * 0.72))
    im.alpha_composite(FIG.panel(f"{LIB}/sunfyre-master.png", sun, radius=22, anchor="center"))
    im.alpha_composite(FIG.panel(f"{LIB}/aegon-ii-targaryen-master.png", aeg, radius=22))

    # the bond line reads as a link between the two panels, not as a HUD element
    line = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    ld = ImageDraw.Draw(line)
    ld.line([(aeg[2] - 6, int(th * 0.44)), (sun[0] + 6, int(th * 0.40))],
            fill=(244, 208, 118, 240), width=10)
    im.alpha_composite(line.filter(ImageFilter.GaussianBlur(8)))
    im.alpha_composite(line.filter(ImageFilter.GaussianBlur(1)))

    T.corner_scrim(im, y_start=int(th * 0.62), x_full=0.66, x_end=0.96, alpha=214)
    # bottom_pad is the TOP of the last line, so it has to clear the glyph height or the second
    # line is cut off by the frame edge
    T.title(im, ["HE STILL", "KNEW HIM"], size=112, x=54, bottom_pad=152)
    T.badge(im, "HOUSE OF THE DRAGON  ·  S3E7")
    im.convert("RGB").save(out)
    return out
