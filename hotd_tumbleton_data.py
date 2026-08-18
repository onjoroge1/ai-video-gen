"""Data for "Why Rhaenyra Cannot Burn Tumbleton" (The Dragon Council) — same engine as S3E7.

This is a single-question case file rather than an episode recap, so the left rail tracks THE CASE
instead of the war: what Rhaenyra holds, what Ormund holds, and which of the four parts of power is
currently doing the deciding. The chip vocabulary is the spec's own -- territory, firepower,
legitimacy, human cost -- so the rail and the narration can never disagree about the argument.

Art comes from four existing packs plus this one. The spec's §7 lists twelve "new original assets
required", but three of them already exist: Tumbleton under occupation (S3E3), the Footly residence
(S3E4), and Reach farmland (S3E3). Nothing was generated for this video.
"""
from __future__ import annotations

PACK = "house-of-dragons/dragon_council_tumbleton_asset_pack/images"
PACK_E3 = "house-of-dragons/house_of_the_dragon_s3e3_complete_asset_pack/images"
PACK_E4 = "house-of-dragons/house_of_the_dragon_s3e4_complete_asset_pack/images"
PACK_E5 = "house-of-dragons/house_of_the_dragon_s3e5_complete_asset_pack/images"
PACK_E7 = "house-of-dragons/house_of_the_dragon_s3e7_complete_asset_pack/images"
LIB = "house-of-dragons/hotd-character-library/masters"

# 1,088 words is the spec's script exactly as written. At the measured 162 wpm of our voice that is
# 6:43, not the spec's stated 9:15-10:00 band -- its word and runtime targets only agree at 145 wpm,
# and its own script is 262 words below its own word floor. Shipping the author's words verbatim was
# an explicit decision, so the bands here describe what the script actually produces.
DURATION_BAND_MIN = (6.0, 7.8)
WORD_BAND = (1000, 1200)
# The spec's §3 defines its own closed label set, and its fourth label exists in no other episode.
CANON_LABELS = ["SHOW CONFIRMED", "STRONG SHOW INFERENCE", "INTERPRETATION",
                "BOOK CONTEXT — NO FUTURE SPOILERS"]


def _s(title, subtitle, left, right, ctrl_label, ctrl_text, chapter,
       held="blacks", dragons=(4, 1, 1), changed=()):
    return {"title": title, "subtitle": f"The Dragon Council · Tumbleton{subtitle}",
            "left": {"name": "RHAENYRA", "accent": "steel", "chips": left},
            "right": {"name": "ORMUND", "accent": "green", "chips": right},
            "control": {"label": ctrl_label, "held_by": held, "text": ctrl_text},
            "dragons": {"left": dragons[0], "right": dragons[1], "right_dim": dragons[2]},
            "footer": chapter, "changed": list(changed)}


def _c(name, role, tag, tone="neutral"):
    return {"name": name, "role": role, "tag": tag, "tone": tone}


