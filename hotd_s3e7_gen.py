"""Generated S3E7 assets: only the location plates no earlier pack already has.

The spec's asset manifest lists two libraries that do not exist on this machine
(`hotd-character-library-wave2`, `hotd-dragon-library`). Every master it names is real, but all 46 of
them -- characters AND dragons -- live in the single `hotd-character-library/masters`. So nothing in
the "approved masters" section needs generating, and neither do the Ulf White and Hugh Hammer cards:
the E3 and E4 packs already contain both, and the multi-pack asset index reuses them.

Reused rather than regenerated: Harrenhal sickroom and courtyard, Tumbleton command post, King's
Landing, the Red Keep, the small-council chamber, Rook's Rest camp, the Reach farmland.

Prompts never ask for lettering: gpt-image-2 garbles text, so any legible text is drawn in code.
No prompt describes a real actor, and none asks for gore -- the spec's own accuracy lock requires the
Corlys signet sequence to stay non-gory, so the severed finger is stated in a code-drawn diagram
rather than pictured.
"""
from __future__ import annotations

from hotd.generate import PLATE_PREAMBLE as _P

# The spec asks for Ser Adrian Redfort and a Nettles silhouette. Both are named once and neither is
# generated: a heraldic card sitting among photoreal portraits reads as an error, and the spec permits
# Nettles to be a silhouette "only". Both are carried in the code-drawn diagrams instead.
SIGILS = {}

LOCATIONS = {
    "82_loc_crownlands_forest":  _P + ("a dense night forest of old oaks in a temperate kingdom, "
                                       "black trunks, thin cold mist between them, a narrow deer "
                                       "track, moonlight broken into fragments on wet leaves"),
    "83_loc_blue_fork":          _P + ("a wide slow river forking around a low wooded island, seen "
                                       "from high above at dusk, pale water, reed banks, flat "
                                       "farmland beyond, no boats and no buildings"),
    "84_loc_dream_meadow":       _P + ("a dreamlike open meadow at first light, a single grey mare "
                                       "standing alone in long silver grass, pale desaturated "
                                       "colour, low ground mist, no rider and no harness"),
    "85_loc_captive_cell":       _P + ("a bare stone cell in a castle undercroft, one high barred "
                                       "slit window, a low cot, an untouched water jug, iron ring "
                                       "set into the wall, cold grey light"),
    "86_loc_dragonpit_gate":     _P + ("the huge closed bronze-banded gates of a domed stone arena "
                                       "on a city hill at dusk, torches in brackets, a broad empty "
                                       "approach of worn steps, smoke haze over the rooftops below"),
    "87_loc_farm_in_snow":       _P + ("a small peaceful farmstead in gentle countryside as the "
                                       "first snow begins, thatched cottage, low stone wall, bare "
                                       "orchard, grey heavy sky, soft snow already on the furrows"),
    "88_loc_royal_bedchamber":   _P + ("a queen's bedchamber in a great castle, carved four-poster "
                                       "bed, heavy drapes, a large pale dragon skull resting on a "
                                       "side table, shuttered window, candlelight"),
    "89_loc_tumbleton_outskirts": _P + ("a besieging army camp on rolling ground outside a walled "
                                        "market town at dusk, ordered rows of tents, cook-fires, "
                                        "pike stands, the town wall and roofs on the horizon"),
}
