"""House of the Dragon S3E4 — episode data. No engine code lives here.

Spec: house-of-dragons/house_of_the_dragon_s3e4_verified_video_spec.md

Packs are declared E3 first, E4 second, so this episode reuses the earlier locations, maps and
heraldry while its own restated status cards win on a name clash (hotd.gates.shadowing_direction
asserts that direction; getting it backwards once shipped stale cards).
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hotd.episode import Episode, chip

# episode-specific asset data + diagram drawing functions
import hotd_s3e4_assets as A4
import hotd_s3e4_gen as G4
import hotd_s3e4_thumbnail as T4
import hotd_s3e4_data as D                   # STATES / POOLS / BLOCK_STATE / chapters / META

PACK = "house-of-dragons/house_of_the_dragon_s3e4_complete_asset_pack/images"
PACK_PREV = "house-of-dragons/house_of_the_dragon_s3e3_complete_asset_pack/images"

STATES = D.STATES
POOLS = D.POOLS
BLOCK_STATE = D.BLOCK_STATE
BLOCK_CHAPTER = D.BLOCK_CHAPTER
META = dict(D.META)

CHARACTERS = A4.CHARACTERS
DRAGONS = A4.DRAGONS
DIAGRAMS = A4.DIAGRAMS
SIGIL_PROMPTS = dict(G4.SIGILS, **{f"dragon_{k}": v for k, v in G4.DRAGONS.items()})
LOCATION_PROMPTS = G4.LOCATIONS


def build_thumbnail():
    T4.gen()
    return T4.build()


def episode():
    return Episode(
        slug="hotd_s3e4", out="renders/hotd_s3e4",
        packs=[PACK_PREV, PACK],
        states=STATES, playlists={}, seg_state={},
        chapter_titles=BLOCK_CHAPTER, meta=META,
        duration_band_min=(12.0, 14.0),      # spec §5
        word_band=(1750, 2100))              # spec §5
