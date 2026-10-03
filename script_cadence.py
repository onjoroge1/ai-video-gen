"""Reference-informed writing guidance and descriptive, non-blocking rhythm metrics.

The operator supplied a partial shark-meat opening on 2026-10-03. Full transcripts
of the two linked videos were not available; these are not whole-video benchmarks.
"""
import re
import statistics

VERSION = "concrete_scene_cadence_v1"
REFERENCE_URLS = ["https://youtu.be/kS0qNsNmxN4", "https://youtu.be/WjVIH-djRpc"]
BRIEF = (
    "\nEDITORIAL REFERENCE — CONCRETE SCENE TO REINTERPRETATION. Where the evidence allows, "
    "give the viewer an ordinary, recognizable action or physical object before showing the "
    "unexpected meaning of it. Let each sentence do new work: orient, add a concrete detail, "
    "establish the expectation, overturn it, then earn the explanation. Name the topic clearly; "
    "do not conceal it behind vague pronouns or prolong setup past the engine's mechanism deadline. "
    "Use short scene-setting beats, flowing everyday sentences and an occasional longer sentence "
    "that carries the reveal or causal relationship. Sentence boundaries are not scene boundaries. "
    "Do not force a long/short pair, rhetorical question or punch line into every scene. "
    "A deliberate complete thought such as a time-setting noun phrase is different from a "
    "grammatically broken repair. Make chapter transitions change the viewer's question rather "
    "than restart the introduction. End by returning to the opening object with a changed meaning. "
    "Concrete details, motives, reactions and sensory descriptions must remain inside the cited "
    "evidence; never invent a historical eyewitness moment. Do not copy reference wording. "
    "Keep existing hook, hinge, runtime and evidence constraints. These are writing principles, "
    "not a claim of measured audience retention.\n"
)


def measure(script):
    text = " ".join(str(s.get("narration") or "") for s in script.get("scenes") or [])
    # Treat decimals as numbers rather than sentence boundaries; remove spoken chapter
    # labels so metadata-like 'Step one.' does not manufacture cadence diversity.
    text = re.sub(r"\b(?:Step|Chapter)\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\.",
                  "", text, flags=re.I)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'])", text) if s.strip()]
    lengths = [len(re.findall(r"\b\w+(?:['’]\w+)*\b", s)) for s in sentences]
    warnings = []
    if len(lengths) >= 6 and max(lengths) - min(lengths) <= 3:
        warnings.append("Similar sentence lengths throughout; review for a mechanical rhythm")
    if len(lengths) >= 6 and sum(n <= 5 for n in lengths) / len(lengths) > .7:
        warnings.append("Mostly very short sentences; review for clipped, telegraphic narration")
    if any(n > 35 for n in lengths):
        warnings.append("A sentence exceeds 35 words; review aloud for breath and clarity")
    return {"version": VERSION, "status": "advisory", "sentence_count": len(lengths),
            "sentence_words": lengths, "median_words": statistics.median(lengths) if lengths else 0,
            "min_words": min(lengths, default=0), "max_words": max(lengths, default=0),
            "short_sentences": sum(n <= 5 for n in lengths),
            "long_sentences": sum(n >= 15 for n in lengths), "warnings": warnings,
            "reference_basis": "operator_supplied_partial_excerpt; full videos unverified"}
