"""Generate the image half of the HotD S3E3 18-asset minimum set.

Split of labour:
  * Card TEMPLATE + text + faction + status  -> code-drawn (hotd_assets.py). Deterministic, free,
    identical across all cards, instantly re-renderable when a status line changes.
  * SIGILS and LOCATIONS                     -> generated. Hand-drawing heraldry in PIL hit a quality
    ceiling (the three-headed dragon read as a trident, the seahorse as an ambiguous "3"), so these
    are gpt-image-2 flat emblems / stylised plates instead.
  * INFOGRAPHICS                             -> code-drawn (diagrams need exact labels, not vibes).

IP posture: heraldic devices and locations are original stylised artwork, NOT character likenesses and
NOT episode footage — the same IP-safe stance as the S3E2 video. No prompt names an actor or asks for a
face. Spec §9: "Prefer original stylized visuals and diagrams over continuous episode footage."

Run: /opt/homebrew/bin/python3 hotd_gen_assets.py
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
for _l in open(".env", encoding="utf8"):
    _l = _l.strip()
    if _l and not _l.startswith("#") and "=" in _l:
        _k, _, _v = _l.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip())

import explainer_pipeline as ep

PACK = "house-of-dragons/house_of_the_dragon_s3e3_complete_asset_pack/images"
SIG_DIR, LOC_DIR = f"{PACK}/generated/sigils", f"{PACK}/generated/locations"

_EMBLEM = ("Flat vector heraldic emblem, perfectly symmetrical, centred, single antique-gold emblem on a "
           "pure black background, clean bold silhouette, medieval coat-of-arms style, high contrast, "
           "no text, no letters, no border, no frame, no shading gradients, no photorealism, no people, "
           "no faces. Subject: ")
SIGILS = {
    "targaryen": _EMBLEM + "a three-headed dragon, all three heads facing outward with open jaws, wings spread behind",
    "hightower": _EMBLEM + "a tall stepped stone watchtower with a single flame burning at its summit",
    "velaryon":  _EMBLEM + "a seahorse with a curled tail, seen in profile",
    "seven":     _EMBLEM + "a seven-pointed star, sharp even points",
    "whisper":   _EMBLEM + "a plain featureless mask flanked by three curved sound-wave lines on each side",
    "decoy":     _EMBLEM + "a plain featureless mask, cracked down the centre, with a single diagonal slash across it",
}

_PLATE = ("Cinematic matte-painting illustration, painterly, muted desaturated palette, dramatic low "
          "light, wide establishing shot, no text, no logos, no people in the foreground, no recognisable "
          "faces, original artwork not resembling any film or television production. Scene: ")
LOCATIONS = {
    "12_loc_kings_landing": _PLATE + ("a vast medieval coastal capital city of pale stone seen from a hill at "
                                      "dusk, dense rooftops, a great fortified castle on the highest hill, "
                                      "harbour and ships below, smoke from cooking fires"),
    "13_loc_iron_throne_room": _PLATE + ("the vast empty stone throne hall of a medieval castle, a single "
                                         "immense jagged throne of blackened welded blades on a raised dais, "
                                         "tall narrow windows throwing hard shafts of light, banners hanging"),
    "14_loc_empty_treasury": _PLATE + ("a stone vault beneath a castle, rows of heavy iron-bound chests thrown "
                                       "open and completely empty, a few scattered gold coins on the flagstones, "
                                       "abandoned ledgers on a table, one guttering torch"),
    "15_loc_rat_banquet_hall": _PLATE + ("a long medieval banquet hall set with fine silver plates and goblets, "
                                         "but the platters hold only small vermin carcasses, chairs pushed back, "
                                         "candles burning low, an air of humiliation"),
    "16_loc_tumbleton_occupied": _PLATE + ("a small medieval river town under military occupation at night, "
                                           "green army banners on the walls, tents and campfires ringing the town, "
                                           "frightened townsfolk silhouettes in doorways, distant fires"),
}


# 8 dragon emblems. Dragons are creatures, not likenesses, so these can be depicted directly. Canon
# colour is the distinguishing feature and is what makes the cards readable at a glance.
_DRAGON = ("Flat vector heraldic emblem of a single dragon in flight, side profile, wings spread, "
           "symmetrical composition, centred on a pure black background, bold clean silhouette with "
           "minimal internal detail, no text, no border, no people. Scale colour: ")
DRAGONS = {
    "syrax":        _DRAGON + "pale yellow gold",
    "caraxes":      _DRAGON + "deep blood red, long serpentine neck",
    "vermithor":     _DRAGON + "weathered bronze, very large and heavy-set",
    "silverwing":   _DRAGON + "pale silver-white",
    "seasmoke":     _DRAGON + "pale silvery grey",
    "sheepstealer": _DRAGON + "muddy brown, lean and rangy",
    "tessarion":    _DRAGON + "deep cobalt blue with copper edges",
    "vhagar":       _DRAGON + "vast ancient greenish bronze, battle-scarred, immense",
}

# The remaining locations from manifest §5-6.
LOCATIONS2 = {
    "51_loc_red_keep": _PLATE + "a massive red sandstone castle on a hill above a medieval city, seven great drum towers, seen at golden hour",
    "52_loc_oldtown_hightower": _PLATE + "a huge ancient lighthouse tower of pale stone rising above a walled harbour city at dusk, a beacon burning at its summit",
    "53_loc_the_reach_farmland": _PLATE + "rolling fertile farmland and orchards in high summer, dirt roads, distant walled town, warm hazy light",
    "54_loc_vale_of_arryn": _PLATE + "a high mountain valley with sheer grey peaks, a narrow switchback road, a small white castle perched impossibly high",
    "55_loc_harrenhal": _PLATE + "an immense ruined castle of five melted blackened towers on a lake shore under a bruised sky",
    "56_loc_riverlands": _PLATE + "a broad slow river valley with willows, water meadows and a stone bridge, grey overcast light",
    "57_loc_dragonstone": _PLATE + "a black volcanic island fortress carved with dragon motifs, rough sea, storm light",
    "58_loc_the_gullet": _PLATE + "a wide sea strait after a naval battle, broken ship timbers and sails drifting, smoke on the water at dawn",
    "59_loc_small_council_chamber": _PLATE + "a medieval council chamber with a great carved table, maps and ledgers spread across it, high windows, empty chairs",
    "60_loc_petition_hall": _PLATE + "a stone hall with common folk queuing to present grievances, plain clothes, shafts of window light, no faces visible",
    "61_loc_food_distribution": _PLATE + "a medieval city square where grain sacks and barrels are being distributed from carts to a crowd, torchlight, dusk",
}


def run():
    costs = []
    os.makedirs(SIG_DIR, exist_ok=True)
    os.makedirs(LOC_DIR, exist_ok=True)
    print(f"generating {len(SIGILS)+len(DRAGONS)} emblems + {len(LOCATIONS)+len(LOCATIONS2)} locations with {ep.IMAGE_MODEL}\n")
    _all_sig = dict(SIGILS)
    _all_sig.update({f"dragon_{k}": v for k, v in DRAGONS.items()})
    for name, prompt in _all_sig.items():
        p = f"{SIG_DIR}/sig_{name}.png"
        if os.path.exists(p) and os.path.getsize(p) > 0:
            print(f"  sigil {name:11s} reuse"); continue
        try:
            ep.generate_image(prompt, p, cost_sink=costs, size="1024x1024")
            print(f"  sigil {name:11s} ok")
        except Exception as e:
            print(f"  sigil {name:11s} FAIL {type(e).__name__}: {e}")
    _all_loc = dict(LOCATIONS); _all_loc.update(LOCATIONS2)
    for stem, prompt in _all_loc.items():
        p = f"{LOC_DIR}/{stem}.png"
        if os.path.exists(p) and os.path.getsize(p) > 0:
            print(f"  {stem:26s} reuse"); continue
        try:
            ep.generate_image(prompt, p, cost_sink=costs, size="1536x1024")
            print(f"  {stem:26s} ok")
        except Exception as e:
            print(f"  {stem:26s} FAIL {type(e).__name__}: {e}")
    print(f"\nimage spend: ${sum(costs):.3f}")
    return costs


if __name__ == "__main__":
    run()
