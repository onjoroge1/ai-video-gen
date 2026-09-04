"""Turn a reference video into a draft causal-story fixture.

The corpus is the source of truth for this lane, but it has grown by hand: transcribe, measure the
cuts, then author a JSON of roles, chapters, causal edges and timings. That took long enough per
video that the corpus stalled at three — and three is where a hardcoded constant is still mostly a
guess. Every constant derived from the first two references was corrected by the third.

So this does the mechanical half. It measures what can be measured and scaffolds the rest, leaving
a draft whose ROLES and CAUSAL EDGES a human corrects. It deliberately does not guess those: role
labelling is the one judgement the corpus exists to capture, and a plausible wrong label is worse
than a blank one because it looks finished.

    python3 scripts/ingest_reference.py video.mp4 --name cobra_effect --engine backfiring_solution

Writes references/<name>.draft.json plus a measurement report. Correct the roles and causal edges,
then move it to fixtures/causal/<name>.json.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import causal_story as cs  # noqa: E402
import reference_corpus as rc  # noqa: E402
import story_engines as se  # noqa: E402


# Matches the reference band: a change smaller than this is a camera move, not a new visual state.
SCENE_THRESHOLD = 0.2
_TIMESTAMP = re.compile(r"(\d+):(\d+):([\d.,]+)")


def _run(args: list[str]) -> str:
    """Both streams. ffmpeg splits its output: volumedetect reports on stderr, while
    `metadata=print:file=-` writes to stdout. Reading only stderr returned zero cuts for a video
    with 65 of them, and zero cuts reads as "one long static shot" — the exact defect this corpus
    exists to measure."""
    done = subprocess.run(args, capture_output=True, text=True)
    return (done.stdout or "") + (done.stderr or "")


def probe_duration(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True).stdout.strip()
    return float(out or 0.0)


def detect_cuts(video: Path) -> list[float]:
    """Visual state changes, the number this whole lane is judged on."""
    stderr = _run(["ffmpeg", "-nostdin", "-i", str(video),
                   "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',metadata=print:file=-",
                   "-f", "null", "-"])
    return [float(value) for value in re.findall(r"pts_time:([0-9.]+)", stderr)]


def mean_volume(video: Path) -> float | None:
    # NOTE: no -v error here. volumedetect prints at info level, and suppressing it returns
    # nothing at all — a silent None that reads like "no audio".
    stderr = _run(["ffmpeg", "-nostdin", "-i", str(video), "-af", "volumedetect",
                   "-f", "null", "/dev/null"])
    found = re.search(r"mean_volume:\s*(-?[0-9.]+)", stderr)
    return float(found.group(1)) if found else None


def transcribe(video: Path, model: str = "small.en") -> list[tuple[float, str]]:
    """(start_sec, text) per cue, via the whisper CLI."""
    if not shutil.which("whisper"):
        raise SystemExit("whisper CLI not found — install it or pass --srt with an existing file")
    workspace = Path(tempfile.mkdtemp(prefix="ingest_"))
    audio = workspace / "audio.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(video),
                    "-ac", "1", "-ar", "16000", str(audio)], check=True)
    subprocess.run(["whisper", str(audio), "--model", model, "--language", "en",
                    "--output_format", "srt", "--output_dir", str(workspace),
                    "--verbose", "False"], check=True, capture_output=True)
    return read_srt(workspace / "audio.srt")


def read_srt(path: Path) -> list[tuple[float, str]]:
    cues = []
    for block in re.split(r"\n\n+", path.read_text(encoding="utf-8").strip()):
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        stamp = _TIMESTAMP.search(lines[1])
        if not stamp:
            continue
        hours, minutes, seconds = stamp.groups()
        start = int(hours) * 3600 + int(minutes) * 60 + float(seconds.replace(",", "."))
        cues.append((start, " ".join(lines[2:]).strip()))
    return cues


def spoken_chapters(cues: list[tuple[float, str]]) -> list[tuple[float, str]]:
    """Where the narrator says "Step one" — the presentational spine, distinct from the chain."""
    return [(start, text) for start, text in cues if cs._MARKER.match(text)]


# Frames sampled by the observation pass. Twelve spans a three-minute reference at roughly one every
# fifteen seconds — enough to catch the opening, the turn and the close in a single call.
OBSERVE_FRAMES = 12

_OBSERVE_SYSTEM = (
    "You are describing the storytelling FORMAT of a reference video so it can be reused on a "
    "COMPLETELY DIFFERENT subject. Report only what the frames and narration show, and never "
    "invent a detail you cannot point at.\n\n"
    "DESCRIBE THE TELLING, NOT THE TOPIC. Your answer must make sense for a video about any "
    "subject at all. Therefore:\n"
    "- Do NOT name this video's subject, people, places, dates, organisations, brands or "
    "sponsors. Write the generic role instead: 'the authority figure', 'the affected "
    "population', 'a named historical leader', 'an app sponsor'.\n"
    "- Do NOT quote its narration. Describe the SHAPE of a line — its length, mood and job — "
    "rather than reproducing the words.\n"
    "- Timings, counts, orderings and visual technique are format and ARE wanted.\n\n"
    "A description that only fits this one topic is useless here. Return ONLY JSON."
)


def sample_blocks(video: Path, cues: list[tuple[float, str]], count: int,
                  workspace: Path) -> list[tuple[float, Path, str]]:
    """(midpoint_sec, frame_path, narration) for `count` equal-length blocks.

    Frames are PAIRED with the words spoken over them rather than sent as a bare contact sheet,
    because every field being judged is a relation between what is said and what is shown: a hook
    type is an opening line against an opening image, a reveal is a sentence landing on a picture.
    A grid cannot express that pairing. It would also have to squash these 9:16 references into
    16:9 cells, distorting the composition the pass exists to describe.
    """
    duration = probe_duration(video)
    if duration <= 0:
        return []
    blocks = []
    span = duration / count
    for index in range(count):
        start, end = index * span, (index + 1) * span
        midpoint = start + span / 2
        frame = workspace / f"observe_{index:02d}.jpg"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{midpoint:.2f}",
                        "-i", str(video), "-frames:v", "1", str(frame)], check=True)
        if not frame.exists():
            continue
        spoken = " ".join(text for start_sec, text in cues if start <= start_sec < end)
        blocks.append((round(midpoint, 1), frame, spoken))
    return blocks


def observe(video: Path, cues: list[tuple[float, str]], count: int = OBSERVE_FRAMES,
            cost_sink: list | None = None) -> dict:
    """The judged half of a reference: how it tells its story, not how fast it cuts.

    Returns {} on any failure. It fails to an EMPTY dict, never a partial or a plausible one,
    because `observed` is context that shapes every video generated from this reference — an absent
    judgement is recoverable and an invented one propagates silently. For the same reason the result
    is filtered to reference_corpus.OBSERVED_FIELDS: a model that returns extra keys must not be
    able to introduce a field that only one reference in the corpus has.
    """
    import explainer_pipeline as ep

    workspace = Path(tempfile.mkdtemp(prefix="observe_"))
    try:
        blocks = sample_blocks(video, cues, count, workspace)
        if not blocks:
            return {}
        content: list[dict] = []
        for midpoint, frame, spoken in blocks:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.b64encode(frame.read_bytes()).decode()}})
            content.append({"type": "text",
                            "text": f"{midpoint:.0f}s — narration: {spoken or '(silence)'}"})
        content.append({"type": "text", "text": (
            "The frames above are one per equal-length block of a single vertical explainer video, "
            "in order, each with the words spoken over it. Describe the storytelling format so a "
            "different video on a different subject could be built to match it. One or two "
            "sentences per field, concrete and specific. Return ONLY JSON with exactly these keys: "
            + json.dumps(list(rc.OBSERVED_FIELDS)))})
        response = ep._claude().messages.create(
            model=ep.ANTHROPIC_MODEL, max_tokens=1600, system=_OBSERVE_SYSTEM,
            messages=[{"role": "user", "content": content}],
        )
        if cost_sink is not None:
            cost_sink.append(ep._msg_cost(response.usage))
        parsed, _ = ep._parse_script_json(response.content[0].text)
        if not isinstance(parsed, dict):
            return {}
        return {field: str(parsed[field]).strip()
                for field in rc.OBSERVED_FIELDS
                if isinstance(parsed.get(field), (str, int, float)) and str(parsed[field]).strip()}
    except Exception as exc:
        print(f"  observation pass unavailable: {type(exc).__name__}: {str(exc)[:160]}",
              file=sys.stderr)
        return {}
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def build_draft(video: Path, name: str, engine_id: str,
                cues: list[tuple[float, str]],
                observed: dict | None = None) -> tuple[dict, dict]:
    duration = probe_duration(video)
    cuts = detect_cuts(video)
    narration = " ".join(text for _, text in cues)
    markers = spoken_chapters(cues)

    holds = [round(b - a, 2) for a, b in zip(cuts, cuts[1:])]
    holds_sorted = sorted(holds)
    measured = {
        "runtime_sec": round(duration, 2),
        "visual_states": len(cuts) + 1,
        "mean_hold_sec": round(duration / max(1, len(cuts) + 1), 2),
        "median_hold_sec": holds_sorted[len(holds_sorted) // 2] if holds_sorted else None,
        "max_hold_sec": max(holds) if holds else None,
        "words": len(narration.split()),
        "words_per_minute": round(len(narration.split()) / duration * 60, 1) if duration else None,
        "spoken_chapter_markers": len(markers),
        "mean_volume_db": mean_volume(video),
    }
    measured.update({
        metric["metric"]: metric["value"]
        for metric in (cs.measure_narration(narration, duration).get("metrics") or [])
    })

    # One draft step per spoken chapter when the video has them, else one per cue. Roles are left
    # BLANK on purpose — that judgement is the thing being collected.
    anchors = markers or cues
    steps = []
    for index, (start, text) in enumerate(anchors):
        steps.append({
            "step_id": f"step_{index + 1:03d}",
            "role": "",                       # <- label me
            "start_sec": round(start, 1),
            "label": "",
            "caused_by": "" if index == 0 else f"step_{index:03d}",   # <- verify me
            "situation": text,
            "chapter": index + 1 if markers else 0,
        })

    draft = {
        "format": "causal_story_v1",
        "source": f"Ingested from {video.name}; timings measured with ffmpeg/whisper.",
        "note": ("DRAFT. Every `role` is blank and every `caused_by` is a naive chain to the "
                 "previous step. Both need a human pass — role labelling is the judgement this "
                 "corpus exists to capture, and a plausible wrong label looks finished."),
        "measured": measured,
        # The judged half, from --observe. Present and empty rather than absent, so every
        # reference has the same shape and a consumer never has to guess which kind of file it
        # is holding. reference_corpus.OBSERVED_FIELDS is the vocabulary.
        "observed": dict(observed or {}),
        "story": {
            "title": name.replace("_", " ").title(),
            "runtime_sec": round(duration, 2),
            "format_tag": "explained like you are five",
            "engine": se.resolve_id(engine_id),
            "opening_object": "",             # <- fill me
            "start_state": "",                # <- fill me
            "hook": {"line": cues[0][1] if cues else ""},
            "steps": steps,
            "parallel_cases": [],
        },
        "expect": {"pass": True},
    }
    return draft, measured


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--name", required=True, help="fixture name, e.g. cobra_effect")
    parser.add_argument("--engine", default=se.DEFAULT_ENGINE,
                        help=f"one of: {', '.join(se.ENGINES)}")
    parser.add_argument("--srt", type=Path, help="reuse an existing transcript")
    parser.add_argument("--out", type=Path, default=ROOT / "references")
    parser.add_argument("--observe", action="store_true",
                        help="run the vision pass that fills `observed` (costs one API call)")
    parser.add_argument("--frames", type=int, default=OBSERVE_FRAMES,
                        help="frames sampled by --observe")
    args = parser.parse_args()

    if not args.video.exists():
        raise SystemExit(f"no such video: {args.video}")

    cues = read_srt(args.srt) if args.srt else transcribe(args.video)

    costs: list[float] = []
    observed = observe(args.video, cues, args.frames, costs) if args.observe else {}
    draft, measured = build_draft(args.video, args.name, args.engine, cues, observed)

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{args.name}.draft.json"
    path.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"wrote {path}\n")
    print("MEASURED")
    for key, value in measured.items():
        print(f"  {key:<24} {value}")
    if args.observe:
        print(f"\nOBSERVED  ({len(observed)}/{len(rc.OBSERVED_FIELDS)} fields, "
              f"${sum(costs):.3f}) — context only, never a gate")
        for key in rc.OBSERVED_FIELDS:
            value = observed.get(key)
            print(f"  {key:<24} {value if value else '-- not returned --'}")

    print(f"\n{len(draft['story']['steps'])} draft steps. Next: label every `role`, verify each")
    print("`caused_by`, and fill opening_object and start_state. Then move it to fixtures/causal/.")


if __name__ == "__main__":
    main()
