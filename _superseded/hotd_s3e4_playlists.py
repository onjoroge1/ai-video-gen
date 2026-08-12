"""Shot playlists for S3E4, generated from per-BLOCK asset pools rather than per-segment lists.

Why pools: the audit requires several segments to be split so each card carries one honest canon
label, so the final segment ids are not known in advance (hidden_heir becomes hidden_heir_a/_b/_c,
and so on). A pool keyed on the storyboard block survives any amount of splitting -- a segment just
draws the next shots from its block's pool, and the cursor carries across the split.

Shot kinds: plate (full-bleed location + rail), card (one card over a dimmed plate + rail),
cards (two stacked cards + rail), full (diagram, full-bleed, no rail), map (supplied map, no rail).

Assets resolve across both packs, E4 winning on a name clash.
"""
from __future__ import annotations

import json

# block -> ordered pool of shots. First entry of every pool must be a plate or a single card:
# a segment may open on one, and a self-titled diagram or a stacked pair leaves the caption nowhere
# to go (hotd_build enforces this).
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

# block -> rail state (hotd_s3e4_episode.STATES)
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

SEC_PER_SHOT = 6.5
MIN_SHOTS, MAX_SHOTS = 3, 6


def block_of(seg_id):
    """Longest-prefix match, so any a/b/c split of a block still resolves to it."""
    best = None
    for b in POOLS:
        if seg_id == b or seg_id.startswith(b + "_"):
            if best is None or len(b) > len(best):
                best = b
    return best


def build(script_path="renders/hotd_s3e4/script.json"):
    segs = json.load(open(script_path))["segments"]
    unmapped = [s["id"] for s in segs if not block_of(s["id"])]
    if unmapped:
        raise SystemExit(f"no pool for segment(s): {unmapped}\nknown blocks: {sorted(POOLS)}")

    cursor = {b: 0 for b in POOLS}
    playlists, seg_state = {}, {}
    for s in segs:
        b = block_of(s["id"])
        pool = POOLS[b]
        n = max(MIN_SHOTS, min(MAX_SHOTS, round(s["target_s"] / SEC_PER_SHOT)))
        n = min(n, len(pool))
        # a segment may not OPEN on a diagram, a map or a stacked pair: advance the cursor until
        # the first slot is a plate or a single card
        tries = 0
        while pool[cursor[b] % len(pool)][0] in ("full", "map", "cards") and tries < len(pool):
            cursor[b] += 1
            tries += 1
        shots, seen_last = [], None
        while len(shots) < n:
            item = pool[cursor[b] % len(pool)]
            cursor[b] += 1
            if item == seen_last and len(pool) > 1:      # never repeat a shot back to back
                continue
            shots.append(item)
            seen_last = item
        playlists[s["id"]] = shots
        seg_state[s["id"]] = BLOCK_STATE[b]
    return playlists, seg_state


if __name__ == "__main__":
    pl, st = build()
    tot = sum(len(v) for v in pl.values())
    print(f"{len(pl)} segments -> {tot} shots")
    for k, v in pl.items():
        print(f"  {k:26s} {st[k]:9s} {len(v)} : {', '.join(i[0] for i in v)}")
