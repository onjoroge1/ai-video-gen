"""Turn an episode spec markdown into a starting episode module.

Everything here is DETERMINISTIC extraction -- no model call, so nothing is invented. A spec states
its own title, its alternative titles, its thumbnail text, its production parameters, its permitted
canon labels, its storyboard blocks with timings, and its required asset lists. All of that can be
read straight out of the document, and reading it by hand is where two of this session's defects came
from: the storyboard block count was mis-stated as 14 when the spec has 15, and the permitted label
set was not noticed to be closed.

What it cannot do is author prose (the description body, the argument line) or decide art direction
(which plate belongs under which beat). Those come out as explicit TODOs rather than as guesses.

    python -m hotd scaffold house-of-dragons/..._s3e5_..._spec.md --slug s3e5
"""
from __future__ import annotations
import os
import re


def _section(md, heading_re, stop_re=r"^#{1,2} "):
    """Body of the first heading matching heading_re, up to the next same-or-higher heading."""
    lines = md.split("\n")
    out, on = [], False
    for ln in lines:
        if on and re.match(stop_re, ln):
            break
        if on:
            out.append(ln)
        elif re.match(heading_re, ln):
            on = True
    return "\n".join(out).strip()


def _bold_lines(block):
    return [m.group(1).strip() for m in re.finditer(r"^\*\*(.+?)\*\*\s*$", block, re.M)]


def _bullets(block):
    return [re.sub(r"\*\*", "", m.group(1)).strip()
            for m in re.finditer(r"^\s*[-*]\s+(.+?)\s*$", block, re.M)]


def parse(md_path):
    md = open(md_path, encoding="utf8").read()
    out = {"spec_path": md_path}

    # --- packaging
    pack = _section(md, r"^# .*[Rr]ecommended packaging", r"^# ")
    titles = _bold_lines(pack)
    out["title"] = titles[0] if titles else ""
    out["alternatives"] = titles[1:5]
    thumb = _section(md, r"^## .*thumbnail text", r"^## ")
    # specs write this either as a blockquote or as a plain bold line
    tt = (re.findall(r"^>\s*\*\*(.+?)\*\*", thumb, re.M)
          or _bold_lines(thumb)
          or re.findall(r"^>\s*(.+)$", thumb, re.M))
    out["thumbnail_text"] = [t.strip() for t in tt]

    # --- production parameters
    prod = _section(md, r"^# .*[Pp]roduction parameters")
    def num2(label):
        m = re.search(label + r"[^0-9]*([0-9,]+)\s*[-–]\s*([0-9,]+)", prod)
        return (int(m.group(1).replace(",", "")),
                int(m.group(2).replace(",", ""))) if m else None
    out["duration_band_min"] = num2(r"[Tt]arget duration")
    out["word_band"] = num2(r"[Tt]arget narration")
    out["wpm_band"] = num2(r"[Nn]arration speed")
    m = re.search(r"recap ceiling[^0-9]*([0-9]+)\s*%", prod)
    out["recap_ceiling_pct"] = int(m.group(1)) if m else None

    # --- canon labels: a spec that enumerates them is mandating a CLOSED set
    # specs word this heading differently ("Required on-screen canon labels" in one,
    # "Required on-screen labels" in the next), so match on the stable part
    lab = _section(md, r"^#{2,3} .*[Rr]equired on-screen.*labels", r"^#{1,3} ")
    out["canon_labels"] = [b for b in _bullets(lab) if b.isupper() or b.replace(" ", "").isalpha()]

    # --- storyboard blocks, with their clock
    story = _section(md, r"^# .*[Ss]cript and storyboard", r"^# ")
    blocks = []
    for m in re.finditer(r"^## +([0-9]{1,2}:[0-9]{2})\s*[-–]\s*([0-9]{1,2}:[0-9]{2})\s*"
                         r"[-—–]+\s*(.+?)\s*$", story, re.M):
        start, end, name = m.group(1), m.group(2), m.group(3)
        def secs(t):
            a, b = t.split(":"); return int(a) * 60 + int(b)
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower().strip("“”\"' ")).strip("_")
        blocks.append({"id": slug, "title": name.strip("“”\"'"),
                       "start_s": secs(start), "seconds": secs(end) - secs(start)})
    out["blocks"] = blocks

    # --- required assets
    assets = _section(md, r"^# .*[Rr]equired visual asset package", r"^# ")
    out["characters"] = _bullets(_section(assets, r"^## .*[Cc]haracter cards", r"^## "))
    out["dragons"] = _bullets(_section(assets, r"^## .*[Dd]ragon cards", r"^## "))
    out["locations"] = _bullets(_section(assets, r"^## .*[Ll]ocation cards", r"^## "))
    out["diagrams"] = [re.sub(r"^\d+\.\s*", "", b) for b in
                       re.findall(r"^\s*\d+\.\s+\*\*(.+?)\*\*",
                                  _section(assets, r"^## .*[Dd]iagrams", r"^## "), re.M)]
    return out


