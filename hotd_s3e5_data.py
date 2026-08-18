"""House of the Dragon S3E5 — episode DATA only.

Spec: house-of-dragons/house_of_the_dragon_s3e5_verified_video_spec.md

Production bands, the closed six-label set and the seventeen storyboard blocks were extracted from
the spec by `python -m hotd scaffold`. Rail states are authored from §7 (the power model), §8 (the
pre-episode board and its six zones) and §10 (character-state changes). Shot pools are art direction.

§7's four axes here are TERRITORY / INFORMATION / LEGITIMACY / FORCE. INFORMATION replaces the
previous episode's HUMAN COST: this episode turns on who knows what and who is acting on false
assumptions, so the closing rail resolves into those axes with INFORMATION as the one that moved.

Chip roles and tags stay under ~13 characters: the chip lays its tag pill on the role's row, so a
long tag ellipsises the role away.
"""
from __future__ import annotations

from hotd.episode import chip

PACK = "house-of-dragons/house_of_the_dragon_s3e5_complete_asset_pack/images"
PACK_PREV = "house-of-dragons/house_of_the_dragon_s3e4_complete_asset_pack/images"
PACK_PREV2 = "house-of-dragons/house_of_the_dragon_s3e3_complete_asset_pack/images"
SUB = "House of the Dragon · S3E5"

# --- spec-derived production parameters (§6) ---------------------------------------------------
DURATION_BAND_MIN = (13.0, 15.0)
WORD_BAND = (1900, 2250)
RECAP_CEILING_PCT = 30
CANON_LABELS = ["SHOW CONFIRMED", "STRONG SHOW INFERENCE", "BOOK ACCOUNT", "SHOW CHANGE",
                "INTERPRETATION", "FUTURE BOOK SPOILER"]

