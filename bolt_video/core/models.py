"""Format-independent output contracts.

Pipelines may still return dictionaries while they are migrated, but new code should
serialize :class:`VideoPackage` at the boundary so every format exposes the same shape.
"""
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class VideoFormatId(str, Enum):
    SHORT_EXPLAINER = "short_explainer"
    LONG_EXPLAINER = "long_explainer"
    SIMULATION = "simulation"
    QUIZ = "quiz"
    TV_REVIEW = "tv_review"


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    OK = "ok"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass(frozen=True)
class ArtifactRef:
    kind: str
    path: str
    media_type: str


@dataclass(frozen=True)
class QualityReport:
    status: JobStatus = JobStatus.OK
    checks: dict[str, bool] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class VideoPackage:
    format_id: VideoFormatId
    title: str
    artifacts: tuple[ArtifactRef, ...]
    quality: QualityReport = field(default_factory=QualityReport)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
