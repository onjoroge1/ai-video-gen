"""Code-drawn diagrams for "Why Rhaenyra Cannot Burn Tumbleton" (The Dragon Council).

The spec's §7 asks for twelve new original assets. Nine of them are information graphics, which is
what this module draws: they cost nothing, are deterministic, and cannot drift from the narration the
way a generated illustration can. The other three -- Tumbleton occupied, the Footly residence, and
Reach farmland -- already exist in the S3E3/S3E4/S3E5 packs, so nothing needs generating for them.

Two constraints from the spec drive the drawing choices:

  * "Civilians must appear as individuals at least twice; do not reduce them entirely to abstract
    dots." Two graphics therefore draw people as figures with heads and shoulders rather than tokens.
  * "Never present 'human shield' as a phrase used by Ormund or Rhaenyra." Every graphic that carries
    the idea is labelled INTERPRETATION, so the reading is attributed to the channel on screen.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import board_pipeline as BP
from hotd import assets as A

W, H = 1920, 1080
PACK = "house-of-dragons/dragon_council_tumbleton_asset_pack/images"
OUT = f"{PACK}/generated"
A.register_pack(PACK)

EP = "SHOW CONFIRMED — Episode 4"
INF = "STRONG SHOW INFERENCE — Episode 4"
INT = "INTERPRETATION — Episode 4"
BOOK = "BOOK CONTEXT — NO FUTURE SPOILERS"

GOLD, IVORY, DIM = (214, 176, 96), (240, 232, 216), (150, 158, 168)
# the spec's colour language, §8: Blacks charcoal/burgundy/gold, Hightowers deep green/silver,
# civilians warm ochre, human cost ember red
BLACKS, GREEN, OCHRE, EMBER = (170, 92, 96), (108, 148, 112), (206, 166, 96), (198, 78, 58)
PEARL = (196, 204, 214)

CHARACTERS: list = []          # people come from the supplied portrait library
DRAGONS: list = []


def _plate(title, subtitle="", label=EP):
    return A.plate(title, subtitle, label)


def _foot(d, text, y=None, col=(214, 200, 172)):
    d.text((104, y or (H - 168)), text, font=BP._F(BP._ARIAL, 29), fill=col)


def _person(d, cx, y, h, col, child=False):
    """One civilian, drawn as a person rather than a dot.

    The spec's QC gate requires that "Tumbleton civilians remain visible as people, not just casualty
    numbers", so the crowd graphics use a head-and-shoulders glyph. A child glyph is shorter with a
    proportionally larger head, which reads as a family at a glance.
    """
    hr = int(h * (0.30 if child else 0.24))
    d.ellipse([cx - hr, y, cx + hr, y + hr * 2], fill=col)
    bw = int(hr * (1.5 if child else 1.7))
    d.polygon([(cx - bw, y + h), (cx - int(bw * 0.72), y + hr * 2 + 4),
               (cx + int(bw * 0.72), y + hr * 2 + 4), (cx + bw, y + h)], fill=col)


def _soldier(d, cx, y, h, col):
    """A Hightower soldier: same scale as a civilian, but a helm and a spear line, so a mixed group
    reads as mixed rather than as two colours of the same shape."""
    hr = int(h * 0.24)
    d.ellipse([cx - hr, y, cx + hr, y + hr * 2], fill=col)
    d.rectangle([cx - hr - 2, y + hr - 3, cx + hr + 2, y + hr + 3], fill=(226, 232, 238))
    bw = int(hr * 1.7)
    d.polygon([(cx - bw, y + h), (cx - int(bw * 0.72), y + hr * 2 + 4),
               (cx + int(bw * 0.72), y + hr * 2 + 4), (cx + bw, y + h)], fill=col)
    d.line([(cx + bw + 8, y - 8), (cx + bw + 8, y + h)], fill=(210, 216, 224), width=3)


def _card(d, box, col, head, lines, head_font=30, fill=(14, 17, 22, 238)):
    x0, y0, x1, y1 = box
    d.rounded_rectangle([x0, y0, x1, y1], radius=14, fill=fill, outline=col, width=3)
    BP._track(d, (x0 + 26, y0 + 20), head, BP._F(BP._COPPER, head_font), col, tr=3)
    for i, ln in enumerate(lines):
        d.text((x0 + 26, y0 + 74 + i * 40), ln, font=BP._F(BP._ARIAL, 26), fill=IVORY)


# --------------------------------------------------------------------------- 1. power board
def g_four_parts_of_power(out):
    """The spine of the whole video: four resources, and only the fourth decides what is allowed."""
    im, d = _plate("The four parts of power",
                   "A ruler needs all four; only one of them sets the limit", INT)
    quads = [("TERRITORY", "who physically holds the ground", "Ormund occupies the town", GREEN),
             ("FIREPOWER", "who can destroy the enemy", "Rhaenyra, without question", BLACKS),
             ("LEGITIMACY", "whom the population accepts", "Tumbleton declared for Rhaenyra", OCHRE),
             ("HUMAN COST", "what using power does to your own", "the deciding resource", EMBER)]
    for i, (name, sub, who, col) in enumerate(quads):
        cx, cy = 104 + (i % 2) * 872, 240 + (i // 2) * 300
        _card(d, (cx, cy, cx + 812, cy + 258), col, name,
              [sub, "", who], head_font=36)
    _foot(d, "She holds the first three in different degrees. The fourth decides what she may do.")
    im.save(out)
    return out


# --------------------------------------------------------------------------- 2. strategic map
def g_reach_map(out):
    """Parchment map with a fixed orientation.

    The spec pins screen geography -- King's Landing east/right, Tumbleton west/left -- and requires a
    compass, because a map that silently flips is worse than no map.
    """
    im, d = _plate("The road the armies use", "Tumbleton sits between the Reach and the capital", EP)
    d.rounded_rectangle([104, 232, W - 104, 812], radius=18,
                        fill=(30, 26, 20, 242), outline=(178, 158, 118), width=3)
    # river and road, drawn as fixed geometry so no arrow can change direction unnarrated
    d.line([(300, 700), (620, 610), (900, 560), (1240, 520), (1600, 470)],
           fill=(96, 118, 132), width=7, joint="curve")
    d.line([(360, 640), (760, 560), (1180, 500), (1560, 430)], fill=(150, 132, 96), width=4)
    # Labels sit ABOVE their marker with a leader line, so neither one lands on the road or the river.
    # Drawn over a scrim: parchment plus a thin road plus 24px type is unreadable without one.
    for x, y, name, sub, col, side in (
            (470, 545, "TUMBLETON", "declared for Rhaenyra, now occupied", OCHRE, 1),
            (1580, 430, "KING'S LANDING", "Rhaenyra's seat", BLACKS, -1)):
        lw = max(BP._tw(d, name, BP._F(BP._COPPER, 34)), BP._tw(d, sub, BP._F(BP._ARIAL, 24))) + 36
        lx = x + 26 if side > 0 else x - 26 - lw
        ly = y - 116
        d.rounded_rectangle([lx, ly, lx + lw, ly + 92], radius=10,
                            fill=(20, 17, 13, 234), outline=col, width=2)
        d.text((lx + 18, ly + 12), name, font=BP._F(BP._COPPER, 34), fill=IVORY)
        d.text((lx + 18, ly + 56), sub, font=BP._F(BP._ARIAL, 24), fill=DIM)
        d.line([(x, y), (lx + (0 if side > 0 else lw), ly + 92)], fill=col, width=2)
        d.ellipse([x - 13, y - 13, x + 13, y + 13], fill=col)
    # Ormund's approach: one arrow, one reason, both kept clear of the panel edge
    d.line([(212, 742), (416, 606)], fill=GREEN, width=6)
    d.polygon([(428, 598), (398, 604), (412, 628)], fill=GREEN)
    lab = "Ormund marches up from the Reach"
    lw = BP._tw(d, lab, BP._F(BP._ARIAL_B, 26)) + 36
    d.rounded_rectangle([140, 654, 140 + lw, 712], radius=10,
                        fill=(16, 20, 17, 234), outline=GREEN, width=2)
    d.text((158, 668), lab, font=BP._F(BP._ARIAL_B, 26), fill=GREEN)
    # compass, because the spec asks for one
    cx, cy = W - 232, 306
    d.ellipse([cx - 46, cy - 46, cx + 46, cy + 46], outline=(178, 158, 118), width=2)
    d.line([(cx, cy + 32), (cx, cy - 32)], fill=IVORY, width=3)
    d.polygon([(cx, cy - 42), (cx - 9, cy - 24), (cx + 9, cy - 24)], fill=IVORY)
    d.text((cx - 7, cy - 74), "N", font=BP._F(BP._ARIAL_B, 22), fill=IVORY)
    d.text((cx + 52, cy - 10), "E", font=BP._F(BP._ARIAL_B, 22), fill=DIM)
    _foot(d, "Orientation is fixed for every map in this video: the capital is east.")
    im.save(out)
    return out


# --------------------------------------------------------------------------- 3. army dissolves
def g_army_in_the_town(out):
    """Soldiers quartered among families. Drawn as people, per the spec's civilian rule."""
    im, d = _plate("An army hidden in plain sight",
                   "Ormund does not camp outside the walls; he moves inside them", EP)
    # left: the army as a formation, separable
    d.rounded_rectangle([104, 236, 900, 792], radius=16,
                        fill=(14, 19, 16, 240), outline=GREEN, width=3)
    BP._track(d, (132, 262), "OUTSIDE THE TOWN", BP._F(BP._COPPER, 30), GREEN, tr=3)
    for r in range(4):
        for c in range(7):
            _soldier(d, 190 + c * 100, 360 + r * 100, 62, GREEN)
    d.text((132, 748), "a target dragonfire can separate", font=BP._F(BP._ARIAL, 26), fill=DIM)
    # right: the same army interleaved with families
    d.rounded_rectangle([W - 900, 236, W - 104, 792], radius=16,
                        fill=(26, 22, 16, 240), outline=EMBER, width=3)
    BP._track(d, (W - 872, 262), "INSIDE THE TOWN", BP._F(BP._COPPER, 30), EMBER, tr=3)
    mix = [(GREEN, 0), (OCHRE, 0), (OCHRE, 1), (GREEN, 0), (OCHRE, 0), (OCHRE, 1), (GREEN, 0)]
    for r in range(4):
        for c, (col, child) in enumerate(mix):
            x = W - 830 + c * 100
            if col is GREEN:
                _soldier(d, x, 360 + r * 100, 62, col)
            else:
                _person(d, x, 360 + r * 100 + (10 if child else 0), 62 - (12 if child else 0),
                        col, child=bool(child))
    d.text((W - 872, 748), "no flame can pick one colour out of this",
           font=BP._F(BP._ARIAL, 26), fill=EMBER)
    _foot(d, "His army does not stand outside waiting to be burned. It dissolves into the town.")
    im.save(out)
    return out


