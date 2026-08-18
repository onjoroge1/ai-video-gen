"""Code-drawn S3E4 assets: character cards, dragon cards and the §12.4 diagram set.

Reuses the S3E3 card template and palette wholesale (hotd_assets). Two things are episode-specific
and cannot be reused:

  * STATUS LINES. Every returning character's status changed in Episode 4 (spec §9), so cards are
    rebuilt rather than reused -- they are code-drawn and free, so there is no reason to ship a card
    saying "throne taken" over narration about a policing crackdown.
  * THE ANALYTICAL MODEL. Episode 3 turned on three forms of power; Episode 4 turns on the §6
    four-part model (TERRITORY / FIREPOWER / LEGITIMACY / HUMAN COST). That is a new graphic, and it
    recurs through the video as the spine.

Run: /opt/homebrew/bin/python3 hotd_s3e4_assets.py
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageDraw

import board_pipeline as BP
import hotd_assets as HA

W, H = HA.W, HA.H
PACK = "house-of-dragons/house_of_the_dragon_s3e4_complete_asset_pack/images"
OUT = f"{PACK}/generated"
HA.register_sigil_dir(f"{OUT}/sigils")

EP = "SHOW CONFIRMED — Episode 4"


def _wrap(text, n):
    """hotd_assets has no wrap helper; diagrams need one for narrow columns."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if len(t) > n and cur:
            lines.append(cur); cur = w
        else:
            cur = t
    lines.append(cur)
    return lines

# ---------------------------------------------------------------------------- character cards
# (name, faction, role, status, tone, sigil, stem, note)   statuses follow spec §9 "After".
CHARACTERS = [
    # --- Team Black and court ---
    ("Rhaenyra Targaryen", "black", "Queen on the Iron Throne", "cannot burn Tumbleton", "key",
     "targaryen", "01_char_rhaenyra", "Holds the city; her strongest weapon is now unusable"),
    ("Daemon Targaryen", "black", "Prince Consort · rides Caraxes", "secures the Vale gold", "neutral",
     "targaryen", "02_char_daemon", "Protects Rhaena by deceiving his own queen"),
    ("Mysaria", "black", "Mistress of Whispers", "suspects the Vale story", "good",
     "whisper", "03_char_mysaria", "The one person tracking the inconsistency"),
    ("Grand Maester Orwyle", "black", "Grand Maester", "serves the new court", "neutral",
     "maester", "04_char_orwyle", "Kept on for continuity of records and counsel"),
    ("Torrhen Manderly", "black", "Council lord", "presses the food question", "neutral",
     "smallfolk", "05_char_torrhen", "Links the blockade to the shortage"),
    ("Corlys Velaryon", "black", "Lord of the Tides", "withdraws from court", "bad",
     "velaryon", "06_char_corlys", "Refused legitimisation; sends his son in his place"),
    ("Alyn of Hull", "black", "Sent in his father's place", "serves without a name", "neutral",
     "velaryon", "07_char_alyn", "Attends the council Corlys will no longer attend"),
    ("Hugh Hammer", "black", "Dragonrider · Vermithor", "set to watch Tumbleton", "neutral",
     "targaryen", "08_char_hugh", "Enormous firepower, no political discipline"),
    ("Ulf White", "black", "Dragonrider · Silverwing", "restricted by the queen", "bad",
     "targaryen", "09_char_ulf", "Resents the control that came with the reward"),
    ("Rhaena Targaryen", "black", "Dragonrider · Sheepstealer", "hidden in the Vale", "key",
     "targaryen", "10_char_rhaena", "Refuses to return; her safety rests on Daemon's lie"),
    ("Jeyne Arryn", "black", "Lady of the Vale", "pays the crown's price", "good",
     "arryn", "11_char_jeyne_arryn", "The gold Daemon was sent to collect"),
    # --- Team Green and associated figures ---
    ("Ormund Hightower", "green", "Lord of Oldtown", "occupies Tumbleton", "bad",
     "hightower", "20_char_ormund", "Fifteen thousand men and a town full of hostages"),
    ("Daeron Targaryen", "green", "The real prince · rides Tessarion", "made to kill", "bad",
     "targaryen", "21_char_daeron", "Positioned by Ormund as a king in waiting"),
    ("Alicent Hightower", "green", "Prisoner · unwilling adviser", "explains Ormund", "neutral",
     "hightower", "22_char_alicent", "Tells Rhaenyra what her cousin actually wants"),
    ("Helaena Targaryen", "green", "Confined with her mother", "pregnancy implied", "bad",
     "targaryen", "23_char_helaena", "STRONG INFERENCE — never stated outright on screen"),
    ("Aegon II Targaryen", "green", "Deposed king", "hiding near Rook's Rest", "bad",
     "targaryen", "24_char_aegon", "At the bottom of the order he used to sit atop"),
    ("Larys Strong", "green", "Master of Whisperers", "outside the capital", "neutral",
     "strong", "25_char_larys", "Moves with Aegon, away from the court"),
    ("Criston Cole", "green", "Lord Commander", "marching the Riverlands", "bad",
     "kingsguard", "26_char_criston", "Chooses a purpose the war has already overtaken"),
    ("Gwayne Hightower", "green", "Rides with Criston", "in the Riverlands", "neutral",
     "hightower", "27_char_gwayne", "Hightower blood attached to a failing column"),
    ("Aemond Targaryen", "green", "Vhagar's rider", "missing", "bad",
     "targaryen", "28_char_aemond_missing", "Ormund stops waiting for him"),
    ("Alys Rivers", "green", "At Harrenhal", "keeps her own counsel", "neutral",
     "witch", "29_char_alys", "Remains where Aemond was last known to be"),
    # --- Episode civilians and supporting figures ---
    ("Lord Glendon Footly", "neutral", "Lord of Tumbleton", "declared for Rhaenyra", "bad",
     "footly", "40_char_glendon_footly", "His allegiance did not protect his town"),
    ("Lady Sharis Footly", "neutral", "Lady of Tumbleton", "hosts the occupier", "bad",
     "footly", "41_char_sharis_footly", "Compelled to quarter Ormund in her own house"),
    ("Garrick of Whitegrove", "neutral", "Hightower soldier", "accused of murder", "bad",
     "smallfolk", "42_char_garrick", "The man Ormund's justice is performed upon"),
    ("Leon", "neutral", "Tumbleton townsman", "his household broken", "bad",
     "smallfolk", "43_char_leon", "The occupation measured in one family"),
    ("Janos", "neutral", "Tumbleton townsman", "under occupation", "bad",
     "smallfolk", "44_char_janos", "One of the residents standing between a dragon and a town"),
    ("A Vale shepherd", "neutral", "Unidentified", "killed to keep a secret", "dead",
     "smallfolk", "45_char_vale_shepherd", "The cost of Daemon protecting his daughter"),
]

