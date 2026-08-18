"""House of the Dragon S3E4 — episode DATA only.

Rail states from spec §6/§7/§9, shot pools per storyboard block, chapter titles and upload metadata.
No engine code: the engine is hotd/, and this module must not import it beyond the chip helper.

Roles and tags in the rail states are kept short on purpose: a chip lays its tag pill on the role's
row, so a long tag ellipsises the role away.
"""
from __future__ import annotations

from hotd.episode import chip

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
            chip("Aegon II", "Deposed king", "AT BOTTOM", "bad"),
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


POOLS = {
    "cold_open": [
        ("plate", "16_loc_tumbleton_occupied"),
        ("card", "21_char_daeron", "70_loc_tumbleton_street"),
        ("card", "20_char_ormund", "71_loc_footly_residence"),
        ("card", "50_dragon_tessarion", "16_loc_tumbleton_occupied"),
        ("full", "61_graphic_why_no_burn"),
    ],
    "board": [
        ("plate", "12_loc_kings_landing"),
        ("full", "6B_graphic_board_map"),
        ("cards", ["28_char_aemond_missing", "56_dragon_vhagar"], "78_loc_harrenhal_courtyard"),
        ("plate", "78_loc_harrenhal_courtyard"),
        ("cards", ["26_char_criston", "27_char_gwayne"], "56_loc_riverlands"),
        ("card", "29_char_alys", "78_loc_harrenhal_courtyard"),
        # NOT E3's 17_graphic_strategic_map: diagrams carry their episode number in the title, so
        # reusing one puts "EPISODE 3 -- THE STRATEGIC PICTURE" on screen inside episode 4. Locations
        # and heraldry travel between episodes; episode-labelled diagrams never do.
        ("full", "60_graphic_four_axes"),
        ("card", "53_dragon_caraxes", "79_loc_eyrie_hall"),
    ],
    "tumbleton_shield": [
        ("plate", "70_loc_tumbleton_street"),
        ("plate", "71_loc_footly_residence"),
        ("cards", ["40_char_glendon_footly", "41_char_sharis_footly"], "71_loc_footly_residence"),
        ("plate", "72_loc_tumbleton_family_home"),
        ("full", "61_graphic_why_no_burn"),
        ("plate", "73_loc_tumbleton_sept"),
        ("card", "20_char_ormund", "70_loc_tumbleton_street"),
    ],
    "real_daeron": [
        ("card", "21_char_daeron", "52_loc_oldtown_hightower"),
        ("full", "63_graphic_real_daeron_id"),
        ("card", "05_char_daeron_false", "16_loc_tumbleton_occupied"),
        ("cards", ["50_dragon_tessarion", "56_dragon_vhagar"], "78_loc_harrenhal_courtyard"),
        ("plate", "52_loc_oldtown_hightower"),
        ("card", "22_char_alicent", "74_loc_alicent_helaena_quarters"),
    ],
    "rhaenyra_response": [
        ("plate", "59_loc_small_council_chamber"),
        ("cards", ["04_char_orwyle", "03_char_mysaria"], "59_loc_small_council_chamber"),
        ("card", "05_char_torrhen", "59_loc_small_council_chamber"),
        ("card", "01_char_rhaenyra", "13_loc_iron_throne_room"),
        ("full", "60_graphic_four_axes"),
        ("card", "51_dragon_vermithor", "16_loc_tumbleton_occupied"),
    ],
    "alicent_motherhood": [
        ("plate", "74_loc_alicent_helaena_quarters"),
        ("card", "22_char_alicent", "74_loc_alicent_helaena_quarters"),
        ("card", "20_char_ormund", "52_loc_oldtown_hightower"),
        ("cards", ["22_char_alicent", "01_char_rhaenyra"], "51_loc_red_keep"),
        ("card", "21_char_daeron", "52_loc_oldtown_hightower"),
    ],
    "aegon_without_kingship": [
        ("plate", "76_loc_rooks_rest_battlefield"),
        ("card", "57_dragon_meleys", "76_loc_rooks_rest_battlefield"),
        ("card", "55_dragon_sunfyre", "76_loc_rooks_rest_battlefield"),
        ("plate", "77_loc_rooks_rest_camp"),
        ("cards", ["24_char_aegon", "25_char_larys"], "77_loc_rooks_rest_camp"),
        ("full", "64_graphic_aegon_inventory"),
    ],
    "dragonseed_control": [
        ("card", "09_char_ulf", "12_loc_kings_landing"),
        ("cards", ["08_char_hugh", "09_char_ulf"], "12_loc_kings_landing"),
        ("card", "51_dragon_vermithor", "16_loc_tumbleton_occupied"),
        ("card", "52_dragon_silverwing", "12_loc_kings_landing"),
        ("full", "65_graphic_dragonseed_control"),
        ("card", "01_char_rhaenyra", "13_loc_iron_throne_room"),
    ],
    "queen_of_bastards": [
        ("plate", "75_loc_graffiti_street"),
        ("full", "66_graphic_graffiti_loop"),
        ("card", "03_char_mysaria", "75_loc_graffiti_street"),
        ("cards", ["06_char_corlys", "07_char_alyn"], "57_loc_dragonstone"),
        ("plate", "60_loc_petition_hall"),
        ("card", "01_char_rhaenyra", "60_loc_petition_hall"),
    ],
    "daemon_finds_rhaena": [
        ("plate", "81_loc_vale_shepherding"),
        ("card", "45_char_vale_shepherd", "81_loc_vale_shepherding"),
        ("plate", "80_loc_vale_cave"),
        ("card", "10_char_rhaena", "80_loc_vale_cave"),
        ("card", "54_dragon_sheepstealer", "80_loc_vale_cave"),
        ("card", "02_char_daemon", "80_loc_vale_cave"),
        ("plate", "79_loc_eyrie_hall"),
        ("card", "11_char_jeyne_arryn", "79_loc_eyrie_hall"),
        ("full", "67_graphic_parallel_deceptions"),
        ("card", "03_char_mysaria", "12_loc_kings_landing"),
    ],
    "hidden_heir": [
        ("plate", "74_loc_alicent_helaena_quarters"),
        ("card", "23_char_helaena", "74_loc_alicent_helaena_quarters"),
        ("full", "68_graphic_helaena_inference"),
        ("card", "22_char_alicent", "74_loc_alicent_helaena_quarters"),
        ("plate", "52_loc_oldtown_hightower"),
        ("card", "01_char_rhaenyra", "74_loc_alicent_helaena_quarters"),
        ("plate", "51_loc_red_keep"),
    ],
    "ormund_changes_plan": [
        ("plate", "71_loc_footly_residence"),
        ("card", "20_char_ormund", "71_loc_footly_residence"),
        ("full", "62_graphic_plan_change"),
        ("card", "42_char_garrick", "70_loc_tumbleton_street"),
        ("card", "43_char_leon", "72_loc_tumbleton_family_home"),
        ("plate", "72_loc_tumbleton_family_home"),
        ("card", "21_char_daeron", "71_loc_footly_residence"),
        ("card", "50_dragon_tessarion", "16_loc_tumbleton_occupied"),
        ("plate", "73_loc_tumbleton_sept"),
        ("plate", "70_loc_tumbleton_street"),
    ],
    "faith_gap": [
        ("plate", "51_loc_red_keep"),
        ("card", "09_char_high_septon", "12_loc_kings_landing"),
        ("full", "60_graphic_four_axes"),
        ("card", "01_char_rhaenyra", "13_loc_iron_throne_room"),
        ("plate", "60_loc_petition_hall"),
    ],
    "fathers": [
        ("card", "07_char_alyn", "59_loc_small_council_chamber"),
        ("cards", ["06_char_corlys", "07_char_alyn"], "57_loc_dragonstone"),
        ("card", "01_char_rhaenyra", "59_loc_small_council_chamber"),
        ("full", "67_graphic_parallel_deceptions"),
        ("plate", "59_loc_small_council_chamber"),
    ],
    "daemon_choice": [
        ("card", "02_char_daemon", "80_loc_vale_cave"),
        ("card", "10_char_rhaena", "80_loc_vale_cave"),
        ("full", "67_graphic_parallel_deceptions"),
        ("card", "45_char_vale_shepherd", "81_loc_vale_shepherding"),
        ("card", "03_char_mysaria", "12_loc_kings_landing"),
    ],
    "who_won": [
        ("card", "20_char_ormund", "16_loc_tumbleton_occupied"),
        ("full", "69_graphic_winner_scoreboard"),
        ("card", "01_char_rhaenyra", "13_loc_iron_throne_room"),
        ("card", "02_char_daemon", "79_loc_eyrie_hall"),
        ("card", "03_char_mysaria", "12_loc_kings_landing"),
        ("card", "21_char_daeron", "71_loc_footly_residence"),
    ],
    "show_versus_book": [
        ("plate", "53_loc_the_reach_farmland"),
        ("full", "6A_graphic_show_vs_book"),
        ("card", "21_char_daeron", "52_loc_oldtown_hightower"),
        ("card", "10_char_rhaena", "80_loc_vale_cave"),
        ("plate", "57_loc_dragonstone"),
        ("card", "05_char_daeron_false", "16_loc_tumbleton_occupied"),
        ("card", "54_dragon_sheepstealer", "80_loc_vale_cave"),
    ],
    "conclusion": [
        ("plate", "16_loc_tumbleton_occupied"),
        ("full", "60_graphic_four_axes"),
        ("card", "21_char_daeron", "71_loc_footly_residence"),
        ("card", "20_char_ormund", "71_loc_footly_residence"),
        ("plate", "70_loc_tumbleton_street"),
        ("card", "01_char_rhaenyra", "13_loc_iron_throne_room"),
    ],
}


BLOCK_STATE = {
    "cold_open": "open", "board": "open",
    "tumbleton_shield": "tumbleton", "real_daeron": "tumbleton",
    "rhaenyra_response": "court", "alicent_motherhood": "court",
    "dragonseed_control": "court", "queen_of_bastards": "court", "hidden_heir": "court",
    "aegon_without_kingship": "aegon",
    "daemon_finds_rhaena": "vale", "ormund_changes_plan": "vale",
    "faith_gap": "court", "fathers": "court", "daemon_choice": "vale",
    "who_won": "final", "show_versus_book": "final", "conclusion": "final",
}


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