STATES = {
    "open": {
        "title": "STATE OF THE WAR", "subtitle": SUB,
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            chip("Rhaenyra", "Queen", "HOLDS THE CITY", "key"),
            chip("Daemon", "Consort", "IN THE KEEP", "neutral"),
            chip("Gold Cloaks", "The Watch", "UNPAID", "bad"),
            chip("Treasury", "Crown coin", "EMPTY", "bad")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            chip("Ormund", "Hightower", "HOLDS THE TOWN", "good"),
            chip("Daeron", "Prince", "BEING BUILT", "good"),
            chip("Aemond", "Wounded", "AT HARRENHAL", "bad"),
            chip("Vhagar", "Aemond's", "SEPARATED", "bad")]},
        "control": {"label": "KING'S LANDING", "held_by": "blacks",
                    "text": "Held by a police force nobody has paid."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 1 · Where everyone stands",
        "changed": ["Gold Cloaks", "Daeron"]},
    "capital": {
        "title": "INSIDE THE CAPITAL", "subtitle": SUB + " · King's Landing",
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            chip("Daemon", "The Watch", "CHOOSES THEM", "neutral"),
            chip("Gold Cloaks", "Massacred", "UNDER THE KEEP", "dead"),
            chip("Mysaria", "Whisperers", "KNOWS MOST", "good"),
            chip("Joffrey", "Her son", "AVOIDED", "bad")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            chip("The coin", "Daeron's face", "IN THE CITY", "good"),
            chip("Assassins", "Ormund's men", "OPERATING", "good"),
            chip("Ormund", "Hightower", "REACH PROVEN", "good"),
            chip("Daeron", "Rival claim", "ON THE MONEY", "good")]},
        "control": {"label": "THE STREETS", "held_by": "contested",
                    "text": "A claimant attacking the capital from inside it."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 2 · The war inside the walls",
        "changed": ["Gold Cloaks", "The coin", "Assassins"]},
    "harrenhal": {
        "title": "HARRENHAL", "subtitle": SUB + " · the ruined seat",
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            chip("Rhaenyra", "The bounty", "OFFERS A SEAT", "neutral"),
            chip("Hunters", "For the bounty", "CLOSING IN", "neutral"),
            chip("Riverlords", "Her host", "IN THE FIELD", "good"),
            chip("Mysaria", "Whisperers", "NOT TOLD YET", "neutral")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            chip("Aemond", "Wounded", "DEPENDENT", "bad"),
            chip("Alys", "Harrenhal", "HOLDS HIM", "good"),
            chip("Vhagar", "Aemond's", "ELSEWHERE", "bad"),
            chip("Daeron", "Prince", "PROMOTED", "good")]},
        "control": {"label": "HARRENHAL", "held_by": "contested",
                    "text": "A prince kept, not commanded."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 3 · What Alys is doing",
        "changed": ["Aemond", "Alys", "Hunters"]},
    "confinement": {
        "title": "THE CONFINEMENT", "subtitle": SUB + " · the Red Keep",
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            chip("Rhaenyra", "Queen", "UNAWARE", "neutral"),
            chip("Mysaria", "Whisperers", "KNOWS MOST", "good"),
            chip("Orwyle", "Maester", "INVOLVED", "neutral"),
            chip("The walls", "The Keep", "A DEAD END", "bad")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            chip("Helaena", "Refuses it", "KEEPS THE CHILD", "key"),
            chip("Alicent", "Drinks it", "COVER STORY", "bad"),
            chip("The escape", "A passage", "SEALED", "bad"),
            chip("Aemond", "Her secret", "AT HARRENHAL", "bad")]},
        "control": {"label": "THE SECRET", "held_by": "contested",
                    "text": "A mother makes herself the cover story."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 4 · Helaena says no",
        "changed": ["Helaena", "Alicent", "The escape"]},
    "field": {
        "title": "THE FIELD", "subtitle": SUB + " · Riverlands and Rook's Rest",
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            chip("Riverlords", "Her host", "ADVANCING", "good"),
            chip("Rhaenyra", "Queen", "WANTS THE GOLD", "neutral"),
            chip("Oscar Tully", "Riverrun", "WITH THE HOST", "good"),
            chip("Roderick", "Winter wolf", "WITH THE HOST", "good")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            chip("Criston", "Kingsguard", "MARCHES ON", "bad"),
            chip("Aegon II", "Deposed king", "KILLS AGAIN", "bad"),
            chip("Larys", "Whisperers", "BREAKS HIM", "neutral"),
            chip("Tyland", "Coin", "ALIVE", "good")]},
        "control": {"label": "THE RIVERLANDS", "held_by": "contested",
                    "text": "One man choosing death over returning beaten."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 5 · Purpose and its price",
        "changed": ["Criston", "Aegon II", "Tyland"]},
    "final": {
        # left column becomes §7's four axes: that is what the episode resolves into
        "title": "END OF EPISODE", "subtitle": SUB,
        "left": {"name": "THE FOUR AXES", "accent": "steel", "chips": [
            chip("Territory", "The capital", "STILL HELD", "good"),
            chip("Information", "Who knows", "SHE IS BEHIND", "bad"),
            chip("Legitimacy", "A rival face", "ON THE COIN", "bad"),
            chip("Force", "Her police", "MASSACRED", "bad")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            chip("Ormund", "Hightower", "REACH PROVEN", "good"),
            chip("Daeron", "Rival claim", "A REAL KING?", "good"),
            chip("Aemond", "Harrenhal", "STILL HIDDEN", "bad"),
            chip("Vhagar", "Unaccounted", "STILL LOOSE", "bad")]},
        "control": {"label": "THE INSURGENCY", "held_by": "greens",
                    "text": "The war moved inside the walls and she was last to know."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 6 · The war is inside the Red Keep",
        "changed": ["Information", "Force", "Legitimacy", "Daeron"]},
}

