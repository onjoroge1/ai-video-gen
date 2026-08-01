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


def run():
    costs = []
    os.makedirs(SIG_DIR, exist_ok=True)
    os.makedirs(LOC_DIR, exist_ok=True)
    print(f"generating {len(SIGILS)} sigils + {len(LOCATIONS)} locations with {ep.IMAGE_MODEL}\n")
    for name, prompt in SIGILS.items():
        p = f"{SIG_DIR}/sig_{name}.png"
        if os.path.exists(p) and os.path.getsize(p) > 0:
            print(f"  sigil {name:11s} reuse"); continue
        try:
            ep.generate_image(prompt, p, cost_sink=costs, size="1024x1024")
            print(f"  sigil {name:11s} ok")
        except Exception as e:
            print(f"  sigil {name:11s} FAIL {type(e).__name__}: {e}")
    for stem, prompt in LOCATIONS.items():
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
