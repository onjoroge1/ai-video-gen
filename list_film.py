"""List films: one umbrella question, answered by a countdown of short sourced stories.

The scout's biggest pools are formats rather than single topics: worst nuclear accidents,
forbidden places, invasive animals. A list film tells four to six entries under one title
question. Each entry is a mini-story built from a film we already researched: its witness moment,
the fix, the consequence, what is still happening. Every factual line cites that film's verified
claims and passes the same fidelity judge as the single-story pipeline.

Entries reuse the film's own pictures, matched by the claims a sentence shares with the scene that
showed them. New pictures are drawn only where a spec asks for a prompt. The playbook's middle and
ending rules apply across the whole film: one umbrella question held open (the countdown is the
loop), the human story in every entry, and an ending that answers the umbrella question.

Spec (JSON):
    {"slug": "...", "title": "<question title>", "question": "<the umbrella question>",
     "channel": "world", "voice": "echo", "engine": "removed_keystone", "style": "<new-picture style>",
     "intro": [beat, ...], "entries": [{"rank": 4, "label": "ASIAN CARP", "place": "United States",
     "job": "jobs/asian-carp-v2", "beats": [beat, ...]}, ...], "outro": [beat, ...]}
    beat = {"text": "...", "claims": ["c03"]} (cites the entry job's claims; picture by claim match)
         | {"text": "...", "rhetorical": true} (asserts no fact: a question, a joint, a transition)
         | either form plus "image": "<prompt>" (draw a new picture) or "scene": 12 (that scene's pictures)
Intro and outro beats cite claims from any entry with "job".
"""
from __future__ import annotations

import glob
import json
import os
import re

CARD_SEC = 2.2
BEAT_GAP_SEC = 0.15
ENTRY_GAP_SEC = 0.45
MAX_SHOT_SEC = 3.4          # the rendered gate rejects a hold over 3.5 s


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def validate_spec(spec: dict) -> list[str]:
    """Structural problems that stop a build before any paid call."""
    errors = []
    for key in ("slug", "title", "question", "entries"):
        if not spec.get(key):
            errors.append(f"spec needs {key!r}")
    entries = spec.get("entries") or []
    if not 3 <= len(entries) <= 7:
        errors.append(f"a list film has 3-7 entries, not {len(entries)}")
    ranks = [e.get("rank") for e in entries]
    if len(set(ranks)) != len(ranks):
        errors.append("entry ranks must be unique")
    if ranks != sorted(ranks, reverse=True):
        errors.append("entries count down: list them from the highest rank to #1")
    for e in entries:
        if not e.get("job") or not e.get("label"):
            errors.append(f"entry #{e.get('rank')} needs job and label")
        if len(e.get("beats") or []) < 3:
            errors.append(f"entry #{e.get('rank')} needs at least 3 beats (moment, fix, consequence)")
    for where, beat in iter_beats(spec):
        if not _text(beat.get("text")):
            errors.append(f"{where}: empty beat")
        elif not beat.get("claims") and not beat.get("rhetorical"):
            errors.append(f"{where}: a factual beat cites claims, or is marked rhetorical")
        if beat.get("claims") and not beat.get("job"):
            errors.append(f"{where}: intro/outro claims need the entry job they come from")
    return errors


def iter_beats(spec: dict):
    """(where, beat) for every beat in order; entry beats inherit their entry's job."""
    for i, beat in enumerate(spec.get("intro") or []):
        yield f"intro[{i}]", beat
    for e in spec.get("entries") or []:
        for i, beat in enumerate(e.get("beats") or []):
            yield f"#{e.get('rank')}[{i}]", dict(beat, job=beat.get("job") or e.get("job"))
    for i, beat in enumerate(spec.get("outro") or []):
        yield f"outro[{i}]", beat


def load_script(job: str) -> dict:
    data = json.load(open(os.path.join(job, "_state.json")))
    return data.get("script", data)


def claim_ceiling(script: dict, claim_ids: list[str]) -> str:
    """The factual ceiling for a sentence: each cited claim's text and its verified quote."""
    claims = {c.get("claim_id"): c for c in (script.get("_research_dossier") or {}).get("claims") or []}
    lines = []
    for cid in claim_ids:
        c = claims.get(cid)
        if not c:
            raise KeyError(f"claim {cid} is not in this job's dossier")
        lines.append(f"{_text(c.get('claim'))} (source: \"{_text(c.get('support_quote'))}\")")
    return "\n".join(lines)


def scene_pictures(job: str, scene_index: int) -> list[str]:
    """Every picture rendered for one scene, in state order (scene_03.jpg, scene_03_e02.jpg, ...)."""
    base = os.path.join(job, "images", f"scene_{scene_index:02d}")
    found = [p for p in glob.glob(base + "*.jpg") if re.search(r"scene_\d\d(_e\d\d)?\.jpg$", p)]
    return sorted(found, key=lambda p: (len(p), p))


def pick_pictures(job: str, script: dict, claim_ids: list[str], used: set, want: int = 2) -> list[str]:
    """Pictures from the scenes that cited these claims, unused first, most-overlapping scene first."""
    wanted = set(claim_ids)
    ranked = []
    for index, scene in enumerate(script.get("scenes") or []):
        cited = {c.get("claim_id") for c in scene.get("claim_refs") or []}
        overlap = len(cited & wanted)
        if overlap:
            ranked.append((-overlap, index))
    pictures = [p for _, index in sorted(ranked) for p in scene_pictures(job, index)]
    fresh = [p for p in pictures if p not in used]
    chosen = (fresh or pictures)[:want]
    used.update(chosen)
    return chosen


def any_pictures(job: str, script: dict, used: set, want: int = 1) -> list[str]:
    """Unused pictures from the entry's film in scene order, for a beat that cites no claim."""
    pictures = [p for index in range(len(script.get("scenes") or [])) for p in scene_pictures(job, index)]
    chosen = [p for p in pictures if p not in used][:want] or pictures[:want]
    used.update(chosen)
    return chosen


def split_shots(start: float, end: float, pictures: list[str], max_sec: float = MAX_SHOT_SEC) -> list[dict]:
    """Cover [start, end) with shots no longer than max_sec, cycling the beat's pictures."""
    if not pictures:
        raise ValueError("a beat needs at least one picture")
    span = max(0.01, end - start)
    n = max(len(pictures), int(-(-span // max_sec)))
    step = span / n
    return [{"start": round(start + k * step, 3), "end": round(start + (k + 1) * step, 3),
             "image": pictures[k % len(pictures)], "variant": k // len(pictures)} for k in range(n)]


def chapter_label(label: str) -> str:
    """Capitalise each word's first letter only: str.title() makes "Escobar's" into "Escobar'S"."""
    return " ".join(w[:1].upper() + w[1:] for w in _text(label).split())


def chapters(entry_starts: list[tuple[str, float]], intro_title: str = "The question") -> list[str]:
    """YouTube chapters: 0:00 first, one per entry, each at least 10 s apart."""
    out, last = [f"0:00 {intro_title}"], 0.0
    for title, t in entry_starts:
        if t - last >= 10:
            out.append(f"{int(t // 60)}:{int(t % 60):02d} {title}")
            last = t
    return out


def srt(cues: list[dict]) -> str:
    def stamp(t: float) -> str:
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "\n".join(f"{i}\n{stamp(c['start'])} --> {stamp(c['end'])}\n{c['text']}\n"
                     for i, c in enumerate(cues, 1))