# ---------------------------------------------------------------------------- dragon cards
DRAGONS = [
    ("Tessarion", "green", "Daeron's mount", "with the Hightower host", "bad", "50_dragon_tessarion"),
    ("Vermithor", "black", "Hugh Hammer's mount", "watching Tumbleton", "neutral", "51_dragon_vermithor"),
    ("Silverwing", "black", "Ulf White's mount", "grounded by the queen", "neutral", "52_dragon_silverwing"),
    ("Caraxes", "black", "Daemon's mount", "in the Vale", "good", "53_dragon_caraxes"),
    ("Sheepstealer", "black", "Rhaena's mount", "hidden in the Vale", "key", "54_dragon_sheepstealer"),
    ("Sunfyre", "green", "Aegon's mount", "status uncertain", "bad", "55_dragon_sunfyre"),
    ("Vhagar", "green", "Aemond's mount", "location unknown", "bad", "56_dragon_vhagar"),
    ("Meleys", "black", "Rhaenys's mount", "remains at Rook's Rest", "dead", "57_dragon_meleys"),
]


def build_characters():
    os.makedirs(OUT, exist_ok=True)
    for name, fac, role, status, tone, sig, stem, note in CHARACTERS:
        HA.character_card(name, fac, role, status, tone, sig, f"{OUT}/{stem}.png", note)
    print(f"  {len(CHARACTERS)} character cards")


def build_dragons():
    os.makedirs(OUT, exist_ok=True)
    for name, fac, role, status, tone, stem in DRAGONS:
        sig = f"dragon_{name.lower()}" if HA.find_sigil(f"dragon_{name.lower()}") else "targaryen"
        HA.character_card(name, fac, role, status, tone, sig, f"{OUT}/{stem}.png", "DRAGON")
    print(f"  {len(DRAGONS)} dragon cards")