STATES = {
    "paradox": _s(
        "THE UNUSABLE WEAPON", "",
        [_c("Dragons", "Firepower", "UNMATCHED", "key"),
         _c("The capital", "Her seat", "SECURE"),
         _c("Tumbleton", "Declared for her", "OCCUPIED", "bad"),
         _c("The order", "Burn it", "NEVER GIVEN", "bad")],
        [_c("15,000 men", "Inside the town", "QUARTERED", "key"),
         _c("No dragon", "Of his own", "NONE NEEDED"),
         _c("The people", "His cover", "IN PLACE", "key"),
         _c("The choice", "Hers to make", "ALREADY LOST", "key")],
        "TUMBLETON", "A town full of people who raised her banner.",
        "CH 1 · The weapon she cannot use", changed=("The order",)),
    "case": _s(
        "FOUR PARTS OF POWER", "",
        [_c("Territory", "The capital", "HELD"),
         _c("Firepower", "From the sky", "GREATER", "key"),
         _c("Legitimacy", "The town chose her", "CLAIMED"),
         _c("Human cost", "Her own people", "THE LIMIT", "bad")],
        [_c("Territory", "Tumbleton streets", "OCCUPIED", "key"),
         _c("Firepower", "Spears, not flame", "LESSER"),
         _c("Legitimacy", "None in this town", "BORROWED"),
         _c("Human cost", "Not his to pay", "FREE", "key")],
        "THE CASE", "A ruler needs all four. Only one of them sets the limit.",
        "CH 2 · The four parts of power", changed=("Human cost",)),
    "inside": _s(
        "HIDDEN IN PLAIN SIGHT", " · the town",
        [_c("The road", "To her seat", "THREATENED", "bad"),
         _c("Her banner", "Raised here", "STILL FLYING"),
         _c("Her army", "Mustering", "IN THE FIELD"),
         _c("Clean shot", "Anywhere in town", "NONE", "bad")],
        [_c("Homes", "Requisitioned", "TAKEN", "key"),
         _c("Soldiers", "Among families", "DISSOLVED", "key"),
         _c("Footly hall", "His residence", "SEIZED"),
         _c("Perimeter", "Outside the walls", "EMPTY")],
        "TUMBLETON", "His army does not stand outside waiting to be burned.",
        "CH 3 · Why Tumbleton", changed=("Soldiers", "Clean shot")),
    "options": _s(
        "EVERY ANSWER COSTS", " · the options",
        [_c("Burn it", "Fastest", "POLITICAL DEFEAT", "bad"),
         _c("Do nothing", "Cheapest", "SHE DRAINS", "bad"),
         _c("Send an army", "Slowest", "LEAST BAD"),
         _c("Other towns", "Watching her", "HESITATING", "bad")],
        [_c("Either way", "He gains", "TIME", "key"),
         _c("If she burns", "He loses men", "SHE LOSES", "key"),
         _c("If she waits", "He rules them", "BY DEFAULT", "key"),
         _c("Allies", "Called for", "COMING")],
        "THE CHOICE", "Ruling is refusing victories that destroy the thing being won.",
        "CH 4 · The options", changed=("Other towns",)),
    "armour": _s(
        "OCCUPATION AS ARMOUR", " · the shield",
        [_c("Her supporters", "Beneath him", "HOSTAGES", "bad"),
         _c("Every death", "Charged to her", "HER FAULT", "bad"),
         _c("Rescue", "By her dragons", "IMPOSSIBLE", "bad"),
         _c("Daeron", "Made complicit", "HIS TOOL")],
        [_c("Discipline", "Of his own men", "PUBLIC", "key"),
         _c("Cruelty", "Kept controlled", "USABLE", "key"),
         _c("Authority", "To name the crime", "CLAIMED", "key"),
         _c("A kingship", "Rehearsed", "IN PROGRESS")],
        "THE SHIELD", "Controlled cruelty keeps the population present and usable.",
        "CH 6 · Occupation as armour", changed=("Every death", "Authority")),
    "answer": _s(
        "TOWN VERSUS ARMY", " · the answer",
        [_c("Vermithor", "Above town", "DETERRENCE", "key"),
         _c("Hugh", "Ties in the town", "DIVIDED"),
         _c("Roads", "To be closed", "ISOLATE"),
         _c("Civilians", "Routes opened", "EVACUATE", "key")],
        [_c("Supplies", "For 15,000", "CUTTABLE", "bad"),
         _c("His shield", "Three parts", "TWO CAN GO", "bad"),
         _c("Concentration", "Forced on him", "COMING", "bad"),
         _c("Patience", "Beats fire", "HIS ENEMY", "bad")],
        "THE ANSWER", "Not to burn Tumbleton, but to take the army out of it.",
        "CH 9 · The least-bad answer", dragons=(4, 1, 1),
        changed=("Civilians", "His shield")),
    "verdict": _s(
        "TAKING IS NOT RULING", " · the verdict",
        [_c("Territory", "Contested", "SPLIT"),
         _c("Firepower", "Uncontested", "HERS", "key"),
         _c("Legitimacy", "The town waits", "LEANS HERS"),
         _c("Human cost", "Over everything", "DECIDES", "bad")],
        [_c("The ground", "Under his boots", "HIS", "key"),
         _c("The claim", "On the people", "NOT HIS"),
         _c("The sky", "Above him", "NEVER HIS"),
         _c("The trap", "He built it", "HOLDING", "key")],
        "THE VERDICT", "He captured a town she could not destroy and remain its queen.",
        "CH 12 · The verdict", changed=("Human cost", "The trap")),
}

BLOCK_STATE = {
    "cold_open": "paradox", "four_parts": "case", "why_tumbleton": "inside",
    "dragonfire": "options", "do_nothing": "options", "occupation": "armour",
    "daeron": "armour", "vermithor": "answer", "least_bad": "answer",
    "weakness": "answer", "book": "verdict", "verdict": "verdict",
}

BLOCK_CHAPTER = {
    "cold_open": "The weapon she cannot use",
    "four_parts": "The four parts of power",
    "why_tumbleton": "Why Tumbleton?",
    "dragonfire": "Why dragonfire loses",
    "do_nothing": "Why doing nothing also loses",
    "occupation": "Occupation as armour",
    "daeron": "What Daeron's execution proves",
    "vermithor": "Why Vermithor cannot solve it",
    "least_bad": "Rhaenyra's least-bad answer",
    "weakness": "Ormund's hidden weakness",
    "book": "Book context — no future spoilers",
    "verdict": "The verdict",
}

