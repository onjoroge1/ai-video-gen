"""House of the Dragon S3E7 data: rail states, shot pools, figures, subject vocabulary.

Built from the docx spec, whose runtime arithmetic does not close: 1,765 words at the measured TTS
rate of 162 wpm is 10:54, not the 14:30 it targets, and its chapter timings would need 251 wpm in the
book-comparison chapter. The script is shipped verbatim by decision, so the duration band is set to
what the words actually produce rather than to the number on the cover.

Nothing here inherits from Episode 6 -- there is no E6 pack, and the spec's own "Where everyone
stands" chapter supplies the board state, so the rail is authored from E7's evidence only.

Two spec paths do not exist on this machine: `hotd-character-library-wave2` and `hotd-dragon-library`.
Every master they name is real and lives in `hotd-character-library/masters`, characters and dragons
together, so FIGURES points there.
"""
from __future__ import annotations

PACK = "house-of-dragons/house_of_the_dragon_s3e7_complete_asset_pack/images"
PACK_PREV = "house-of-dragons/house_of_the_dragon_s3e5_complete_asset_pack/images"
PACK_PREV2 = "house-of-dragons/house_of_the_dragon_s3e4_complete_asset_pack/images"
PACK_PREV3 = "house-of-dragons/house_of_the_dragon_s3e3_complete_asset_pack/images"
LIB = "house-of-dragons/hotd-character-library/masters"

DURATION_BAND_MIN = (10.0, 12.0)     # what 1,765 words at 162 wpm actually yields
WORD_BAND = (1650, 1900)
CANON_LABELS = ["SHOW CONFIRMED", "STRONG SHOW INFERENCE", "INTERPRETATION",
                "BOOK ACCOUNT", "SHOW CHANGE"]     # the spec's closed set of five

# --------------------------------------------------------------------------- court board
def _s(title, subtitle, left, right, ctrl_label, ctrl_text, chapter,
       held="blacks", dragons=(5, 3, 1), changed=()):
    """One rail state. `control` is the single-line reading of who holds what, `dragons` the
    in-play count (left, right, right_dim), and `changed` the chips to flag as newly moved."""
    return {"title": title, "subtitle": f"House of the Dragon · S3E7{subtitle}",
            "left": {"name": "THE BLACKS", "accent": "steel", "chips": left},
            "right": {"name": "THE GREENS", "accent": "green", "chips": right},
            "control": {"label": ctrl_label, "held_by": held, "text": ctrl_text},
            "dragons": {"left": dragons[0], "right": dragons[1], "right_dim": dragons[2]},
            "footer": chapter, "changed": list(changed)}


def _c(name, role, tag, tone="neutral"):
    return {"name": name, "role": role, "tag": tag, "tone": tone}