# --- supplied character portraits ------------------------------------------------------------
# 13 of this episode's 27 named figures exist in the library, so those shots use a framed portrait
# panel (hotd.figure) instead of a heraldic card. The other 14 keep their cards until portraits
# arrive. Name/role/status come from the same source as the cards, so the two treatments always
# agree about what a character's state is.
LIBRARY = "house-of-dragons/hotd-character-library/masters"
STEM_TO_SLUG = {'01_char_rhaenyra': 'rhaenyra-targaryen', '02_char_daemon': 'daemon-targaryen', '03_char_mysaria': 'mysaria', '04_char_orwyle': 'grand-maester-orwyle', '05_char_torrhen': 'torrhen-manderly', '07_char_alyn': 'alyn-of-hull', '08_char_addam': 'addam-of-hull', '09_char_baela': 'baela-targaryen', '10_char_joffrey': 'joffrey-velaryon', '11_char_largent': 'ser-luthor-largent', '20_char_ormund': 'ormund-hightower', '21_char_daeron': 'daeron-targaryen', '22_char_aegon': 'aegon-ii-targaryen', '23_char_aemond': 'aemond-targaryen', '24_char_alicent': 'alicent-hightower', '25_char_helaena': 'helaena-targaryen', '26_char_larys': 'larys-strong', '27_char_tyland': 'tyland-lannister', '28_char_criston': 'criston-cole', '29_char_gwayne': 'gwayne-hightower', '30_char_alys': 'alys-rivers', '40_char_oscar_tully': 'oscar-tully', '41_char_roderick_dustin': 'roderick-dustin', '43_char_janos': 'janos'}

# Dragons are landscape subjects, so their panel uses the wide box and a centred crop.
DRAGON_TO_SLUG = {'50_dragon_vhagar': 'vhagar', '51_dragon_caraxes': 'caraxes', '52_dragon_seasmoke': 'seasmoke', '53_dragon_moondancer': 'moondancer', '54_dragon_tessarion': 'tessarion', '55_dragon_sunfyre': 'sunfyre'}


def _figures():
    import hotd_s3e5_assets as A5
    TONE = {"key": (214, 176, 96), "bad": (196, 74, 66), "good": (110, 168, 116),
            "neutral": (150, 160, 176), "dead": (196, 74, 66)}
    out = {}
    for stem, slug in STEM_TO_SLUG.items():
        r = {x[6]: x for x in A5.CHARACTERS}.get(stem)
        if r:
            out[slug] = {"portrait": f"{LIBRARY}/{slug}-master.png", "name": r[0],
                         "role": r[2], "status": r[3], "stem": stem, "shape": "tall",
                         "tone": TONE.get(r[4], TONE["bad"])}
    for stem, slug in DRAGON_TO_SLUG.items():
        r = {x[5]: x for x in A5.DRAGONS}.get(stem)
        if r:
            out[slug] = {"portrait": f"{LIBRARY}/{slug}-master.png", "name": r[0],
                         "role": r[2], "status": r[3], "stem": stem, "shape": "wide",
                         "tone": TONE.get(r[4], TONE["bad"])}
    return out


FIGURES = _figures()