# --------------------------------------------------------------------------- 4. fire spread
def g_fire_spread(out):
    """Open field versus dense town: the same weapon, two completely different blast radii."""
    im, d = _plate("The same flame, two results",
                   "Precision is a property of the ground, not of the dragon", INT)
    d.rounded_rectangle([104, 236, 900, 792], radius=16,
                        fill=(16, 20, 18, 240), outline=GREEN, width=3)
    BP._track(d, (132, 262), "OPEN FIELD", BP._F(BP._COPPER, 30), GREEN, tr=3)
    d.polygon([(500, 340), (330, 660), (670, 660)], fill=(198, 78, 58, 120), outline=EMBER)
    for c in range(6):
        _soldier(d, 360 + c * 56, 600, 52, GREEN)
    d.text((132, 706), "the cone lands where it is aimed", font=BP._F(BP._ARIAL, 26), fill=DIM)
    d.text((132, 744), "collateral spread: contained", font=BP._F(BP._ARIAL_B, 26), fill=GREEN)

    d.rounded_rectangle([W - 900, 236, W - 104, 792], radius=16,
                        fill=(26, 20, 16, 240), outline=EMBER, width=3)
    BP._track(d, (W - 872, 262), "DENSE TOWN", BP._F(BP._COPPER, 30), EMBER, tr=3)
    # roofs catch, streets funnel: the fire branches instead of landing
    d.polygon([(1420, 340), (1330, 500), (1510, 500)], fill=(198, 78, 58, 120), outline=EMBER)
    for (x0, y0, x1, y1) in ((1330, 500, 1160, 690), (1510, 500, 1700, 690),
                             (1420, 500, 1420, 700), (1160, 690, 1080, 760),
                             (1700, 690, 1780, 760)):
        d.line([(x0, y0), (x1, y1)], fill=EMBER, width=6)
    for c in range(5):
        _person(d, 1180 + c * 130, 620, 56, OCHRE, child=c % 2 == 1)
    d.text((W - 872, 706), "roofs catch, streets funnel the heat",
           font=BP._F(BP._ARIAL, 26), fill=DIM)
    d.text((W - 872, 744), "collateral spread: the whole town",
           font=BP._F(BP._ARIAL_B, 26), fill=EMBER)
    _foot(d, "Even if every Hightower dies, the survivors remember who brought the fire.")
    im.save(out)
    return out