STATES = {
    # the cold open states the question, so the board states the asymmetry it will answer
    "open": _s("APPOINTED, OR KNOWN", "", [
        _c("Rhaenyra", "Queen", "HOLDS THE CITY", "key"),
        _c("Daemon", "Consort", "HIDING A BOND", "bad"),
        _c("Rhaena", "Sheepstealer", "UNDECLARED", "neutral"),
        _c("Helaena", "A Dreamer", "NOW KNOWN", "bad")],
        [_c("Aegon", "No court", "IN THE WOOD", "bad"),
         _c("Sunfyre", "Aegon's", "PRESUMED DEAD", "neutral"),
         _c("Ormund", "Hightower", "HOLDS CORLYS", "good"),
         _c("Aemond", "At Harrenhal", "WITH VHAGAR", "good")],
        "THE QUESTION", "Power can appoint a ruler. It cannot appoint a rider.", "CH 1 · Where everyone stands", dragons=(5, 3, 1),
        changed=("Daemon", "Sunfyre")),

    "capital": _s("INSIDE THE RED KEEP", " · King's Landing", [
        _c("Rhaenyra", "Queen", "WANTS CERTAINTY", "key"),
        _c("Helaena", "Confined", "NOT OBEYED", "bad"),
        _c("Daemon", "Consort", "SENT AWAY", "bad"),
        _c("The skull", "False", "EVIDENCE", "bad")],
        [_c("Aemond", "At Harrenhal", "WITH VHAGAR", "good"),
         _c("Alicent", "Sent to kill", "HER TOOL", "neutral"),
         _c("Ormund", "Hightower", "HOLDS CORLYS", "good"),
         _c("Aegon", "Crownlands", "STILL MOVING", "bad")],
        "THE PALACE", "Prophecy will not report on command.", "CH 3 · Rhaenyra and the Dreamer", dragons=(5, 3, 1),
        changed=("Helaena", "The skull")),

    "river": _s("FOUR OVER THE RIVER", " · the Blue Fork", [
        _c("Rhaenyra", "Syrax", "IN THE AIR", "key"),
        _c("Rhaena", "Sheepstealer", "ATTACKS", "bad"),
        _c("Addam", "Seasmoke", "JOINS IN", "neutral"),
        _c("Daemon", "Caraxes", "ENDS IT", "good")],
        [_c("Aemond", "At Harrenhal", "ELSEWHERE", "neutral"),
         _c("Ormund", "Tumbleton", "UNWORRIED", "good"),
         _c("Ulf", "Silverwing", "ON WATCH", "neutral"),
         _c("Aegon", "Crownlands", "HUNTED", "bad")],
        "THE BLUE FORK", "The bond is suspended, not erased.", "CH 4 · The dragon she cannot control", dragons=(5, 3, 1),
        changed=("Rhaena", "Addam")),

    "harrenhal": _s("THE POISONED CUP", " · Harrenhal", [
        _c("Rhaenyra", "Queen", "GAVE THE ORDER", "key"),
        _c("Alicent", "The mother", "SERVES IT", "bad"),
        _c("Rhaena", "Returned", "SEPARATED", "bad"),
        _c("Daemon", "Consort", "SENT AWAY", "bad")],
        [_c("Aemond", "Poisoned", "COLLAPSED", "bad"),
         _c("Alys", "Harrenhal", "IN CONTROL", "good"),
         _c("Ser Adrian", "Redfort", "KILLED", "bad"),
         _c("Vhagar", "Aemond's", "RIDERLESS", "neutral")],
        "HARRENHAL", "The poison works because the bond is damaged, not absent.", "CH 6 · Alicent at Harrenhal", dragons=(5, 3, 1),
        changed=("Aemond", "Alys")),

    "tumbleton": _s("A THRONE NOT HIS", " · Tumbleton", [
        _c("Rhaenyra", "Queen", "DOES NOT KNOW", "bad"),
        _c("Ulf", "Her watchman", "TURNS", "bad"),
        _c("Corlys", "Lord of Tides", "A PRISONER", "bad"),
        _c("Alyn", "Sent a finger", "WARNED", "bad")],
        [_c("Ormund", "Hightower", "OFFERS A SEAT", "good"),
         _c("Silverwing", "Ulf's", "CHANGES SIDES", "good"),
         _c("Daeron", "Prince", "UNEASY", "neutral"),
         _c("Winter Wolves", "One day out", "MARCHING", "bad")],
        "OUTSIDE THE WALLS", "Control of a person is not control of the title.", "CH 7 · Ormund and Ulf", held="greens", dragons=(4, 4, 0),
        changed=("Ulf", "Silverwing")),

    "forest": _s("THE LAST NAME", " · the Crownlands", [
        _c("Rhaenyra", "Queen", "HOLDS THE CITY", "key"),
        _c("House Mooton", "Loyalists", "CLOSING IN", "good"),
        _c("Helaena", "Confined", "SEES THE BILL", "neutral"),
        _c("Daemon", "Consort", "SENT AWAY", "bad")],
        [_c("Aegon", "No crown", "NAMES HIMSELF", "bad"),
         _c("Tyland", "Beside him", "STANDS", "neutral"),
         _c("Larys", "Separated", "GONE", "bad"),
         _c("Sunfyre", "Scarred", "ANSWERS", "good")],
        "IN THE WOOD", "The soldiers are not persuaded. Sunfyre is.", "CH 9 · Aegon and Sunfyre", held="greens", dragons=(4, 4, 0),
        changed=("Sunfyre", "Larys")),

    "final": _s("WHAT IS STILL TRUE", " · end of Episode 7", [
        _c("Rhaenyra", "Territory", "WON", "key"),
        _c("Rhaena", "Sheepstealer", "UNRESOLVED", "neutral"),
        _c("Helaena", "Dreamfyre", "WITNESS", "neutral"),
        _c("Smallfolk", "Human cost", "RISING", "bad")],
        [_c("Ormund", "Surprise", "WON", "good"),
         _c("Aegon", "Sunfyre", "RESTORED", "good"),
         _c("Aemond", "Poisoned", "UNRESOLVED", "bad"),
         _c("Ulf", "Silverwing", "TURNED", "good")],
        "THE ANSWER", "Recognition is not the same thing as obedience.", "CH 12 · Who won, and what it means", dragons=(4, 4, 0),
        changed=("Aegon", "Ulf")),
}

