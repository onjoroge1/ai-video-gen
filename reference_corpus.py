"""The reference corpus: labelled videos that define this lane, loaded as data.

Every constant this project derived from two reference videos was corrected by the third — four
times, each discovered by a failing run rather than by reading the code. A hardcoded number cannot
tell you it was fitted to a sample of two. A corpus can, because you can count it.

So the references are the source of truth and this module is how the rest of the system reads them.

THE AUTHORITY SPLIT IS STRUCTURAL, NOT ADVISORY.

    measured{}   ffmpeg and whisper — cut cadence, words per minute, loudness, hold times.
                 Deterministic and reproducible, so it MAY gate a run.

    observed{}   a vision model reading sampled frames — hook type, tone, humour placement,
                 composition, character reuse. Judgement, so it MUST NOT gate a run.

Those are returned by two different functions rather than one dict with a convention, because a
convention gets forgotten. This session shipped three gates built on judgement — an ending-first
binding rule, two hinge trims — and all three damaged scripts. `gating_metrics()` cannot hand you a
judged field; `creative_context()` is explicitly for prompting only.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import story_engines as se
import causal_story as cs


CORPUS_DIR = Path(__file__).resolve().parent / "fixtures" / "causal"

# Files that are pipeline OUTPUT, not references. They live alongside the corpus for inspection but
# must never teach it — training the format on our own generations would launder our mistakes into
# the spec.
_GENERATED_PREFIX = "generated_"

# The judged half. Named here so the ingester's vision prompt and any consumer agree on one
# vocabulary; an `observed` block with different keys per reference is not a corpus.
OBSERVED_FIELDS = (
    "hook_type",              # how the opening earns the next ten seconds
    "story_pattern",          # the beat names the video actually walks
    "recurring_characters",   # how many identities recur, and how they are kept recognisable
    "location_reuse",         # how few places it returns to
    "visual_composition",     # framing, depth, what fills the frame
    "on_screen_text",         # caption style, placement, how much is lettered
    "narrator_tone",          # register and sentence shape
    "humour_and_interrupts",  # where it breaks pattern to re-earn attention
    "reveal_placement",       # when the governing idea lands, in the video's own words
    "ending_callback",        # how the close returns to the opening
)


class Reference:
    """One labelled reference video."""

    def __init__(self, path: Path, payload: dict):
        self.path = path
        self.name = path.stem
        self._payload = payload
        self.story: dict = payload.get("story") or {}
        self.engine_id: str = se.resolve_id(self.story.get("engine"))
        self._measured: dict = payload.get("measured") or {}
        self._observed: dict = payload.get("observed") or {}

    @property
    def has_measurements(self) -> bool:
        """False for operator-written references, which have no source video to measure.

        `hippo_weed` is written, not transcribed. Treating its absent numbers as zeros would drag
        every derived band toward nothing, so callers must check rather than assume.
        """
        return bool(self._measured)

    @property
    def has_observations(self) -> bool:
        return bool(self._observed)

    def gating_metrics(self) -> dict[str, Any]:
        """Deterministic measurements. These may inform a gate."""
        return dict(self._measured)

    def creative_context(self) -> dict[str, Any]:
        """Judged observations plus the labelled spine. PROMPTING ONLY — never a gate.

        Returns abstract structure, never verbatim narration: the blueprint teaches the format, it
        does not license reproducing the reference's content.
        """
        return {
            "engine": self.engine_id,
            "observed": dict(self._observed),
            "spine": [
                {"role": step.get("role"), "label": step.get("label"),
                 "chapter": step.get("chapter"), "caused_by": step.get("caused_by")}
                for step in self.story.get("steps") or []
            ],
        }

    def __repr__(self) -> str:
        return f"<Reference {self.name} engine={self.engine_id}>"


def load(corpus_dir: Path | None = None) -> list[Reference]:
    """Every labelled reference, generated samples excluded."""
    directory = Path(corpus_dir or CORPUS_DIR)
    references = []
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith(_GENERATED_PREFIX):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload.get("story"), dict) or "steps" not in payload["story"]:
            continue
        references.append(Reference(path, payload))
    return references


def by_engine(engine_id: str, corpus_dir: Path | None = None) -> list[Reference]:
    """References that teach one engine.

    Retrieval is keyed on the ENGINE, not on topic similarity. The cobra and famine references
    share no subject and the same structure, so a topic embedding would rank them as the least
    relevant pair in the corpus when they are the most relevant.
    """
    wanted = se.resolve_id(engine_id)
    return [reference for reference in load(corpus_dir) if reference.engine_id == wanted]


def coverage(corpus_dir: Path | None = None) -> dict[str, int]:
    """References per engine. An engine at zero has a sequence nobody has checked against a video.

    Two engine sequences were written from imagination and both were wrong; each was corrected the
    first time a real reference was labelled against it. This is how that gap stays visible.
    """
    counts = {engine_id: 0 for engine_id in se.ENGINES}
    for reference in load(corpus_dir):
        counts[reference.engine_id] = counts.get(reference.engine_id, 0) + 1
    return counts


def _positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def runtime_fit_guidance(duration_sec: float, corpus_dir: Path | None = None) -> list[dict]:
    """Compare labelled reference openings with the existing target deadline, for PROMPTS ONLY.

    A labelled mechanism timestamp is an observation about one telling, not an empirical minimum
    for its engine. Counts include the mechanism itself, and required/optional roles remain
    distinct. Written references and missing/invalid timings supply no timing evidence. Compression
    percentages use 0–100 and describe shortening that particular opening, never a pass guarantee.
    """
    duration = _positive_number(duration_sec)
    if duration is None:
        raise ValueError("runtime-fit guidance requires a positive finite duration_sec")
    references = load(corpus_dir)
    guidance = []
    for engine_id, engine in se.ENGINES.items():
        opening_roles = list(engine["sequence"])
        opening_roles = opening_roles[:opening_roles.index(cs.MECHANISM) + 1]
        deadline_pct = se.mechanism_deadline_pct(engine, cs.MECHANISM_DEADLINE_PCT)
        deadline = duration * deadline_pct
        samples = []
        for reference in references:
            if reference.engine_id != engine_id:
                continue
            steps = reference.story.get("steps") or []
            index = next((i for i, step in enumerate(steps)
                          if isinstance(step, dict) and step.get("role") == cs.MECHANISM), None)
            runtime = _positive_number(reference.gating_metrics().get("runtime_sec"))
            opening = _positive_number(steps[index].get("start_sec")) if index is not None else None
            if runtime is None or opening is None or opening > runtime:
                opening = None
            compression = max(0.0, opening - deadline) if opening is not None else None
            samples.append({
                "reference_id": reference.name,
                "runtime_sec": runtime,
                "observed_opening_sec": opening,
                "milestones_through_mechanism": sum(
                    isinstance(step, dict) and step.get("role") in opening_roles
                    and step.get("role") not in (cs.ESCALATION, cs.GENERALIZATION)
                    for step in steps[:index + 1]) if index is not None else None,
                "compression_needed_sec": compression,
                "compression_needed_pct": round(100 * compression / opening, 3)
                if opening is not None else None,
                "unchanged_opening_min_runtime_sec": opening / deadline_pct
                if opening is not None and deadline_pct > 0 else None,
            })
        guidance.append({
            "engine_id": engine_id,
            "target_deadline_sec": deadline,
            "mechanism_deadline_pct": deadline_pct,
            "required_milestones_through_mechanism": sum(
                role in engine["required"] for role in opening_roles),
            "optional_milestones_before_mechanism": [
                role for role in opening_roles if role not in engine["required"]],
            "reference_count": len(samples),
            "support_count": sum(sample["observed_opening_sec"] is not None for sample in samples),
            "references": samples,
        })
    return guidance


def runtime_fit_block(duration_sec: float, corpus_dir: Path | None = None) -> str:
    """Prompt guidance from reference timings, with uncertainty and authority made explicit."""
    return (
        "\n\nRUNTIME FIT — planning guidance, not a gate or an engine ban.\n"
        "Choose for factual causal fit first, then consider whether its opening fits the target "
        "deadline. Reference mechanism timestamps are labelled observations of particular tellings, "
        "not minimum runtimes or proof that compression is impossible. Milestone counts include "
        "the mechanism; optional milestones need not be added. Zero support means timing fit is "
        "unknown. Compression percentages describe shortening the reference opening, not increasing "
        "narration speed. If compression is needed, plan concise truthful beats in the required "
        "order; prefer another engine only when the topic genuinely fits it. Do not extend the "
        "requested runtime or the validation deadline.\n"
        + json.dumps(runtime_fit_guidance(duration_sec, corpus_dir), ensure_ascii=False, indent=2)
        + "\n"
    )


# How much of a reference reaches the generator.
#
# Default LOOSE, not balanced. The plan specified balanced, but the corpus holds one reference per
# engine, so "balanced" currently means "imitate this single video" — and every constant fitted to
# a sample this small was later corrected by the next reference, four times out of four. Widen the
# default when the corpus supports it, not before.
ADHERENCE_LEVELS = ("loose", "balanced", "strong")
DEFAULT_ADHERENCE = "loose"

_ADHERENCE_FIELDS = {
    # Voice and posture only — the things that are true of the format regardless of subject.
    "loose": ("hook_type", "narrator_tone", "humour_and_interrupts"),
    # Adds the shape of the telling: where the turn lands and how it closes.
    "balanced": ("hook_type", "story_pattern", "narrator_tone", "humour_and_interrupts",
                 "reveal_placement", "ending_callback"),
    # Everything judged, plus the abstract spine and the reference's own pacing.
    "strong": OBSERVED_FIELDS,
}

# Pacing passed as GUIDANCE at strong adherence. Numbers carry no subject, so they cannot bleed a
# topic; they are still measurements, and passing them into a prompt is not gating on them.
_PACING_FIELDS = ("mean_hold_sec", "words_per_minute", "spoken_chapter_markers")

# Format vocabulary that is legitimately capitalised. "Step" is the spoken chapter marker — the
# retention device this whole lane is built on — not a subject noun, and dropping a field over it
# would discard the most useful observation in the corpus.
_FORMAT_VOCABULARY = {"Step", "Steps", "Chapter", "Part", "Numbered", "Split", "Hand", "Cold",
                      "Dark", "Simple", "Closes", "Opens", "Conversational", "Comedy", "Dramatic"}

# Capitalised words and years are how a subject leaks into a description of a telling. The FIRST
# observation pass, before its prompt was made subject-free, returned 17 and 29 of these per
# reference — Churchill, Gandhi, and the name of the video's sponsor — plus 6 and 8 verbatim
# narration quotes. Rewriting the prompt took those to 0 and 1. This is the check that proved it,
# and the net that catches a reference ingested with an older prompt.
_TOPIC_TOKEN = re.compile(r"\b[A-Z][a-z]{3,}\b|\b(?:1[0-9]{3}|20[0-9]{2})\b")

# Sentence-initial capitals are grammar, not topic.
_SENTENCE_START = re.compile(r"(?:^|[.!?]\s+|[-\u2014(]\s*)([A-Z][a-z]{3,})")

# A quote delimiter is not a possessive. Requiring a non-letter on the outside stops "the viewer's
# own life ... a narrator's aside" from reading as one 40-character quoted span, which is how a
# strip built on this regex would have deleted the description between two apostrophes.
_QUOTED_SPAN = re.compile(
    r"""(?<![A-Za-z])["'\u2018\u201c]([^"'\u2018\u2019\u201c\u201d]{20,}?)["'\u2019\u201d](?![A-Za-z])"""
)


def topic_tokens(text: str) -> list[str]:
    """Words that name a subject rather than describe a telling. A REPORT, not a mangler.

    Nothing here rewrites an observation. An earlier version stripped quoted spans in place, which
    deletes format templates like 'Step one, Step two...' — the single most useful thing the corpus
    records — while a half-deleted sentence still reads as authoritative. A field is either clean
    enough to pass whole or it is dropped whole; there is no partial credit.
    """
    text = str(text or "")
    grammatical = set(_SENTENCE_START.findall(text))
    return sorted({token for token in _TOPIC_TOKEN.findall(text)
                   if token not in grammatical and token not in _FORMAT_VOCABULARY})


def blueprint(reference: "Reference", adherence: str = DEFAULT_ADHERENCE) -> dict:
    """The prompt-safe projection of a reference. THE ONLY sanctioned route into a generation call.

    `creative_context()` is faithful to the reference, quotes and all, because a corpus entry should
    stay verifiable. This is the derived view that travels: narration stripped, and — at strong
    adherence — a spine of role/chapter/edge with the LABELS REMOVED. Labels like "Cobra farms" are
    content, and a blueprint that carries them invites a video about antibiotic resistance to drift
    toward snakes.
    """
    level = adherence if adherence in _ADHERENCE_FIELDS else DEFAULT_ADHERENCE
    observed = reference.creative_context()["observed"]
    rules, omitted = {}, {}
    for field in _ADHERENCE_FIELDS[level]:
        value = str(observed.get(field, "")).strip()
        if not value:
            continue
        leaked = topic_tokens(value)
        if leaked:
            omitted[field] = leaked
        else:
            rules[field] = value

    block: dict[str, Any] = {"engine": reference.engine_id, "adherence": level,
                             "format_rules": rules}
    if omitted:
        # Visible, not silent. A field withheld for naming a subject is a defect in the capture,
        # and the fix belongs in the ingestion prompt rather than in a filter downstream.
        block["omitted_for_topic_leak"] = omitted
    if level == "strong":
        block["spine"] = [
            {"role": step.get("role"), "chapter": step.get("chapter"),
             "caused_by": step.get("caused_by")}
            for step in reference.story.get("steps") or []
        ]
        pacing = {field: value for field, value in reference.gating_metrics().items()
                  if field in _PACING_FIELDS and value is not None}
        if pacing:
            block["pacing"] = pacing
    return block


def blueprint_block(reference: "Reference", adherence: str = DEFAULT_ADHERENCE) -> str:
    """`blueprint()` rendered for a prompt, with the instruction that keeps it a format and not a
    template. Returns "" when there is nothing to say, so a caller can concatenate it blindly."""
    data = blueprint(reference, adherence)
    if not data.get("format_rules"):
        return ""
    return (
        "\n\nFORMAT REFERENCE — how a proven video of this engine is TOLD.\n"
        "This describes STORYTELLING TECHNIQUE from a video about an unrelated subject. Match the "
        "technique. Do NOT borrow its topic, characters, places or examples, and do not mention a "
        "sponsor. If any rule below names a specific thing, it is a mistake in the reference — "
        "apply the underlying technique to THIS video's subject instead.\n"
        + json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    )