def _subject_words():
    """asset name -> the words that would name that subject in narration.

    Built from the same rosters the cards and portraits come from, so the shot chooser and the
    on-screen status can never disagree about who a shot is of.
    """
    import hotd_s3e5_assets as A5
    out = {}
    # Titles identify nobody in a story where everyone has one.
    STOP = {"lord", "lady", "house", "prince", "princess", "king", "queen", "ser"}
    # A role is only allowed to identify someone through words that MEAN that role. Left unfiltered,
    # roles matched: places ("At Harrenhal" made a castle mean Alys Rivers, so "the Harrenhal Jacaerys
    # promised her house" showed the wrong woman), other people ("rides with Criston" made every
    # Criston mention show Gwayne, and "Aemond's mount" made Vhagar mean Aemond), and common nouns
    # ("Master of Coin" made THE COIN -- this episode's central object -- mean Tyland Lannister).
    ROLE_STOP = {"coin", "crown", "council", "rest", "with", "rides", "serves", "iron", "mount",
                 "master", "maester", "grand", "dragonrider", "claimant", "rival", "throne",
                 "deposed", "wounded", "confined", "dowager"}
    def add(key, label):
        ws = {w.lower().strip(",.") for w in label.replace("'s", "").split() if len(w) > 3}
        ws -= STOP
        if ws:
            out.setdefault(key, set()).update(ws)
    for r in A5.CHARACTERS:
        add(r[6], r[0])                                    # heraldic card stem
        if r[6] in STEM_TO_SLUG:
            add(STEM_TO_SLUG[r[6]], r[0])                   # portrait slug
    # Roles matter as much as names: the cold open kills "her Watch commander" and never says Luthor
    # Largent, so a name-only matcher shows the wrong man during the episode's first thirty seconds.
    # every word that is somebody's NAME, and every location token, is off limits to a role
    forbidden = set(ROLE_STOP)
    for f in FIGURES.values():
        forbidden |= {w.lower().strip("'s") for w in f["name"].split() if len(w) > 3}
    role = {}
    def add_role(key, label):
        ws = {w.lower().strip(",.'") for w in label.replace("'s", "").split() if len(w) > 3}
        ws -= STOP | forbidden
        if ws:
            role.setdefault(key, set()).update(ws)
    for slug, f in FIGURES.items():
        add_role(slug, f.get("role", ""))
        if f.get("stem"):
            add_role(f["stem"], f.get("role", ""))
    for r in A5.DRAGONS:
        add(r[5], r[0])
        if r[5] in DRAGON_TO_SLUG:
            add(DRAGON_TO_SLUG[r[5]], r[0])
    # A word shared by several people identifies nobody. "Targaryen" is in almost every sentence of
    # this episode and belongs to seven characters, so leaving it in marks all seven as named and the
    # relevance test stops meaning anything. Same for Hightower and Velaryon.
    seen = {}
    for words in out.values():
        for w in words:
            seen[w] = seen.get(w, 0) + 1
    shared = {w for w, n in seen.items() if n > 2}        # >2 because card + portrait share a name
    for k in out:
        out[k] = out[k] - shared
    rseen = {}
    for words in role.values():
        for w in words:
            rseen[w] = rseen.get(w, 0) + 1
    rshared = {w for w, n in rseen.items() if n > 2}      # "Commander" is Criston AND Largent
    role = {k: (v - rshared) for k, v in role.items()}
    return ({k: v for k, v in out.items() if v}, {k: v for k, v in role.items() if v})


SUBJECT_WORDS, ROLE_WORDS = _subject_words()
# every portrait a segment may be given if its block pool cannot show who it names
PORTRAITS = [s for s in list(STEM_TO_SLUG.values()) + list(DRAGON_TO_SLUG.values()) if s in FIGURES]

# One person, not two assets: a heraldic card stem and a portrait slug are the same human, and
# treating them separately made a single mention look like two people being discussed at once.
_P = dict(STEM_TO_SLUG); _P.update(DRAGON_TO_SLUG)
PERSON_OF = lambda asset: _P.get(asset, asset)