BLOCK_STATE = {
    "cold_open": "open", "where_stands": "open",
    "prophecy_property": "capital",
    "four_dragons": "river",
    "daemon_lie": "capital",
    "alicent_poison": "harrenhal",
    "ulf_bargain": "tumbleton", "corlys_leverage": "tumbleton",
    "aegon_name": "forest", "sunfyre_answers": "forest",
    "helaena_bill": "capital",
    "who_won": "final", "show_versus_book": "final", "conclusion": "final",
}

BLOCK_CHAPTER = {
    "cold_open": "The rider power cannot appoint",
    "where_stands": "Where everyone stands",
    "prophecy_property": "Rhaenyra turns prophecy into state property",
    "four_dragons": "The dragon Rhaenyra cannot control",
    "daemon_lie": "Daemon's lie returns home",
    "alicent_poison": "Alicent weaponizes motherhood",
    "ulf_bargain": "Ormund sells a throne he does not own",
    "corlys_leverage": "Corlys becomes collateral",
    "aegon_name": "Aegon names himself",
    "sunfyre_answers": "Sunfyre answers",
    "helaena_bill": "Helaena sees the bill come due",
    "who_won": "Who won the episode?",
    "show_versus_book": "Show versus book",
    "conclusion": "Ruling is not the same as being recognized",
}
BLOCK_ALIASES = {}

# --------------------------------------------------------------------------- figures
# name -> (portrait slug, role, status, shape, tone). Statuses are this episode's end state, not
# Episode 5's: Aemond is poisoned, Corlys is a prisoner, Sunfyre is alive and scarred.
_KEY, _RED, _GREEN, _STEEL, _GOLD = ((214, 176, 96), (196, 74, 66), (108, 148, 112),
                                     (150, 160, 176), (222, 176, 88))