def report(info):
    L = []
    L.append(f"spec              : {info['spec_path']}")
    L.append(f"title             : {info['title']}")
    L.append(f"alternatives      : {len(info['alternatives'])}")
    L.append(f"thumbnail text    : {info['thumbnail_text']}")
    L.append(f"duration (min)    : {info['duration_band_min']}")
    L.append(f"words             : {info['word_band']}")
    L.append(f"wpm (spec)        : {info['wpm_band']}  <- our voice measures 162")
    L.append(f"recap ceiling     : {info['recap_ceiling_pct']}%")
    L.append(f"canon labels      : {len(info['canon_labels'])} "
             f"{'(CLOSED SET - compound labels are a violation)' if info['canon_labels'] else ''}")
    for x in info["canon_labels"]:
        L.append(f"                    {x}")
    L.append(f"storyboard blocks : {len(info['blocks'])}")
    for b in info["blocks"]:
        L.append(f"                    {b['id']:34s} {b['seconds']:4d}s  {b['title']}")
    L.append(f"characters needed : {len(info['characters'])}")
    L.append(f"dragons needed    : {len(info['dragons'])}")
    L.append(f"locations needed  : {len(info['locations'])}")
    L.append(f"diagrams needed   : {len(info['diagrams'])}")
    for d in info["diagrams"]:
        L.append(f"                    {d}")
    return "\n".join(L)


DATA_TEMPLATE = '''"""House of the Dragon {SLUG_UPPER} — episode DATA only. Scaffolded from the spec.

Spec: {SPEC}

Scaffolded deterministically: titles, production bands, the permitted canon-label set, the
storyboard blocks and the required-asset lists are read from the spec. Everything marked TODO needs
a human: rail states, art direction (which plate under which beat), and the description prose.
"""
from __future__ import annotations

from hotd.episode import chip

PACK = "house-of-dragons/{SLUG}_asset_pack/images"
PACK_PREV = "{PACK_PREV}"
SUB = "House of the Dragon · {SLUG_UPPER}"

# --- spec-derived production parameters -------------------------------------------------------
DURATION_BAND_MIN = {DURATION}
WORD_BAND = {WORDS}
RECAP_CEILING_PCT = {RECAP}
CANON_LABELS = {LABELS}

# --- rail states: TODO author from the spec's board/state sections ----------------------------
# One state per act. Keep chip roles and tags under ~13 characters: the chip lays its tag pill on
# the role's row, so a long tag ellipsises the role away.
STATES = {{
    "open": {{
        "title": "STATE OF THE WAR", "subtitle": SUB,
        "left": {{"name": "THE BLACKS", "accent": "steel", "chips": [
            chip("TODO", "TODO", "TODO", "neutral")] * 4}},
        "right": {{"name": "THE GREENS", "accent": "green", "chips": [
            chip("TODO", "TODO", "TODO", "neutral")] * 4}},
        "control": {{"label": "TODO", "held_by": "contested", "text": "TODO"}},
        "dragons": {{"left": 5, "right": 2, "right_dim": 1}},
        "footer": "CH 1 · TODO",
        "changed": []}},
}}

# --- storyboard blocks, from the spec ---------------------------------------------------------
BLOCK_CHAPTER = {{
{CHAPTERS}}}

# --- shot pools: TODO art direction. First entry of each pool MUST be a plate or a single card.
POOLS = {{
{POOLS}}}

# --- every block needs a rail state -----------------------------------------------------------
BLOCK_STATE = {{
{BLOCK_STATE}}}

META = {{
    "module": "episodes/{SLUG}.py",
    "title": {TITLE!r},
    "alternatives": {ALTS!r},
    "intro": "TODO one or two sentences: the hook, in plain prose.",
    "body": "TODO what the episode covers.",
    "argument": "TODO the thesis in one or two sentences.",
    "spoilers": "TODO the spoiler notice.",
    "hashtags": "#HouseOfTheDragon #HOTD",
    "tags": ["house of the dragon", "hotd explained"],  # TODO expand to ~20
    "thumbnail": PACK + "/thumbnail/TODO.png",
    "image_spend_usd": 0.0,
    "accuracy_note": "",
}}
'''

