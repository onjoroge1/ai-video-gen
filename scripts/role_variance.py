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


def function_stability(fixture: dict, reports: list[Path]) -> dict:
    """After the redesign the question changes, because the compiler cannot fail.

    Roles are now derived, so "complete spine" would read 5/5 by construction and prove only that
    the planner filled in a form. What can still genuinely fail is what the planner declares each
    fact to BE, whether that event survives the evidence boundary, and whether the computed
    reversal inverts a setup property rather than restating the programme's failure.
    """
    seen: dict[str, int] = {}
    disagreed: dict[str, dict[str, int]] = {}
    sheets = spines = judged = inverted = 0
    for path in reports:
        for sample in json.loads(path.read_text()).get("samples") or []:
            beats = ((sample.get("spine") or {}).get("beats")) or []
            if not beats:
                continue
            sheets += 1
            compiled = (sample.get("spine") or {}).get("compiled") or {}
            coverage = compiled.get("coverage") or {}
            spines += bool(coverage.get("covered"))
            judged += bool(coverage.get("covered")) and not compiled.get("still_failing")
            functions = set()
            for beat in beats:
                declared = (beat.get("event_function") or "").strip().lower()
                text = sfm.event_of(beat)["text"]
                if not declared or not text:
                    continue
                functions.add(declared)
                expected = _match(text, fixture)
                if expected and expected != declared:
                    disagreed.setdefault(expected, {})
                    disagreed[expected][declared] = disagreed[expected].get(declared, 0) + 1
                if (beat.get("role") or "") == "reversal" and beat.get("derived_from"):
                    inverted += 1
            for function in functions:
                seen[function] = seen.get(function, 0) + 1
    return {"sheets": sheets, "present": seen, "disagreed": disagreed,
            "covered_spines": spines, "fully_judged": judged, "computed_reversals": inverted}


def acceptance(reports) -> str:
    """The five conditions, and how many sheets satisfy all of them AT ONCE.

    Reported per sheet rather than per condition because four separate 4/5s can still be 0/5
    together, and it is the joint figure that decides whether narration may be bought.
    """
    import story_fact_model as _sfm
    rows, spend = [], 0.0
    for path in reports:
        payload = json.loads(Path(path).read_text())
        for sample in payload.get("samples") or []:
            spend += float(sample.get("recorded_cost_usd") or 0)
            spine = sample.get("spine") or {}
            beats, compiled = spine.get("beats") or [], spine.get("compiled") or {}
            if not beats:
                rows.append({"sheet": sample.get("sample"), "reached_compiler": False})
                continue
            coverage = compiled.get("coverage") or {}
            failing = set(compiled.get("still_failing") or [])
            mech = next((b for b in beats if (b.get("role") or "") == "mechanism"), None)
            rev = next((b for b in beats if (b.get("role") or "") == "reversal"), None)
            rows.append({
                "sheet": sample.get("sample"), "reached_compiler": True,
                # every required function present AND its beat not failing the evidence boundary
                "functions": bool(coverage.get("covered")),
                # the two halves cited separately, and the mechanism beat not among the failures
                "citations": bool(mech and _sfm.event_of(mech)["claim_refs"]),
                "mechanism": bool(mech and _sfm._text(mech.get("beat_id")) not in failing),
                "reversal": bool(rev and rev.get("derived_from")
                                 and _sfm._text(rev.get("beat_id")) not in failing),
            })
    total = len(rows) or 1
    def _count(key):
        return sum(1 for row in rows if row.get(key))
    joint = sum(1 for row in rows
                if all(row.get(k) for k in ("functions", "citations", "mechanism", "reversal")))
    lines = ["ACCEPTANCE", ""]
    lines.append(f"  required event functions present and supported   {_count('functions')}/{total}")
    lines.append(f"  measure and goal supported by their citations    {_count('citations')}/{total}")
    lines.append(f"  derived mechanism passes Boundary A             {_count('mechanism')}/{total}")
    lines.append(f"  reversal inverts a sourced property             {_count('reversal')}/{total}")
    lines.append(f"  ALL OF THE ABOVE ON THE SAME SHEET              {joint}/{total}")
    lines.append(f"  total spend including failures and repairs      ${spend:.2f}")
    lines += ["", "Per sheet:"]
    for row in rows:
        if not row["reached_compiler"]:
            lines.append(f"  sheet {row['sheet']}: never reached the compiler")
            continue
        marks = " ".join(f"{k}={'+' if row[k] else '-'}"
                         for k in ("functions", "citations", "mechanism", "reversal"))
        lines.append(f"  sheet {row['sheet']}: {marks}")
    return "\n".join(lines)


def render_stability(fixture: dict, result: dict) -> str:
    import event_functions as ef
    lines = [f"EVENT FUNCTION STABILITY ACROSS {result['sheets']} SHEETS", ""]
    total = result["sheets"] or 1
    for function in ef.map_for("backfiring_solution").required:
        count = result["present"].get(function, 0)
        mark = "+" if count == total else ("~" if count >= total * 0.8 else "!")
        drift = result["disagreed"].get(function) or {}
        note = ("  (the fixture's event was called "
                + ", ".join(f"{k} x{v}" for k, v in drift.items()) + ")") if drift else ""
        lines.append(f"  {mark} {function:<22s} present in {count}/{total} sheets{note}")
    lines += ["",
              f"  spines with every required role covered   {result['covered_spines']}/{total}",
              f"  ... and every event past Boundary A        {result['fully_judged']}/{total}",
              f"  reversals computed from a state inversion  {result['computed_reversals']}/{total}"]
    lines += ["", "Coverage alone is not the target: the compiler assigns roles deterministically, "
                  "so it cannot fail. The second and third lines are the ones that can."]
    return "\n".join(lines)


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
    if argv[1] == "--acceptance":
        print(acceptance(argv[2:]))
        return 0
    stability = argv[1] == "--functions"
    paths = [Path(p) for p in argv[(2 if stability else 1):]]
    if stability:
        print(render_stability(fixture, function_stability(fixture, paths)))
        return 0
    result = collect(fixture, paths)
    if not result["runs"]:
        print("No sheets found. The reports carry a sheet only for samples that reached the "
              "spine gate.")
        return 1
    print(render(fixture, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
