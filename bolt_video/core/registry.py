"""Small declarative registry used by the API and UI for format discovery."""
from dataclasses import asdict, dataclass

from .models import VideoFormatId


@dataclass(frozen=True)
class FormatDescriptor:
    id: VideoFormatId
    label: str
    aspect_ratio: str
    input_mode: str
    description: str


FORMAT_REGISTRY = {
    f.id.value: f for f in (
        FormatDescriptor(VideoFormatId.SHORT_EXPLAINER, "Short", "9:16", "topic",
                         "Fast curiosity-gap explainer."),
        FormatDescriptor(VideoFormatId.LONG_EXPLAINER, "Explainer", "16:9", "topic",
                         "Beat-sheet-driven long-form explainer."),
        FormatDescriptor(VideoFormatId.SIMULATION, "Simulation", "9:16", "rule",
                         "Deterministic time-and-magnitude science simulation."),
        FormatDescriptor(VideoFormatId.QUIZ, "Rapid Quiz", "9:16", "category",
                         "Cold-open guessing game with immediate clues and rapid reveals."),
        FormatDescriptor(VideoFormatId.TV_REVIEW, "TV Review", "16:9", "script",
                         "Spoiler-scoped episode review with an evolving story board."),
    )
}


def get_format(format_id: str) -> FormatDescriptor:
    try:
        return FORMAT_REGISTRY[format_id]
    except KeyError as exc:
        raise ValueError(f"Unknown video format: {format_id}") from exc


def list_formats() -> list[dict]:
    return [asdict(item) for item in FORMAT_REGISTRY.values()]