# ---------------------------------------------------------------------------- diagrams (§12.4)
def _plate(title, subtitle="", label=EP):
    return HA._plate(title, subtitle, label)


def g_four_axes(out):
    """§6 -- the recurring model AND its episode-4 state table. The spine of the whole video.

    The four definitions alone leave most of the frame empty, and this graphic recurs, so it also
    carries §6's per-figure state table. That makes it a board the audience can re-read each time
    rather than a title card they have already absorbed.
    """
    im, d = _plate("The four things that decide this war",
                   "Every scene in the episode moves at least one of them")
    cols = [("TERRITORY", "Who controls the location?", BP.STEEL, 104),
            ("FIREPOWER", "Which forces can act?", BP.GOLD, 536),
            ("LEGITIMACY", "Whose claim draws allegiance?", BP.GREEN, 968),
            ("HUMAN COST", "Who restricts the choices?", BP.RED, 1400)]
    for t, body, col, x in cols:
        d.rounded_rectangle([x, 240, x + 386, 372], radius=14, fill=(14, 17, 22, 240),
                            outline=col, width=3)
        BP._track(d, (x + 26, 264), t, BP._F(BP._COPPER, 30), col, tr=3)
        for k, line in enumerate(_wrap(body, 28)):
            d.text((x + 26, 308 + k * 28), line, font=BP._F(BP._ARIAL, 22), fill=(180, 186, 194))

    # §6 episode-4 state
    xs = [104, 430, 760, 1090, 1440]
    heads = ["", "TERRITORY", "FIREPOWER", "LEGITIMACY", "HUMAN CONSTRAINT"]
    for x, hd in zip(xs, heads):
        d.text((x, 420), hd, font=BP._F(BP._ARIAL_B, 20), fill=(136, 142, 152))
    d.line([(104, 450), (1816, 450)], fill=BP.GOLD, width=2)
    rows = [("Rhaenyra", "King's Landing", "Multiple dragons", "Contested by Faith and rivals",
             "Cannot burn a Black-aligned town", BP.STEEL),
            ("Ormund", "Occupied Tumbleton", "15,000 men; Tessarion", "Daeron's blood claim",
             "Uses residents as protection", BP.RED),
            ("Daeron", "None of his own", "Tessarion", "Son of Viserys and Alicent",
             "Controlled by Ormund", BP.RED),
            ("Aegon", "Hiding near Rook's Rest", "Sunfyre uncertain", "Still the Green king",
             "No court, army or authority", BP.GOLD),
            ("Daemon", "Securing Vale gold", "Caraxes", "Authority through Rhaenyra",
             "Protecting Rhaena means lying", BP.STEEL),
            ("Rhaena", "Hidden in the Vale", "Sheepstealer", "Targaryen dragonrider",
             "Believes returning exposes her", BP.GREEN)]
    for i, r in enumerate(rows):
        y = 474 + i * 68
        BP._track(d, (xs[0], y + 6), r[0].upper(), BP._F(BP._COPPER, 24), r[5], tr=2)
        for j in range(1, 5):
            for k, line in enumerate(_wrap(r[j], 27)):
                d.text((xs[j], y + k * 26), line, font=BP._F(BP._ARIAL, 21), fill=(190, 196, 204))
        d.line([(104, y + 56), (1816, y + 56)], fill=(38, 42, 50), width=1)
    d.text((104, 906), "Episode 4 turns on the fourth column. Tumbleton's people are the constraint.",
           font=BP._F(BP._ARIAL, 28), fill=(214, 200, 172))
    im.save(out); return out


def g_no_burn(out):
    """§12.4 #1 -- why Tumbleton cannot be burned."""
    im, d = _plate("Why Tumbleton cannot be burned",
                   "The town declared for Rhaenyra before Ormund took it")
    rows = [("The obvious answer", "Send a dragon and destroy the occupying army", BP.STEEL),
            ("What is inside the town", "Fifteen thousand soldiers quartered in civilian homes", BP.GOLD),
            ("Who else is inside", "Residents who declared for Rhaenyra, held as protection", BP.RED),
            ("What dragonfire cannot do", "Separate the army from the people sheltering it", BP.RED),
            ("So the weapon becomes", "Politically unusable while the town still stands", BP.RED)]
    for i, (lab, val, col) in enumerate(rows):
        y = 246 + i * 106
        d.text((104, y), lab.upper(), font=BP._F(BP._ARIAL_B, 24), fill=(140, 146, 156))
        d.text((104, y + 34), val, font=BP._F(BP._GEO_B, 36), fill=col)
    d.text((104, 800), "Occupying a Black-aligned town converts its residents into armour.",
           font=BP._F(BP._ARIAL, 29), fill=(214, 200, 172))
    im.save(out); return out


