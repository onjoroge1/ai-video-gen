"""Turn an operator's specification document into a script the pipeline can render.

When the operator writes the narration themselves, two of the most expensive stages disappear:
the beat sheet and the research dossier. The words are written and the operator owns the facts,
so there is nothing for a research pass to verify that they have not already asserted.

What a supplied narration CANNOT skip is per-scene image prompts -- nothing renders without
them -- so this composes each one from the spec's own world templates plus the beat anchor for
that timestamp, rather than asking a model to invent them. That keeps the whole path free of
the script provider.

MARKDOWN IN, JSON OUT. The operator writes prose in a document they can think in; this parses
it once, validates it, and persists a JSON contract the pipeline consumes. Parsing markdown at
render time would be brittle in the worst place -- a heading renamed months later would surface
as a malformed script three stages downstream. Failing loudly here, with the section that broke,
is the whole point of the intermediate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# Narration sections look like:  ### 0:00–0:45 — The impossible grocery aisle
# En dash and hyphen both appear in real documents; accept either everywhere.
_DASH = r"[–—-]"
_SECTION = re.compile(
    rf"^###\s+(\d+):(\d{{2}})\s*{_DASH}\s*(\d+):(\d{{2}})\s*{_DASH}\s*(.+?)\s*$", re.M)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

# Which visual world a timestamp belongs to. Taken from the spec's own three-world table rather
# than inferred from the prose, so a scene cannot silently land in the wrong palette.
WORLDS = ("alternate_2026", "historical_1910", "modern_evidence")


@dataclass
class SpecScene:
    index: int
    narration: str
    start_sec: float
    world: str
    beat: str
    image_prompt: str
    story_role: str = "beat"

    def as_scene(self) -> dict:
        return {
            "n": self.index + 1,
            "narration": self.narration,
            "role": self.story_role,
            "story_role": self.story_role,
            "scene_type": self.world,
            "environment_type": self.world,
            "image_prompt": self.image_prompt,
            "human_present": self.world == "historical_1910",
            "mascot_present": False,
            "bolt_mode": "absent",
            "shot_type": "medium",
            "visual_beats": [],
            "claim_refs": [],
            "evidence_id": "",
            "_spec_beat": self.beat,
            "_spec_start_sec": self.start_sec,
        }


@dataclass
class ParsedSpec:
    title: str
    scenes: list = field(default_factory=list)
    words: int = 0
    warnings: list = field(default_factory=list)

    def as_script(self) -> dict:
        return {
            "title": self.title,
            "hook": self.scenes[0].narration if self.scenes else "",
            "style_mode": "cinematic",
            "scenes": [scene.as_scene() for scene in self.scenes],
            "_operator_supplied": True,
        }


def _seconds(minutes: str, secs: str) -> float:
    return int(minutes) * 60 + int(secs)


def _world_for(start_sec: float, worlds: list) -> str:
    """Which world owns this timestamp, from the spec's declared ranges."""
    for begin, end, world in worlds:
        if begin <= start_sec < end:
            return world
    return WORLDS[0]


def extract_title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("## ") and "specification" not in line.lower():
            return line[3:].strip()
    return "Untitled"


def extract_base_prompts(text: str) -> dict:
    """The spec's four world templates, quoted as markdown blockquotes under ### headings."""
    prompts: dict = {}
    # The heading is ONE line. With (.+?) under DOTALL it spanned sections until it found any
    # blockquote, so "### Primary title" swallowed the page and the pinned comment ended up as
    # the historical image prompt. [^\n]+ keeps a heading a heading.
    blocks = re.findall(r"^###[ \t]+([^\n]+)\n+>[ \t]*(.+?)(?=\n\n|\n###|\Z)",
                        text, re.M | re.S)
    for heading, body in blocks:
        key = heading.lower()
        body = " ".join(part.strip().lstrip("> ") for part in body.splitlines() if part.strip())
        if "reenactment" in key or "historical" in key:
            prompts["historical_1910"] = body
        elif "2026" in key or "alternate" in key:
            prompts["alternate_2026"] = body
        elif "counterfactual" in key:
            prompts["counterfactual"] = body
        elif "colombia" in key or "modern" in key:
            prompts["modern_evidence"] = body
        elif "negative" in key:
            prompts["negative"] = body
    return prompts


