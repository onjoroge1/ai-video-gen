#!/usr/bin/env python3
"""Author shot-table rows for one narration section of an operator spec.

The spec's section 9 covers only the first 45 seconds. Everything good about the pilot came
from that table -- cadence, camera move, and the mode that decides whether a shot wants true
video. Past 0:45 the renderer would be inventing the breakdown, which is exactly what produced
the four-state slideshow the operator caught.

This generates candidate rows for ONE section at a time, in the spec's own format, and writes
them to a review file rather than editing the spec. The operator's document stays theirs; the
merge is their decision. Run on the script provider (Luna by default), not Anthropic, because
this is a formatting job over words that are already written -- roughly a cent per section.

The camera-move vocabulary is not decorative. spec_pilot._motion_for reads the move verb out of
each row's visual text to pick a zoompan preset, so a row phrased without one silently falls
back to a positional cycle. The prompt below pins the verbs to that mapping.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

import explainer_pipeline as ep  # noqa: E402
import script_provider  # noqa: E402
import user_directed as ud  # noqa: E402

# Must stay in sync with spec_pilot._MOVE_WORDS -- these are the phrases the renderer can map
# to a real camera move. A row using any other verb renders on the fallback cycle.
MOVE_VERBS = ("macro glide", "rack focus", "push", "pull back", "glide", "crosses",
              "drops", "opens toward", "collapse", "split screen", "freeze")

MODES = ("Still + camera path", "Full motion", "Motion insert", "Graphic",
         "Graphic transition", "Motion graphic", "Archival evidence",
         "Dramatization", "Evidence montage")


def fmt(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def parse_rows(raw: str, start: int, end: int) -> tuple[list, list]:
    """Parse integer-second rows and check the contract the renderer depends on.

    Returns (rows, problems). Timing is repaired where it is unambiguous -- a model that drifts
    by a second should not cost a regeneration -- but anything that would change MEANING is
    reported rather than silently rewritten.
    """
    rows, problems = [], []
    for line in raw.splitlines():
        line = line.strip().strip("|").strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            problems.append(f"skipped malformed row: {line[:60]}")
            continue
        try:
            begin, finish = int(parts[0]), int(parts[1])
        except ValueError:
            problems.append(f"non-integer times, skipped: {parts[0]!r}/{parts[1]!r}")
            continue
        visual, mode = parts[2], parts[3]
        purpose = parts[4] if len(parts) > 4 else ""
        if mode not in MODES:
            problems.append(f"unknown mode {mode!r} at {begin}s")
        if not any(verb in visual.lower() for verb in MOVE_VERBS):
            problems.append(f"no camera verb at {begin}s -- will use the fallback cycle")
        rows.append({"start_sec": begin, "end_sec": finish, "visual": visual,
                     "mode": mode, "purpose": purpose})

    rows.sort(key=lambda r: r["start_sec"])
    if not rows:
        return rows, problems

    # Close gaps and overlaps by snapping each row to its predecessor. A visual is written for a
    # moment in the narration, so shifting a boundary a second is safe; dropping or reordering
    # a row is not, and is never done here.
    if rows[0]["start_sec"] != start:
        problems.append(f"first row began at {rows[0]['start_sec']}s, snapped to {start}s")
        rows[0]["start_sec"] = start
    for earlier, later in zip(rows, rows[1:]):
        if later["start_sec"] != earlier["end_sec"]:
            problems.append(
                f"{'gap' if later['start_sec'] > earlier['end_sec'] else 'overlap'} at "
                f"{earlier['end_sec']}s->{later['start_sec']}s, snapped")
            later["start_sec"] = earlier["end_sec"]
    if rows[-1]["end_sec"] != end:
        problems.append(f"last row ended at {rows[-1]['end_sec']}s, snapped to {end}s")
        rows[-1]["end_sec"] = end

    for row in rows:
        span = row["end_sec"] - row["start_sec"]
        if span > 4:
            problems.append(f"{span}s hold at {row['start_sec']}s exceeds the 4s ceiling")
        elif span < 2:
            problems.append(f"{span}s hold at {row['start_sec']}s is below the 2s floor")
    return rows, problems


def build_prompt(section_title: str, narration: str, start: int, end: int,
                 world: str, existing_rows: str) -> str:
    count = max(1, round((end - start) / 2.8))
    start_plus = start + 3
    return f"""You are extending the shot plan of a documentary video specification.

