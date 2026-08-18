"""House of the Dragon S3E5 — episode config. Engine is hotd/; data is hotd_s3e5_data.py."""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hotd.episode import Episode
import hotd_s3e5_data as D
import hotd_s3e5_assets as A5
import hotd_s3e5_gen as G5

PACK = D.PACK
PACK_PREV = D.PACK_PREV

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

CHARACTERS = A5.CHARACTERS
DRAGONS = A5.DRAGONS
DIAGRAMS = A5.DIAGRAMS
SIGIL_PROMPTS = G5.SIGILS
LOCATION_PROMPTS = G5.LOCATIONS


def episode():
    return Episode(
        slug="hotd_s3e5", out="renders/hotd_s3e5",
        # three packs: E3 and E4 art is reused, E5's own restated cards win on a name clash
        packs=[D.PACK_PREV2, D.PACK_PREV, D.PACK],
        states=STATES, playlists={}, seg_state={},
        chapter_titles=BLOCK_CHAPTER, meta=META,
        duration_band_min=D.DURATION_BAND_MIN,
        word_band=D.WORD_BAND,
        canon_labels=set(D.CANON_LABELS),
        rail_side="left",          # the court board sits on the left this episode
        figures=D.FIGURES)
