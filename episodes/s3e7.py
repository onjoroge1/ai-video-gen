"""House of the Dragon S3E7 — episode config. Engine is hotd/; data is hotd_s3e7_data.py."""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hotd.episode import Episode
import hotd_s3e7_data as D
import hotd_s3e7_assets as A7
import hotd_s3e7_gen as G7

PACK = D.PACK

STATES = D.STATES
POOLS = D.POOLS
BLOCK_STATE = D.BLOCK_STATE
BLOCK_CHAPTER = D.BLOCK_CHAPTER
BLOCK_ALIASES = D.BLOCK_ALIASES
FIGURES = D.FIGURES
SUBJECT_WORDS = D.SUBJECT_WORDS
ROLE_WORDS = D.ROLE_WORDS
PORTRAITS = D.PORTRAITS
PERSON_OF = D.PERSON_OF
META = dict(D.META)

CHARACTERS = A7.CHARACTERS          # empty: people come from the portrait library
DRAGONS = A7.DRAGONS
DIAGRAMS = A7.DIAGRAMS
SIGIL_PROMPTS = G7.SIGILS           # empty: no new heraldry this episode
LOCATION_PROMPTS = G7.LOCATIONS
build_thumbnail = A7.build_thumbnail


def episode():
    return Episode(
        slug="hotd_s3e7", out="renders/hotd_s3e7",
        # four packs: E3 supplies the Ulf and Hugh cards, E4/E5 the reused plates, E7's own art wins
        packs=[D.PACK_PREV3, D.PACK_PREV2, D.PACK_PREV, D.PACK],
        states=STATES, playlists={}, seg_state={},
        chapter_titles=BLOCK_CHAPTER, meta=META,
        duration_band_min=D.DURATION_BAND_MIN,
        word_band=D.WORD_BAND,
        canon_labels=set(D.CANON_LABELS),
        rail_side="left",
        figures=D.FIGURES)
