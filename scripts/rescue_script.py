#!/usr/bin/env python3
"""Rescue a failed script by REVISING it: fix only what broke, check every gate, show the diff.

    python3 scripts/rescue_script.py report  jobs/<job>
    python3 scripts/rescue_script.py apply   jobs/<job> edits.json --out /tmp/rescue_r1.json
    python3 scripts/rescue_script.py check   jobs/<job> /tmp/rescue_r1.json [--grades 3]
    python3 scripts/rescue_script.py diff    jobs/<job> /tmp/rescue_r1.json
    python3 scripts/rescue_script.py install jobs/<job> /tmp/rescue_r1.json

Operator rule (2026-10-19): when the pipeline's script fails a gate, revise the failed script:
fix the blocking errors and the lines the grader names, and keep the pipeline's opening, order
and voice. A full rewrite on the planner's skeleton (the pythons rescue) passed every gate and
read as inconsistent. First get the hard gates passing (storyboard, claims, dossier, retention);
then at most three grade rounds, each cutting only what the grader names. Still under the bar:
the operator chooses to accept the script or approve an outline for a restructure, never a silent
rewrite. Measured on the pythons failure (10-19): one revision with 14% of sentences changed passed
every hard gate and moved the grade from 68 to 72; a careless replacement in the close then dropped
it to 68, because each cut can open a new seam. Keep a revision's new words few.

`report` prints the failing gate's errors next to the scenes they name, the grader's notes, and
the storyboard check, so the edit list can be short. `apply` takes edits.json, a list of:
    {"scene": "event_02b", "replace": ["old exact text", "new text"]}
    {"scene": "event_02b", "delete": "an exact sentence to remove"}
    {"scene": "event_03", "move": "an exact sentence", "to": "event_02b"}   # appended to that scene
    {"scene": "event_01", "narration": "the whole new narration"}         # last resort, one scene
    {"scene": "event_01", "event_text": "...", "event_claims": ["c02", "c06"]}
A scene is named by beat_id, scene_id or index. Claim phrases and picture anchors are re-derived
from the edited narration (rederive_narration_bindings), as every pipeline pass that rewrites
narration does. `check` runs the gates resume will run, `diff` shows sentence-level changes, and
`install` stamps the opening, sets the failure file aside and writes _state.json for --resume.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import difflib
import glob
import json
import os
import re
import shlex
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
MAX_ROUNDS = 3        # grade rounds after the hard gates pass
GRADE_BAR = 78
LOG_NAME = "rescue_log.json"
_SENT = re.compile(r"(?<=[.!?])\s+")


# --- loading -------------------------------------------------------------------------------

def failure_file(job: str) -> str:
    """The newest saved pre-media failure in the job, or ""."""
    found = sorted(glob.glob(os.path.join(job, "semantic_failure_*.json")), key=os.path.getmtime)
    return found[-1] if found else ""


def load_failed(job: str) -> dict:
    """{"script", "report", "stage", "source"} from the newest failure, else from _state.json."""
    path = failure_file(job)
    if path:
        data = json.load(open(path))
        return {"script": data["script"], "report": data.get("report") or {}, "stage": data.get("stage", ""),
                "source": path}
    state = os.path.join(job, "_state.json")
    data = json.load(open(state))
    return {"script": data.get("script", data), "report": {}, "stage": "state", "source": state}


def launch_flags(job: str) -> dict:
    """Environment the launcher set for this job, read from its run.log launch line and flags."""
    env = {}
    text = ""
    for name in ("run_command.txt", "run.log"):
        path = os.path.join(job, name)
        if os.path.exists(path):
            text += open(path).read() + "\n"
    if "--no-synthesis" in text or "SYNTHESIS_DEVICE=off" in text:
        env["SYNTHESIS_DEVICE"] = "off"
    m = re.search(r"--engine\s+(\S+)", text)
    if m:
        env["STORY_ENGINE"] = m.group(1)
    m = re.search(r"--opening\s+(myth|witness)", text)
    if m:
        env["OPENING_HOOK"] = m.group(1)
    if re.search(r"--palette\s+natural", text):
        env["ILLUSTRATED_PALETTE"] = "natural"
    if re.search(r"--music-mix\s+ambient_pad", text):
        env["MUSIC_MIX"] = "ambient_pad"
    return env


def resume_command(job: str) -> str:
    """The launcher command recorded for this job, with --resume added."""
    for name in ("run_command.txt",):
        path = os.path.join(job, name)
        if os.path.exists(path):
            cmd = open(path).read().strip()
            return cmd if "--resume" in cmd else cmd + " --resume"
    return f"/opt/homebrew/bin/python3 scripts/run_illustrated_local.py ... --out {job} --resume  (copy the original flags)"


# --- addressing and edits ------------------------------------------------------------------

def scene_index(script: dict, ref) -> int:
    scenes = script.get("scenes") or []
    if isinstance(ref, int):
        if 0 <= ref < len(scenes):
            return ref
        raise KeyError(f"no scene {ref}")
    for i, s in enumerate(scenes):
        if ref in (s.get("beat_id"), s.get("scene_id"), s.get("id")):
            return i
    raise KeyError(f"no scene named {ref!r}")


def _tidy(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def apply_edits(script: dict, edits: list[dict]) -> tuple[dict, list[str]]:
    """A copy of the script with the edits applied, and a line per edit. Exact-text edits fail loudly
    when the text is not in the scene, so an edit can never silently miss."""
    out = copy.deepcopy(script)
    scenes = out["scenes"]
    notes = []
    for e in edits:
        i = scene_index(out, e["scene"])
        s = scenes[i]
        where = s.get("beat_id") or s.get("scene_id") or str(i)
        if "replace" in e:
            old, new = e["replace"]
            if old not in s["narration"]:
                raise ValueError(f"{where}: replace text not found: {old!r}")
            s["narration"] = _tidy(s["narration"].replace(old, new, 1))
            notes.append(f"{where}: replaced {old!r} -> {new!r}")
        if "delete" in e:
            if e["delete"] not in s["narration"]:
                raise ValueError(f"{where}: delete text not found: {e['delete']!r}")
            s["narration"] = _tidy(s["narration"].replace(e["delete"], "", 1))
            notes.append(f"{where}: deleted {e['delete']!r}")
        if "move" in e:
            j = scene_index(out, e["to"])
            if e["move"] not in s["narration"]:
                raise ValueError(f"{where}: move text not found: {e['move']!r}")
            s["narration"] = _tidy(s["narration"].replace(e["move"], "", 1))
            scenes[j]["narration"] = _tidy(scenes[j]["narration"] + " " + e["move"])
            notes.append(f"{where}: moved {e['move']!r} to {scenes[j].get('beat_id') or j}")
        if "narration" in e:
            s["narration"] = _tidy(e["narration"])
            notes.append(f"{where}: narration rewritten ({len(s['narration'].split())} words)")
        if "event_text" in e:
            s["event"] = {"text": e["event_text"], "claim_refs": list(e.get("event_claims") or [])}
            notes.append(f"{where}: event text set ({', '.join(e.get('event_claims') or [])})")
        s["_words_as_written"] = len(s["narration"].split())
    empty = [s.get("beat_id") or str(k) for k, s in enumerate(scenes) if not s["narration"].strip()]
    if empty:
        raise ValueError(f"edits left empty narration in {empty}; a scene needs words (or a restructure)")
    out.pop("_grade", None)
    return out, notes


def rebind(script: dict) -> None:
    """Re-derive claim phrases, picture anchors and story positions from the edited narration."""
    import explainer_pipeline as ep
    ep.rederive_narration_bindings(script, research_dossier=script.get("_research_dossier"))


# --- diff ----------------------------------------------------------------------------------

def sentences(text: str) -> list[str]:
    return [s for s in _SENT.split(text or "") if s.strip()]


def narration_diff(before: dict, after: dict) -> dict:
    """Per scene, the sentences removed and added, and totals."""
    rows, changed_sentences, total = [], 0, 0
    for a, b in zip(before["scenes"], after["scenes"]):
        sa, sb = sentences(a["narration"]), sentences(b["narration"])
        total += len(sa)
        removed = [x for x in sa if x not in sb]
        added = [x for x in sb if x not in sa]
        if removed or added:
            changed_sentences += max(len(removed), len(added))
            rows.append({"scene": a.get("beat_id") or a.get("scene_id"), "removed": removed, "added": added})
    return {"scenes_changed": len(rows), "sentences_changed": changed_sentences, "sentences_before": total,
            "share_changed": round(changed_sentences / total, 3) if total else 0.0, "rows": rows}


def diff_text(d: dict) -> str:
    lines = [f"{d['scenes_changed']} scene(s) and {d['sentences_changed']} of {d['sentences_before']} sentences changed "
             f"({d['share_changed']:.0%})."]
    for r in d["rows"]:
        lines.append(f"\n[{r['scene']}]")
        lines += [f"  - {x}" for x in r["removed"]] + [f"  + {x}" for x in r["added"]]
    if d["share_changed"] > 0.35:
        lines.append("\nThis is more than a third of the script: a rewrite, not a revision. Propose an outline first.")
    return "\n".join(lines)


# --- rounds --------------------------------------------------------------------------------

def record_round(job: str, notes: list[str], out_path: str) -> int:
    path = os.path.join(job, LOG_NAME)
    log = json.load(open(path)) if os.path.exists(path) else {"rounds": []}
    log["rounds"].append({"at": dt.datetime.now().isoformat(timespec="seconds"), "edits": notes, "state": out_path})
    json.dump(log, open(path, "w"), indent=1)
    return len(log["rounds"])


# --- gates ---------------------------------------------------------------------------------

def run_gates(script: dict, question: str, grades: int = 3, *, judge_claims=None, grader=None) -> dict:
    """Storyboard, claims, dossier, retention contract and N grades. Injected callables replace the
    paid judges in tests."""
    import illustrated_story as ist
    import longform_research as lr
    import longform_retention as lrt
    sc = copy.deepcopy(script)
    sb = ist.build_storyboard(sc, question)
    if judge_claims is None:
        import explainer_pipeline as ep
        judge_claims = lambda s: ep._validate_claims(s, s.get("_research_dossier") or {}, cost_sink=[])  # noqa: E731
    if grader is None:
        import explainer_pipeline as ep
        grader = lambda s: ep.grade_script(s, cost_sink=[])  # noqa: E731
    claims = judge_claims(script)
    blocking = [e for e in claims.get("errors") or [] if e.get("severity") != "soft"]
    # A judge outage is not a pass: nothing was checked (ENTAILMENT_UNAVAILABLE, provider_unavailable).
    outage = [e for e in blocking if "UNAVAILABLE" in str(e.get("code", "")) or "provider_unavailable" in str(e.get("message", ""))]
    dossier = lr.validate_research_dossier(script.get("_research_dossier") or {})
    retention = lrt.validate_longform_story(script, question)
    scores = [g for g in (grader(script) for _ in range(grades)) if g]
    mean = round(statistics.mean(g["overall"] for g in scores), 1) if scores else None
    result = {
        "storyboard": {"passed": sb["validation"]["passed"], "errors": sb["validation"]["errors"],
                       "warnings": sb["validation"]["warnings"]},
        "claims": {"passed": bool(claims.get("passed")) and not outage,
                   "errors": ([f"judge unavailable for {len(outage)} beat(s): check credentials or the provider"] if outage else [])
                             + [f"{e.get('code')} {e.get('scene')}: {e.get('message', '')[:240]}" for e in blocking if e not in outage]},
        "dossier": {"passed": bool(dossier.get("passed")), "errors": [e.get("code") for e in dossier.get("errors") or []]},
        "retention": {"passed": bool(retention.get("passed")) if isinstance(retention, dict) else bool(retention),
                      "errors": [(e.get("code") or e.get("message") or str(e)) if isinstance(e, dict) else str(e)
                                 for e in ((retention.get("errors") or []) if isinstance(retention, dict) else [])][:6]},
        "grades": [g["overall"] for g in scores], "grade_mean": mean,
        "grade_notes": [g.get("notes", "") for g in scores],
    }
    result["passed"] = (result["storyboard"]["passed"] and result["claims"]["passed"] and result["dossier"]["passed"]
                        and result["retention"]["passed"] and mean is not None and mean >= GRADE_BAR)
    return result


# --- install -------------------------------------------------------------------------------

def stamp_opening(script: dict) -> None:
    """Stamp the opening turn on this exact narration so resume does not re-read and revise it."""
    import opening_turn as ot
    if not script.get("_opening_contract") or not ot.script_rule(script):
        return
    turn = ot.measure_script(script)
    turn["digest"] = ot.window_digest(script.get("scenes") or [])
    turn["revised"] = False
    script["_opening_turn"] = turn


def install(job: str, state: dict, style_mode: str = "") -> str:
    """Write _state.json for --resume; set the failure file aside so resume cannot restore it."""
    script = state["script"]
    stamp_opening(script)
    failure = failure_file(job)
    if failure:
        os.replace(failure, failure + ".rescued.bak")
    payload = {"script": script, "style_mode": state.get("style_mode") or style_mode or script.get("style_mode", ""),
               "short_grade": state.get("short_grade"), "video_format": state.get("video_format") or "landscape"}
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    json.dump(payload, open(os.path.join(job, f"_state.rescue_{stamp}.json"), "w"), indent=1)
    json.dump(payload, open(os.path.join(job, "_state.json"), "w"), indent=1)
    return os.path.join(job, "_state.json")


# --- report --------------------------------------------------------------------------------

def report_text(failed: dict) -> str:
    script, rep = failed["script"], failed["report"]
    # The storyboard reports its errors as "CODE: message" strings; the ledger as dicts.
    errors = [e if isinstance(e, dict) else {"code": str(e).split(":", 1)[0], "message": str(e).split(":", 1)[-1].strip()}
              for e in rep.get("errors") or []]
    by_scene = {}
    for e in errors:
        by_scene.setdefault(e.get("scene") or "", []).append(e)
    g = script.get("_grade") or {}
    lines = [f"Failed at: {failed['stage']} ({os.path.basename(failed['source'])})",
             f"Grade: {g.get('overall')} {json.dumps(g.get('scores') or {})} weakest={g.get('weakest')}",
             f"Grader notes: {g.get('notes', '')}", "", "Errors:"]
    lines += [f"  [{e.get('severity', '')}] {e.get('code')} {e.get('scene')}: {e.get('message', '')[:300]}"
              + (f"\n      supported core: {e['supported_core']}" if e.get("supported_core") else "")
              for e in errors] or ["  (none recorded)"]
    lines += ["", "Scenes (beat, role, words) — '!' marks a scene with an error:"]
    for i, s in enumerate(script.get("scenes") or []):
        bid = s.get("beat_id") or s.get("scene_id")
        mark = "!" if bid in by_scene else " "
        ev = (s.get("event") or {}).get("text", "") if isinstance(s.get("event"), dict) else ""
        lines.append(f"{mark}{i:02d} {bid} [{s.get('_role') or s.get('story_role')}] ({len(s['narration'].split())}w) {s['narration']}")
        if mark == "!":
            lines.append(f"      event: {ev[:260]}")
    lines += ["", "Revise, don't rewrite: fix each error and the grader's named lines with the smallest edit. "
              f"At most {MAX_ROUNDS} rounds; then propose an outline for approval."]
    return "\n".join(lines)


# --- CLI -----------------------------------------------------------------------------------

def _question(script: dict) -> str:
    return script.get("title") or (script.get("_story_contract") or {}).get("title_promise") or ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report"); r.add_argument("job")
    a = sub.add_parser("apply"); a.add_argument("job"); a.add_argument("edits"); a.add_argument("--out", required=True)
    a.add_argument("--from-state", default="", help="revise this state file instead of the failure (a later round)")
    c = sub.add_parser("check"); c.add_argument("job"); c.add_argument("state"); c.add_argument("--grades", type=int, default=3)
    d = sub.add_parser("diff"); d.add_argument("job"); d.add_argument("state")
    i = sub.add_parser("install"); i.add_argument("job"); i.add_argument("state")
    args = ap.parse_args(argv)
    os.chdir(ROOT)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.expanduser("~/ai-video-gen-local"), ".env"))   # credentials live only here
    load_dotenv(os.path.join(ROOT, ".env"))
    os.environ.update({k: v for k, v in launch_flags(args.job).items() if k not in os.environ})
    failed = load_failed(args.job) if args.cmd != "install" else None

    if args.cmd == "report":
        print(report_text(failed))
        import illustrated_story as ist
        sb = ist.build_storyboard(copy.deepcopy(failed["script"]), _question(failed["script"]))
        print("\nStoryboard:", "PASS" if sb["validation"]["passed"] else "FAIL")
        for e in sb["validation"]["errors"]:
            print("  ERR", e[:300])
        return 0
    if args.cmd == "apply":
        base = json.load(open(args.from_state))["script"] if args.from_state else failed["script"]
        script, notes = apply_edits(base, json.load(open(args.edits)))
        rebind(script)
        state = {"script": script, "style_mode": script.get("style_mode", ""), "short_grade": None,
                 "video_format": "landscape"}
        json.dump(state, open(args.out, "w"), indent=1)
        n = record_round(args.job, notes, args.out)
        print("\n".join(notes))
        print(f"\nround {n} of {MAX_ROUNDS} -> {args.out}")
        if n >= MAX_ROUNDS:
            print("Last round: if the gates still fail, stop and propose a restructure as an outline for approval.")
        return 0
    state = json.load(open(args.state))
    if args.cmd == "diff":
        print(diff_text(narration_diff(failed["script"], state["script"])))
        return 0
    if args.cmd == "check":
        res = run_gates(state["script"], _question(state["script"]), args.grades)
        for k in ("storyboard", "claims", "dossier", "retention"):
            print(f"{k:<10} {'PASS' if res[k]['passed'] else 'FAIL'}", *(res[k].get("errors") or [])[:6], sep="\n  ")
        print(f"grades     {res['grades']} mean {res['grade_mean']} (bar {GRADE_BAR})")
        for n in res["grade_notes"]:
            print("  note:", n[:300])
        print("ALL PASS" if res["passed"] else "NOT YET")
        return 0 if res["passed"] else 1
    if args.cmd == "install":
        path = install(args.job, state)
        print(f"installed {path}\nresume with: {resume_command(args.job)}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