BLOCK_ALIASES = {}

# --------------------------------------------------------------------------- figures
_KEY, _RED, _GREEN, _STEEL, _OCHRE = ((214, 176, 96), (196, 74, 66), (108, 148, 112),
                                      (150, 160, 176), (206, 166, 96))
# Only the people and dragons the spec's §7 manifest names. Statuses describe their position IN THIS
# CASE, not their standing in the wider war -- this is a case file about one town.
_PEOPLE = [
    ("rhaenyra-targaryen", "Rhaenyra Targaryen", "Queen on the Iron Throne",
     "cannot use her advantage", _KEY),
    ("ormund-hightower", "Ormund Hightower", "Commands the Hightower host",
     "holds the town and its people", _GREEN),
    ("daeron-targaryen", "Daeron Targaryen", "Prince at Tumbleton",
     "made part of the authority", _GREEN),
    ("hugh-hammer", "Hugh Hammer", "Vermithor's rider", "ties inside the town", _STEEL),
    ("grand-maester-orwyle", "Grand Maester Orwyle", "Of her small council",
     "argues for conventional force", _STEEL),
    ("mysaria-", "Mysaria", "Mistress of whispers", "counts what a burning would cost", _STEEL),
]
_DRAGONS = [
    ("syrax", "Syrax", "Rhaenyra's mount", "the order never given", _KEY),
    ("vermithor", "Vermithor", "Hugh's mount", "deterrence, not liberation", _STEEL),
    ("tessarion", "Tessarion", "Daeron's mount", "blue flame, watching", _GREEN),
    ("vhagar", "Vhagar", "Aemond's mount", "the help Ormund expected", _GREEN),
]


def _figures():
    dragon_slugs = {d[0] for d in _DRAGONS}
    out = {}
    for slug, name, role, status, tone in _PEOPLE + _DRAGONS:
        s = slug.rstrip("-")
        out[s] = {"portrait": f"{LIB}/{s}-master.png", "name": name, "role": role,
                  "status": status, "shape": "wide" if slug in dragon_slugs else "tall",
                  "tone": tone}
    return out


FIGURES = _figures()
PORTRAITS = list(FIGURES)
PERSON_OF = lambda asset: asset      # no heraldic cards in this video, so nothing to fold


def _vocab():
    """(names, role hints). A word shared by two subjects identifies neither.

    "Targaryen" belongs to Rhaenyra and Daeron here, and "rider"/"mount" belong to every dragon, so
    both are dropped -- a shared word does not merely fail to help, it points at the wrong face.
    """
    STOP = {"lord", "lady", "house", "prince", "princess", "king", "queen", "ser", "rider",
            "mount", "commands", "council"}
    names, roles, everyone = {}, {}, set()
    for f in FIGURES.values():
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
OCCUPIED, STREET, FOOTLY = ("16_loc_tumbleton_occupied", "70_loc_tumbleton_street",
                            "71_loc_footly_residence")
HOME, SEPT, COMMAND = ("72_loc_tumbleton_family_home", "73_loc_tumbleton_sept",
                       "75_loc_tumbleton_command")
OUTSKIRTS, FARMLAND = "89_loc_tumbleton_outskirts", "53_loc_the_reach_farmland"
KL, COUNCIL = "12_loc_kings_landing", "59_loc_small_council_chamber"

POWER, MAP, ARMY = ("80_graphic_four_parts_of_power", "81_graphic_reach_map",
                    "82_graphic_army_in_the_town")
FIRE, TREE, SHIELD = ("83_graphic_fire_spread", "84_graphic_decision_tree",
                      "85_graphic_civilian_shield")
DISC, RETICLE, PLAN = ("86_graphic_discipline_not_mercy",
                       "87_graphic_deterrence_not_liberation", "88_graphic_five_step_plan")
LOCKS, BOOKC, BOARD = ("89_graphic_three_locks", "8A_graphic_book_context",
                       "8B_graphic_verdict_board")


def _P(*items):
    return list(items)


