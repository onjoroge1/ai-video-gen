"""The Episode config object: everything that differs between episodes, and nothing else.

An episode is DATA. The engine (hotd.render), the checks (hotd.gates), the generators
(hotd.generate, hotd.animate) and the packaging (hotd.deliver) are shared and episode-agnostic.

Asset packs are applied in declared order so LATER packs override earlier ones: an episode reuses
the previous pack's locations, maps and heraldry, and its own restated cards win. Getting that
backwards silently shipped stale status cards once, so overrides are recorded in `shadowed` and
hotd.gates.shadowing_direction asserts the direction.
"""
from __future__ import annotations
import glob
import os
from dataclasses import dataclass, field


@dataclass
class Episode:
    slug: str                             # output stem, e.g. "hotd_s3e4"
    out: str                              # render dir, e.g. "renders/hotd_s3e4"
    packs: list                           # asset image dirs, searched in order
    states: dict                          # rail state name -> board_pipeline state dict
    playlists: dict                       # segment id -> list of shot tuples
    seg_state: dict                        # segment id -> rail state name
    voice: str = "echo"
    seg_gap: float = 0.35                 # silence between segments
    script: str = ""                      # defaults to <out>/script.json
    allow_foreign_graphics: bool = False  # opt out of the episode-label leak guard
    chapter_titles: dict = field(default_factory=dict)   # block id -> chapter title
    meta: dict = field(default_factory=dict)             # upload metadata
    duration_band_min: tuple = (11.0, 14.0)              # spec runtime target
    word_band: tuple = (1600, 2200)
    canon_labels: set = None              # None -> gates.CANON_LABELS (the six)
    rail_side: str = "right"              # which side the court board sits on
    figures: dict = field(default_factory=dict)   # slug -> portrait + name/role/status
    chapter_groups: list = None           # [(title, [segment ids])]; overrides chapter_titles

    def __post_init__(self):
        if not self.script:
            self.script = f"{self.out}/script.json"

    @property
    def work(self):
        return f"{self.out}/work"

    _index: dict = field(default_factory=dict, repr=False)
    shadowed: list = field(default_factory=list, repr=False)

    def index(self):
        """Build the asset index. Packs are applied in declared order so LATER packs override
        earlier ones -- an episode reuses the previous pack's art but its own restated cards must
        win. Getting this backwards silently shipped E3's stale status cards into E4 (Rhaenyra,
        Daemon and Helaena all collide by stem), so shadowing is recorded and reported.
        """
        if not self._index:
            for pack in self.packs:
                for p in sorted(glob.glob(f"{pack}/**/*.png", recursive=True)):
                    b = os.path.basename(p)[:-4]
                    if b.startswith("_"):
                        continue
                    if b in self._index:
                        self.shadowed.append((b, self._index[b], p))
                    self._index[b] = p
        return self._index

    def asset(self, name):
        ix = self.index()
        if name not in ix:
            raise KeyError(f"asset not found in {len(self.packs)} pack(s): {name}")
        return ix[name]


def chip(name, role, tag, tone):
    """Rail chip. Keep role and tag short: the tag pill shares the role's row."""
    return {"name": name, "role": role, "tag": tag, "tone": tone}


def chip(name, role, tag, tone):
    """One rail chip. Keep role and tag short: the chip lays its tag pill on the role's row, so a
    long tag ellipsises the role away."""
    return {"name": name, "role": role, "tag": tag, "tone": tone}
