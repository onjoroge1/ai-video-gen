"""Engine-neutral, provider-free storyboard and ViMax description importer.

Validation establishes structural consistency, not factual truth, editorial approval,
render quality, or spending authority. No path/URL is dereferenced by these models.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=8000)]
Ident = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")]
Seconds = Annotated[float, Field(ge=0, le=86400, allow_inf_nan=False, strict=True)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Shot(Contract):
    id: Ident
    start: Seconds
    end: Seconds
    narration: Text
    visual: Text
    first_frame: Text
    change: Text
    last_frame: Text
    treatment: Literal["illustrated", "stock", "motion_canvas", "source_clip"] = "illustrated"
    reference_ids: list[Ident] = Field(default_factory=list, max_length=30)
    claim_ids: list[Ident] = Field(default_factory=list, max_length=30)
    audio_notes: str = Field(default="", max_length=8000)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("shot end must be after start")
        return self


class SourceSpan(Contract):
    # IDs only. A future authenticated worker must resolve ownership and ffprobe
    # the actual bytes, rather than trusting the declared duration here.
    finished_video_id: Ident
    duration: Annotated[float, Field(gt=0, le=86400, allow_inf_nan=False, strict=True)]
    start: Seconds
    end: Seconds
    layout: Literal["general", "track", "split", "screencast"] = "general"
    content_type: Literal["illustrated", "talking_head", "screen", "mixed"] = "illustrated"

    @model_validator(mode="after")
    def bounded(self):
        if not 0 <= self.start < self.end <= self.duration:
            raise ValueError("source span must lie within the declared source duration")
        if self.content_type == "illustrated" and self.layout != "general":
            raise ValueError("illustrated sources require general framing until a crop is reviewed")
        return self


class Storyboard(Contract):
    schema_version: Literal[1] = 1
    status: Literal["draft"] = "draft"
    title: Annotated[str, Field(min_length=1, max_length=200)]
    flow: Literal["stock_short", "motion_scene", "repurpose", "storyboard"] = "storyboard"
    aspect_ratio: Literal["9:16", "16:9", "1:1"] = "9:16"
    narration_script: Text
    shots: list[Shot] = Field(min_length=1, max_length=180)
    reference_ids: list[Ident] = Field(default_factory=list, max_length=500)
    claim_ids: list[Ident] = Field(default_factory=list, max_length=500)
    source: SourceSpan | None = None
    provenance: Literal["reelforge", "vimax_import"] = "reelforge"

    @model_validator(mode="after")
    def consistent(self):
        ids = [s.id for s in self.shots]
        if len(ids) != len(set(ids)):
            raise ValueError("shot IDs must be unique")
        previous_end = 0.0
        for shot in self.shots:
            if abs(shot.start - previous_end) > 0.001:
                raise ValueError("timeline must start at zero with no gaps or overlaps")
            previous_end = shot.end
            if not set(shot.reference_ids).issubset(self.reference_ids):
                raise ValueError("shot refers to an undeclared reference ID")
            if not set(shot.claim_ids).issubset(self.claim_ids):
                raise ValueError("shot refers to an undeclared claim ID")
        normalize = lambda s: " ".join(s.split())
        if normalize(" ".join(s.narration for s in self.shots)) != normalize(self.narration_script):
            raise ValueError("shot narration must exactly cover narration_script in order")
        if self.flow == "repurpose":
            if self.source is None:
                raise ValueError("repurpose requires a finished video source span")
            if abs(previous_end - (self.source.end - self.source.start)) > 0.001:
                raise ValueError("repurpose timeline must match the selected source span")
        elif self.source is not None:
            raise ValueError("source span belongs only to the repurpose flow")
        if self.flow == "stock_short" and self.aspect_ratio != "9:16":
            raise ValueError("stock_short v1 is a portrait flow")
        return self


def review(board: Storyboard) -> dict:
    payload = board.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    notes = ["Structural validation is not fact verification or operator approval."]
    notes.extend(f"{s.id}: no claim references declared" for s in board.shots if not s.claim_ids)
    notes.extend(f"{s.id}: unchanged first/last frame; inspect whether visible information changes"
                 for s in board.shots if s.first_frame == s.last_frame)
    if board.source:
        notes.append("Source duration and ownership still require verification against stored bytes.")
    return {"schema_version": 1, "status": "draft", "structurally_valid": True,
            "spend_authorized": False, "production_enabled": False,
            "duration_seconds": board.shots[-1].end,
            "plan_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
            "warnings": notes, "storyboard": payload}


def import_vimax(raw: dict) -> dict:
    """Map inspected ViMax ShotDescription fields, requiring external alignment.

Input: {title, shots: [...ViMax descriptions...], alignment: [{idx,start,end,
 narration}], narration_script, ...optional board metadata}. No default duration
or invented narration is supplied. audio_desc stays notes, never spoken copy.
"""
    allowed = {"title", "shots", "alignment", "narration_script", "flow", "aspect_ratio", "reference_ids", "claim_ids"}
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise ValueError("ViMax import envelope contains unsupported fields")
    shots, alignment = raw.get("shots"), raw.get("alignment")
    if not isinstance(shots, list) or not 1 <= len(shots) <= 180 or not isinstance(alignment, list):
        raise ValueError("supply 1–180 ViMax shots and a separate alignment list")
    index = {}
    for item in alignment:
        if not isinstance(item, dict) or set(item) != {"idx", "start", "end", "narration"}:
            raise ValueError("each alignment requires exactly idx, start, end and narration")
        key = item["idx"]
        if type(key) is not int or key < 0 or key in index:
            raise ValueError("alignment indices must be unique nonnegative integers")
        index[key] = item
    mapped = []
    seen = set()
    for item in shots:
        if not isinstance(item, dict) or type(item.get("idx")) is not int:
            raise ValueError("each ViMax shot needs an integer idx")
        key = item["idx"]
        if key in seen or key not in index:
            raise ValueError("every shot needs unique, explicit timing and narration alignment")
        seen.add(key)
        a = index[key]
        mapped.append({"id": f"vimax-{key}", "start": a["start"], "end": a["end"],
                       "narration": a["narration"], "visual": item.get("visual_desc"),
                       "first_frame": item.get("ff_desc"), "last_frame": item.get("lf_desc"),
                       "change": item.get("motion_desc"), "audio_notes": item.get("audio_desc") or ""})
    if seen != set(index):
        raise ValueError("alignment contains indices absent from the imported shots")
    data = {key: value for key, value in raw.items() if key not in {"shots", "alignment"}}
    data.update(shots=mapped, provenance="vimax_import", status="draft")
    return review(Storyboard.model_validate(data))
