"""Generated S3E5 assets: only the heraldry and locations the earlier packs do not already have.

Everything the E3 and E4 packs provide is reused: Targaryen/Hightower/Velaryon/Whisper/Maester/
Strong/Kingsguard/Witch/Smallfolk heraldry, five of the six dragon emblems, and the King's Landing,
small-council, Harrenhal-courtyard, Rook's-Rest-camp and confined-quarters plates.

Prompts never ask for lettering: gpt-image-2 garbles text, so signage and slogans are asked for as
MARKS and any legible text is drawn in code afterwards.
"""
from __future__ import annotations

from hotd.generate import DRAGON_PREAMBLE as _D, EMBLEM_PREAMBLE as _E, PLATE_PREAMBLE as _P

SIGILS = {
    "tully":     _E + "a leaping trout, seen from the side, curved as though breaking water",
    "dustin":    _E + "two battle axes crossed behind a plain crown of iron",
    "piper":     _E + "a dancing maiden in a swirling gown, holding a spindle",
    "lannister": _E + "a lion rampant, standing on its hind legs with one paw raised",
    "frey":      _E + "two tall narrow bridge towers joined by a single stone span",
    "watch":     _E + "a city watchman's tall helm above two crossed pikes and a short cloak",
    "coin":      _E + "a single struck coin seen face-on, a crowned profile in relief on its face",
    "dragon_moondancer": _D + "pale green with mother-of-pearl highlights, small and slender",
}

LOCATIONS = {
    "70_loc_red_keep_sept":      _P + ("a small stone prayer chamber inside a great castle, a "
                                       "seven-sided altar, banks of guttering candles, kneeling "
                                       "cushions, high narrow windows"),
    "71_loc_joffrey_bedroom":    _P + ("a boy's bedchamber in a royal castle, a small canopied bed, "
                                       "wooden toys and a carved dragon on a chest, one candle, "
                                       "shutters half closed"),
    "72_loc_hidden_passage":     _P + ("a narrow stone service passage inside a castle wall, rough "
                                       "unfinished blocks, a single guttering torch, the passage "
                                       "ending abruptly in a blank sealed wall of newer stone"),
    "73_loc_flea_bottom":        _P + ("a filthy crowded slum alley in a medieval city, open "
                                       "gutters, leaning timber tenements, cook-fires and steam "
                                       "from a pot-shop, washing strung overhead"),
    "74_loc_watch_undercroft":   _P + ("a low vaulted undercroft beneath a castle used as a "
                                       "guardroom, benches and a long table, gold-trimmed cloaks "
                                       "hung on pegs, spilled cups, one lantern, a dark stain "
                                       "spreading across the flagstones"),
    "75_loc_tumbleton_command":  _P + ("a commandeered manor room turned into a war room, a great "
                                       "table covered in maps and tally sheets, stacked strongboxes, "
                                       "green banners on the wall, candles burned low"),
    "76_loc_harrenhal_sickroom": _P + ("a bleak chamber in a ruined castle used as a sickroom, a "
                                       "low cot with blankets, a basin and bloodied cloths, dried "
                                       "herbs hanging, cold light from a broken window"),
    "77_loc_riverlands_camp":    _P + ("a large medieval army camp in a river valley at dawn, rows "
                                       "of tents, picketed horses, cook-smoke, a muddy churned "
                                       "track, banners hanging limp in still air"),
    "78_loc_caltrop_ambush":     _P + ("a narrow forest track after an ambush, scattered iron "
                                       "caltrops glinting in the mud, broken spears, a toppled "
                                       "cart, dense trees crowding both sides, cold grey light"),
    "79_loc_ruined_crossing":    _P + ("a destroyed stone river crossing, the central span "
                                       "collapsed into fast brown water, burnt timbers, a small "
                                       "town on the far bank under a bruised sky"),
    "80_loc_wendish_town":       _P + ("a burning countryside seen from a low ridge at night, a "
                                       "small town alight in the distance, fields of standing crops "
                                       "on fire, an enormous winged shadow just visible against the "
                                       "smoke, no creature clearly shown"),
}