# --------------------------------------------------------------------------- 5. decision tree
def g_decision_tree(out):
    """Attack, wait, or march: three routes, and the cost each one charges."""
    im, d = _plate("Every obvious answer costs her something",
                   "Three routes out of the same position", INT)
    routes = [("BURN IT", EMBER, ["Ormund loses an army", "Rhaenyra loses the reason",
                                 "for the war itself"], "MILITARY WIN, POLITICAL DEFEAT"),
              ("DO NOTHING", DIM, ["The people survive today", "Her banner is shown to be",
                                   "worth nothing on the ground"], "LEGITIMACY DRAINS AWAY"),
              ("SEND AN ARMY", OCHRE, ["Slower, and it gives him time", "to call allies and work on",
                                       "Daeron"], "THE LEAST BAD ROUTE")]
    for i, (name, col, lines, verdict) in enumerate(routes):
        x = 104 + i * 578
        d.rounded_rectangle([x, 300, x + 530, 616], radius=16,
                            fill=(14, 17, 22, 238), outline=col, width=3)
        BP._track(d, (x + 26, 324), name, BP._F(BP._COPPER, 34), col, tr=3)
        for j, ln in enumerate(lines):
            d.text((x + 26, 396 + j * 40), ln, font=BP._F(BP._ARIAL, 25), fill=IVORY)
        d.rounded_rectangle([x, 648, x + 530, 706], radius=10,
                            fill=(10, 12, 18, 235), outline=col, width=2)
        d.text((x + 26, 664), verdict, font=BP._F(BP._ARIAL_B, 24), fill=col)
        d.line([(x + 265, 252), (x + 265, 296)], fill=col, width=3)
    d.line([(369, 252), (1633, 252)], fill=DIM, width=3)
    d.text((104, 202), "ONE POSITION", font=BP._F(BP._COPPER, 30), fill=IVORY)
    _foot(d, "Ruling is the art of refusing victories that destroy the thing being won.")
    im.save(out)
    return out


