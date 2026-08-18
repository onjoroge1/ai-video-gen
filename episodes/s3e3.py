"""House of the Dragon S3E3 — episode data, kept as the regression fixture.

The engine must keep reproducing this episode's shot ledger exactly; `python -m hotd plan
episodes/s3e3.py` is the equivalence test that proved the engine generalisation was safe.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hotd.episode import Episode
import hotd_s3e3_data as D

PACK = "house-of-dragons/house_of_the_dragon_s3e3_complete_asset_pack/images"

STATES = D.STATES
POOLS = D.POOLS
BLOCK_STATE = D.BLOCK_STATE
# hand-authored per-segment shots, from before the block-pool scheme: used verbatim so
# the shipped 119-shot ledger stays reproducible
PLAYLISTS_EXACT = D.PLAYLISTS_EXACT
SEG_STATE_EXACT = D.SEG_STATE_EXACT
BLOCK_CHAPTER = D.BLOCK_CHAPTER
META = D.META


def episode():
    return Episode(
        slug="hotd_s3e3", out="renders/hotd_s3e3",
        packs=[PACK], states=STATES, playlists={}, seg_state={},
        chapter_titles=BLOCK_CHAPTER, chapter_groups=D.CHAPTER_GROUPS, meta=META,
        duration_band_min=(11.0, 13.0), word_band=(1650, 1950),
        # S3E3's spec did not mandate a closed label set; the shipped video uses compound labels
        # deliberately, because one label per card could not describe a card mixing fact with
        # reading. S3E4's spec closed the set, which is why that episode uses only the six.
        canon_labels={
            "SHOW CONFIRMED", "BOOK CONFIRMED", "SHOW CHANGE", "STRONG INFERENCE",
            "INTERPRETATION", "UNVERIFIED",
            "SHOW CONFIRMED · WITH INTERPRETATION",
            "SHOW CONFIRMED · WITH STRONG INFERENCE",
            "INTERPRETATION · ON SHOW-CONFIRMED FACTS"})
