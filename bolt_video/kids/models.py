"""Provider-free, strict authoring contract for a two-minute Bolt Kids episode.

The operator approves this contract, not an arbitrary prompt or executable scene.
Audio cues are first-class: a viewer response pause is not missing narration.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

POLICY_VERSION = "bolt_kids_gates_v1"
SCHEMA_VERSION = "bolt_kids_episode_v1"
OPERATION = "bolt_kids_episode"
Id = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
Seconds = Annotated[float, Field(ge=0, le=180, allow_inf_nan=False)]
Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Voice = Literal["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx",
                "sage", "shimmer", "verse", "marin", "cedar"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class Reference(Strict):
    id: Id
    # Only repository assets and studio-owned catalog entries; no caller-controlled HTTP/file URLs.
    uri: str = Field(min_length=1, max_length=300)
    sha256: Sha
    mime_type: Literal["image/png", "image/jpeg", "audio/wav", "audio/mpeg", "video/mp4"]
    license: Text
    origin: Text

    @model_validator(mode="after")
    def safe_source(self):
        if self.license.lower() in {"unknown", "unresolved", "tbd", "verify"}:
            raise ValueError("Reference rights must be resolved before approval")
        if self.uri.startswith("asset://"):
            part = self.uri[8:]
            if not re.fullmatch(r"[A-Za-z0-9_./-]+", part) or ".." in part.split("/") or part.startswith("/"):
                raise ValueError("Unsafe repository asset reference")
        elif not re.fullmatch(r"library://[0-9a-f]{32}", self.uri):
            raise ValueError("Use asset:// or a studio-owned library:// asset; arbitrary URLs/paths are forbidden")
        if self.sha256 == "0" * 64:
            raise ValueError("Resolve the actual reference checksum; placeholders cannot spend")
        return self


class Character(Strict):
    id: Id
    identity: Text
    reference_id: Id
    voice: Voice = "cedar"
    voice_instructions: str = Field(min_length=20, max_length=1000)


class World(Strict):
    id: Id
    description: Text
    reference_id: Id


class Song(Strict):
    id: Id
    lyrics: str = Field(min_length=5, max_length=1800)
    style: str = Field(min_length=10, max_length=1400)
    duration_sec: float = Field(ge=3, le=40, allow_inf_nan=False)
    # Empty means generate with the approved provider; otherwise reuse exact saved audio.
    reference_id: str = Field(default="", max_length=64)


class VisualAsset(Strict):
    id: Id
    world_id: Id
    cast: list[Id] = Field(min_length=1, max_length=5)
    prompt: str = Field(min_length=10, max_length=2500)
    reference_id: str = Field(default="", max_length=64)
    mode: Literal["still", "motion"] = "still"
    motion_prompt: str = Field(default="", max_length=1200)
    motion_seconds: Literal[5, 10] = 5
    # Only cyclic actions (e.g. a dance), never hatching/revealing/exiting, may loop.
    loopable: bool = False

    @model_validator(mode="after")
    def motion_contract(self):
        if self.mode == "motion" and not self.reference_id and len(self.motion_prompt) < 10:
            raise ValueError("Generated motion requires an explicit action prompt")
        if self.mode == "still" and (self.loopable or self.motion_prompt):
            raise ValueError("A still cannot promise animation or looped action")
        return self


class Cue(Strict):
    id: Id
    kind: Literal["speech", "song", "pause", "sfx"]
    text: str = Field(default="", max_length=1000)
    character_id: str = Field(default="", max_length=64)
    song_id: str = Field(default="", max_length=64)
    reference_id: str = Field(default="", max_length=64)
    duration_sec: Seconds = 0

    @model_validator(mode="after")
    def typed_cue(self):
        if self.kind == "speech":
            if not self.text or not self.character_id or self.song_id or self.duration_sec:
                raise ValueError("Speech needs text/character; measured audio owns its duration")
        elif self.kind == "song":
            if not self.song_id or self.text or self.character_id or self.reference_id or self.duration_sec:
                raise ValueError("Song cue must reference exactly one song")
        elif self.kind == "pause":
            if not 1 <= self.duration_sec <= 4 or self.text or self.character_id or self.song_id or self.reference_id:
                raise ValueError("Explicit response pauses are 1–4 seconds with no audio source")
        elif not self.reference_id or self.text or self.character_id or self.song_id or self.duration_sec:
            raise ValueError("Sound effects need a saved audio reference, not pretend TTS")
        return self


class Shot(Strict):
    id: Id
    asset_id: Id
    weight: float = Field(default=1, gt=0, le=10, allow_inf_nan=False)
    first_state: Text
    visible_action: Text
    last_state: Text
    requires_motion: bool = False


class Beat(Strict):
    id: Id
    role: Literal["hook", "clue", "question", "reveal", "celebration", "song", "recap", "goodbye"]
    round_id: str = Field(default="", max_length=64)
    answer: str = Field(default="", max_length=100)
    learning_purpose: Text
    audio: list[Cue] = Field(min_length=1, max_length=5)
    shots: list[Shot] = Field(min_length=1, max_length=5)


class Episode(Strict):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    project_id: Id
    title: str = Field(min_length=5, max_length=120)
    target_duration_sec: Literal[120] = 120
    audience: Literal["preschool_3_5"] = "preschool_3_5"
    world_mode: Literal["storybook"] = "storybook"
    learning_goal: str = Field(min_length=10, max_length=500)
    brand_pack_id: Id
    brand_pack_version: int = Field(ge=1, le=1000)
    # The uploaded reference, not a newly imagined dog mascot, is authoritative.
    bolt_design: Literal["white_teal_robot"] = "white_teal_robot"
    references: list[Reference] = Field(min_length=2, max_length=50)
    characters: list[Character] = Field(min_length=1, max_length=5)
    worlds: list[World] = Field(min_length=1, max_length=2)
    songs: list[Song] = Field(min_length=1, max_length=3)
    assets: list[VisualAsset] = Field(min_length=4, max_length=30)
    beats: list[Beat] = Field(min_length=8, max_length=30)

    @model_validator(mode="after")
    def graph_and_story(self):
        def index(rows, name):
            values = {x.id: x for x in rows}
            if len(values) != len(rows):
                raise ValueError(f"Duplicate {name} IDs")
            return values
        refs = index(self.references, "reference")
        cast = index(self.characters, "character")
        worlds = index(self.worlds, "world")
        songs = index(self.songs, "song")
        assets = index(self.assets, "visual asset")
        index(self.beats, "beat")
        if "bolt" not in cast:
            raise ValueError("The recurring robot Bolt must be in the cast")
        for item in [*self.characters, *self.worlds]:
            if item.reference_id not in refs or not refs[item.reference_id].mime_type.startswith("image/"):
                raise ValueError(f"Missing image identity/set reference for {item.id}")
        for song in self.songs:
            if song.reference_id and (song.reference_id not in refs or not refs[song.reference_id].mime_type.startswith("audio/")):
                raise ValueError(f"Song {song.id} needs an audio reference")
        for asset in self.assets:
            if asset.world_id not in worlds or not set(asset.cast) <= cast.keys():
                raise ValueError(f"Unresolved cast/world for {asset.id}")
            if len(set(asset.cast)) != len(asset.cast):
                raise ValueError("Duplicate character in a visual cast")
            if asset.reference_id:
                expected = "video/" if asset.mode == "motion" else "image/"
                if asset.reference_id not in refs or not refs[asset.reference_id].mime_type.startswith(expected):
                    raise ValueError(f"Asset {asset.id} requires a {expected} reference")
        cues = [cue for beat in self.beats for cue in beat.audio]
        shots = [shot for beat in self.beats for shot in beat.shots]
        index(cues, "cue"); index(shots, "shot")
        for cue in cues:
            if cue.kind == "speech" and cue.character_id not in cast:
                raise ValueError(f"Unknown speaker {cue.character_id}")
            if cue.kind == "song" and cue.song_id not in songs:
                raise ValueError(f"Unknown song {cue.song_id}")
            if cue.reference_id and (cue.reference_id not in refs or not refs[cue.reference_id].mime_type.startswith("audio/")):
                raise ValueError(f"Cue {cue.id} needs an audio reference")
        for shot in shots:
            if shot.asset_id not in assets:
                raise ValueError(f"Shot {shot.id} has no asset")
            if shot.requires_motion and assets[shot.asset_id].mode != "motion":
                raise ValueError(f"Required action {shot.id} cannot become a still-image fallback")
        if set(assets) != {s.asset_id for s in shots}:
            raise ValueError("Unused visual assets would authorize unexplained spending")
        if set(songs) != {c.song_id for c in cues if c.kind == "song"}:
            raise ValueError("Every song must be used")
        if self.beats[0].role != "hook" or self.beats[-1].role != "goodbye":
            raise ValueError("Begin with the story hook and end with a resolved goodbye")
        if not any(b.role == "recap" for b in self.beats) or not any(b.role == "song" for b in self.beats):
            raise ValueError("An episode needs a musical payoff and a learning recap")
        questions = [(i, b) for i, b in enumerate(self.beats) if b.role == "question"]
        reveals = [(i, b) for i, b in enumerate(self.beats) if b.role == "reveal"]
        if len(questions) != 3 or len(reveals) != 3:
            raise ValueError("Hide-and-seek v1 has exactly three question/reveal rounds")
        if len({b.round_id for _, b in questions}) != 3:
            raise ValueError("Question round IDs must be unique")
        for position, question in questions:
            if not question.round_id or not question.answer:
                raise ValueError("Each question must declare its answer and round")
            wait = question.audio[-1]
            if wait.kind != "pause" or not 2 <= wait.duration_sec <= 4:
                raise ValueError("Every question ends with a real 2–4 second response pause")
            matches = [(i, b) for i, b in reveals if b.round_id == question.round_id]
            if len(matches) != 1 or matches[0][0] <= position or matches[0][1].answer != question.answer:
                raise ValueError("Question/reveal order or answer does not match")
            next_question = next((i for i, _ in questions if i > position), len(self.beats))
            if matches[0][0] >= next_question:
                raise ValueError("Resolve this round before asking the next question")
            if any(assets[s.asset_id].loopable for s in matches[0][1].shots):
                raise ValueError("A one-time animal reveal must not loop")
        if sum(s.requires_motion for s in shots) < 3:
            raise ValueError("At least three story actions must be rendered as motion")
        if not any("bolt" in assets[s.asset_id].cast for b in self.beats for s in b.shots):
            raise ValueError("Bolt must actually appear, not only be named in metadata")
        return self


def canonical_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def validate_episode(value: dict) -> dict:
    """No provider imports, downloads, database calls or spending."""
    try:
        episode = Episode.model_validate(value)
    except (ValidationError, TypeError, ValueError) as exc:
        return {"valid": False, "policy_version": POLICY_VERSION,
                "issues": [str(exc)], "status": "needs_repair"}
    spec = episode.model_dump(mode="json")
    return {"valid": True, "policy_version": POLICY_VERSION,
            "status": "validated_not_authorized", "spec_sha256": canonical_hash(spec),
            "normalized_spec": spec, "issues": [], "target_duration_sec": 120}
