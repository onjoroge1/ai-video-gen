"""Episode config for HotD S3E4 — everything episode-specific for hotd_build.py.

Asset packs are searched E4-first, then E3, so this episode reuses the earlier locations, maps and
heraldry and only pays for genuine gaps.

The rail advances through six states, one per act, tracking the spec §6 model
(TERRITORY / FIREPOWER / LEGITIMACY / HUMAN COST). The final state switches the rail's left column
from people to those four axes, because that is what the episode's argument resolves into.

Roles and tags are kept short: the chip lays its tag pill on the role's row, so long strings
ellipsise the role away.
"""
from __future__ import annotations

import hotd_build as HB
from hotd_build import chip

PACK_E4 = "house-of-dragons/house_of_the_dragon_s3e4_complete_asset_pack/images"
PACK_E3 = "house-of-dragons/house_of_the_dragon_s3e3_complete_asset_pack/images"
SUB = "House of the Dragon · S3E4"

STATES = {
    "open": {
        "title": "STATE OF THE WAR", "subtitle": SUB,
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            chip("Rhaenyra", "Queen", "HOLDS THE CITY", "key"),
            chip("Daemon", "Consort", "SENT TO VALE", "neutral"),
            chip("Mysaria", "Whisperers", "NETWORK LIVE", "good"),
            chip("Hugh & Ulf", "Dragonriders", "UNSTABLE", "neutral")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            chip("Ormund", "Hightower", "TOOK THE TOWN", "good"),
            chip("Daeron", "Prince", "WITH ORMUND", "neutral"),
            chip("Aemond", "Vhagar", "MISSING", "bad"),
            chip("Aegon II", "Deposed", "OUT OF SIGHT", "bad")]},
        "control": {"label": "TUMBLETON", "held_by": "greens",
                    "text": "A town that declared for her, taken by a feint."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 1 · Where everyone stands",
        "changed": ["Ormund", "control"]},
    "tumbleton": {
        "title": "THE OCCUPATION", "subtitle": SUB + " · Tumbleton",
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            chip("Rhaenyra", "Queen", "CANNOT BURN IT", "bad"),
            chip("Hugh", "Vermithor", "SENT TO WATCH", "neutral"),
            chip("Tumbleton", "Declared Black", "OCCUPIED", "bad"),
            chip("The Footlys", "Town's lords", "DISPOSSESSED", "bad")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            chip("Ormund", "Hightower", "15,000 MEN", "good"),
            chip("Residents", "Human shield", "HELD", "bad"),
            chip("Daeron", "Tessarion", "IN THE TOWN", "neutral"),
            chip("Aemond", "Vhagar", "STILL MISSING", "bad")]},
        "control": {"label": "TUMBLETON", "held_by": "greens",
                    "text": "Fifteen thousand men quartered in civilian homes."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 2 · Why the town cannot be burned",
        "changed": ["Rhaenyra", "Residents", "Tumbleton", "The Footlys"]},
    "court": {
        "title": "THE COURT", "subtitle": SUB + " · King's Landing",
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            chip("Rhaenyra", "Queen", "POLICING TALK", "bad"),
            chip("Corlys", "Hand", "WITHDRAWN", "bad"),
            chip("Alyn", "Sent instead", "NO NAME YET", "neutral"),
            chip("Ulf", "Silverwing", "RESTRICTED", "bad")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            chip("Alicent", "Dowager", "EXPLAINS HIM", "neutral"),
            chip("Helaena", "Confined", "PREGNANCY?", "bad"),
            chip("High Septon", "The Faith", "STILL OUTSIDE", "bad"),
            chip("Aemond", "Vhagar", "MISSING", "bad")]},
        "control": {"label": "LEGITIMACY", "held_by": "contested",
                    "text": "Suppressing the insult is what spreads it."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 3 · The court she cannot control",
        "changed": ["Corlys", "Ulf", "Alicent", "Helaena"]},
    "aegon": {
        "title": "THE FUGITIVE KING", "subtitle": SUB + " · Rook's Rest",
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            chip("Rhaenyra", "Queen", "UNAWARE", "neutral"),
            chip("Mysaria", "Whisperers", "SUSPICIOUS", "good"),
            chip("Meleys", "Rhaenys's", "REMAINS", "dead"),
            chip("Hugh & Ulf", "Dragonriders", "WATCHED", "neutral")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            chip("Aegon II", "Deposed king", "AT THE BOTTOM", "bad"),
            chip("Larys", "Whisperers", "WITH AEGON", "neutral"),
            chip("Sunfyre", "His dragon", "UNCERTAIN", "bad"),
            chip("Criston", "Kingsguard", "MARCHING", "bad")]},
        "control": {"label": "ROOK'S REST", "held_by": "contested",
                    "text": "A king nobody is looking for any more."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 4 · Aegon without kingship",
        "changed": ["Aegon II", "Sunfyre", "Criston", "Larys"]},
    "vale": {
        "title": "THE DECEPTION", "subtitle": SUB + " · the Vale",
        "left": {"name": "THE BLACKS", "accent": "steel", "chips": [
            chip("Daemon", "Consort", "LIES TO HER", "bad"),
            chip("Rhaena", "Sheepstealer", "FOUND", "key"),
            chip("Jeyne Arryn", "The Vale", "PAYS UP", "good"),
            chip("Mysaria", "Whisperers", "SUSPECTS HIM", "good")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            chip("Ormund", "Hightower", "STOPS WAITING", "good"),
            chip("Daeron", "Prince", "BEING BUILT", "bad"),
            chip("Vhagar", "Aemond's", "NOT COMING", "bad"),
            chip("Tessarion", "Daeron's", "WITH HOST", "good")]},
        "control": {"label": "THE TRUTH", "held_by": "contested",
                    "text": "Two fathers, the same method."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 5 · Daemon finds Rhaena",
        "changed": ["Daemon", "Rhaena", "Ormund", "Vhagar"]},
    "final": {
        # left column switches from people to the §6 axes: that is what the episode resolves into
        "title": "END OF EPISODE", "subtitle": SUB,
        "left": {"name": "THE FOUR AXES", "accent": "steel", "chips": [
            chip("Territory", "The capital", "HELD", "good"),
            chip("Firepower", "Many dragons", "UNUSABLE", "bad"),
            chip("Legitimacy", "The Faith", "OUTSIDE", "bad"),
            chip("Human cost", "A whole town", "BINDING", "bad")]},
        "right": {"name": "THE GREENS", "accent": "green", "chips": [
            chip("Ormund", "Hightower", "EP. WINNER", "good"),
            chip("Daeron", "Made to kill", "A NEW KING?", "bad"),
            chip("Aegon II", "Deposed", "STILL HIDDEN", "bad"),
            chip("Aemond", "Vhagar", "STILL MISSING", "bad")]},
        "control": {"label": "THE PLAN", "held_by": "greens",
                    "text": "He stopped waiting and started building."},
        "dragons": {"left": 5, "right": 2, "right_dim": 1},
        "footer": "CH 6 · Ormund changes the plan",
        "changed": ["Firepower", "Human cost", "Daeron", "Ormund"]},
}

# Filled once the script's segment ids exist.
PLAYLISTS: dict = {}
SEG_STATE: dict = {}

# spec §11 has FIFTEEN storyboard blocks (0:00 cold open through 13:30 conclusion). Chapter names
# follow those blocks; ids are attached after the script is written.
# block id -> chapter title. Keyed by block, not by position, so the three blocks the correction
# pass added (faith_gap, fathers, daemon_choice) get real names instead of a titleized id.
BLOCK_CHAPTER = {
    "cold_open": "A new king?",
    "board": "Where everyone stands",
    "tumbleton_shield": "Why Tumbleton is a human shield",
    "real_daeron": "The real Daeron",
    "rhaenyra_response": "Rhaenyra's impossible response",
    "faith_gap": "The Faith still says no",
    "alicent_motherhood": "Alicent's truest act of motherhood",
    "fathers": "Fathers and the sons they place",
    "aegon_without_kingship": "Aegon without kingship",
    "dragonseed_control": "She cannot control every dragonrider",
    "queen_of_bastards": "Queen of Bastards",
    "daemon_finds_rhaena": "Daemon finds Rhaena",
    "daemon_choice": "Why Daemon lies",
    "hidden_heir": "The hidden heir",
    "ormund_changes_plan": "Ormund changes the plan",
    "who_won": "Who won the episode?",
    "show_versus_book": "Show versus book",
    "conclusion": "Ruling means building a king",
}

META = {
    "module": "hotd_s3e4_episode",
    "title": "House of the Dragon S3E4 Explained: Ormund Is Building a New King",
    "alternatives": [
        "House of the Dragon Season 3 Episode 4 Explained: Why Ormund Took Tumbleton",
        "Why Ormund Forced Daeron to Kill | HOTD S3E4 Explained",
        "Tumbleton Was Never the Real Target - Daeron Was",
    ],
    "intro": ("Ormund Hightower did not take Tumbleton because he needed the town. He took it "
              "because a town full of people who had declared for Rhaenyra is the one thing her "
              "dragons cannot burn."),
    "body": ("This is a full breakdown of House of the Dragon Season 3, Episode 4: the occupation "
             "that turns residents into armour, the real Daeron finally revealed, the execution "
             "Ormund forces him to perform, Aegon at the bottom of the order he used to sit atop, "
             "and a father in the Vale who protects his daughter with exactly the method Ormund is "
             "using in the Reach."),
    "argument": ("Power in this war has four parts - territory, firepower, legitimacy, and human "
                 "cost. Rhaenyra ends the episode holding the first two and unable to use either, "
                 "because the fourth one now decides what she is allowed to do."),
    "spoilers": ("Covers up to and including Season 3, Episode 4. No leaks and no unaired "
                 "material. Book readers: the show-versus-book chapter is flagged before it starts."),
    "hashtags": "#HouseOfTheDragon #HOTD #Ormund #Daeron #DanceOfTheDragons #FireAndBlood",
    "tags": ["house of the dragon", "house of the dragon season 3", "house of the dragon s3e4",
             "house of the dragon episode 4 explained", "hotd s3e4", "hotd explained",
             "ormund hightower", "daeron targaryen", "tumbleton", "tessarion",
             "rhaenyra targaryen", "daemon targaryen", "rhaena targaryen", "sheepstealer",
             "aegon ii", "sunfyre", "dance of the dragons", "fire and blood",
             "hotd season 3 explained", "westeros politics"],
    "thumbnail": (f"{PACK_E4}/thumbnail/90_thumbnail_a_new_king.png"),
    "image_spend_usd": 1.06,
    "accuracy_note": "",
}


def episode():
    return HB.Episode(
        slug="hotd_s3e4", out="renders/hotd_s3e4",
        packs=[PACK_E3, PACK_E4],          # later pack wins on a name clash
        states=STATES, playlists=PLAYLISTS, seg_state=SEG_STATE)