EPISODE_TEMPLATE = '''"""House of the Dragon {SLUG_UPPER} — episode config. Engine is hotd/; data is hotd_{SLUG}_data.py."""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hotd.episode import Episode
import hotd_{SLUG}_data as D

PACK = D.PACK
PACK_PREV = D.PACK_PREV

STATES = D.STATES
POOLS = D.POOLS
BLOCK_STATE = D.BLOCK_STATE
BLOCK_CHAPTER = D.BLOCK_CHAPTER
META = dict(D.META)

# TODO: SIGIL_PROMPTS / LOCATION_PROMPTS / CHARACTERS / DRAGONS / DIAGRAMS / build_thumbnail


def episode():
    return Episode(
        slug="hotd_{SLUG}", out="renders/hotd_{SLUG}",
        packs=[PACK_PREV, PACK],
        states=STATES, playlists={{}}, seg_state={{}},
        chapter_titles=BLOCK_CHAPTER, meta=META,
        duration_band_min=D.DURATION_BAND_MIN,
        word_band=D.WORD_BAND,
        canon_labels=set(D.CANON_LABELS) or None)
'''


def write(info, slug, pack_prev, force=False):
    blocks = info["blocks"]
    chapters = "".join(f'    {b["id"]!r}: {b["title"]!r},\n' for b in blocks)
    pools = "".join(
        f'    {b["id"]!r}: [\n'
        f'        ("plate", "TODO_loc"),          # {b["seconds"]}s block\n'
        f'        ("card", "TODO_char", "TODO_loc"),\n'
        f'        ("full", "TODO_graphic"),\n'
        f'    ],\n' for b in blocks)
    bstate = "".join(f'    {b["id"]!r}: "open",\n' for b in blocks)
    subs = {
        "SLUG": slug, "SLUG_UPPER": slug.upper(), "SPEC": info["spec_path"],
        "PACK_PREV": pack_prev,
        "DURATION": tuple(float(x) for x in (info["duration_band_min"] or (11, 14))),
        "WORDS": tuple(info["word_band"] or (1750, 2100)),
        "RECAP": info["recap_ceiling_pct"] or 30,
        "LABELS": info["canon_labels"] or [],
        "CHAPTERS": chapters, "POOLS": pools, "BLOCK_STATE": bstate,
        "TITLE": info["title"], "ALTS": info["alternatives"],
    }
    data_path = f"hotd_{slug}_data.py"
    ep_path = os.path.join("episodes", f"{slug}.py")
    for p in (data_path, ep_path):
        if os.path.exists(p) and not force:
            raise SystemExit(f"{p} already exists (use --force to overwrite)")
    open(data_path, "w").write(DATA_TEMPLATE.format(**subs))
    open(ep_path, "w").write(EPISODE_TEMPLATE.format(**subs))
    return data_path, ep_path
