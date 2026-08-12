"""The Dragon Council — "Why Rhaenyra Cannot Burn Tumbleton". Engine is hotd/; data is
hotd_tumbleton_data.py. Same format as S3E7: portrait library, left rail, code-drawn diagrams."""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hotd.episode import Episode
import hotd_tumbleton_data as D
import hotd_tumbleton_assets as AT

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

CHARACTERS = AT.CHARACTERS          # people come from the supplied portrait library
DRAGONS = AT.DRAGONS
DIAGRAMS = AT.DIAGRAMS
SIGIL_PROMPTS: dict = {}            # no new heraldry
LOCATION_PROMPTS: dict = {}         # every plate already exists in an earlier pack
build_thumbnail = AT.build_thumbnail


def episode():
    return Episode(
        slug="dragon_council_tumbleton", out="renders/dragon_council_tumbleton",
        # five packs: E3/E4/E5/E7 supply every location plate, this pack supplies the diagrams
        packs=[D.PACK_E3, D.PACK_E4, D.PACK_E5, D.PACK_E7, D.PACK],
        states=STATES, playlists={}, seg_state={},
        chapter_titles=BLOCK_CHAPTER, meta=META,
        duration_band_min=D.DURATION_BAND_MIN,
        word_band=D.WORD_BAND,
        canon_labels=set(D.CANON_LABELS),
        rail_side="left",
        figures=D.FIGURES)