# --- shot pools, one per storyboard block ------------------------------------------------------
# First entry of every pool MUST be a plate or a single card: a segment's caption is drawn on its
# first shot, and a self-titled diagram or a stacked pair has nowhere to put it.
# Diagram shots ("full") are the ones hotd.reveal animates into a claim-by-claim build, so each
# block that carries an argument gets one.
POOLS = {
    "cold_open": [
        ("plate", "74_loc_watch_undercroft"),
        ("card", "44_char_conspirator", "73_loc_flea_bottom"),
        ("figure", "daeron-targaryen", "75_loc_tumbleton_command"),
        ("full", "60_graphic_attack_chain"),
        ("plate", "12_loc_kings_landing"),
    ],
    "the_six_active_crises": [
        ("plate", "12_loc_kings_landing"),
        ("full", "62_graphic_six_crises"),
        ("cards", ["01_char_rhaenyra", "02_char_daemon"], "59_loc_small_council_chamber"),
        ("plate", "59_loc_small_council_chamber"),
        ("figure", "torrhen-manderly", "59_loc_small_council_chamber"),
        ("full", "6B_graphic_territory_vs_control"),
    ],
    "daemon_chooses_the_gold_cloaks_over_vhagar": [
        ("figure", "daemon-targaryen", "74_loc_watch_undercroft"),
        ("plate", "74_loc_watch_undercroft"),
        ("figure", "ser-luthor-largent", "74_loc_watch_undercroft"),
        ("cards", ["50_dragon_vhagar", "51_dragon_caraxes"], "80_loc_wendish_town"),
        ("plate", "80_loc_wendish_town"),
        ("full", "6B_graphic_territory_vs_control"),
    ],
    "joffrey_and_the_cost_of_naming_another_heir": [
        ("plate", "71_loc_joffrey_bedroom"),
        ("figure", "joffrey-velaryon", "71_loc_joffrey_bedroom"),
        ("cards", ["09_char_baela", "53_dragon_moondancer"], "12_loc_kings_landing"),
        ("figure", "rhaenyra-targaryen", "70_loc_red_keep_sept"),
    ],
    "ormund_puts_daeron_on_the_money": [
        ("plate", "75_loc_tumbleton_command"),
        ("full", "61_graphic_coin_anatomy"),
        ("figure", "ormund-hightower", "75_loc_tumbleton_command"),
        ("figure", "daeron-targaryen", "75_loc_tumbleton_command"),
        ("plate", "73_loc_flea_bottom"),
        ("full", "60_graphic_attack_chain"),
    ],
    "two_brothers_who_both_think_the_mother_chose_the_other": [
        ("figure", "aemond-targaryen", "76_loc_harrenhal_sickroom"),
        ("full", "63_graphic_two_brothers"),
        ("figure", "aegon-ii-targaryen", "77_loc_rooks_rest_camp"),
        ("figure", "alicent-hightower", "74_loc_alicent_helaena_quarters"),
        ("plate", "78_loc_harrenhal_courtyard"),
    ],
    "what_alys_is_doing_to_aemond": [
        ("plate", "76_loc_harrenhal_sickroom"),
        ("figure", "alys-rivers", "76_loc_harrenhal_sickroom"),
        ("full", "64_graphic_aemond_identity"),
        ("figure", "aemond-targaryen", "78_loc_harrenhal_courtyard"),
        ("figure", "vhagar", "80_loc_wendish_town"),
        ("plate", "78_loc_harrenhal_courtyard"),
    ],
    "helaena_says_no": [
        ("plate", "74_loc_alicent_helaena_quarters"),
        ("figure", "helaena-targaryen", "74_loc_alicent_helaena_quarters"),
        ("full", "65_graphic_helaena_decision"),
        ("figure", "grand-maester-orwyle", "74_loc_alicent_helaena_quarters"),
        ("figure", "alicent-hightower", "74_loc_alicent_helaena_quarters"),
        ("plate", "70_loc_red_keep_sept"),
    ],
    "alicent_turns_herself_into_the_cover_story": [
        ("figure", "alicent-hightower", "74_loc_alicent_helaena_quarters"),
        ("cards", ["24_char_alicent", "25_char_helaena"], "74_loc_alicent_helaena_quarters"),
        ("full", "66_graphic_mysaria_inventory"),
        ("figure", "mysaria", "12_loc_kings_landing"),
        ("plate", "74_loc_alicent_helaena_quarters"),
    ],
    "the_passage_that_goes_nowhere": [
        ("plate", "72_loc_hidden_passage"),
        ("figure", "helaena-targaryen", "72_loc_hidden_passage"),
        ("figure", "alicent-hightower", "72_loc_hidden_passage"),
        ("full", "66_graphic_mysaria_inventory"),
    ],
    "criston_wins_time_and_loses_purpose": [
        ("plate", "78_loc_caltrop_ambush"),
        ("figure", "criston-cole", "78_loc_caltrop_ambush"),
        ("full", "67_graphic_criston_mission"),
        ("plate", "79_loc_ruined_crossing"),
        ("figure", "gwayne-hightower", "77_loc_riverlands_camp"),
        ("cards", ["40_char_oscar_tully", "41_char_roderick_dustin"], "77_loc_riverlands_camp"),
    ],
    "aegon_is_told_he_is_terrible_and_becomes_active_again": [
        ("plate", "77_loc_rooks_rest_camp"),
        ("figure", "larys-strong", "77_loc_rooks_rest_camp"),
        ("full", "68_graphic_aegon_before_after"),
        ("figure", "aegon-ii-targaryen", "77_loc_rooks_rest_camp"),
        ("figure", "tyland-lannister", "77_loc_rooks_rest_camp"),
        ("figure", "janos", "77_loc_rooks_rest_camp"),
    ],
    "the_coin_reaches_the_red_keep": [
        ("card", "44_char_conspirator", "73_loc_flea_bottom"),
        ("full", "61_graphic_coin_anatomy"),
        ("figure", "mysaria", "59_loc_small_council_chamber"),
        ("figure", "rhaenyra-targaryen", "59_loc_small_council_chamber"),
        ("plate", "59_loc_small_council_chamber"),
    ],
    "a_feast_for_traitors": [
        ("plate", "74_loc_watch_undercroft"),
        ("figure", "ser-luthor-largent", "74_loc_watch_undercroft"),
        ("figure", "daemon-targaryen", "74_loc_watch_undercroft"),
        ("full", "60_graphic_attack_chain"),
        ("plate", "73_loc_flea_bottom"),
    ],
    "show_versus_book": [
        ("plate", "12_loc_kings_landing"),
        ("full", "69_graphic_show_vs_book"),
        ("figure", "alys-rivers", "76_loc_harrenhal_sickroom"),
        ("figure", "helaena-targaryen", "74_loc_alicent_helaena_quarters"),
        ("plate", "78_loc_harrenhal_courtyard"),
    ],
    "who_won_the_episode": [
        ("figure", "ormund-hightower", "75_loc_tumbleton_command"),
        ("full", "6A_graphic_winner_scoreboard"),
        ("figure", "mysaria", "12_loc_kings_landing"),
        ("figure", "rhaenyra-targaryen", "59_loc_small_council_chamber"),
        ("figure", "alys-rivers", "76_loc_harrenhal_sickroom"),
    ],
    "conclusion": [
        ("plate", "74_loc_watch_undercroft"),
        ("full", "6B_graphic_territory_vs_control"),
        ("figure", "daeron-targaryen", "75_loc_tumbleton_command"),
        ("plate", "12_loc_kings_landing"),
    ],
}


