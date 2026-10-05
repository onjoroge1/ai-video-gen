"""Score a delivered illustrated film across every dimension the lane measures.

One report, deterministic, no model calls. Each section scores 0-100 from checks that already
exist somewhere in the pipeline or were added after a measured defect, so a number here is
traceable to a thing that went wrong on a real film.

    python3 scripts/audit_film.py jobs/<id> [--baseline jobs/<other>] [--json out.json]

Sections: script (repeats, cold open, runtime, claims), imagery (palette arc, cut-to-cut
change, shot grammar), audio (loudness, silence), structure (rendered contract, readiness,
cadence), packaging (title, description, thumbnail).
"""
from __future__ import annotations

import argparse
import colorsys
import glob
import json
import math
import os
import re
import statistics
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Measured on the three delivered films, for context in the report.
BASELINE = {"hue_sd": 4.6, "cut_delta": 16.7, "close_ratio": 0.12, "avg_view_pct": 0.14}


def _text(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _circular_sd(hues: list) -> float:
    if len(hues) < 2:
        return 0.0
    xs = [math.cos(math.radians(h)) for h in hues]
    ys = [math.sin(math.radians(h)) for h in hues]
    r = math.hypot(sum(xs) / len(hues), sum(ys) / len(hues))
    return 180.0 if r <= 1e-9 else math.degrees(math.sqrt(max(0.0, -2.0 * math.log(min(1.0, r)))))


def _frame_stats(path: str) -> dict:
    from PIL import Image
    im = Image.open(path).convert("RGB").resize((48, 27))
    px = list(im.getdata())
    n = len(px)
    r, g, b = (sum(p[i] for p in px) / n for i in range(3))
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return {"hue": h * 360, "sat": s, "lum": l, "rgb": (r, g, b)}


def _section(name: str, checks: list) -> dict:
    """checks: list of (label, passed, detail, weight)."""
    total = sum(w for _, _, _, w in checks) or 1
    got = sum(w for _, ok, _, w in checks if ok)
    return {"name": name, "score": round(100 * got / total),
            "checks": [{"check": c, "pass": bool(ok), "detail": d} for c, ok, d, _ in checks]}


def audit_script(job: str) -> dict:
    import explainer_pipeline as ep
    import causal_story as cs
    from runtime_planner import estimate_narration_seconds
    state_path = os.path.join(job, "_state.json")
    if not os.path.isfile(state_path):
        return {"name": "Script", "score": 0, "checks": [], "note": "no _state.json"}
    script = json.load(open(state_path, encoding="utf-8"))["script"]
    scenes = script.get("scenes") or []
    dupes = ep.duplicate_narration(scenes)
    words = sum(len(_text(s.get("narration")).split()) for s in scenes)
    est = estimate_narration_seconds([{"narration": _text(s.get("narration"))} for s in scenes])
    manifest = {}
    mpath = os.path.join(job, "generation_manifest.json")
    if os.path.isfile(mpath):
        manifest = json.load(open(mpath, encoding="utf-8"))
    target = float(manifest.get("duration_sec") or manifest.get("target_seconds") or 300)
    cold = _text(script.get("_cold_open"))
    first = _text(scenes[0].get("narration")) if scenes else ""
    grade = (script.get("_grade") or {}).get("overall")
    cited = sum(1 for s in scenes if s.get("claim_refs"))
    meta = [i + 1 for i, s in enumerate(scenes)
            if re.search(r"in this video|explained like|as we saw|let'?s dive", _text(s.get("narration")), re.I)]
    hooklen = len(_text(script.get("hook")).split())
    return _section("Script", [
        ("no repeated scenes", not dupes, f"{len(dupes)} repeat pair(s)", 3),
        ("cold open spoken in scene 1", bool(cold) and cold.rstrip(".!?").casefold() in first.casefold(),
         (cold[:70] or "none"), 2),
        ("runtime within 15% of target", abs(est - target) <= 0.15 * target,
         f"{est:.0f}s for {target:.0f}s ({words} words)", 3),
        ("hook within budget", 0 < hooklen <= cs.MAX_HOOK_WORDS, f"{hooklen} words", 1),
        ("most scenes cite a claim", cited >= 0.7 * max(1, len(scenes)),
         f"{cited}/{len(scenes)} scenes cited", 2),
        ("no meta narration", not meta, f"scenes {meta}" if meta else "none", 1),
        ("engagement grade at or above 70", bool(grade) and grade >= 70,
         f"{grade}/100" if grade is not None else "ungraded", 2),
    ])


def audit_imagery(job: str, film: str) -> dict:
    import illustrated_story as lane
    frames_dir = os.path.join(job, "rendered_gate_frames_full")
    paths = sorted(glob.glob(os.path.join(frames_dir, "*.jpg")))
    if not paths and os.path.isfile(film):
        tmp = os.path.join(job, "_audit_frames")
        os.makedirs(tmp, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", film, "-vf", "fps=1/3",
                        os.path.join(tmp, "f_%04d.jpg")], check=True)
        paths = sorted(glob.glob(os.path.join(tmp, "*.jpg")))
    if not paths:
        return {"name": "Imagery", "score": 0, "checks": [], "note": "no frames"}
    stats = [_frame_stats(p) for p in paths]
    hues = [s["hue"] for s in stats if s["sat"] >= 0.08]
    sd = _circular_sd(hues)
    sectors = len({int(h % 360 // 30) for h in hues})
    deltas = [sum(abs(a - b) for a, b in zip(stats[i]["rgb"], stats[i + 1]["rgb"])) / 3
              for i in range(len(stats) - 1)]
    mean_delta = statistics.mean(deltas) if deltas else 0.0
    # The flattest run of consecutive frames, and where it sits.
    win = min(10, max(2, len(deltas) // 6))
    flat, flat_at = mean_delta, 0.0
    for i in range(max(0, len(deltas) - win)):
        m = statistics.mean(deltas[i:i + win])
        if m < flat:
            flat, flat_at = m, i / max(1, len(deltas))
    opening = statistics.mean(deltas[:max(1, len(deltas) // 5)]) if deltas else 0.0
    sats = [s["sat"] for s in stats]
    state_path = os.path.join(job, "_state.json")
    scenes = (json.load(open(state_path, encoding="utf-8"))["script"]["scenes"]
              if os.path.isfile(state_path) else [])
    grammar = lane.shot_grammar_report(scenes) if scenes else {"passed": False, "fails": ["no plan"],
                                                               "close_ratio": 0, "wide_ratio": 0,
                                                               "longest_wide_run": 0}
    return _section("Imagery", [
        ("palette arc moves (circular hue SD >= 40 deg)", sd >= 40,
         f"{sd:.1f} deg (films measured {BASELINE['hue_sd']})", 3),
        ("hue occupies >= 4 of 12 sectors", sectors >= 4, f"{sectors}/12", 2),
        ("cut-to-cut change >= 24", mean_delta >= 24,
         f"{mean_delta:.1f} (films measured {BASELINE['cut_delta']})", 3),
        ("opening is not the flattest part", opening >= mean_delta * 0.9,
         f"opening {opening:.1f} vs film {mean_delta:.1f}", 2),
        ("no dead stretch (flattest window >= 8)", flat >= 8,
         f"{flat:.1f} at {flat_at:.0%} through", 2),
        ("saturation range is wide", (max(sats) - min(sats)) >= 0.25,
         f"{min(sats):.2f}-{max(sats):.2f}", 1),
        ("shot grammar passes", grammar["passed"],
         f"close {grammar.get('close_ratio', 0):.0%}, wide {grammar.get('wide_ratio', 0):.0%}, "
         f"longest wide run {grammar.get('longest_wide_run', 0)}"
         + ("; " + "; ".join(grammar["fails"]) if grammar.get("fails") else ""), 3),
    ])


def audit_audio(film: str) -> dict:
    if not os.path.isfile(film):
        return {"name": "Audio", "score": 0, "checks": [], "note": "no film"}
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", film, "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    if not len(x):
        return {"name": "Audio", "score": 0, "checks": [], "note": "no audio"}
    n = len(x) // 800
    segs = x[:n * 800].reshape(n, -1)
    rms = 20 * np.log10(np.sqrt(np.mean(segs ** 2, axis=1)) + 1e-9)
    silence = float(np.mean(rms < -45))
    overall = 20 * math.log10(float(np.sqrt(np.mean(x ** 2))) + 1e-9)
    peak = 20 * math.log10(float(np.max(np.abs(x))) + 1e-9)
    return _section("Audio", [
        ("loudness in range", -20 <= overall <= -10, f"{overall:.1f} dBFS RMS", 2),
        ("no clipping", peak <= -0.5, f"peak {peak:.1f} dBFS", 1),
        ("silence under 14%", silence <= 0.14, f"{silence:.1%}", 2),
    ])


def audit_structure(job: str) -> dict:
    def load(name):
        p = os.path.join(job, name)
        return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}
    contract = load("rendered_contract_full.json") or load("rendered_contract.json")
    readiness = load("retention_readiness.json")
    det = (contract.get("inspection") or {}).get("deterministic") or {}
    hard = contract.get("hard_failures") or []
    return _section("Structure", [
        ("rendered contract passes", not hard and (contract.get("score") or 0) >= 85,
         f"{contract.get('score')}/100 {contract.get('status', '')}"
         + (f"; {hard}" if hard else ""), 3),
        ("no long visual hold", not det.get("long_hold_count"),
         f"{det.get('long_hold_count', '?')} holds over ceiling, max {det.get('max_visual_state_sec', '?')}s", 2),
        ("cadence in band", 1.8 <= float(det.get("average_visual_state_sec") or 99) <= 3.2,
         f"avg state {det.get('average_visual_state_sec', '?')}s over {det.get('shot_count', '?')} shots", 2),
        ("retention readiness at or above 80", (readiness.get("score") or 0) >= 80,
         f"{readiness.get('score', '?')}/100 {readiness.get('grade', '')}", 2),
        ("every cut verified", float(det.get("per_cut_verification_ratio") or 0) >= 0.95,
         f"{det.get('per_cut_verification_ratio', '?')}", 1),
    ])


def audit_packaging(job: str) -> dict:
    desc_path = os.path.join(job, "description.txt")
    desc = open(desc_path, encoding="utf-8").read() if os.path.isfile(desc_path) else ""
    state_path = os.path.join(job, "_state.json")
    title = ""
    if os.path.isfile(state_path):
        title = _text(json.load(open(state_path, encoding="utf-8"))["script"].get("title"))
    meta = re.search(r"optimi[sz]ed layout|rank for key search|drive viewer engagement", desc, re.I)
    tags = next((l for l in desc.splitlines() if l.lower().startswith("tags:")), "")
    tag_list = [t.strip() for t in tags.split(":", 1)[-1].split(",") if t.strip()] if tags else []
    return _section("Packaging", [
        ("title within 100 chars", 0 < len(title) <= 100, f"{len(title)}: {title[:60]}", 1),
        ("description has chapters", "CHAPTERS" in desc, "yes" if "CHAPTERS" in desc else "missing", 2),
        ("description has sources", "SOURCES" in desc, "yes" if "SOURCES" in desc else "missing", 2),
        ("no leaked model preamble", not meta, meta.group(0) if meta else "clean", 2),
        ("tags present and API-safe", bool(tag_list) and all(len(t) <= 30 for t in tag_list),
         f"{len(tag_list)} tags, longest {max((len(t) for t in tag_list), default=0)}", 1),
        ("thumbnail exists", os.path.isfile(os.path.join(job, "thumbnail.jpg")), "", 1),
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job")
    ap.add_argument("--film", default="explainer.mp4")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    job = os.path.abspath(args.job)
    film = os.path.join(job, args.film)
    sections = [audit_script(job), audit_imagery(job, film), audit_audio(film),
                audit_structure(job), audit_packaging(job)]
    overall = round(statistics.mean(s["score"] for s in sections))
    print(f"\n{'=' * 78}\nAUDIT  {os.path.basename(job)}   OVERALL {overall}/100\n{'=' * 78}")
    for sec in sections:
        print(f"\n{sec['name']:11} {sec['score']:3}/100" + (f"   ({sec['note']})" if sec.get("note") else ""))
        for c in sec["checks"]:
            print(f"   {'PASS' if c['pass'] else 'FAIL'}  {c['check']:44} {c['detail'][:70]}")
    failures = [f"{s['name']}: {c['check']}" for s in sections for c in s["checks"] if not c["pass"]]
    print(f"\n{len(failures)} failing check(s)")
    out = {"job": job, "overall": overall, "sections": sections, "failures": failures}
    if args.json:
        json.dump(out, open(args.json, "w"), indent=1)
        print("wrote", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