# Each pool is the legal art for one chapter. The beat planner decides which shot lands on which
# sentence; the pool only fixes what the chapter is allowed to show.
POOLS = {
    "cold_open": _P(("plate", OCCUPIED), ("figure", "syrax", OCCUPIED),
                    ("figure", "ormund-hightower", OCCUPIED),
                    ("figure", "rhaenyra-targaryen", KL), ("plate", STREET)),
    "four_parts": _P(("plate", KL), ("full", POWER),
                     ("figure", "rhaenyra-targaryen", KL),
                     ("figure", "ormund-hightower", COMMAND), ("plate", OCCUPIED)),
    "why_tumbleton": _P(("plate", STREET), ("full", MAP), ("full", ARMY),
                        ("figure", "ormund-hightower", FOOTLY), ("plate", FOOTLY),
                        ("plate", HOME)),
    "dragonfire": _P(("plate", FARMLAND), ("full", FIRE), ("full", TREE),
                     ("figure", "syrax", FARMLAND), ("plate", HOME),
                     ("figure", "rhaenyra-targaryen", KL)),
    "do_nothing": _P(("plate", KL), ("full", TREE),
                     ("figure", "rhaenyra-targaryen", COUNCIL),
                     ("figure", "mysaria", COUNCIL), ("plate", OCCUPIED)),
    "occupation": _P(("plate", SEPT), ("full", SHIELD), ("full", DISC),
                     ("figure", "ormund-hightower", SEPT), ("plate", HOME),
                     ("plate", STREET)),
    "daeron": _P(("plate", COMMAND), ("figure", "daeron-targaryen", COMMAND),
                 ("figure", "ormund-hightower", COMMAND),
                 ("figure", "tessarion", OUTSKIRTS), ("plate", OUTSKIRTS)),
    "vermithor": _P(("plate", OUTSKIRTS), ("full", RETICLE),
                    ("figure", "vermithor", OUTSKIRTS),
                    ("figure", "hugh-hammer", STREET), ("plate", STREET)),
    "least_bad": _P(("plate", COUNCIL), ("full", PLAN),
                    ("figure", "grand-maester-orwyle", COUNCIL),
                    ("figure", "rhaenyra-targaryen", COUNCIL), ("plate", FARMLAND)),
    "weakness": _P(("plate", FARMLAND), ("full", LOCKS),
                   ("figure", "ormund-hightower", COMMAND),
                   ("figure", "vhagar", FARMLAND), ("plate", OUTSKIRTS)),
    # the book chapter opens on a plate: a self-titled chronicle card cannot host a caption
    "book": _P(("plate", OCCUPIED), ("full", BOOKC), ("plate", SEPT)),
    "verdict": _P(("plate", KL), ("full", BOARD),
                  ("figure", "rhaenyra-targaryen", KL), ("figure", "syrax", KL),
                  ("plate", OCCUPIED)),
}

META = {
    "title": "Why Rhaenyra Can't Burn Tumbleton | House of the Dragon",
    "alternatives": ["Ormund Beat Rhaenyra Without Fighting Her Dragons",
                     "Tumbleton Explained: Why Rhaenyra Can't Use Her Dragons"],
    "module": "The Dragon Council",
    "intro": ("Ormund Hightower did not take Tumbleton because he needed its walls. He took a town "
              "that had already declared for Rhaenyra, because its people make dragonfire "
              "politically impossible."),
    "argument": ("Power here has four parts: territory, firepower, legitimacy, and human cost. "
                 "Rhaenyra holds the first three in different degrees. The fourth decides what she "
                 "is allowed to do, and it is the one Ormund took away from her."),
    "body": ("This analysis explains how Ormund turns an occupied population into armour, why "
             "Rhaenyra's dragons cannot liberate a friendly town without destroying it, what "
             "Daeron's forced execution reveals about Hightower rule, and why Vermithor can watch "
             "Tumbleton without solving the problem beneath him."),
    "spoilers": ("Covers House of the Dragon through Season 3, Episode 4. No leaks or unaired "
                 "material. The book section contains no future plot outcomes."),
    "accuracy_note": ("Every claim is labelled on screen as SHOW CONFIRMED, STRONG SHOW INFERENCE, "
                      "INTERPRETATION, or BOOK CONTEXT. \"Human shield\" is this channel's "
                      "description of the effect of the occupation, never a phrase either commander "
                      "uses."),
    "hashtags": "#HouseOfTheDragon #RhaenyraTargaryen #Tumbleton",
    "thumbnail": f"{PACK}/thumbnail/8C_thumbnail_she_cannot_burn_it.png",
    "tags": ["house of the dragon", "house of the dragon explained",
             "house of the dragon season 3", "house of the dragon season 3 episode 4",
             "tumbleton explained", "why rhaenyra cannot burn tumbleton",
             "why rhaenyra can't use her dragons", "rhaenyra targaryen",
             "ormund hightower", "ormund hightower explained", "daeron targaryen",
             "daeron targaryen explained", "vermithor", "hugh hammer", "tessarion",
             "dance of the dragons", "fire and blood", "team black", "team green",
             "house of the dragon analysis", "tumbleton human shield", "rhaenyra queen",
             "dragon warfare", "the dragon council"],
}