# --- storyboard blocks (§12), ids from the scaffold ---------------------------------------------
BLOCK_CHAPTER = {
    "cold_open": "They are already inside",
    "the_six_active_crises": "Six crises at once",
    "daemon_chooses_the_gold_cloaks_over_vhagar": "Why Daemon ignores Vhagar",
    "joffrey_and_the_cost_of_naming_another_heir": "The cost of naming an heir",
    "ormund_puts_daeron_on_the_money": "Daeron on the money",
    "two_brothers_who_both_think_the_mother_chose_the_other": "Two brothers, one mother",
    "what_alys_is_doing_to_aemond": "What Alys is doing",
    "helaena_says_no": "Helaena says no",
    "alicent_turns_herself_into_the_cover_story": "Alicent becomes the cover",
    "the_passage_that_goes_nowhere": "The passage that goes nowhere",
    "criston_wins_time_and_loses_purpose": "Criston wins time, loses purpose",
    "aegon_is_told_he_is_terrible_and_becomes_active_again": "Aegon is told the truth",
    "the_coin_reaches_the_red_keep": "The coin reaches the Keep",
    "a_feast_for_traitors": "A feast for traitors",
    "show_versus_book": "Show versus book",
    "who_won_the_episode": "Who won the episode?",
    "conclusion": "The war is inside",
}

