"""Generate the S3E4 image assets the S3E3 pack does not already contain (spec §12.2, §12.3).

Reuse policy: everything in the S3E3 pack stays. This adds only the genuine gaps --
  * 7 heraldic emblems for characters new to this episode (Orwyle, Jeyne Arryn, Larys, Criston,
    Alys, the Footlys, and a generic mark for the townsfolk and the shepherd)
  * 2 dragon emblems (Sunfyre, Meleys) -- the other six already exist
  * 12 location plates -- Tumbleton's interiors, Rook's Rest, the Vale and the graffiti street

Text in prompts: gpt-image-2 garbles lettering, so the graffiti street asks for crude scrawled
MARKS, never readable words. Any legible text is drawn in code on top.

IP posture unchanged: original stylised artwork, no likenesses, no episode footage.

Run: /opt/homebrew/bin/python3 hotd_s3e4_gen.py
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

PACK = "house-of-dragons/house_of_the_dragon_s3e4_complete_asset_pack/images"
SIG_DIR, LOC_DIR = f"{PACK}/generated/sigils", f"{PACK}/generated/locations"

_EMBLEM = ("Flat vector heraldic emblem, perfectly symmetrical, centred, single antique-gold emblem on a "
           "pure black background, clean bold silhouette, medieval coat-of-arms style, high contrast, "
           "no text, no letters, no border, no frame, no shading gradients, no photorealism, no people, "
           "no faces. Subject: ")
SIGILS = {
    "arryn":     _EMBLEM + "a falcon in flight with wings spread, soaring in front of a full moon disc",
    "maester":   _EMBLEM + "a heavy chain collar of many differently shaped links, laid out as a closed circle",
    "strong":    _EMBLEM + "a single broad medieval battle axe, blade upward, crossed by a narrow tower",
    "kingsguard": _EMBLEM + "a tall knight's kite shield in front of a vertical longsword, wings on the helm above",
    "witch":     _EMBLEM + "a bare gnarled tree with a hollow oval face carved into its trunk, roots spreading",
    "footly":    _EMBLEM + "a stag's head facing forward with tall antlers, above three small wheat sheaves",
    "smallfolk": _EMBLEM + "a simple clay water jug flanked by two crossed reaping sickles",
}

_DRAGON = ("Flat vector heraldic emblem of a single dragon in flight, side profile, wings spread, "
           "symmetrical composition, centred on a pure black background, bold clean silhouette with "
           "minimal internal detail, no text, no border, no people. Scale colour: ")
DRAGONS = {
    "sunfyre": _DRAGON + "brilliant gold with pale pink membranes, one wing held crooked and damaged",
    "meleys":  _DRAGON + "deep scarlet red with copper highlights, wings torn and body broken",
}

_PLATE = ("Cinematic matte-painting illustration, painterly, muted desaturated palette, dramatic low "
          "light, wide establishing shot, no text, no lettering, no logos, no recognisable faces, "
          "original artwork not resembling any film or television production. Scene: ")
LOCATIONS = {
    "70_loc_tumbleton_street": _PLATE + (
        "a narrow medieval town street under military occupation in daylight, soldiers' spears and "
        "tents crowding the lane, shuttered windows, townsfolk keeping to the walls, distant banners"),
    "71_loc_footly_residence": _PLATE + (
        "the modest great hall of a small medieval manor house, long table, worn tapestries, a large "
        "hearth, soldiers' gear stacked against the wall as though the house has been taken over"),
    "72_loc_tumbleton_family_home": _PLATE + (
        "the cramped interior of a poor medieval townhouse at night, one low fire, straw bedding on "
        "the floor, soldiers' packs and weapons leaning by the door, a family's belongings pushed aside"),
    "73_loc_tumbleton_sept": _PLATE + (
        "the stone interior of a small medieval town sept turned into a shelter, townsfolk's bundles "
        "and blankets on the flagstones, a seven-sided altar in shadow, thin light from high windows"),
    "74_loc_alicent_helaena_quarters": _PLATE + (
        "a comfortable but confined castle bedchamber, two chairs by a shuttered window, an unmade "
        "bed, a barred door visible at the edge of frame, warm candlelight, an air of quiet captivity"),
    "75_loc_graffiti_street": _PLATE + (
        "a narrow medieval city alley at dusk, pale plaster walls covered in crude scrawled charcoal "
        "MARKS and rough scratched symbols and shapes, absolutely no readable letters or words, "
        "a bucket of pitch abandoned below, one guard's shadow falling across the wall"),
    "76_loc_rooks_rest_battlefield": _PLATE + (
        "a burnt coastal battlefield weeks after a dragon fight, blackened earth, the vast bleached "
        "ribcage and wing bones of an enormous dead beast half sunk in ash, carrion birds, grey sky"),
    "77_loc_rooks_rest_camp": _PLATE + (
        "a squalid medieval labourers' work camp beside a ruined castle, mud, open trench latrines, "
        "sagging canvas tents, carts of rubble, men at distant menial work, cold overcast light"),
    "78_loc_harrenhal_courtyard": _PLATE + (
        "the vast inner courtyard of an immense ruined castle, five melted blackened towers rising "
        "around it, cracked flagstones, a few horses and soldiers dwarfed by the scale, bruised sky"),
    "79_loc_eyrie_hall": _PLATE + (
        "a high pale stone audience chamber in a mountain castle, slender columns, a narrow throne on "
        "a dais, tall open arches showing snow peaks and cloud far below, cold bright daylight"),
    "80_loc_vale_cave": _PLATE + (
        "the mouth of a large rocky cave high on a mountainside at dawn, scorched stone and huge claw "
        "gouges at the entrance, scattered bones, mist in the valley far below, no creature visible"),
    "81_loc_vale_shepherding": _PLATE + (
        "a high remote mountain pasture with scattered sheep and a low stone sheepfold, steep grey "
        "slopes above, a lone shepherd's hut, thin cold morning light, no people visible"),
}


def run():
    costs = []
    os.makedirs(SIG_DIR, exist_ok=True)
    os.makedirs(LOC_DIR, exist_ok=True)
    allsig = dict(SIGILS)
    allsig.update({f"dragon_{k}": v for k, v in DRAGONS.items()})
    print(f"generating {len(allsig)} emblems + {len(LOCATIONS)} locations with {ep.IMAGE_MODEL}\n")
    for name, prompt in allsig.items():
        p = f"{SIG_DIR}/sig_{name}.png"
        if os.path.exists(p) and os.path.getsize(p) > 0:
            print(f"  sigil {name:12s} reuse", flush=True); continue
        try:
            ep.generate_image(prompt, p, cost_sink=costs, size="1024x1024")
            print(f"  sigil {name:12s} ok", flush=True)
        except Exception as e:
            print(f"  sigil {name:12s} FAIL {type(e).__name__}: {e}", flush=True)
    for stem, prompt in LOCATIONS.items():
        p = f"{LOC_DIR}/{stem}.png"
        if os.path.exists(p) and os.path.getsize(p) > 0:
            print(f"  {stem:34s} reuse", flush=True); continue
        try:
            ep.generate_image(prompt, p, cost_sink=costs, size="1536x1024")
            print(f"  {stem:34s} ok", flush=True)
        except Exception as e:
            print(f"  {stem:34s} FAIL {type(e).__name__}: {e}", flush=True)
    print(f"\nimage spend: ${sum(costs):.3f}")
    return costs


if __name__ == "__main__":
    run()