_PEOPLE = [
    ("rhaenyra-targaryen", "Rhaenyra Targaryen", "Queen on the Iron Throne", "wants certainty", _KEY),
    ("daemon-targaryen", "Daemon Targaryen", "Prince Consort", "sent away", _RED),
    ("rhaena-targaryen", "Rhaena Targaryen", "Sheepstealer's rider", "separated from her dragon", _RED),
    ("baela-targaryen", "Baela Targaryen", "Moondancer's rider", "at the capital", _STEEL),
    ("aegon-ii-targaryen", "Aegon II Targaryen", "A king without a court", "names himself", _GOLD),
    ("aemond-targaryen", "Aemond Targaryen", "Vhagar's rider", "poisoned at Harrenhal", _RED),
    ("helaena-targaryen", "Helaena Targaryen", "The Dreamer", "sees the bill come due", _STEEL),
    ("alicent-hightower", "Alicent Hightower", "Queen Dowager", "serves the cup", _GREEN),
    ("ormund-hightower", "Ormund Hightower", "Hand of the Hightower host", "offers Driftmark", _GREEN),
    ("gwayne-hightower", "Gwayne Hightower", "At Tumbleton", "uneasy", _GREEN),
    ("daeron-targaryen", "Daeron Targaryen", "Prince at Tumbleton", "not told the plan", _GREEN),
    ("corlys-velaryon", "Corlys Velaryon", "Lord of the Tides", "a prisoner", _RED),
    ("alyn-of-hull", "Alyn of Hull", "Serves the crown", "sent a signet", _STEEL),
    ("addam-of-hull", "Addam of Hull", "Seasmoke's rider", "joins the fight", _STEEL),
    ("larys-strong", "Larys Strong", "Master of whisperers", "separated", _GREEN),
    ("tyland-lannister", "Tyland Lannister", "Master of coin", "stands beside Aegon", _GREEN),
    ("alys-rivers", "Alys Rivers", "At Harrenhal", "left in control", _GREEN),
    ("mysaria-", "Mysaria", "Mistress of whispers", "at the capital", _STEEL),
    ("torrhen-manderly", "Torrhen Manderly", "Winter Wolves", "one day from Tumbleton", _STEEL),
    ("roderick-dustin", "Roderick Dustin", "Roddy the Ruin", "marching south", _STEEL),
]
_DRAGONS = [
    ("sunfyre", "Sunfyre", "Aegon's mount", "alive and scarred", _GOLD),
    ("dreamfyre", "Dreamfyre", "Helaena's mount", "inside the vision", _STEEL),
    ("sheepstealer", "Sheepstealer", "Rhaena's mount", "retreats, not erased", (168, 132, 92)),
    ("silverwing", "Silverwing", "Ulf's mount", "changes sides", _GREEN),
    ("syrax", "Syrax", "Rhaenyra's mount", "attacked in the air", _KEY),
    ("seasmoke", "Seasmoke", "Addam's mount", "joins the fight", _STEEL),
    ("caraxes", "Caraxes", "Daemon's mount", "ends the contest", _RED),
    ("vhagar", "Vhagar", "Aemond's mount", "rider poisoned", _GREEN),
]


def _figures():
    out = {}
    for slug, name, role, status, tone in _PEOPLE + _DRAGONS:
        s = slug.rstrip("-")
        out[s] = {"portrait": f"{LIB}/{s}-master.png", "name": name, "role": role,
                  "status": status, "shape": "wide" if (slug, name) in
                  [(d[0], d[1]) for d in _DRAGONS] else "tall", "tone": tone}
    return out


FIGURES = _figures()
PORTRAITS = list(FIGURES)
PERSON_OF = lambda asset: asset          # E7 has no heraldic cards to fold into a person


def _vocab():
    """(names, role hints). Names identify; roles only fill stretches where nobody is named.

    Words shared by more than one person identify nobody -- "Targaryen" belongs to seven people here
    and "Hightower" to three -- and a role word that is somebody else's name, or a place, is worse than
    useless: it actively points at the wrong face.
    """
    STOP = {"lord", "lady", "house", "prince", "princess", "king", "queen", "ser", "rider", "mount"}
    names, roles = {}, {}
    everyone = set()
    for slug, f in FIGURES.items():
        everyone |= {w.lower().strip("'s") for w in f["name"].split() if len(w) > 3}
    for slug, f in FIGURES.items():
        n = {w.lower() for w in f["name"].split() if len(w) > 3} - STOP
        if n:
            names[slug] = n
        r = {w.lower().strip(",.'") for w in f["role"].replace("'s", "").split() if len(w) > 3}
        r -= STOP | everyone
        if r:
            roles[slug] = r
    for bag in (names, roles):
        seen = {}
        for ws in bag.values():
            for w in ws:
                seen[w] = seen.get(w, 0) + 1
        shared = {w for w, k in seen.items() if k > 1}
        for k in list(bag):
            bag[k] = bag[k] - shared
            if not bag[k]:
                del bag[k]
    return names, roles