# --------------------------------------------------------------------------- 6. civilian shield
def g_civilian_shield(out):
    """The video's central reading, labelled as a reading.

    "Human shield" is the channel's analytical description, never a phrase either character uses --
    so the plate carries the INTERPRETATION label and says so in the footer.
    """
    im, d = _plate("Occupation as armour",
                   "Loyal residents are worth more to him than neutral ones", INT)
    # overlapping scales of civilians around the green army
    for r in range(3):
        n = 9 - r
        for c in range(n):
            x = W // 2 - (n - 1) * 92 // 2 + c * 92
            y = 300 + r * 104
            d.rounded_rectangle([x - 42, y - 10, x + 42, y + 96], radius=30,
                                fill=(38, 32, 22, 240), outline=OCHRE, width=2)
            _person(d, x, y + 8, 62, OCHRE, child=(r + c) % 3 == 0)
            d.rectangle([x - 7, y + 74, x + 7, y + 92], fill=(52, 56, 66))    # a black banner
    d.rounded_rectangle([W // 2 - 220, 622, W // 2 + 220, 716], radius=14,
                        fill=(14, 19, 16, 242), outline=GREEN, width=3)
    BP._track(d, (W // 2 - 188, 648), "THE HIGHTOWER ARMY", BP._F(BP._COPPER, 28), GREEN, tr=3)
    d.text((W // 2 - 188, 682), "sheltered behind their loyalty",
           font=BP._F(BP._ARIAL, 24), fill=IVORY)
    _foot(d, "Their loyalty is the point: every death can be charged against Rhaenyra's claim.")
    d.text((104, H - 128), "\"Human shield\" is this channel's description of the effect, "
                           "not a phrase either commander uses.",
           font=BP._F(BP._ARIAL, 24), fill=DIM)
    im.save(out)
    return out


# --------------------------------------------------------------------------- 7. discipline
def g_discipline_not_mercy(out):
    """Why punishing his own soldier protects the occupation rather than the town."""
    im, d = _plate("Discipline is not mercy",
                   "What public punishment actually preserves", INT)
    _card(d, (104, 262, 900, 600), PEARL, "WHAT IT LOOKS LIKE",
          ["A soldier attacks a woman.", "Ormund punishes him publicly.",
           "The town sees justice done."], head_font=30)
    _card(d, (W - 900, 262, W - 104, 600), EMBER, "WHAT IT PRESERVES",
          ["An army that terrorises openly", "creates revolt, refugees,",
           "witnesses, and a reason to", "intervene."], head_font=30)
    d.rounded_rectangle([104, 646, W - 104, 748], radius=14,
                        fill=(26, 20, 16, 240), outline=EMBER, width=3)
    d.text((132, 668), "Controlled cruelty keeps the population present, frightened, and usable.",
           font=BP._F(BP._GEO_B, 30), fill=IVORY)
    d.text((132, 708), "The threat is disguised as a guarantee: your safety depends on obedience "
                       "to him, not rescue by her.", font=BP._F(BP._ARIAL, 24), fill=DIM)
    im.save(out)
    return out


# --------------------------------------------------------------------------- 8. reticle
def g_deterrence_not_liberation(out):
    """Vermithor over the roofs: a targeting problem that has no clean solution."""
    im, d = _plate("Deterrence, not liberation",
                   "What the largest dragon in the world can and cannot do", INF)
    d.rounded_rectangle([104, 236, W - 104, 792], radius=16,
                        fill=(20, 22, 28, 240), outline=(96, 112, 130), width=3)
    # rows of rooftops with mixed groups; every reticle over a mixed group turns red
    # (label, reticle colour, has a soldier, has a civilian, civilian is a child)
    groups = [("soldiers only", GREEN, True, False, False),
              ("soldiers and a family", EMBER, True, True, True),
              ("a family only", OCHRE, False, True, True),
              ("soldiers and elders", EMBER, True, True, False)]
    for i, (lab, col, has_sol, has_civ, child) in enumerate(groups):
        y = 320 + i * 122
        x0 = 200
        # a wider roof, drawn first, so both figures stand inside the house rather than on its edge
        d.polygon([(x0 - 66, y + 84), (x0 + 20, y - 20), (x0 + 106, y + 84)],
                  fill=(34, 38, 46), outline=(70, 78, 90))
        d.rectangle([x0 - 66, y + 84, x0 + 106, y + 92], fill=(44, 48, 58))
        if has_sol:
            _soldier(d, x0 - 16, y + 26, 54, GREEN)
        if has_civ:
            _person(d, x0 + 54, y + 30 + (6 if child else 0), 50 - (8 if child else 0),
                    OCHRE, child=child)
        d.ellipse([x0 - 74, y - 26, x0 + 118, y + 96], outline=col, width=4)
        d.line([(x0 + 22, y - 26), (x0 + 22, y - 4)], fill=col, width=3)
        d.line([(x0 + 22, y + 74), (x0 + 22, y + 96)], fill=col, width=3)
        d.text((x0 + 176, y + 20), lab, font=BP._F(BP._ARIAL_B, 28), fill=IVORY)
        d.text((x0 + 700, y + 20), "CLEAR" if col is GREEN else "NO CLEAN SHOT",
               font=BP._F(BP._ARIAL_B, 28), fill=col)
    _foot(d, "A dragon can threaten his perimeter or punish an army that leaves cover. "
             "It cannot un-quarter soldiers from families.")
    im.save(out)
    return out


# --------------------------------------------------------------------------- 9. five steps
def g_five_step_plan(out):
    """The least-bad answer, as five ordered moves rather than a slogan."""
    im, d = _plate("Separate the town from the army",
                   "Rhaenyra's least-bad response, in order", INT)
    steps = [("WATCH", "dragons stay outside as deterrence; scouts find barracks and commanders"),
             ("ISOLATE", "surround the roads and cut the supplies feeding fifteen thousand men"),
             ("EVACUATE", "open routes so the residents stop being the thing that protects him"),
             ("NEGOTIATE", "messengers offer terms while his position gets more expensive"),
             ("STRIKE", "only once soldiers are concentrated and visible, away from families")]
    for i, (name, sub) in enumerate(steps):
        y = 258 + i * 108
        col = OCHRE if i < 4 else BLACKS
        d.ellipse([116, y + 10, 176, y + 70], fill=(10, 12, 18), outline=col, width=3)
        d.text((139 if i != 0 else 140, y + 26), str(i + 1),
               font=BP._F(BP._GEO_B, 30), fill=col)
        d.rounded_rectangle([204, y, W - 104, y + 84], radius=12,
                            fill=(14, 17, 22, 238), outline=col, width=2)
        BP._track(d, (232, y + 14), name, BP._F(BP._COPPER, 28), col, tr=3)
        d.text((232, y + 48), sub, font=BP._F(BP._ARIAL, 25), fill=IVORY)
    _foot(d, "The objective is not to burn Tumbleton. It is to take the army out of it.")
    im.save(out)
    return out


# --------------------------------------------------------------------------- 10. three locks
def g_three_locks(out):
    """Ormund's shield has three conditions, and two of them are hers to remove."""
    im, d = _plate("Ormund's hidden weakness",
                   "The shield holds only while all three stay true", INF)
    locks = [("THE CIVILIANS STAY INSIDE", "Evacuation removes this one.", OCHRE, "she can"),
             ("HIS SOLDIERS STAY MIXED IN", "A sortie or redeployment removes this one.",
              GREEN, "he might"),
             ("SHE KEEPS VALUING THEIR LIVES", "Only she can remove this one, and it costs "
              "her the crown.", EMBER, "never")]
    for i, (name, sub, col, who) in enumerate(locks):
        y = 276 + i * 176
        d.rounded_rectangle([104, y, W - 104, y + 148], radius=16,
                            fill=(14, 17, 22, 238), outline=col, width=3)
        # a shackle glyph, closed
        cx = 196
        d.arc([cx - 34, y + 28, cx + 34, y + 96], 180, 360, fill=col, width=7)
        d.rounded_rectangle([cx - 42, y + 70, cx + 42, y + 124], radius=8,
                            fill=(10, 12, 18), outline=col, width=3)
        BP._track(d, (290, y + 34), name, BP._F(BP._COPPER, 32), col, tr=3)
        d.text((290, y + 84), sub, font=BP._F(BP._ARIAL, 26), fill=IVORY)
        d.text((W - 330, y + 58), who.upper(), font=BP._F(BP._ARIAL_B, 26), fill=col)
    _foot(d, "He has not made his army invincible. He has made patience worth more than fire.")
    im.save(out)
    return out


# --------------------------------------------------------------------------- 11. book card
def g_book_context(out):
    """A sealed chronicle. The seal is the point: it says what is deliberately withheld."""
    im, d = _plate("Book context", "Background only, with the outcome withheld", BOOK)
    d.rounded_rectangle([320, 250, W - 320, 780], radius=18,
                        fill=(30, 26, 20, 244), outline=(178, 158, 118), width=4)
    d.text((376, 306), "FIRE & BLOOD", font=BP._F(BP._COPPER, 46), fill=(206, 186, 146))
    d.line([(376, 372), (W - 376, 372)], fill=(140, 122, 92), width=2)
    for i, ln in enumerate([
            "Tumbleton is remembered as one of the Dance's decisive theatres.",
            "The book and the series do not reach it by the same chain of events.",
            "",
            "What matters now is that the show has turned the town into an",
            "argument before it becomes a battlefield."]):
        d.text((376, 420 + i * 46), ln, font=BP._F(BP._ARIAL, 28), fill=IVORY)
    cx, cy = W // 2, 700
    d.ellipse([cx - 74, cy - 46, cx + 74, cy + 62], fill=(126, 44, 40), outline=(88, 28, 26), width=3)
    BP._track(d, (cx - 62, cy - 8), "SEALED", BP._F(BP._COPPER, 24), (238, 214, 196), tr=2)
    _foot(d, "FUTURE EVENTS WITHHELD — no later combatants, betrayals, or outcomes appear here.",
          col=(206, 186, 146))
    im.save(out)
    return out


# --------------------------------------------------------------------------- 12. verdict board
def g_verdict_board(out):
    """The power board again, scored. Human cost glows over both columns rather than picking a side."""
    im, d = _plate("The verdict", "Who holds what, once the case is closed", INT)
    rows = [("TERRITORY", "SPLIT", "he occupies the ground she claims", PEARL),
            ("FIREPOWER", "RHAENYRA", "uncontested, and unusable here", BLACKS),
            ("LEGITIMACY", "LEANS RHAENYRA", "the town declared for her, and waits", OCHRE),
            ("HUMAN COST", "OVER BOTH", "the resource that decides what she may do", EMBER)]
    for i, (name, who, sub, col) in enumerate(rows):
        y = 258 + i * 122
        d.rounded_rectangle([104, y, W - 104, y + 100], radius=12,
                            fill=(14, 17, 22, 238), outline=col, width=3)
        BP._track(d, (132, y + 18), name, BP._F(BP._ARIAL_B, 24), col, tr=3)
        d.text((132, y + 52), sub, font=BP._F(BP._ARIAL, 25), fill=IVORY)
        tw = BP._tw(d, who, BP._F(BP._GEO_B, 32))
        d.text((W - 148 - tw, y + 34), who, font=BP._F(BP._GEO_B, 32), fill=col)
    _foot(d, "He captured a town she could not destroy and remain its queen.")
    im.save(out)
    return out


DIAGRAMS = [
    ("80_graphic_four_parts_of_power", g_four_parts_of_power),
    ("81_graphic_reach_map", g_reach_map),
    ("82_graphic_army_in_the_town", g_army_in_the_town),
    ("83_graphic_fire_spread", g_fire_spread),
    ("84_graphic_decision_tree", g_decision_tree),
    ("85_graphic_civilian_shield", g_civilian_shield),
    ("86_graphic_discipline_not_mercy", g_discipline_not_mercy),
    ("87_graphic_deterrence_not_liberation", g_deterrence_not_liberation),
    ("88_graphic_five_step_plan", g_five_step_plan),
    ("89_graphic_three_locks", g_three_locks),
    ("8A_graphic_book_context", g_book_context),
    ("8B_graphic_verdict_board", g_verdict_board),
]


def build_all():
    os.makedirs(OUT, exist_ok=True)
    stems = A.build_diagrams(DIAGRAMS, OUT)
    A.overflow_check(OUT, stems)
    print(f"  diagrams   {len(stems)} (all {W}x{H})")


# ------------------------------------------------------------------------------ thumbnail
def build_thumbnail(out=None):
    """The spec's composition: she has the power, he has made using it self-defeating.

    Rhaenyra on the left, the town's people as an actual barrier in the centre, Ormund calm in cold
    green on the right. The spec bars the Iron Throne, maps, extra dragons, Daeron and army formations
    from the frame, so nothing else is composited in.

    Portraits are FRAMED, never cut out. The library masters sit on an opaque studio sweep that no
    threshold can key -- hotd/portrait.py records the measurements -- so compositing one raw leaves a
    grey rectangle around the figure. The first attempt at this thumbnail did exactly that and looked
    broken. The framed panel is the same treatment the video uses, so the thumbnail also previews the
    format.
    """
    from PIL import Image, ImageDraw, ImageFilter
    from hotd import figure as FIG
    from hotd import thumbnail as T

    LIB = "house-of-dragons/hotd-character-library/masters"
    out = out or f"{PACK}/thumbnail/8C_thumbnail_she_cannot_burn_it.png"
    os.makedirs(os.path.dirname(out), exist_ok=True)

    base = T.cover("house-of-dragons/house_of_the_dragon_s3e3_complete_asset_pack/images/"
                   "generated/locations/16_loc_tumbleton_occupied.png")
    base = Image.blend(base.convert("RGB"), Image.new("RGB", base.size, (9, 7, 6)), 0.46)
    im = base.convert("RGBA")
    tw, th = im.size

    # She is the larger panel and the curiosity object; he is smaller, calm, and cold.
    rh = (int(tw * 0.020), int(th * 0.085), int(tw * 0.262), int(th * 0.760))
    orm = (int(tw * 0.700), int(th * 0.175), int(tw * 0.945), int(th * 0.735))
    im.alpha_composite(FIG.panel(f"{LIB}/rhaenyra-targaryen-master.png", rh,
                                 border=(226, 176, 104), anchor="top"))
    im.alpha_composite(FIG.panel(f"{LIB}/ormund-hightower-master.png", orm,
                                 border=(120, 158, 122), anchor="top"))

    # Dragonfire crosses from her side and stops dead against the townspeople.
    flame = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    fd = ImageDraw.Draw(flame)
    x_wall = int(tw * 0.438)
    fd.polygon([(rh[2] - 6, int(th * 0.40)), (x_wall, int(th * 0.20)), (x_wall, int(th * 0.88))],
               fill=(228, 116, 52, 190))
    im.alpha_composite(flame.filter(ImageFilter.GaussianBlur(14)))

    # The wall of people. The diagram glyph is deliberately chunky so it survives being small on a
    # crowded plate; at thumbnail scale that same glyph reads as a row of blobs, so the crowd here uses
    # human proportions -- smaller head, neck, narrower shoulders -- and stays inside the centre gap
    # rather than running under Ormund's panel.
    wall = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    wd = ImageDraw.Draw(wall)
    # Spacing is derived from shoulder width, not chosen by eye: seven figures in this gap made the
    # shoulder polygons overlap into one solid ochre slab, and the row stopped reading as people at all.
    OCHRE_W = (240, 206, 138)
    ph, base = int(th * 0.22), int(th * 0.70)
    x_end = orm[0] - 30
    n = 4
    step = (x_end - x_wall - 34) / float(n - 1)
    assert step > int(ph * 0.155) * 1.55 * 2, "crowd figures would overlap"
    for i in range(n):
        x = int(x_wall + 22 + i * step)
        small = i % 3 == 1
        h = int(ph * (0.74 if small else 1.0))
        hr = int(h * 0.155)
        top = base - h
        wd.ellipse([x - hr, top, x + hr, top + hr * 2], fill=OCHRE_W)
        wd.rectangle([x - int(hr * 0.42), top + hr * 2 - 2, x + int(hr * 0.42),
                      top + hr * 2 + 5], fill=OCHRE_W)
        sw = int(hr * 1.55)
        wd.polygon([(x - sw, base), (x - int(sw * 0.80), top + int(h * 0.30)),
                    (x + int(sw * 0.80), top + int(h * 0.30)), (x + sw, base)], fill=OCHRE_W)
    im.alpha_composite(wall)
    barrier = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    ImageDraw.Draw(barrier).line([(x_wall, int(th * 0.16)), (x_wall, int(th * 0.92))],
                                 fill=(248, 230, 180, 165), width=9)
    im.alpha_composite(barrier.filter(ImageFilter.GaussianBlur(10)))

    T.corner_scrim(im, y_start=int(th * 0.60), x_full=0.44, x_end=0.80, alpha=204)
    # bottom_pad is measured from the LAST line's TOP, not its baseline: at pad 54 the
    # descender row of "BURN IT" fell off the canvas.
    T.title(im, ["SHE CAN'T", "BURN IT"], size=112, x=48, bottom_pad=108)
    T.badge(im, "THE DRAGON COUNCIL  ·  TUMBLETON")
    im.convert("RGB").save(out)
    return out


if __name__ == "__main__":
    build_all()
