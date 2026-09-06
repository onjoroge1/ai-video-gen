#!/usr/bin/env python3
"""How stably does the planner assign causal FUNCTIONS to the same factual EVENTS?

Reads the sheets that `longform_script_check.py --output` now keeps for failed attempts and
prints a role confusion matrix. The question is not "how many passed" -- that number moves for
reasons that have nothing to do with roles -- but whether the same event lands in the same
function every time. If one pair of roles swaps, tighten those two definitions. If everything
moves, the generator should stop assigning roles at all and have them derived from the events and
their state transitions.

Events are grouped by hand-labelled `event_function` from a golden fixture, matched on stems so
that a planner's rewording does not read as a different event. Deliberately NOT keyword scoring
of the role itself -- that is the mistake this codebase has now made four times (tail/tails, the
four-letter floor, "and", claim_kind as a content proxy). The fixture is the authority; matching
is only how a run's wording is tied back to it.

    python scripts/role_variance.py fixtures/fact_model/hanoi_event_functions.json report*.json
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import story_fact_model as sfm


def _match(event_text: str, fixture: dict) -> str:
    """Which labelled event function this event is an instance of, or "" if none is close."""
    stems = sfm._stems(event_text)
    if not stems:
        return ""
    best, best_score = "", 0.0
    for entry in fixture["events"]:
        for phrasing in [entry["event"]] + list(entry.get("also_seen_as") or []):
            other = sfm._stems(phrasing)
            if not other:
                continue
            # Jaccard, so a long event cannot win by sheer vocabulary.
            score = len(stems & other) / len(stems | other)
            if score > best_score:
                best, best_score = entry["event_function"], score
    return best if best_score >= fixture.get("min_similarity", 0.22) else ""


def collect(fixture: dict, reports: list[Path]) -> dict:
    table: dict[str, dict[str, int]] = {}
    unmatched: list[str] = []
    runs = 0
    for path in reports:
        payload = json.loads(path.read_text())
        for sample in payload.get("samples") or []:
            beats = ((sample.get("spine") or {}).get("beats")) or []
            if not beats:
                continue
            runs += 1
            for beat in beats:
                text = sfm.event_of(beat)["text"]
                role = (beat.get("role") or beat.get("causal_role") or "?").lower()
                if not text:
                    continue
                function = _match(text, fixture)
                if not function:
                    unmatched.append(f"[{role}] {text[:88]}")
                    continue
                table.setdefault(function, {})
                table[function][role] = table[function].get(role, 0) + 1
    return {"runs": runs, "table": table, "unmatched": unmatched}


def render(fixture: dict, result: dict) -> str:
    order = [entry["event_function"] for entry in fixture["events"]]
    lines = [f"ROLE ASSIGNMENT ACROSS {result['runs']} SHEETS", ""]
    width = max([len(f) for f in order] + [22])
    stable = unstable = 0
    for function in order:
        rows = result["table"].get(function) or {}
        expected = next(e for e in fixture["events"] if e["event_function"] == function)
        want = expected["expected_role"]
        if not rows:
            lines.append(f"  {function:<{width}}  (absent from every sheet)")
            continue
        ranked = sorted(rows.items(), key=lambda kv: -kv[1])
        agreed = rows.get(want, 0)
        total = sum(rows.values())
        mark = "+" if agreed == total else ("~" if agreed >= total * 0.6 else "!")
        stable += agreed == total
        unstable += agreed != total
        spread = "  ".join(f"{role} {count}" for role, count in ranked)
        lines.append(f"  {mark} {function:<{width}}  want {want:<16s} {spread}")
    lines += ["", f"{stable} functions assigned consistently, {unstable} unstable."]
    if result["unmatched"]:
        lines += ["", f"Events not in the fixture ({len(result['unmatched'])}) — either new "
                      "material or the fixture needs another phrasing:"]
        lines += [f"    {row}" for row in sorted(set(result["unmatched"]))]
    return "\n".join(lines)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print(__doc__)
        return 2
    fixture = json.loads(Path(argv[0]).read_text())
    result = collect(fixture, [Path(p) for p in argv[1:]])
    if not result["runs"]:
        print("No sheets found. The reports carry a sheet only for samples that reached the "
              "spine gate.")
        return 1
    print(render(fixture, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