SUBJECT_WORDS, ROLE_WORDS = _vocab()

# --------------------------------------------------------------------------- shot pools
# Each pool is the legal art for one chapter. The beat planner picks WHICH shot lands on which
# sentence; the pool only decides what art the chapter is allowed to use.
def _P(*items):
    return list(items)


FOREST, FORK, MEADOW, CELL = ("82_loc_crownlands_forest", "83_loc_blue_fork",
                              "84_loc_dream_meadow", "85_loc_captive_cell")
PIT, FARM, CHAMBER, CAMP = ("86_loc_dragonpit_gate", "87_loc_farm_in_snow",
                            "88_loc_royal_bedchamber", "89_loc_tumbleton_outskirts")
KL, KEEP, COUNCIL = "12_loc_kings_landing", "51_loc_red_keep", "59_loc_small_council_chamber"
SICKROOM, COURTYARD, COMMAND = ("76_loc_harrenhal_sickroom", "78_loc_harrenhal_courtyard",
                                "75_loc_tumbleton_command")

POOLS = {
    "cold_open": _P(("plate", FOREST), ("figure", "aegon-ii-targaryen", FOREST),
                    ("figure", "sunfyre", FOREST),
                    ("full", "70_graphic_recognition_vs_appointment")),
    "where_stands": _P(("plate", KL), ("figure", "rhaenyra-targaryen", KL),
                       ("figure", "ormund-hightower", COMMAND),
                       ("figure", "aemond-targaryen", SICKROOM),
                       ("full", "70_graphic_recognition_vs_appointment")),
    "prophecy_property": _P(("plate", MEADOW), ("figure", "helaena-targaryen", COUNCIL),
                            ("figure", "rhaenyra-targaryen", COUNCIL),
                            ("figure", "dreamfyre", MEADOW)),
    "four_dragons": _P(("plate", FORK), ("figure", "rhaena-targaryen", FORK),
                       ("figure", "sheepstealer", FORK), ("figure", "syrax", FORK),
                       ("figure", "caraxes", FORK), ("figure", "seasmoke", FORK),
                       ("full", "71_graphic_four_dragon_collision")),
    "daemon_lie": _P(("plate", CHAMBER), ("figure", "daemon-targaryen", CHAMBER),
                     ("figure", "rhaenyra-targaryen", CHAMBER),
                     ("figure", "rhaena-targaryen", CHAMBER)),
    "alicent_poison": _P(("plate", SICKROOM), ("figure", "alicent-hightower", SICKROOM),
                         ("figure", "aemond-targaryen", SICKROOM),
                         ("figure", "alys-rivers", SICKROOM), ("plate", COURTYARD)),
    "ulf_bargain": _P(("plate", CAMP), ("figure", "ormund-hightower", CAMP),
                      ("card", "09_char_ulf", CAMP), ("figure", "silverwing", CAMP),
                      ("figure", "daeron-targaryen", COMMAND),
                      ("full", "72_graphic_illegitimate_offer")),
    "corlys_leverage": _P(("plate", CELL), ("figure", "corlys-velaryon", CELL),
                          ("figure", "alyn-of-hull", CELL),
                          ("full", "73_graphic_corlys_three_panels")),
    "aegon_name": _P(("plate", FOREST), ("figure", "aegon-ii-targaryen", FOREST),
                     ("figure", "tyland-lannister", FOREST),
                     ("figure", "larys-strong", FOREST),
                     ("full", "74_graphic_name_stripped")),
    "sunfyre_answers": _P(("plate", FOREST), ("figure", "sunfyre", FOREST),
                          ("figure", "aegon-ii-targaryen", FOREST),
                          ("full", "70_graphic_recognition_vs_appointment")),
    "helaena_bill": _P(("plate", PIT), ("figure", "helaena-targaryen", PIT),
                       ("figure", "dreamfyre", PIT), ("plate", FARM),
                       ("full", "75_graphic_helaena_triptych")),
    "who_won": _P(("plate", KEEP), ("figure", "ormund-hightower", CAMP),
                  ("figure", "sunfyre", FOREST), ("figure", "helaena-targaryen", PIT),
                  ("full", "76_graphic_winner_matrix")),
    "show_versus_book": _P(("plate", KEEP), ("figure", "rhaena-targaryen", FORK),
                           ("figure", "sunfyre", FOREST),
                           ("figure", "helaena-targaryen", PIT),
                           ("full", "77_graphic_show_vs_book")),
    "conclusion": _P(("plate", KL), ("figure", "sunfyre", FOREST),
                     ("figure", "helaena-targaryen", PIT),
                     ("figure", "sheepstealer", FORK), ("figure", "silverwing", CAMP),
                     ("full", "70_graphic_recognition_vs_appointment")),
}