# Segment ids come from the script author, block names from the spec's storyboard headings, and the
# two need not match: the script sensibly wrote `six_crises_a` where the scaffold slugified the
# heading to `the_six_active_crises`. Prefix matching alone then finds no pool, so ids are mapped
# explicitly. Aliases are checked before prefixes.
BLOCK_ALIASES = {
    "six_crises": "the_six_active_crises",
    "daemon_chooses": "daemon_chooses_the_gold_cloaks_over_vhagar",
    "joffrey_cost": "joffrey_and_the_cost_of_naming_another_heir",
    "daeron_money": "ormund_puts_daeron_on_the_money",
    "two_brothers": "two_brothers_who_both_think_the_mother_chose_the_other",
    "alys_control": "what_alys_is_doing_to_aemond",
    "alicent_cover": "alicent_turns_herself_into_the_cover_story",
    "passage_nowhere": "the_passage_that_goes_nowhere",
    "criston_wins_time": "criston_wins_time_and_loses_purpose",
    "aegon_told_terrible": "aegon_is_told_he_is_terrible_and_becomes_active_again",
    "coin_reaches_red_keep": "the_coin_reaches_the_red_keep",
    "feast_for_traitors": "a_feast_for_traitors",
    "who_won": "who_won_the_episode",
}

BLOCK_STATE = {
    "cold_open": "open",
    "the_six_active_crises": "open",
    "daemon_chooses_the_gold_cloaks_over_vhagar": "capital",
    "joffrey_and_the_cost_of_naming_another_heir": "capital",
    "ormund_puts_daeron_on_the_money": "capital",
    "two_brothers_who_both_think_the_mother_chose_the_other": "harrenhal",
    "what_alys_is_doing_to_aemond": "harrenhal",
    "helaena_says_no": "confinement",
    "alicent_turns_herself_into_the_cover_story": "confinement",
    "the_passage_that_goes_nowhere": "confinement",
    "criston_wins_time_and_loses_purpose": "field",
    "aegon_is_told_he_is_terrible_and_becomes_active_again": "field",
    "the_coin_reaches_the_red_keep": "capital",
    "a_feast_for_traitors": "capital",
    "show_versus_book": "final",
    "who_won_the_episode": "final",
    "conclusion": "final",
}

# --- upload metadata (§5) ----------------------------------------------------------------------
META = {
    "module": "episodes/s3e5.py",
    "title": "House of the Dragon S3E5 Explained: The War Is Inside the Red Keep",
    "alternatives": [
        "House of the Dragon Season 3 Episode 5 Explained: The Daeron Coin",
        "Why Ormund Put Daeron's Face on the Money | HOTD S3E5 Explained",
        "The Gold Cloaks Were Killed Under the Red Keep - Here Is Why",
    ],
    "intro": ("Ormund Hightower never marched on King's Landing. He put another king's face on the "
              "money and let the city carry the war in its pockets."),
    "body": ("A full breakdown of Season 3, Episode 5: why Daemon chooses an unpaid police force "
             "over hunting a dragon, what the Daeron coins actually do, what Alys is building at "
             "Harrenhal, why Helaena refuses, what Alicent drinks to cover for her, and why Criston "
             "marches toward a death he has already accepted."),
    "argument": ("Power here has four parts - territory, information, legitimacy and force. "
                 "Rhaenyra keeps the territory and loses the other three, and information is the "
                 "one she loses first."),
    "spoilers": ("Covers up to and including Season 3, Episode 5. No leaks and no unaired material. "
                 "Book readers: the show-versus-book chapter is flagged before it starts."),
    "hashtags": "#HouseOfTheDragon #HOTD #Daeron #Aemond #DanceOfTheDragons #FireAndBlood",
    "tags": ["house of the dragon", "house of the dragon season 3", "house of the dragon s3e5",
             "house of the dragon episode 5 explained", "hotd s3e5", "hotd explained",
             "daeron targaryen", "aemond targaryen", "alys rivers", "helaena targaryen",
             "alicent hightower", "daemon targaryen", "gold cloaks", "ormund hightower",
             "criston cole", "aegon ii", "tyland lannister", "dance of the dragons",
             "fire and blood", "westeros politics"],
    "thumbnail": PACK + "/thumbnail/95_thumbnail_they_are_inside.png",
    "image_spend_usd": 0.0,
    "accuracy_note": "",
}