The narration for this section is already written and MUST NOT be changed. Your job is only to
break it into visual shots.

SECTION: {section_title}  ({start}s to {end}s, {end - start} seconds)
VISUAL WORLD: {world}

NARRATION (fixed):
{narration}

Existing rows from the same document, for tone and level of visual detail:
{existing_rows}

Produce {count} rows covering second {start} to second {end}, with NO gaps and NO overlaps.

OUTPUT FORMAT -- one row per line, exactly four pipe-separated fields:

START_SECOND | END_SECOND | Visual description | Mode

START_SECOND and END_SECOND are PLAIN INTEGERS counting seconds from the beginning of the
film. Write {start} and {start_plus}, never "0:45" or "45:00". Do not use colons in the
first two fields.

Rules:

1. Each shot is 2 to 4 seconds. Never longer than 4 -- a longer hold reads as a slideshow.
2. Contiguous: each row's START_SECOND equals the previous row's END_SECOND.
3. The first row starts at {start}. The last row ends at exactly {end}.
4. The Visual description MUST contain one of these exact camera phrases, because the renderer
   parses it to choose the camera move: {", ".join(MOVE_VERBS)}.
5. Mode MUST be exactly one of: {", ".join(MODES)}.
6. Visuals must depict only what the narration supports. This is a factual documentary about
   1910 Congress and water hyacinth. Do not invent events, statistics, or people.
7. No lettering or signage in a visual unless the narration itself names those words.

Output ONLY the rows. No header, no commentary, no code fences."""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--section", required=True,
                    help="section start time, e.g. 0:45")
    ap.add_argument("--world", default="historical_1910")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    text = Path(args.spec).read_text(encoding="utf-8")

    mins, secs = args.section.split(":")
    start = int(mins) * 60 + int(secs)

    sections = re.findall(
        r"^###\s+(\d+):(\d{2})\s*[–—-]\s*(\d+):(\d{2})\s*[–—-]\s*(.+?)\s*$\n(.*?)(?=\n###|\n##\s|\Z)",
        text, re.M | re.S)
    match = None
    for m1, s1, m2, s2, title, body in sections:
        if int(m1) * 60 + int(s1) == start:
            match = (int(m2) * 60 + int(s2), title, body.strip())
            break
    if not match:
        print(f"No narration section starting at {args.section}", file=sys.stderr)
        return 1
    end, title, body = match
    body = re.split(r"\n##\s|\n---\s*\n", body)[0].strip()

    existing = ud.extract_shot_plan(text)[:4]
    rows = "\n".join(
        f"| {i+1} | {s['start_sec']//60}:{s['start_sec']%60:02d}–"
        f"{s['end_sec']//60}:{s['end_sec']%60:02d} | {s['visual']} | {s['mode']} | ... |"
        for i, s in enumerate(existing))

    prompt = build_prompt(title, body, start, end, args.world, rows)
    client = script_provider.OpenAIScriptClient(ep._openai())
    response = client.messages.create(
        model=script_provider.openai_script_model(),
        max_tokens=4000,
        system="You output only markdown table rows. No prose, no code fences.",
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r"^```[a-z]*\n|\n```$", "", raw).strip()

    usage = getattr(response, "usage", None)
    if usage:
        print(f"tokens: in={getattr(usage,'input_tokens','?')} "
              f"out={getattr(usage,'output_tokens','?')}", file=sys.stderr)

    rows_out, problems = parse_rows(raw, start, end)
    for problem in problems:
        print(f"  ! {problem}", file=sys.stderr)
    if not rows_out:
        print("no usable rows parsed; raw response follows:\n" + raw, file=sys.stderr)
        return 1

    table = "\n".join(
        f"| {i+1} | {fmt(r['start_sec'])}–{fmt(r['end_sec'])} | {r['visual']} | "
        f"{r['mode']} | {r['purpose']} |"
        for i, r in enumerate(rows_out))

    dest = Path(args.out or f"spec/shot_plan_{start}s.md")
    dest.write_text(table + "\n", encoding="utf-8")
    print(f"wrote {dest}  ({len(rows_out)} shots, "
          f"{min(r['end_sec']-r['start_sec'] for r in rows_out)}-"
          f"{max(r['end_sec']-r['start_sec'] for r in rows_out)}s holds, "
          f"{len(problems)} problem(s))")
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