META = {
    "module": "episodes/s3e7.py",
    "title": "The Dragon That Proved Aegon Was Still King | HOTD S3E7 Breakdown",
    "alternatives": [
        "Sunfyre Answered When Aegon's Crown Could Not | HOTD S3E7",
        "Ormund Promised a Throne He Does Not Own | HOTD S3E7",
        "The Bonds Rhaenyra Cannot Command | House of the Dragon S3E7",
    ],
    "intro": ("Sunfyre did not return merely to save Aegon. He returned to prove the one claim no "
              "council, crown, or historian could appoint: the bond between a dragon and its rider."),
    "body": ("A full breakdown of House of the Dragon Season 3, Episode 7: Rhaenyra's attempt to "
             "command prophecy, the four-dragon collision around Rhaena and Sheepstealer, Alicent's "
             "mission at Harrenhal, Ormund's offer to Ulf, Corlys turned into leverage, and the "
             "moment Aegon's name finally receives an answer.\n\n"
             "Every claim is labeled on screen as SHOW CONFIRMED, STRONG SHOW INFERENCE, "
             "INTERPRETATION, BOOK ACCOUNT, or SHOW CHANGE. Aired material through Season 3, "
             "Episode 7 only -- no previews, leaks, or unaired plot material.\n\n"
             "Original character renders, dragon renders, maps and diagrams. No episode footage."),
    # the spec's own core argument, stated once for the description
    "argument": ("Human power can appoint a ruler, promise a title, or demand a prophecy. It cannot "
                 "order a dragon to recognize the wrong rider. Every major story in Episode 7 is a "
                 "fight over who has the authority to name a rider, a king, a traitor, or a future."),
    "spoilers": ("Covers aired material up to and including Season 3, Episode 7. No previews, leaks "
                 "or unaired plot material. Book readers: the show-versus-book chapter is flagged "
                 "before it starts and contains no post-Episode-7 outcomes."),
    "hashtags": "#HouseOfTheDragon #HOTD #Sunfyre #Aegon #Helaena #Dreamfyre",
    "thumbnail": (PACK + "/thumbnail/90_thumbnail_he_still_knew_him.png"),
    "tags": ["house of the dragon season 3 episode 7", "house of the dragon s3e7 breakdown",
             "hotd episode 7 explained", "sunfyre alive", "aegon sunfyre", "helaena dreamfyre",
             "rhaena sheepstealer", "ormund hightower ulf", "ulf betrayal",
             "alicent aemond harrenhal", "house of the dragon analysis",
             "fire and blood changes", "dance of the dragons", "the dragon council"],
}