def g_plan_change(out):
    """§12.4 #2 -- Ormund's original plan versus the revised plan."""
    im, d = _plate("Ormund's plan, before and after",
                   "Losing Vhagar did not stop him; it changed what he was building")
    for i, (head, col, items) in enumerate([
            ("ORIGINAL PLAN", BP.STEEL, ["Hold Tumbleton as a forward base",
                                         "Wait for Aemond and Vhagar",
                                         "Win the war with the largest dragon",
                                         "Restore Aegon to the throne"]),
            ("REVISED PLAN", BP.RED, ["Stop waiting for Aemond",
                                      "Use Daeron's blood claim instead",
                                      "Make Daeron publicly capable of killing",
                                      "Build a king he controls"])]):
        x = 104 + i * 880
        d.rounded_rectangle([x, 246, x + 800, 720], radius=16, fill=(14, 17, 22, 240),
                            outline=col, width=3)
        BP._track(d, (x + 34, 282), head, BP._F(BP._COPPER, 34), col, tr=4)
        d.line([(x + 34, 336), (x + 766, 336)], fill=col, width=2)
        for j, it in enumerate(items):
            yy = 370 + j * 76
            d.ellipse([x + 38, yy + 10, x + 52, yy + 24], fill=col)
            d.text((x + 70, yy), it, font=BP._F(BP._ARIAL, 28), fill=(196, 202, 210))
    d.text((104, 766), "The target was never only the town. It was a replacement claimant.",
           font=BP._F(BP._ARIAL, 30), fill=(214, 200, 172))
    im.save(out); return out


def g_daeron_id(out):
    """§12.4 #3 -- the real Daeron identity card."""
    im, d = _plate("The real Daeron", "The prince the decoy was standing in for")
    rows = [("PREVIOUSLY", "A hidden squire in Ormund's household", BP.STEEL),
            ("NOW", "Publicly presented as Viserys and Alicent's son", BP.GOLD),
            ("HIS DRAGON", "Tessarion, with the Hightower host", BP.RED),
            ("HIS VALUE", "A blood claim Ormund can direct", BP.RED),
            ("HIS FIRST ACT", "An execution he did not choose", BP.RED)]
    for i, (lab, val, col) in enumerate(rows):
        y = 246 + i * 106
        d.text((104, y), lab, font=BP._F(BP._ARIAL_B, 24), fill=(140, 146, 156))
        d.text((104, y + 34), val, font=BP._F(BP._GEO_B, 36), fill=col)
    d.text((104, 800), "A claimant with a dragon is worth more to Ormund than a missing one.",
           font=BP._F(BP._ARIAL, 29), fill=(214, 200, 172))
    im.save(out); return out


def g_aegon_inventory(out):
    """§12.4 #4 -- Aegon's kingship inventory."""
    im, d = _plate("What is left of Aegon's kingship",
                   "He is still a king by claim and by nothing else")
    rows = [("A crown", 0.0, "gone with the city"),
            ("A court", 0.0, "no one to command"),
            ("An army", 0.0, "no men of his own"),
            ("His dragon", 0.15, "Sunfyre's condition uncertain"),
            ("Public authority", 0.0, "no one knows he lives"),
            ("A blood claim", 0.85, "the one thing nobody can take"),
            ("Anonymity", 0.9, "worth more to him now than status")]
    for i, (lab, frac, note) in enumerate(rows):
        y = 258 + i * 82
        d.text((104, y), lab, font=BP._F(BP._ARIAL_B, 28), fill=(206, 212, 220))
        col = BP.GREEN if frac > 0.6 else (BP.GOLD if frac > 0.1 else BP.RED)
        HA._bar(d, 470, y + 4, 620, frac, col)
        d.text((1140, y), note, font=BP._F(BP._ARIAL, 25), fill=(168, 174, 184))
    d.text((104, 852), "Being believed dead may protect him better than being obeyed ever did.",
           font=BP._F(BP._ARIAL, 29), fill=(214, 200, 172))
    im.save(out); return out


def g_dragonseed(out):
    """§12.4 #5 -- Rhaenyra's dragonseed-control problem."""
    im, d = _plate("Rhaenyra's dragonrider problem",
                   "The power she added is the power she cannot direct")
    for i, (name, mount, gain, risk) in enumerate([
            ("Hugh Hammer", "Vermithor", "Sent to watch Tumbleton", "Loyalty untested under pressure"),
            ("Ulf White", "Silverwing", "Given access to the queen", "Resents being restricted"),
            ("Addam of Hull", "Seasmoke", "Serves willingly", "Still denied a name")]):
        y = 250 + i * 190
        d.rounded_rectangle([104, y, 1816, y + 160], radius=14, fill=(14, 17, 22, 235),
                            outline=BP.STEEL, width=2)
        BP._track(d, (136, y + 24), name.upper(), BP._F(BP._COPPER, 32), BP.WHITE, tr=3)
        d.text((136, y + 76), mount, font=BP._F(BP._ARIAL, 26), fill=BP.GOLD)
        d.text((620, y + 34), "GAIN", font=BP._F(BP._ARIAL_B, 22), fill=(140, 146, 156))
        d.text((620, y + 66), gain, font=BP._F(BP._ARIAL, 27), fill=BP.GREEN)
        d.text((1180, y + 34), "RISK", font=BP._F(BP._ARIAL_B, 22), fill=(140, 146, 156))
        d.text((1180, y + 66), risk, font=BP._F(BP._ARIAL, 27), fill=BP.RED)
    d.text((104, 840), "Dragons obey riders. Riders obey the queen only as far as they choose to.",
           font=BP._F(BP._ARIAL, 30), fill=(214, 200, 172))
    im.save(out); return out


def g_graffiti_loop(out):
    """§12.4 #6 -- graffiti to crackdown to resentment."""
    im, d = _plate("The loop she cannot police her way out of",
                   "Suppressing the insult manufactures the grievance")
    HA._chain(d, [("INSULT\nappears on\nthe walls", BP.GOLD),
                  ("CRACKDOWN\nGold Cloaks\nsent out", BP.RED),
                  ("RESENTMENT\npunishment\nseen in public", BP.RED),
                  ("MORE INSULT\nthe claim\nspreads wider", BP.RED)], y=360)
    d.text((104, 700), "Each pass through the loop costs her more legitimacy than the last insult did.",
           font=BP._F(BP._ARIAL, 30), fill=(214, 200, 172))
    d.text((104, 760), "INTERPRETATION — the episode shows the mechanism; it does not name it.",
           font=BP._F(BP._ARIAL, 26), fill=(150, 156, 166))
    im.save(out); return out


def g_parallel_deceptions(out):
    """§12.4 #7 -- Ormund and Daemon's parallel deceptions."""
    im, d = _plate("Two men, the same method",
                   "Both protect a child by controlling what everyone else believes")
    for i, (head, col, rows) in enumerate([
            ("ORMUND", BP.RED, [("Protects", "his family's claim to the throne"),
                                ("By hiding", "that the surrender was a feint"),
                                ("Cost to others", "a town used as a shield"),
                                ("What it builds", "a king who owes him everything")]),
            ("DAEMON", BP.STEEL, [("Protects", "his daughter Rhaena"),
                                  ("By hiding", "who Sheepstealer's rider is"),
                                  ("Cost to others", "a shepherd killed to keep it quiet"),
                                  ("What it builds", "a lie inside his own marriage")])]):
        x = 104 + i * 880
        d.rounded_rectangle([x, 246, x + 800, 740], radius=16, fill=(14, 17, 22, 240),
                            outline=col, width=3)
        BP._track(d, (x + 34, 282), head, BP._F(BP._COPPER, 36), col, tr=4)
        d.line([(x + 34, 340), (x + 766, 340)], fill=col, width=2)
        for j, (lab, val) in enumerate(rows):
            yy = 376 + j * 90
            d.text((x + 34, yy), lab.upper(), font=BP._F(BP._ARIAL_B, 22), fill=(140, 146, 156))
            d.text((x + 34, yy + 30), val, font=BP._F(BP._ARIAL, 28), fill=(198, 204, 212))
    d.text((104, 786), "INTERPRETATION — the parallel is the episode's argument about fathers.",
           font=BP._F(BP._ARIAL, 27), fill=(150, 156, 166))
    im.save(out); return out


