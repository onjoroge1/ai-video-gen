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

# Measured on the three delivered films, for context in the report. cut_delta was taken in filename
# order (cut_* pairs, then shot_* mids); audit_imagery now walks the shot mids in time order, which
# reads a little higher (the delivered bees film: 16.3 filename order -> ~17.5 time order).
BASELINE = {"hue_sd": 4.6, "cut_delta": 16.7, "close_ratio": 0.12, "avg_view_pct": 0.14}


def _text(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _load_json(path: str) -> dict:
    """A JSON object from disk, or {} when the file is absent, unreadable or not an object."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _binary(name: str) -> str:
    """ffmpeg/ffprobe through media_binaries (bundled builds included), else trust PATH."""
    try:
        import media_binaries
        return media_binaries.require(name)
    except Exception:
        return name


def _circular_sd(hues: list) -> float:
    if len(hues) < 2:
        return 0.0
    xs = [math.cos(math.radians(h)) for h in hues]
    ys = [math.sin(math.radians(h)) for h in hues]
    r = math.hypot(sum(xs) / len(hues), sum(ys) / len(hues))
    return 180.0 if r <= 1e-9 else math.degrees(math.sqrt(max(0.0, -2.0 * math.log(min(1.0, r)))))


def _frame_stats(path: str) -> dict:
    from PIL import Image, ImageStat
    im = Image.open(path).convert("RGB").resize((48, 27))
    r, g, b = ImageStat.Stat(im).mean  # per-band means; Image.getdata is deprecated in Pillow 12
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return {"hue": h * 360, "sat": s, "lum": l, "rgb": (r, g, b)}


def _section(name: str, checks: list, info: list | None = None) -> dict:
    """checks: list of (label, passed, detail, weight). info: lines printed above the checks."""
    total = sum(w for _, _, _, w in checks) or 1
    got = sum(w for _, ok, _, w in checks if ok)
    return {"name": name, "score": round(100 * got / total), "info": list(info or []),
            "checks": [{"check": c, "pass": bool(ok), "detail": d} for c, ok, d, _ in checks]}


def _script_sources(job: str) -> dict:
    """Title and hook from run_result.json first, _state.json second, naming the file that supplied each.

    _state.json is rewritten by every attempt that runs in a job dir, so it describes the LAST
    attempt, not the film on disk. On the delivered bees run a later failed attempt overwrote it at
    22:47:55 while explainer.mp4 dates from 22:37:06, and the audit graded that attempt's title and
    script. run_result.json is written once, by the attempt that produced the film, and carries the
    title and hook that actually went out with it.
    """
    result = _load_json(os.path.join(job, "run_result.json"))
    state = _load_json(os.path.join(job, "_state.json"))
    script = state.get("script") if isinstance(state.get("script"), dict) else None
    out = {"script": script, "title": "", "hook": "", "title_from": "", "hook_from": ""}
    for key in ("title", "hook"):
        for name, source in (("run_result.json", result), ("_state.json", script or {})):
            if _text(source.get(key)):
                out[key], out[key + "_from"] = _text(source[key]), name
                break
    return out


def _state_staleness(job: str, film: str) -> str:
    """Warning text when _state.json post-dates the film, else ''.

    The pipeline writes _state.json before it renders, so on a clean run the state file is OLDER
    than explainer.mp4 (killerbees02: 36 minutes older). A state file newer than the film can only
    come from a later attempt in the same dir; the 60 s grace covers same-attempt bookkeeping.
    """
    state_path = os.path.join(job, "_state.json")
    if not (os.path.isfile(state_path) and os.path.isfile(film)):
        return ""
    lag = os.path.getmtime(state_path) - os.path.getmtime(film)
    if lag <= 60:
        return ""
    return (f"_state.json is newer than the film by {lag:.0f}s; script metrics may belong to a "
            "later attempt in this job dir")


def audit_script(job: str, film: str = "") -> dict:
    import explainer_pipeline as ep
    import causal_story as cs
    from runtime_planner import estimate_narration_seconds
    src = _script_sources(job)
    info = []
    stale = _state_staleness(job, film)
    if stale:
        info.append("WARNING " + stale)
    if src["hook_from"]:
        info.append(f"hook from {src['hook_from']}")
    hook = src["hook"]
    hooklen = len(hook.split())
    hook_score = 0
    try:
        import hook_patterns as hp
        hook_score = hp.score_hook(hook)["score"]
    except Exception:
        pass
    hook_checks = [
        ("hook within budget", 0 < hooklen <= cs.MAX_HOOK_WORDS, f"{hooklen} words", 1),
        ("hook carries the opening devices", hook_score >= 70, f"{hook_score}/100", 2),
    ]
    script = src["script"]
    if script is None:
        # A frozen delivery snapshot keeps run_result.json but not _state.json. Grade what the film's
        # own record carries and say what was skipped, rather than returning a bare 0.
        sec = _section("Script", hook_checks if hook else [], info)
        sec["note"] = "no _state.json; scene checks skipped" + ("" if hook else "; no hook on record")
        return sec
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
    # Did this film actually come from the scene template? The manifest records the slot plan.
    used_template = bool(script.get("_template_slots") or manifest.get("story_template"))
    return _section("Script", [
        ("no repeated scenes", not dupes, f"{len(dupes)} repeat pair(s)", 3),
        ("cold open spoken in scene 1", bool(cold) and cold.rstrip(".!?").casefold() in first.casefold(),
         (cold[:70] or "none"), 2),
        ("runtime within 15% of target", abs(est - target) <= 0.15 * target,
         f"{est:.0f}s for {target:.0f}s ({words} words)", 3),
        hook_checks[0],
        ("most scenes cite a claim", cited >= 0.7 * max(1, len(scenes)),
         f"{cited}/{len(scenes)} scenes cited", 2),
        ("no meta narration", not meta, f"scenes {meta}" if meta else "none", 1),
        ("engagement grade at or above 70", bool(grade) and grade >= 70,
         f"{grade}/100" if grade is not None else "ungraded", 2),
        hook_checks[1],
        ("built from the scene template", used_template, "yes" if used_template else "no", 1),
    ], info)


_SHOT_MID = re.compile(r"^shot_(\d+)_mid\.jpe?g$", re.I)


def _numeric_order(paths: list) -> list:
    """Paths sorted by the integers in their basename, so index 9 precedes 10 whatever the padding."""
    def key(path):
        name = os.path.basename(path)
        return [int(t) for t in re.findall(r"\d+", name)] or [0], name
    return sorted(paths, key=key)


def _time_ordered_mid_frames(frames_dir: str) -> list:
    """shot_NNN_mid.jpg paths by shot index: the order the film plays them, and nothing else.

    sorted(glob("*.jpg")) was FILENAME order, and the render gate writes two kinds of frame: the
    delivered bees film had 112 cut_NNN_{after,before}.jpg sorting ahead of its 57 shot_NNN_mid.jpg.
    So its "dead stretch 6.6 at 55%" was filename index 92 = cut_047..cut_052 = the reversal scene
    at ~85-95% of runtime, while the real flattest window (shots 22-33, the escalation at 38-57%)
    read 8.8. The cut pairs are also near-duplicates of the mid frames either side of each cut, so
    they double-weighted the palette statistics; only the mids are measured now.
    """
    mids = [p for p in glob.glob(os.path.join(frames_dir, "*.jp*g"))
            if _SHOT_MID.match(os.path.basename(p))]
    return _numeric_order(mids)


def _shot_index(path: str):
    m = _SHOT_MID.match(os.path.basename(path))
    return int(m.group(1)) if m else None


def _contract_frames(job: str) -> dict:
    """inspection.frames from rendered_contract_full.json (else rendered_contract.json), by frame basename."""
    for name in ("rendered_contract_full.json", "rendered_contract.json"):
        frames = ((_load_json(os.path.join(job, name)).get("inspection") or {}).get("frames")) or []
        frames = [f for f in frames if isinstance(f, dict) and f.get("frame_path")]
        if frames:
            return {os.path.basename(str(f["frame_path"])): f for f in frames}
    return {}


def _time_positions(paths: list, meta: dict) -> list:
    """Each frame's position as a fraction of runtime: the contract's timing when it covers every
    frame, else the frame's share of the sequence."""
    times, total = [], 0.0
    for path in paths:
        rec = meta.get(os.path.basename(path)) or {}
        try:
            start, end = float(rec["global_start_sec"]), float(rec["global_end_sec"])
        except (KeyError, TypeError, ValueError):
            times = []
            break
        times.append(0.5 * (start + end))
        total = max(total, end)
    if times and total > 0:
        return [t / total for t in times]
    n = max(1, len(paths) - 1)
    return [i / n for i in range(len(paths))]


def _flattest_window(deltas: list, ceiling: float) -> tuple:
    """(mean, first frame, last frame) of the flattest run of consecutive cuts below `ceiling`, or
    the whole film when no run is. The window is a sixth of the cuts, clamped to 2..10."""
    if not deltas:
        return 0.0, 0, 0
    win = min(10, max(2, len(deltas) // 6))
    flat, span = ceiling, (0, len(deltas))
    for i in range(len(deltas) - win + 1):
        m = statistics.mean(deltas[i:i + win])
        if m < flat:
            flat, span = m, (i, i + win)
    return flat, span[0], span[1]


def audit_imagery(job: str, film: str) -> dict:
    import illustrated_story as lane
    info = []
    paths = _time_ordered_mid_frames(os.path.join(job, "rendered_gate_frames_full"))
    if paths:
        info.append(f"frames: {len(paths)} shot mid-frames from rendered_gate_frames_full, in shot order")
    elif os.path.isfile(film):
        tmp = os.path.join(job, "_audit_frames")
        os.makedirs(tmp, exist_ok=True)
        subprocess.run([_binary("ffmpeg"), "-y", "-loglevel", "error", "-i", film, "-vf", "fps=1/3",
                        os.path.join(tmp, "f_%04d.jpg")], check=True)
        paths = _numeric_order(glob.glob(os.path.join(tmp, "*.jpg")))
        info.append(f"frames: {len(paths)} sampled 1 per 3 s from {os.path.basename(film)} "
                    "(no rendered_gate_frames_full, so deltas are 3 s steps rather than cuts)")
    if not paths:
        return {"name": "Imagery", "score": 0, "checks": [], "note": "no frames", "info": info}
    stats = [_frame_stats(p) for p in paths]
    hues = [s["hue"] for s in stats if s["sat"] >= 0.08]
    sd = _circular_sd(hues)
    sectors = len({int(h % 360 // 30) for h in hues})
    deltas = [sum(abs(a - b) for a, b in zip(stats[i]["rgb"], stats[i + 1]["rgb"])) / 3
              for i in range(len(stats) - 1)]
    mean_delta = statistics.mean(deltas) if deltas else 0.0
    meta = _contract_frames(job)
    pos = _time_positions(paths, meta)
    # The flattest run of consecutive cuts: where it sits in the runtime, and which shots it is.
    flat, i0, i1 = _flattest_window(deltas, mean_delta)
    shots = [_shot_index(p) for p in paths]
    where = (f"shots {shots[i0]}-{shots[i1]}" if None not in (shots[i0], shots[i1])
             else f"frames {i0}-{i1}")
    flat_detail = f"{flat:.1f} at {pos[i0]:.0%}-{pos[i1]:.0%} of runtime ({where})"
    # Within- vs across-scene change, when the contract says which scene each mid frame belongs to.
    scene = [(meta.get(os.path.basename(p)) or {}).get("scene_index") for p in paths]
    if deltas and all(s is not None for s in scene):
        within = [d for d, a, b in zip(deltas, scene, scene[1:]) if a == b]
        across = [d for d, a, b in zip(deltas, scene, scene[1:]) if a != b]
        info.append(f"mean |dRGB| within-scene {statistics.mean(within) if within else 0.0:.1f} "
                    f"(n={len(within)}; delivered film 13.3, n=44)")
        info.append(f"mean |dRGB| across-scene {statistics.mean(across) if across else 0.0:.1f} "
                    f"(n={len(across)}; delivered film 33.0, n=12) -- informational pending a calibration decision")
    opening = statistics.mean(deltas[:max(1, len(deltas) // 5)]) if deltas else 0.0
    sats = [s["sat"] for s in stats]
    scenes = (_load_json(os.path.join(job, "_state.json")).get("script") or {}).get("scenes") or []
    grammar = lane.shot_grammar_report(scenes) if scenes else {"passed": False, "fails": ["no plan"],
                                                               "close_ratio": 0, "wide_ratio": 0,
                                                               "longest_wide_run": 0}
    return _section("Imagery", [
        ("palette arc moves (circular hue SD >= 40 deg)", sd >= 40,
         f"{sd:.1f} deg (films measured {BASELINE['hue_sd']})", 3),
        ("hue occupies >= 4 of 12 sectors", sectors >= 4, f"{sectors}/12", 2),
        # Re-baselines slightly: deltas now run between consecutive shot mids in time order rather
        # than between files in name order (the delivered film: 16.3 filename order -> ~17.5 time
        # order). The within/across-scene split printed above is informational pending a
        # calibration decision; this single threshold is still the check.
        ("cut-to-cut change >= 24", mean_delta >= 24,
         f"{mean_delta:.1f} (films measured {BASELINE['cut_delta']})", 3),
        ("opening is not the flattest part", opening >= mean_delta * 0.9,
         f"opening {opening:.1f} vs film {mean_delta:.1f}", 2),
        ("no dead stretch (flattest window >= 8)", flat >= 8, flat_detail, 2),
        ("saturation range is wide", (max(sats) - min(sats)) >= 0.25,
         f"{min(sats):.2f}-{max(sats):.2f}", 1),
        ("shot grammar passes", grammar["passed"],
         f"close {grammar.get('close_ratio', 0):.0%}, wide {grammar.get('wide_ratio', 0):.0%}, "
         f"longest wide run {grammar.get('longest_wide_run', 0)}"
         + ("; " + "; ".join(grammar["fails"]) if grammar.get("fails") else ""), 3),
    ], info)


def _audio_layout(film: str) -> tuple:
    """(channels, sample_rate) of the first audio stream, or (0, 0) when ffprobe cannot say."""
    try:
        out = subprocess.run([_binary("ffprobe"), "-v", "error", "-select_streams", "a:0",
                              "-show_entries", "stream=channels,sample_rate", "-of", "json", film],
                             capture_output=True, text=True, timeout=30).stdout
        stream = ((json.loads(out or "{}").get("streams") or [{}])[0]) or {}
        channels, rate = int(stream.get("channels") or 0), int(stream.get("sample_rate") or 0)
        return (channels, rate) if channels > 0 and rate > 0 else (0, 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0, 0


def audit_audio(film: str) -> dict:
    if not os.path.isfile(film):
        return {"name": "Audio", "score": 0, "checks": [], "note": "no film"}
    import numpy as np
    channels, rate = _audio_layout(film)
    # Decode every channel at the native rate. The old "-ac 1 -ar 16000" decode measured
    # libswresample's mono downmix, which for float input is 0.707*L + 0.707*R with no
    # normalisation: on an L/R-correlated master (both delivered masters: correlation 0.999) that
    # reads +3.0 dB high. Measured on the delivered bees film: true peak -0.71 dBFS (astats,
    # volumedetect and ebur128 agree) while the mono decode said +2.3; RMS -15.1 true vs -12.2
    # reported. So "no clipping" failed on every film this project has shipped. The 16 kHz
    # resample is not free either: on killerbees02 it alone moved the stereo peak -0.21 -> -0.74.
    cmd = [_binary("ffmpeg"), "-v", "error", "-i", film, "-vn"]
    if not channels:
        # ffprobe could not describe the stream, so pin a layout the reshape below can trust.
        channels, rate = 2, 16000
        cmd += ["-ac", "2", "-ar", "16000"]
    try:
        raw = subprocess.run(cmd + ["-f", "f32le", "-"], capture_output=True).stdout
    except OSError:
        return {"name": "Audio", "score": 0, "checks": [], "note": "ffmpeg unavailable"}
    x = np.frombuffer(raw, dtype=np.float32)
    x = x[: len(x) // channels * channels].reshape(-1, channels)
    if not len(x):
        return {"name": "Audio", "score": 0, "checks": [], "note": "no audio"}
    # Peak is the loudest sample on ANY channel: that is what clips a DAC. Loudness and the silence
    # fraction are read on the equal-weight fold 0.5*(L+R), which is what a mono listener hears;
    # a 1-channel stream is its own fold.
    peak = 20 * math.log10(float(np.max(np.abs(x))) + 1e-9)
    mid = x.mean(axis=1) if channels > 1 else x[:, 0]
    seg = max(1, rate // 20)  # 50 ms windows, as the 800-sample windows were at 16 kHz
    n = len(mid) // seg
    rms = (20 * np.log10(np.sqrt(np.mean(mid[: n * seg].reshape(n, seg) ** 2, axis=1)) + 1e-9)
           if n else np.zeros(0))
    silence = float(np.mean(rms < -45)) if n else 0.0
    overall = 20 * math.log10(float(np.sqrt(np.mean(mid ** 2))) + 1e-9)
    return _section("Audio", [
        ("loudness in range", -20 <= overall <= -10, f"{overall:.1f} dBFS RMS", 2),
        ("no clipping", peak <= -0.5, f"peak {peak:.1f} dBFS", 1),
        ("silence under 14%", silence <= 0.14, f"{silence:.1%}", 2),
    ], [f"{channels} ch @ {rate} Hz decoded natively; peak over every channel, RMS on 0.5*(L+R)"])


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
    src = _script_sources(job)
    title = src["title"]
    info = [f"title from {src['title_from']}" if src["title_from"]
            else "title: none in run_result.json or _state.json"]
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
    ], info)


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
    sections = [audit_script(job, film), audit_imagery(job, film), audit_audio(film),
                audit_structure(job), audit_packaging(job)]
    overall = round(statistics.mean(s["score"] for s in sections))
    print(f"\n{'=' * 78}\nAUDIT  {os.path.basename(job)}   OVERALL {overall}/100\n{'=' * 78}")
    for sec in sections:
        print(f"\n{sec['name']:11} {sec['score']:3}/100" + (f"   ({sec['note']})" if sec.get("note") else ""))
        for line in sec.get("info") or []:
            print(f"   {line}")
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
