"""Code-drawn S3E5 assets: character cards, dragon cards and the §13.4 diagram set.

Statuses are §10's "After" states, not the previous episode's: Daemon has learned his power base was
massacred, Helaena has refused, Alicent has drunk the medicine herself, Tyland is alive. Cards are
free to redraw, so there is no reason to ship one that was true last week.

The twelve diagrams carry this episode's retention load. They are the shots hotd.reveal animates, so
each is written as an ordered sequence of claims -- the reveal derives its beats from the bands of ink
in the finished PNG, and a diagram whose rows ARE its argument builds into that argument.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import board_pipeline as BP
from hotd import assets as A

W, H = A.W, A.H
PACK = "house-of-dragons/house_of_the_dragon_s3e5_complete_asset_pack/images"
OUT = f"{PACK}/generated"
A.register_pack(PACK)

EP = "SHOW CONFIRMED — Episode 5"


def _plate(title, subtitle="", label=EP):
    return A.plate(title, subtitle, label)


def _rows(d, rows, y0=252, step=126, x=104):
    """Label/value rows: the shape the reveal turns into one claim per beat."""
    for i, (lab, val, col) in enumerate(rows):
        y = y0 + i * step
        d.text((x, y), lab.upper(), font=BP._F(BP._ARIAL_B, 24), fill=(140, 146, 156))
        d.text((x, y + 34), val, font=BP._F(BP._GEO_B, 36), fill=col)


def _cols(d, cols, y0=246, h=470, x0=104, gap=24):
    n = len(cols)
    cw = (W - 2 * x0 - (n - 1) * gap) // n
    for i, (head, col, items) in enumerate(cols):
        x = x0 + i * (cw + gap)
        d.rounded_rectangle([x, y0, x + cw, y0 + h], radius=16, fill=(14, 17, 22, 240),
                            outline=col, width=3)
        BP._track(d, (x + 26, y0 + 30), head, BP._F(BP._COPPER, 30), col, tr=3)
        d.line([(x + 26, y0 + 78), (x + cw - 26, y0 + 78)], fill=col, width=2)
        yy = y0 + 106
        for it in items:
            for k, line in enumerate(A.wrap(it, max(18, cw // 13))):
                d.text((x + 26, yy + k * 30), line, font=BP._F(BP._ARIAL, 25),
                       fill=(196, 202, 210))
            yy += 30 * len(A.wrap(it, max(18, cw // 13))) + 18


def _foot(d, text, y=None, col=(214, 200, 172)):
    d.text((104, y or (H - 172)), text, font=BP._F(BP._ARIAL, 29), fill=col)


# ---------------------------------------------------------------------------- character cards
CHARACTERS = [
    # --- Rhaenyra's court ---
    ("Rhaenyra Targaryen", "black", "Queen on the Iron Throne", "the war is inside", "key",
     "targaryen", "01_char_rhaenyra", "Learns her police force is the weak point"),
    ("Daemon Targaryen", "black", "Prince Consort · Caraxes", "his power base killed", "bad",
     "targaryen", "02_char_daemon", "Refuses her order in public"),
    ("Mysaria", "black", "Mistress of Whispers", "holds every secret", "good",
     "whisper", "03_char_mysaria", "Knows about Alicent, Helaena, Orwyle and the passage"),
    ("Grand Maester Orwyle", "black", "Grand Maester", "brings the medicine", "neutral",
     "maester", "04_char_orwyle", "Drawn into the confinement without choosing it"),
    ("Torrhen Manderly", "black", "Council lord", "counts the shortfall", "neutral",
     "smallfolk", "05_char_torrhen", "The unpaid Watch is his problem to fund"),
    ("Sabitha Frey", "black", "Lady of the Crossing", "with the host", "neutral",
     "frey", "06_char_sabitha_frey", "Riverlands strength Rhaenyra depends on"),
    ("Alyn of Hull", "black", "Serves the crown", "still unnamed", "neutral",
     "velaryon", "07_char_alyn", "Sent where his father will not go"),
    ("Addam of Hull", "black", "Dragonrider · Seasmoke", "flies for her", "good",
     "velaryon", "08_char_addam", "Loyal, and still denied the name"),
    ("Baela Targaryen", "black", "Dragonrider · Moondancer", "watching the skies", "good",
     "targaryen", "09_char_baela", "One of the few who could find Vhagar"),
    ("Joffrey Velaryon", "black", "Rhaenyra's son", "avoided", "bad",
     "velaryon", "10_char_joffrey", "Naming another heir has a cost inside the family"),
    ("Ser Luthor Largent", "black", "Commander of the Watch", "leads unpaid men", "bad",
     "watch", "11_char_largent", "Commands the force Ormund has already infiltrated"),
    # --- Greens and rival claimants ---
    ("Ormund Hightower", "green", "Lord of Oldtown", "reach proven", "bad",
     "hightower", "20_char_ormund", "Attacks the capital without marching on it"),
    ("Daeron Targaryen", "green", "The rival claimant", "on the money", "bad",
     "targaryen", "21_char_daeron", "His face now circulates in Rhaenyra's city"),
    ("Aegon II Targaryen", "green", "Deposed king", "kills again", "bad",
     "targaryen", "22_char_aegon", "Reclaims agency the only way he still can"),
    ("Aemond Targaryen", "green", "Wounded prince", "dependent on Alys", "bad",
     "targaryen", "23_char_aemond", "Physically able to defend her, unable to leave"),
    ("Alicent Hightower", "green", "Queen Dowager", "drinks it herself", "bad",
     "hightower", "24_char_alicent", "Becomes the cover story for her daughter"),
    ("Helaena Targaryen", "green", "Confined", "refuses; keeps it", "key",
     "targaryen", "25_char_helaena", "STRONG SHOW INFERENCE on the pregnancy itself"),
    ("Larys Strong", "green", "Master of Whisperers", "breaks his self-pity", "neutral",
     "strong", "26_char_larys", "Brutal honesty as a political instrument"),
    ("Tyland Lannister", "green", "Master of Coin", "alive", "good",
     "lannister", "27_char_tyland", "Rhaenyra still wants what he knows about the gold"),
    ("Criston Cole", "green", "Lord Commander", "chooses the march", "bad",
     "kingsguard", "28_char_criston", "Prefers a near-certain death to returning beaten"),
    ("Gwayne Hightower", "green", "Rides with Criston", "follows him", "neutral",
     "hightower", "29_char_gwayne", "Hightower blood on a march with no return"),
    ("Alys Rivers", "green", "At Harrenhal", "makes herself kept", "good",
     "witch", "30_char_alys", "Every new hunter makes her secret harder to hold"),
    # --- Riverlands and supporting figures ---
    ("Oscar Tully", "black", "Lord of Riverrun", "leads the host", "good",
     "tully", "40_char_oscar_tully", "Young command over an old alliance"),
    ("Roderick Dustin", "black", "Roddy the Ruin", "with the host", "good",
     "dustin", "41_char_roderick_dustin", "Winter wolves in the Riverlands"),
    ("Petyr Piper", "black", "Riverlands lord", "with the host", "neutral",
     "piper", "42_char_petyr_piper", "One more sword Rhaenyra has not paid for"),
    ("Janos", "neutral", "At Rook's Rest", "killed by Aegon", "dead",
     "smallfolk", "43_char_janos", "The cost of a king reasserting himself"),
    ("A captured conspirator", "green", "King Daeron network", "taken alive", "bad",
     "coin", "44_char_conspirator", "The link between the coin and Ormund"),
]

DRAGONS = [
    ("Vhagar", "green", "Aemond's mount", "sighted, rider absent", "bad", "50_dragon_vhagar"),
    ("Caraxes", "black", "Daemon's mount", "available", "good", "51_dragon_caraxes"),
    ("Seasmoke", "black", "Addam's mount", "flies for the queen", "good", "52_dragon_seasmoke"),
    ("Moondancer", "black", "Baela's mount", "young and quick", "good", "53_dragon_moondancer"),
    ("Tessarion", "green", "Daeron's mount", "at Tumbleton", "bad", "54_dragon_tessarion"),
    ("Sunfyre", "green", "Aegon's mount", "status unresolved", "bad", "55_dragon_sunfyre"),
]


# ---------------------------------------------------------------------------- diagrams (§13.4)
def g_attack_chain(out):
    im, d = _plate("Ormund's remote attack chain",
                   "He never marches on the city; the city carries the war for him")
    A.chain(d, [("MINT\nDaeron's face\nstruck on coin", BP.GOLD),
                ("CARRIERS\ncoin moves\ninto the city", BP.GOLD),
                ("NETWORK\npayment and\nidentification", BP.RED),
                ("ASSASSINS\nGold Cloaks\nkilled below", BP.RED)], y=350)
    _foot(d, "A claimant three hundred miles away, operating inside her walls.", 700)
    d.text((104, 760), "SHOW CONFIRMED — the chain; INTERPRETATION — calling it a single design.",
           font=BP._F(BP._ARIAL, 26), fill=(150, 156, 166))
    im.save(out); return out


def g_coin_anatomy(out):
    im, d = _plate("What the Daeron coin actually does",
                   "One object doing four jobs at once")
    _rows(d, [("AS PROPAGANDA", "A rival king's face in every hand", BP.GOLD),
              ("AS PAYMENT", "Buys men the crown has not paid", BP.RED),
              ("AS IDENTIFICATION", "Carrying one marks you as his", BP.RED),
              ("AS PROOF", "It is physical evidence of a network", BP.STEEL),
              ("WHAT IT COSTS ORMUND", "Metal, and a face he already controls", BP.GREEN)])
    _foot(d, "Currency is the cheapest army anyone in this war has raised.")
    im.save(out); return out


def g_six_crises(out):
    im, d = _plate("Rhaenyra's six simultaneous crises",
                   "None of them can be solved with a dragon")
    _cols(d, [("MONEY", BP.RED, ["Treasury empty", "Gold Cloaks unpaid",
                                 "Tyland's knowledge lost"]),
              ("ORDER", BP.RED, ["Watch infiltrated", "Killings under the Keep",
                                 "Slogans on the walls"]),
              ("A RIVAL", BP.GOLD, ["Daeron on the coin", "Ormund holds Tumbleton",
                                    "Assassins inside"])], y0=250, h=300)
    _cols(d, [("MISSING", BP.RED, ["Aegon unlocated", "Aemond unlocated", "Vhagar loose"]),
              ("FAMILY", BP.GOLD, ["Joffrey avoided", "Daemon defies her",
                                   "Command visibly split"]),
              ("THE FIELD", BP.STEEL, ["Criston still marching", "Riverlands host stretched",
                                       "Harrenhal offered as a bounty"])], y0=576, h=300)
    _foot(d, "Six problems, one queen, and a police force that has not been paid.", 906)
    im.save(out); return out


def g_brothers(out):
    im, d = _plate("Two brothers, one mother, two different childhoods",
                   "Each believes she chose the other")
    _cols(d, [("AEGON BELIEVES", BP.GOLD, ["Their mother favored Aemond",
                                           "He was the disappointment",
                                           "His crown was an accident of birth order",
                                           "Nobody wanted him to rule"]),
              ("AEMOND BELIEVES", BP.RED, ["Their mother favored Aegon",
                                           "He was the spare who tried harder",
                                           "He earned what Aegon inherited",
                                           "Nobody trusted him to rule"])],
          y0=250, h=430)
    _foot(d, "Both cannot be right, and the episode does not adjudicate it.", 720)
    d.text((104, 776), "INTERPRETATION — the symmetry is the reading, not a stated fact.",
           font=BP._F(BP._ARIAL, 26), fill=(150, 156, 166))
    im.save(out); return out


def g_aemond_identity(out):
    im, d = _plate("Aemond without Vhagar", "Subtract the dragon and see what is left")
    _rows(d, [("WITH VHAGAR", "The most destructive force in the war", BP.GOLD),
              ("WITHOUT HER", "A wounded man in a ruined castle", BP.RED),
              ("WHAT HE STILL HAS", "Personal skill, and Green royal blood", BP.STEEL),
              ("WHAT HOLDS HIM", "Dependence on the woman who kept him alive", BP.RED),
              ("WHAT HE IS WORTH", "A bounty: Harrenhal itself", BP.GOLD)])
    _foot(d, "A prince is only a prince while somebody is obeying him.")
    im.save(out); return out


def g_helaena_tree(out):
    im, d = _plate("Helaena's decision", "What each choice costs her",
                   "STRONG SHOW INFERENCE — Episode 5")
    _cols(d, [("TAKE THE MEDICINE", BP.STEEL, ["Stays politically invisible",
                                               "Loses the child",
                                               "The secret dies with it"]),
              ("REFUSE IT", BP.GOLD, ["Keeps the child",
                                      "Becomes a succession question",
                                      "Someone else must carry the lie"])],
          y0=250, h=340)
    _rows(d, [("WHAT SHE CHOOSES", "She refuses, and claims the child as hers", BP.GOLD)],
          y0=630, step=106)
    _foot(d, "Her mother resolves the second column by drinking it herself.", 780)
    im.save(out); return out


def g_mysaria_inventory(out):
    im, d = _plate("What Mysaria knows and has not said",
                   "The most powerful position in the Keep is being informed")
    _rows(d, [("ABOUT HELAENA", "The pregnancy, and the refusal", BP.GOLD),
              ("ABOUT ALICENT", "That she drank it to cover for her daughter", BP.GOLD),
              ("ABOUT ORWYLE", "That he was part of it", BP.STEEL),
              ("ABOUT THE ESCAPE", "That there was an attempt, and where it ended", BP.RED),
              ("WHAT SHE RISKS", "Trust, if the queen learns she was last to know", BP.RED)])
    _foot(d, "Withholding is a use of information, not an absence of one.")
    im.save(out); return out


def g_criston_mission(out):
    im, d = _plate("Criston's two objectives", "Only one of them is military")
    _cols(d, [("THE STATED MISSION", BP.STEEL, ["Delay the Riverlands host",
                                                "Buy Ormund time",
                                                "Preserve what men remain"]),
              ("THE PRIVATE OBJECTIVE", BP.RED, ["Not return defeated",
                                                 "Be remembered as a soldier",
                                                 "Choose the ending himself"])],
          y0=250, h=380)
    _foot(d, "His men are now serving the second one, whether they know it or not.", 680)
    d.text((104, 736), "INTERPRETATION — the second column is the reading of his choice.",
           font=BP._F(BP._ARIAL, 26), fill=(150, 156, 166))
    im.save(out); return out


def g_aegon_before_after(out):
    im, d = _plate("Aegon before and after", "What killing Janos restored, and what it cost")
    _cols(d, [("BEFORE", BP.STEEL, ["Hiding and anonymous",
                                    "Told plainly he was a terrible king",
                                    "Accepting Larys's strategy",
                                    "Passive"]),
              ("AFTER", BP.RED, ["Acts on his own authority",
                                 "Kills a man to prove he still can",
                                 "Strategy subordinated to pride",
                                 "Dangerous to Larys's plan"])],
          y0=250, h=400)
    _foot(d, "He recovers agency, and immediately spends it on the wrong thing.", 700)
    im.save(out); return out


def g_show_vs_book(out):
    im, d = _plate("Show timeline versus book timeline",
                   "The adaptation reorders and invents — label them separately",
                   "SHOW CHANGE / BOOK ACCOUNT — Episode 5")
    for i, (lane, col, beats) in enumerate([
            ("TELEVISION", BP.STEEL, ["A coin campaign inside the capital",
                                      "Gold Cloaks killed beneath the Keep",
                                      "Aemond kept at Harrenhal by Alys",
                                      "Helaena refuses, Alicent covers"]),
            ("FIRE & BLOOD", BP.GOLD, ["No direct equivalent to the coin campaign",
                                       "City unrest recorded differently",
                                       "Harrenhal and Alys told by other sources",
                                       "Succession pressure, different sequence"])]):
        y = 310 + i * 250
        BP._track(d, (104, y - 44), lane, BP._F(BP._COPPER, 32), col, tr=4)
        d.line([(104, y + 30), (W - 104, y + 30)], fill=col, width=3)
        for j, b in enumerate(beats):
            x = 150 + j * 430
            d.ellipse([x - 9, y + 21, x + 9, y + 39], fill=col)
            yy = y + 58
            for line in A.wrap(b, 26):
                d.text((x - 40, yy), line, font=BP._F(BP._ARIAL, 23), fill=(186, 192, 200))
                yy += 30
    d.text((104, 866), "The book is an in-universe history compiled from conflicting sources.",
           font=BP._F(BP._ARIAL, 26), fill=(168, 174, 184))
    im.save(out); return out


def g_scoreboard(out):
    im, d = _plate("Who won Episode 5?", "Gains against the weaknesses that came with them")
    for t, x in (("", 104), ("GAINED", 560), ("LOST", 1030), ("NEW WEAKNESS", 1420)):
        d.text((x, 236), t, font=BP._F(BP._ARIAL_B, 24), fill=(140, 146, 156))
    d.line([(104, 272), (W - 104, 272)], fill=BP.GOLD, width=2)
    rows = [("Ormund", "A working network inside the city", "Nothing visible",
             "The coin is traceable to him", BP.GREEN),
            ("Daeron", "A circulating claim", "Any deniability",
             "Rhaenyra now hunts him", BP.GOLD),
            ("Alys", "A prince who protects her", "Privacy",
             "Every hunter narrows her cover", BP.GOLD),
            ("Helaena", "The child, and the choice", "Political invisibility",
             "Trapped inside the walls", BP.GOLD),
            ("Alicent", "Her daughter's secret held", "Her own cover",
             "Sealed in a passage", BP.RED),
            ("Mysaria", "Knowledge of everything", "Nothing yet",
             "What she withheld", BP.GOLD),
            ("Rhaenyra", "A tangible link to Ormund", "Her police force, and time",
             "Last to know, in her own city", BP.RED)]
    for i, (who, g, l, wk, col) in enumerate(rows):
        y = 296 + i * 84
        BP._track(d, (104, y), who.upper(), BP._F(BP._COPPER, 26), col, tr=3)
        for txt, x in ((g, 560), (l, 1030), (wk, 1420)):
            for k, line in enumerate(A.wrap(txt, 30)):
                d.text((x, y + k * 26), line, font=BP._F(BP._ARIAL, 22), fill=(190, 196, 204))
        d.line([(104, y + 68), (W - 104, y + 68)], fill=(40, 44, 52), width=1)
    d.text((104, 906), "INTERPRETATION — Ormund gains most and exposes least.",
           font=BP._F(BP._ARIAL, 28), fill=(214, 200, 172))
    im.save(out); return out


def g_territory_vs_control(out):
    im, d = _plate("Territory versus actual control",
                   "Holding a place is not the same as governing it")
    _cols(d, [("SHE HOLDS", BP.STEEL, ["The Iron Throne",
                                       "The Red Keep",
                                       "The city walls",
                                       "More dragons than anyone"]),
              ("SHE DOES NOT CONTROL", BP.RED, ["Who her Watch works for",
                                                "What the city carries in its pockets",
                                                "Where Aegon, Aemond or Vhagar are",
                                                "What her own consort will obey"])],
          y0=250, h=430)
    _foot(d, "Every item on the right is information she does not have.", 720)
    d.text((104, 776), "The four axes: TERRITORY held, INFORMATION lost, "
                       "LEGITIMACY contested, FORCE unpaid.",
           font=BP._F(BP._ARIAL, 26), fill=(150, 156, 166))
    im.save(out); return out


DIAGRAMS = [
    ("60_graphic_attack_chain", g_attack_chain),
    ("61_graphic_coin_anatomy", g_coin_anatomy),
    ("62_graphic_six_crises", g_six_crises),
    ("63_graphic_two_brothers", g_brothers),
    ("64_graphic_aemond_identity", g_aemond_identity),
    ("65_graphic_helaena_decision", g_helaena_tree),
    ("66_graphic_mysaria_inventory", g_mysaria_inventory),
    ("67_graphic_criston_mission", g_criston_mission),
    ("68_graphic_aegon_before_after", g_aegon_before_after),
    ("69_graphic_show_vs_book", g_show_vs_book),
    ("6A_graphic_winner_scoreboard", g_scoreboard),
    ("6B_graphic_territory_vs_control", g_territory_vs_control),
]


def build_all():
    os.makedirs(OUT, exist_ok=True)
    print(f"  characters {len(A.build_cards(CHARACTERS, OUT))}")
    print(f"  dragons    {len(A.build_dragon_cards(DRAGONS, OUT))}")
    stems = A.build_diagrams(DIAGRAMS, OUT)
    A.overflow_check(OUT, stems)
    print(f"  diagrams   {len(stems)} (all {W}x{H})")


if __name__ == "__main__":
    build_all()