def g_helaena_inference(out):
    """§12.4 #8 -- the pregnancy inference card. Labelled as inference, on the asset itself."""
    im, d = _plate("Helaena: what the episode shows and does not say",
                   "Handle as inference, not as fact", "STRONG SHOW INFERENCE — Episode 4")
    for i, (lab, val, col) in enumerate([
            ("WHAT IS SHOWN", "Staging and reactions that strongly imply a pregnancy", BP.GOLD),
            ("WHAT IS SAID", "No on-screen confirmation", BP.RED),
            ("WHY IT MATTERS", "Another Targaryen child changes the succession maths", BP.STEEL),
            ("WHY IT IS DANGEROUS", "It ends her ability to stay politically invisible", BP.RED),
            ("HOW WE LABEL IT", "Strong show inference — never stated as confirmed", BP.GOLD)]):
        y = 246 + i * 106
        d.text((104, y), lab, font=BP._F(BP._ARIAL_B, 24), fill=(140, 146, 156))
        d.text((104, y + 34), val, font=BP._F(BP._GEO_B, 34), fill=col)
    im.save(out); return out


def g_scoreboard(out):
    """§12.4 #9 -- episode winner scoreboard."""
    im, d = _plate("Who won Episode 4?", "Gains against the new weaknesses that came with them")
    hdr = [("", 104), ("GAINED", 620), ("LOST", 1080), ("NEW WEAKNESS", 1450)]
    for t, x in hdr:
        d.text((x, 236), t, font=BP._F(BP._ARIAL_B, 24), fill=(140, 146, 156))
    d.line([(104, 272), (1816, 272)], fill=BP.GOLD, width=2)
    rows = [("Ormund", "A town, a shield, a king in waiting", "Vhagar's reinforcement",
             "Vermithor now watches him", BP.GREEN),
            ("Daeron", "Political importance", "Moral distance from Ormund",
             "Every faction's target", BP.GOLD),
            ("Daemon", "Gold and his daughter's trust", "Honesty with his queen",
             "Mysaria suspects him", BP.GOLD),
            ("Rhaenyra", "Vale gold and an aerial watch", "Public confidence, Corlys",
             "Her crackdown breeds the revolt", BP.RED),
            ("Rhaena", "Her father's protection", "Any easy way back to court",
             "Safety rests on a lie", BP.GOLD),
            ("Aegon", "Anonymity", "The last of his visible status",
             "His pride resists hiding", BP.RED)]
    for i, (who, g, l, wk, col) in enumerate(rows):
        y = 296 + i * 92
        BP._track(d, (104, y), who.upper(), BP._F(BP._COPPER, 28), col, tr=3)
        for txt, x in ((g, 620), (l, 1080), (wk, 1450)):
            d.text((x, y + 2), txt, font=BP._F(BP._ARIAL, 24), fill=(190, 196, 204))
        d.line([(104, y + 74), (1816, y + 74)], fill=(40, 44, 52), width=1)
    d.text((104, 860), "INTERPRETATION — Ormund gains the most and takes on the least new risk.",
           font=BP._F(BP._ARIAL, 28), fill=(214, 200, 172))
    im.save(out); return out


def g_show_vs_book(out):
    """§12.4 #10 -- show timeline versus book timeline."""
    im, d = _plate("Show timeline versus book timeline",
                   "The adaptation reorders and compresses — label them separately",
                   "SHOW CHANGE / BOOK ACCOUNT — Episode 4")
    for i, (lane, col, beats) in enumerate([
            ("TELEVISION", BP.STEEL, ["Daeron kept hidden, then revealed",
                                      "Tumbleton taken by a feint",
                                      "Rhaena found by Daemon in the Vale",
                                      "Ormund manufactures a claimant"]),
            ("FIRE & BLOOD", BP.GOLD, ["Daeron introduced as a known prince",
                                       "Tumbleton falls in its own chapter",
                                       "No direct equivalent to this meeting",
                                       "Testimony conflicts by source"])]):
        y = 300 + i * 250
        BP._track(d, (104, y - 44), lane, BP._F(BP._COPPER, 32), col, tr=4)
        d.line([(104, y + 30), (1816, y + 30)], fill=col, width=3)
        for j, b in enumerate(beats):
            x = 150 + j * 430
            d.ellipse([x - 9, y + 21, x + 9, y + 39], fill=col)
            yy = y + 58
            for line in _wrap(b, 26):
                d.text((x - 40, yy), line, font=BP._F(BP._ARIAL, 23), fill=(186, 192, 200)); yy += 30
    d.text((104, 860), "The book is an in-universe history compiled from conflicting sources — not a camera record.",
           font=BP._F(BP._ARIAL, 26), fill=(168, 174, 184))
    im.save(out); return out