def extract_beat_anchors(text: str) -> list:
    """(start_sec, beat_name, visual_anchor) from the beat-map table."""
    anchors = []
    row = re.compile(
        rf"^\|\s*(\d+):(\d{{2}})\s*{_DASH}\s*\d+:\d{{2}}\s*\|\s*([^|]+?)\s*\|"
        rf"\s*([^|]*?)\s*\|\s*([^|]+?)\s*\|\s*$", re.M)
    for m, s, beat, _info, anchor in row.findall(text):
        anchors.append((_seconds(m, s), beat.strip(), anchor.strip()))
    return sorted(anchors)


def _anchor_for(start_sec: float, anchors: list) -> tuple:
    best = ("", "")
    for begin, beat, anchor in anchors:
        if begin <= start_sec:
            best = (beat, anchor)
    return best


def split_into_scenes(narration: str, words_per_scene: int = 28) -> list:
    """Group sentences into scene-sized runs, never splitting a sentence.

    A scene boundary mid-sentence would break the anchor phrases every downstream gate matches
    against measured speech -- five separate causes of that were fixed in this codebase already.
    """
    sentences = [s.strip() for s in _SENTENCE.split(narration.strip()) if s.strip()]
    scenes, current, count = [], [], 0
    for sentence in sentences:
        length = len(sentence.split())
        if current and count + length > words_per_scene * 1.35:
            scenes.append(" ".join(current))
            current, count = [sentence], length
        else:
            current.append(sentence)
            count += length
    if current:
        scenes.append(" ".join(current))
    return scenes


def parse_spec(path: str | Path, *, words_per_scene: int = 28) -> ParsedSpec:
    text = Path(path).read_text(encoding="utf-8")
    title = extract_title(text)
    prompts = extract_base_prompts(text)
    anchors = extract_beat_anchors(text)

    sections = list(_SECTION.finditer(text))
    if not sections:
        raise ValueError(
            "No narration sections found. Expected headings like "
            "'### 0:00-0:45 - Section name' under the narration chapter.")

    # World ranges derived from the beat map: the historical reveal onward is 1910 until the
    # modern-evidence beat, then modern. Declared here rather than guessed per scene.
    # From the spec's own beat map. The closing callback returns to the 2026 grocery case, so
    # the last stretch is NOT 1910 -- getting that wrong would render the final shelf shot in a
    # tobacco-brown hearing-room palette and break the callback the whole film is built on.
    worlds = [(0, 18, "alternate_2026"), (18, 325, "historical_1910"),
              (325, 415, "modern_evidence"), (415, 465, "historical_1910"),
              (465, 9999, "alternate_2026")]

    parsed = ParsedSpec(title=title)
    warnings = parsed.warnings
    for missing in [w for w in ("historical_1910", "alternate_2026") if w not in prompts]:
        warnings.append(f"no base image prompt found for '{missing}'; scenes will use narration only")

    index = 0
    for match in sections:
        start = _seconds(match.group(1), match.group(2))
        end = _seconds(match.group(3), match.group(4))
        body_start = match.end()
        body_end = sections[sections.index(match) + 1].start() if match is not sections[-1] else len(text)
        body = text[body_start:body_end]
        # Stop at the next chapter heading so a trailing '---' or '## 8. Visual system' never
        # becomes narration.
        body = re.split(r"\n##\s|\n---\s*\n", body)[0].strip()
        if not body:
            warnings.append(f"section at {match.group(0).strip()} has no narration")
            continue

        chunks = split_into_scenes(body, words_per_scene)
        span = max(1.0, (end - start) / max(1, len(chunks)))
        for offset, chunk in enumerate(chunks):
            at = start + offset * span
            world = _world_for(at, worlds)
            beat, anchor = _anchor_for(at, anchors)
            base = prompts.get(world, "")
            subject = anchor or beat or match.group(5)
            parsed.scenes.append(SpecScene(
                index=index, narration=chunk, start_sec=round(at, 1), world=world,
                beat=beat or match.group(5),
                image_prompt=(f"{base} Subject: {subject}." if base else f"Subject: {subject}."),
            ))
            index += 1

    parsed.words = sum(len(s.narration.split()) for s in parsed.scenes)
    return parsed


def to_json(spec: ParsedSpec, path: str | Path) -> dict:
    """Persist the machine contract beside the human document.

    The JSON is what the pipeline reads. Keeping it as a written artifact rather than an
    in-memory step means a render can be reproduced, diffed, and hand-corrected without
    reparsing prose that may have been edited since.
    """
    payload = {
        "title": spec.title,
        "word_count": spec.words,
        "scene_count": len(spec.scenes),
        "warnings": spec.warnings,
        "script": spec.as_script(),
    }
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload
