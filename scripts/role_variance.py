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
            sheets += 1
            beats = ((sample.get("spine") or {}).get("beats")) or []
            if not beats:
                continue
            compiled = (sample.get("spine") or {}).get("compiled") or {}
            coverage = compiled.get("coverage") or {}
            spines += bool(coverage.get("covered"))
            acceptance, _ = acceptance_rows([{"samples": [sample]}])
            judged += acceptance[0]["functions"] and acceptance[0]["mechanism"]
            inverted += acceptance[0]["reversal"]
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
            for function in functions:
                seen[function] = seen.get(function, 0) + 1
    return {"sheets": sheets, "present": seen, "disagreed": disagreed,
            "covered_spines": spines, "fully_judged": judged, "computed_reversals": inverted}


def acceptance_rows(payloads) -> tuple[list, float]:
    """Only positive judgments of the current accepted objects count as support."""
    import story_fact_model as sfm
    import event_functions as ef
    rows, spend = [], 0.0
    for payload in payloads:
        for sample in payload.get("samples") or []:
            spend += float(sample.get("recorded_cost_usd") or 0)
            spine = sample.get("spine") or {}
            compiled = spine.get("compiled") or {}
            beats = compiled.get("effective_beats") or spine.get("beats") or []
            cascade = compiled.get("cascade") or {}
            judgments = {j["beat_id"]: j for j in cascade.get("judgments") or []}
            def supported(beat):
                result = judgments.get(beat.get("beat_id"), {})
                return (result.get("passed") is True and result.get("verdict") == "entailed"
                        and result.get("event") == sfm.event_of(beat))
            mapping = ef.map_for(compiled.get("engine") or "backfiring_solution")
            required = mapping.required if mapping else ()
            mech = next((b for b in beats if sfm.compiled_mechanism(b)), {})
            rev = next((b for b in beats if b.get("role") == "reversal"), {})
            assertions = {j["field"]: j for j in cascade.get("assertion_judgments") or []
                          if j["beat_id"] == mech.get("beat_id")}
            parts = (mech.get("derivation") or {}).get("assertions") or {}
            citations = all(assertions.get(f, {}).get("passed") is True
                            and assertions[f].get("assertion") == parts.get(f)
                            for f in ("measure", "goal"))
            relationships = {(r["beat_id"], r["kind"]): r
                             for r in compiled.get("relationships") or []}
            def relationship_supported(beat, kind):
                result = relationships.get((beat.get("beat_id"), kind), {})
                return (result.get("passed") is True and result.get("verdict") == "entailed"
                        and result.get("input_fingerprint") == sfm.relationship_fingerprint(beat, beats))
            row = {"sheet": sample.get("sample"), "reached_compiler": bool(beats),
                   "functions": bool(required) and all(any(
                       b.get("event_function") == f and supported(b) for b in beats) for f in required),
                   "citations": citations,
                   "mechanism": bool(mech and supported(mech) and citations
                                     and relationship_supported(mech, "proxy_gap")),
                   "reversal": bool(rev and supported(rev)
                                    and relationship_supported(rev, "behavior_inversion"))}
            row["joint"] = (compiled.get("passed") is True and not cascade.get("unavailable")
                            and not compiled.get("still_failing") and all(
                                row[k] for k in ("functions", "citations", "mechanism", "reversal")))
            rows.append(row)
    return rows, spend


def acceptance(reports) -> str:
    rows, spend = acceptance_rows([json.loads(Path(p).read_text()) for p in reports])
    total = len(rows)
    def count(key):
        return sum(bool(row.get(key)) for row in rows)
    lines = ["ACCEPTANCE", "",
        f"  required event functions present and supported   {count('functions')}/{total}",
        f"  measure and goal supported by their citations    {count('citations')}/{total}",
        f"  derived mechanism passes Boundary A             {count('mechanism')}/{total}",
        f"  reversal inverts a sourced property             {count('reversal')}/{total}",
        f"  ALL OF THE ABOVE ON THE SAME SHEET              {count('joint')}/{total}",
        f"  total spend including failures and repairs      ${spend:.6f}", "", "Per sheet:"]
    for row in rows:
        marks = " ".join(f"{key}={'+' if row[key] else '-'}"
                         for key in ("functions", "citations", "mechanism", "reversal", "joint"))
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
