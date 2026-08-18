"""House of the Dragon S3E3 — episode DATA only, extracted from the original single-episode builder.

Kept verbatim so the shipped episode stays reproducible: `python -m hotd plan episodes/s3e3.py`
must still produce the same 119-shot ledger as renders/hotd_s3e3/build_report.json. That equivalence
is the regression test for every future change to the engine.

S3E3's shots were hand-authored per SEGMENT, before the block-pool scheme existed, so they are
exported as PLAYLISTS_EXACT rather than as pools.
"""
from __future__ import annotations

from hotd.episode import chip


_BASE_SUB = "House of the Dragon · S3E3"


def _c(name, role, tag, tone):
    return chip(name, role, tag, tone)


STATES = {
    "open": {
        "title": "STATE OF THE WAR", "subtitle": _BASE_SUB,
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            _c("Rhaenyra", "Queen", "THRONE TAKEN", "key"),
            _c("Daemon", "Consort", "IN THE FIELD", "good"),
            _c("Mysaria", "Whisperers", "NETWORK LIVE", "good"),
            _c("Corlys", "Hand", "SERVING", "neutral")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            _c("Aegon II", "Deposed", "MISSING", "bad"),
            _c("Aemond", "Vhagar", "MISSING", "bad"),
            _c("Alicent", "Dowager", "CONFINED", "bad"),
            _c("Ormund", "Hightower", "IN THE REACH", "neutral")]},
        "control": {"label": "KING'S LANDING", "held_by": "blacks",
                    "text": "Throne held. Nothing else settled."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 1 · The morning after victory",
        "changed": ["Rhaenyra", "control"]},
    "treasury": {
        "title": "STATE OF THE WAR", "subtitle": _BASE_SUB,
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            _c("Rhaenyra", "Queen", "UNANOINTED", "neutral"),
            _c("Treasury", "Crown coin", "EMPTY", "bad"),
            _c("Food", "The capital", "CRITICAL", "bad"),
            _c("Mysaria", "Whisperers", "NETWORK LIVE", "good")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            _c("Tyland", "Coin", "PRESUMED DEAD", "dead"),
            _c("High Septon", "The Faith", "WITHHOLDING", "bad"),
            _c("Aegon II", "Deposed", "MISSING", "bad"),
            _c("Aemond", "Vhagar", "MISSING", "bad")]},
        "control": {"label": "THE CAPITAL", "held_by": "contested",
                    "text": "Held by force. Not yet governed."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 2 · What victory did not deliver",
        "changed": ["Treasury", "Food", "High Septon", "control"]},
    "field": {
        "title": "THE FIELD", "subtitle": _BASE_SUB + " · the Reach",
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            _c("Daemon", "Consort", "TERMS GIVEN", "good"),
            _c("Caraxes", "Dragon", "IN THE AIR", "good"),
            _c("Hostage", "Claimed heir", "SECURED", "key"),
            _c("Reach army", "Hightower", "DISBANDING", "good")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            _c("Ormund", "Hightower", "KNELT", "neutral"),
            _c("Daeron", "Prince", "UNVERIFIED", "bad"),
            _c("Tessarion", "Dragon", "WITH HOST", "bad"),
            _c("Oldtown", "The seat", "UNTOUCHED", "neutral")]},
        "control": {"label": "THE REACH ROAD", "held_by": "contested",
                    "text": "A surrender accepted before it was verified."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 3 · Defeated by information",
        "changed": ["Daemon", "Ormund", "Hostage", "Daeron"]},
    "court": {
        "title": "THE COURT", "subtitle": _BASE_SUB + " · King's Landing",
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            _c("Rhaenyra", "Queen", "GOVERNING", "key"),
            _c("Corlys", "Hand", "PRESSING", "neutral"),
            _c("Mysaria", "Whisperers", "ESSENTIAL", "good"),
            _c("New knights", "Three riders", "OWED", "neutral")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            _c("Alicent", "Dowager", "USEFUL", "neutral"),
            _c("Helaena", "Confined", "HELD", "bad"),
            _c("High Septon", "The Faith", "WITHHOLDING", "bad"),
            _c("Smallfolk", "The city", "HUNGRY", "bad")]},
        "control": {"label": "LEGITIMACY", "held_by": "contested",
                    "text": "Every ally is also an invoice."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 4 · The price of every ally",
        "changed": ["Corlys", "Alicent", "New knights", "Smallfolk"]},
    "decoy": {
        "title": "THE DECEPTION", "subtitle": _BASE_SUB + " · Tumbleton",
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            _c("Rhaenyra", "Queen", "MISINFORMED", "bad"),
            _c("Daemon", "Sent away", "THE VALE", "neutral"),
            _c("Hostage", "Not Daeron", "A DECOY", "bad"),
            _c("Syrax", "Dragon", "GROUNDED", "neutral")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            _c("Ormund", "Hightower", "AT TUMBLETON", "good"),
            _c("Tumbleton", "River town", "TAKEN", "good"),
            _c("Daeron", "Prince", "UNKNOWN", "good"),
            _c("Tessarion", "Dragon", "WITH HOST", "good")]},
        "control": {"label": "TUMBLETON", "held_by": "greens",
                    "text": "A road nobody was watching."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 5 · What the decoy bought",
        "changed": ["Ormund", "Tumbleton", "Hostage", "Rhaenyra", "control"]},
    "final": {
        "title": "END OF EPISODE", "subtitle": _BASE_SUB,
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            _c("Force", "Dragons", "HELD", "good"),
            _c("Legitimacy", "The oil", "WITHHELD", "bad"),
            _c("Governing", "Coin, grain", "MISSING", "bad"),
            _c("Mysaria", "Whisperers", "QUIET WINNER", "key")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            _c("Ormund", "Hightower", "EP. WINNER", "good"),
            _c("Alicent", "Dowager", "STILL USEFUL", "neutral"),
            _c("Aegon II", "Deposed", "STILL MISSING", "bad"),
            _c("Aemond", "Vhagar", "STILL MISSING", "bad")]},
        "control": {"label": "THE THRONE", "held_by": "blacks",
                    "text": "One of three forms of power. Only one."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 6 · Ruling begins after victory",
        "changed": ["Legitimacy", "Governing", "Mysaria", "Ormund"]},
}