def g_board_map(out):
    """§7 -- the five-zone opening board.

    Deliberately NOT drawn on the Westeros map: the supplied map has verified pin coordinates for
    only four of these five places, and Rook's Rest would have to be placed by guesswork. Inventing
    a coordinate on a real map is the one failure this asset set has already made once. A code-drawn
    zone board carries the same information (who is where, and what it costs them) and claims no
    geography. Actual geography stays in the annotated strategic map.
    """
    im, d = _plate("Where everyone stands before Episode 4",
                   "Five active zones — five separate problems")
    zones = [("TUMBLETON", BP.RED, ["Ormund Hightower", "Daeron · Tessarion", "15,000 men",
                                    "Occupied residents"]),
             ("KING'S LANDING", BP.STEEL, ["Rhaenyra", "Alicent · Helaena", "Hugh · Vermithor",
                                           "Ulf · Silverwing"]),
             ("ROOK'S REST", BP.GOLD, ["Aegon II", "Larys Strong", "Sunfyre — uncertain",
                                       "No court, no army"]),
             ("HARRENHAL", BP.GOLD, ["Criston Cole", "Gwayne Hightower", "Alys Rivers",
                                     "Aemond — absent"]),
             ("THE VALE", BP.GREEN, ["Daemon · Caraxes", "Rhaena — hidden", "Sheepstealer",
                                     "Jeyne Arryn's gold"])]
    for i, (name, col, rows) in enumerate(zones):
        x = 74 + i * 356
        d.rounded_rectangle([x, 244, x + 330, 748], radius=14, fill=(14, 17, 22, 240),
                            outline=col, width=3)
        d.rounded_rectangle([x, 244, x + 330, 300], radius=14, fill=(*col[:3], 42))
        BP._track(d, (x + 22, 260), name, BP._F(BP._COPPER, 26), col, tr=2)
        for j, r in enumerate(rows):
            yy = 336 + j * 92
            d.ellipse([x + 24, yy + 8, x + 36, yy + 20], fill=col)
            for k, line in enumerate(_wrap(r, 22)):
                d.text((x + 50, yy + k * 30), line, font=BP._F(BP._ARIAL, 24),
                       fill=(196, 202, 210))
    d.text((74, 796), "Aemond and Vhagar are missing. Every plan in the episode is built around that gap.",
           font=BP._F(BP._ARIAL, 30), fill=(214, 200, 172))
    im.save(out); return out


DIAGRAMS = [
    ("60_graphic_four_axes", g_four_axes),
    ("61_graphic_why_no_burn", g_no_burn),
    ("62_graphic_plan_change", g_plan_change),
    ("63_graphic_real_daeron_id", g_daeron_id),
    ("64_graphic_aegon_inventory", g_aegon_inventory),
    ("65_graphic_dragonseed_control", g_dragonseed),
    ("66_graphic_graffiti_loop", g_graffiti_loop),
    ("67_graphic_parallel_deceptions", g_parallel_deceptions),
    ("68_graphic_helaena_inference", g_helaena_inference),
    ("69_graphic_winner_scoreboard", g_scoreboard),
    ("6A_graphic_show_vs_book", g_show_vs_book),
    ("6B_graphic_board_map", g_board_map),
]


def build_diagrams():
    os.makedirs(OUT, exist_ok=True)
    for stem, fn in DIAGRAMS:
        try:
            fn(f"{OUT}/{stem}.png")
        except Exception as e:
            print(f"  {stem:34s} FAIL {type(e).__name__}: {e}")
    print(f"  {len(DIAGRAMS)} diagrams")


def build_all():
    build_characters()
    build_dragons()
    build_diagrams()
    n = len([f for f in os.listdir(OUT) if f.endswith(".png")])
    print(f"\n{OUT}: {n} png")


if __name__ == "__main__":
    build_all()