PLAYLISTS_EXACT = {
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


SEG_STATE_EXACT = {
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


# blocks are the segment ids themselves for this episode
POOLS = {k: v for k, v in PLAYLISTS_EXACT.items()}
BLOCK_STATE = dict(SEG_STATE_EXACT)

_CHAPTERS = [
    ("She won. Now what?", ["cold_open"]),
    ("Rhaenyra's first-day board", ["board"]),
    ("Ormund's false surrender", ["ormund_a", "ormund_b"]),
    ("No gold, no grain", ["first_day_a", "first_day_b"]),
    ("The Faith says no", ["faith_a", "faith_b"]),
    ("The prisoner who knows how", ["alicent_a", "alicent_b"]),
    ("The Velaryon invoice", ["corlys_a", "corlys_b"]),
    ("Two crowds and a rat banquet", ["smallfolk_a", "smallfolk_b", "smallfolk_c"]),
    ("Fear versus government", ["philosophy_a", "philosophy_b"]),
    ("She does not know him", ["false_daeron_a", "false_daeron_b"]),
    ("Tumbleton falls", ["tumbleton_a", "tumbleton_b"]),
    ("Show versus book", ["book_a", "book_b"]),
    ("Who won the episode?", ["scoreboard_a", "scoreboard_b"]),
    ("Ruling begins after victory", ["conclusion"]),
]

BLOCK_CHAPTER = {ids[0]: name for name, ids in _CHAPTERS}
# chapters legitimately span segments (ormund_a + ormund_b are one chapter)
CHAPTER_GROUPS = [(name, list(ids)) for name, ids in _CHAPTERS]

TITLE = ("House of the Dragon S3E3 Explained: Rhaenyra Won the Throne — "
         "Why Is She Losing Control?")

TAGS = ["house of the dragon", "house of the dragon season 3", "house of the dragon s3e3",
        "house of the dragon episode 3 explained", "hotd s3e3", "hotd explained",
        "rhaenyra targaryen", "ormund hightower", "false daeron", "tumbleton",
        "dance of the dragons", "fire and blood", "targaryen", "game of thrones lore",
        "hotd season 3 explained", "rhaenyra iron throne", "alicent hightower",
        "corlys velaryon", "mysaria", "westeros politics"]

META = {
    "module": "episodes/s3e3.py",
    "title": TITLE,
    "alternatives": [
        "Rhaenyra Triumphant Explained: The Queen With No Gold and No Control",
        "House of the Dragon Episode 3: How Ormund Tricked Rhaenyra",
        "Rhaenyra Has Six Dragons - So Why Can't She Rule?",
    ],
    "intro": "Rhaenyra took the Iron Throne. Within a day she discovered that holding the capital "
             "and governing it are two different things.",
    "body": "A full breakdown of Season 3, Episode 3: the false surrender, the empty treasury, the "
            "Faith that will not anoint her, and the decoy that bought Ormund an unwatched road.",
    "argument": "Power comes in three forms - coercion, legitimacy and administration. Rhaenyra "
                "ends the episode holding one of the three.",
    "spoilers": "Covers up to and including Season 3, Episode 3.",
    "hashtags": "#HouseOfTheDragon #HOTD #Rhaenyra #DanceOfTheDragons #FireAndBlood",
    "tags": TAGS,
    "thumbnail": "house-of-dragons/house_of_the_dragon_s3e3_complete_asset_pack/images/"
                 "thumbnail/08_thumbnail_she_won_now_what.png",
    "image_spend_usd": 0.08,
    "accuracy_note": "",
}
