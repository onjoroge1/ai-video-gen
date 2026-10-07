"""Score a delivered illustrated film across every dimension the lane measures.

One report, deterministic, no model calls. Each section scores 0-100 from checks that already
exist somewhere in the pipeline or were added after a measured defect, so a number here is
traceable to a thing that went wrong on a real film.

    python3 scripts/audit_film.py jobs/<id> [--baseline jobs/<other>] [--json out.json]

Sections: script (repeats, cold open, runtime, claims), imagery (palette arc, cut-to-cut
change, shot grammar), audio (loudness, peak headroom, clipping, silence), structure (rendered
contract, readiness, cadence), packaging (title, description, thumbnail).

A check is UNGRADED (printed N/A, `pass: null` in the JSON) when the thing it measures is not on
disk for THIS film: a contract that describes the first-minute preview, shot sizes that would come
from a _state.json a later attempt overwrote, 3 s frame samples standing in for cuts. An ungraded
check counts toward neither the section total nor the failures, so a missing input reads as
"not measured", never as a pass or a fail.
"""
from __future__ import annotations

import argparse
import colorsys
import glob
import hashlib
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

# The hook floor the pipeline's degraded reason uses (explainer_pipeline: "hook scores N/100 against
# the 70 contract"). accept_v4 imports it so the two scripts cannot disagree again (it said 68).
HOOK_FLOOR = 70

# The master is encoded after loudnorm I=-12:TP=-1 (explainer_pipeline._assemble), so a sample peak
# above -0.5 dBFS is drift from that target, not a clip: killerbees02 peaks at -0.21 dBFS with zero
# clipped samples. Clipping proper is a run of consecutive samples pinned at or above -0.1 dBFS.
PEAK_HEADROOM_DBFS = -0.5
CLIP_LEVEL_DBFS = -0.1
MASTER_TRUE_PEAK_DBTP = -1


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


_SHA_CACHE: dict = {}


def _file_sha256(path: str) -> str:
    """sha256 of a file, or '' when it is absent. Cached on (path, size, mtime): the imagery and
    structure sections both ask which contract describes the film, and the film is ~115 MB."""
    try:
        st = os.stat(path)
    except OSError:
        return ""
    key = (os.path.abspath(path), st.st_size, int(st.st_mtime))
    if key not in _SHA_CACHE:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        _SHA_CACHE[key] = digest.hexdigest()
    return _SHA_CACHE[key]


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
    """checks: list of (label, passed, detail, weight); passed None means ungraded, which leaves
    the check out of the total rather than scoring it either way. info: lines printed above."""
    graded = [c for c in checks if c[1] is not None]
    total = sum(w for _, _, _, w in graded) or 1
    got = sum(w for _, ok, _, w in graded if ok)
    return {"name": name, "score": round(100 * got / total), "info": list(info or []),
            "checks": [{"check": c, "pass": None if ok is None else bool(ok), "detail": d}
                       for c, ok, d, _ in checks]}


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


def _film_duration(job: str, film: str) -> tuple:
    """(seconds, source) of the film itself: ffprobe on the mp4, else run_result.json's
    duration_sec (the frozen delivery snapshot keeps that file), else (0.0, '')."""
    if os.path.isfile(film):
        try:
            out = subprocess.run([_binary("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                                  "-of", "csv=p=0", film], capture_output=True, text=True, timeout=30).stdout
            sec = float(out.strip())
            if sec > 0:
                return sec, "ffprobe"
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    try:
        sec = float(_load_json(os.path.join(job, "run_result.json")).get("duration_sec") or 0)
    except (TypeError, ValueError):
        sec = 0.0
    return (sec, "run_result.json duration_sec") if sec > 0 else (0.0, "")


def _runtime_target(job: str, script: dict | None) -> tuple:
    """(seconds, source) the run was asked for.

    generation_manifest.json carries neither duration_sec nor target_seconds, so the old
    `manifest.get(...) or 300` was the literal 300 on every film. The request IS on disk, in these
    places, read in this order; the music spec's duration comes last because the bed is sized to
    the target rather than being the target.
    """
    script = script if isinstance(script, dict) else {}

    def sub(obj, key):
        return obj.get(key) if isinstance(obj, dict) else None

    manifest = _load_json(os.path.join(job, "generation_manifest.json"))
    candidates = [
        (sub(script.get("_runtime_plan"), "target_seconds"),
         "_state.json script._runtime_plan.target_seconds"),
        (sub(script.get("_story_contract"), "target_runtime_sec"),
         "_state.json script._story_contract.target_runtime_sec"),
        (_load_json(os.path.join(job, "audio_timing_report.json")).get("target_seconds"),
         "audio_timing_report.json target_seconds"),
        (sub(_load_json(os.path.join(job, "retention_report.json")).get("contract"), "target_runtime_sec"),
         "retention_report.json contract.target_runtime_sec"),
        (sub(sub(manifest.get("music"), "spec"), "duration_sec"),
         "generation_manifest.json music.spec.duration_sec"),
    ]
    for value, source in candidates:
        try:
            sec = float(value)
        except (TypeError, ValueError):
            continue
        if sec > 0:
            return sec, source
    return 300.0, "default (no target on disk)"


def _runtime_check(job: str, film: str, script: dict | None, scenes: list, info: list):
    """The runtime check tuple, graded on the FILM's duration, or None when nothing measures it.

    The old check compared the narration estimate with the target and never looked at the mp4;
    the estimate stays in the detail, labelled, because the gap between it and the film is itself
    informative (killerbees02: 155 s estimated, 179 s delivered).
    """
    target, source = _runtime_target(job, script)
    dur, dur_src = _film_duration(job, film)
    info.append(f"runtime target {target:.0f}s from {source}")
    est, words, est_detail = 0.0, 0, ""
    if scenes:
        from runtime_planner import estimate_narration_seconds
        words = sum(len(_text(s.get("narration")).split()) for s in scenes)
        est = estimate_narration_seconds([{"narration": _text(s.get("narration"))} for s in scenes])
        est_detail = f"; narration estimate {est:.0f}s ({words} words)"
    if dur > 0:
        return ("runtime within 15% of target", abs(dur - target) <= 0.15 * target,
                f"film {dur:.0f}s vs {target:.0f}s target ({dur_src}){est_detail}", 3)
    if scenes:
        return ("runtime within 15% of target", abs(est - target) <= 0.15 * target,
                f"narration estimate {est:.0f}s vs {target:.0f}s target ({words} words); "
                "no film duration on disk", 3)
    return None


def audit_script(job: str, film: str = "", stale: str | None = None) -> dict:
    import explainer_pipeline as ep
    import causal_story as cs
    src = _script_sources(job)
    info = []
    if stale is None:
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
        hp.register_people(_load_json(os.path.join(job, "research_dossier.json")) or {})
        hook_score = hp.score_hook(hook)["score"]
    except Exception:
        pass
    hook_checks = [
        ("hook within budget", 0 < hooklen <= cs.MAX_HOOK_WORDS, f"{hooklen} words", 1),
        ("hook carries the opening devices", hook_score >= HOOK_FLOOR, f"{hook_score}/100", 2),
    ]
    script = src["script"]
    if script is None:
        # A frozen delivery snapshot keeps run_result.json but not _state.json. Grade what the film's
        # own record carries -- the hook, and the runtime from the mp4 or run_result.json -- and say
        # what was skipped, rather than returning a bare 0.
        runtime = _runtime_check(job, film, None, [], info)
        checks = (hook_checks if hook else []) + ([runtime] if runtime else [])
        sec = _section("Script", checks, info)
        sec["note"] = ("no _state.json; scene checks skipped" + ("" if hook else "; no hook on record")
                       + ("" if runtime else "; no film duration on disk"))
        return sec
    scenes = script.get("scenes") or []
    dupes = ep.duplicate_narration(scenes)
    runtime = _runtime_check(job, film, script, scenes, info)
    manifest = _load_json(os.path.join(job, "generation_manifest.json"))
    cold = _text(script.get("_cold_open"))
    first = _text(scenes[0].get("narration")) if scenes else ""
    grade = (script.get("_grade") or {}).get("overall")
    cited = sum(1 for s in scenes if s.get("claim_refs"))
    meta = [i + 1 for i, s in enumerate(scenes)
            if re.search(r"in this video|explained like|as we saw|let'?s dive", _text(s.get("narration")), re.I)]
    # Did this film actually come from the scene template? The manifest records the slot plan.
    used_template = bool(script.get("_template_slots") or manifest.get("story_template"))
    checks = [
        ("no repeated scenes", not dupes, f"{len(dupes)} repeat pair(s)", 3),
        ("cold open spoken in scene 1", bool(cold) and cold.rstrip(".!?").casefold() in first.casefold(),
         (cold[:70] or "none"), 2),
        runtime,
        hook_checks[0],
        ("most scenes cite a claim", cited >= 0.7 * max(1, len(scenes)),
         f"{cited}/{len(scenes)} scenes cited", 2),
        ("no meta narration", not meta, f"scenes {meta}" if meta else "none", 1),
        ("engagement grade at or above 70", bool(grade) and grade >= 70,
         f"{grade}/100" if grade is not None else "ungraded", 2),
        hook_checks[1],
        ("built from the scene template", used_template, "yes" if used_template else "no", 1),
    ]
    return _section("Script", [c for c in checks if c], info)


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


def _contract_for_film(job: str, film: str) -> dict:
    """The rendered contract whose inspection describes THIS film, plus notes on any that do not.

    rendered_contract.json is the first-minute preview's gate: its inspection.video_path is
    first_minute_preview.mp4 (23 shots against the film's 57 on bees_c), and the plain fallback to
    it graded the preview's cadence and holds as the film's. Each candidate is matched on
    inspection.video_sha256 against the film's bytes, else on basename(video_path); a contract that
    names neither is assumed to be the film's and the assumption is printed.

    Returns {"contract", "name", "identity", "notes"}; contract is {} when none describes the film.
    """
    film_sha = _file_sha256(film) if film else ""
    film_name = os.path.basename(film) if film else "the film"
    notes = []
    for name in ("rendered_contract_full.json", "rendered_contract.json"):
        contract = _load_json(os.path.join(job, name))
        if not contract:
            continue
        insp = contract.get("inspection") if isinstance(contract.get("inspection"), dict) else {}
        sha, path = _text(insp.get("video_sha256")), os.path.basename(_text(insp.get("video_path")))
        if sha and film_sha:
            ok, how = sha == film_sha, "matched by sha256"
        elif path and film:
            ok, how = path == film_name, "matched by basename"
        else:
            ok, how = True, "assumed: the contract names no video"
            notes.append(f"{name} names no video; assumed to describe {film_name}")
        if ok:
            return {"contract": contract, "name": name, "identity": how, "notes": notes}
        described = path or f"sha {sha[:12]}"
        if sha and film_sha:
            described += f" (sha {sha[:12]}, film {film_sha[:12]})"
        notes.append(f"{name} describes {described}, not this {film_name}; its cadence/hold numbers "
                     "are not the film's")
    return {"contract": {}, "name": "", "identity": "", "notes": notes}


def _contract_frames(contract: dict) -> dict:
    """inspection.frames of one contract, by frame basename."""
    frames = ((contract.get("inspection") or {}).get("frames")) or []
    frames = [f for f in frames if isinstance(f, dict) and f.get("frame_path")]
    return {os.path.basename(str(f["frame_path"])): f for f in frames}


def _time_positions(paths: list, meta: dict) -> tuple:
    """(positions, timed): each frame's position as a fraction of runtime when the contract's
    timing covers every frame (timed=True), else its share of the frame sequence (timed=False).
    The caller must say which it printed; "of runtime" on frame-index shares was a false label."""
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
        return [t / total for t in times], True
    n = max(1, len(paths) - 1)
    return [i / n for i in range(len(paths))], False


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


def _shot_grammar(job: str, sel: dict, meta: dict, stale: str, info: list) -> tuple:
    """(report or None, detail when ungraded). Shot sizes for the grammar check, from the source
    that belongs to the film.

    The contract's frames belong to the film by sha, so when they carry a shot size per shot they
    win. Today they carry story_role and kind but no shot_type, so that path is latent until the
    gate records one, and the sizes come from _state.json script.scenes -- which describes the LAST
    attempt in the dir: bees_c graded a 14-scene failed attempt's grammar for a 13-scene film. The
    staleness computed once in main gates that read, and so does a scene count that disagrees with
    the film's own contract.
    """
    import illustrated_story as lane

    def start(rec):
        try:
            return float(rec.get("global_start_sec"))
        except (TypeError, ValueError):
            return math.inf

    # One frame record per shot (killerbees02: 100 frames, 100 mids, shot_count 100), in play order.
    # The gate's shot_index restarts at 0 in every scene, so keying on it folded 20 scenes into one.
    shots = sorted(meta.values(), key=start)
    film_scenes = len({r.get("scene_index") for r in shots if r.get("scene_index") is not None})
    if shots and all(_text(r.get("shot_type")) for r in shots):
        info.append(f"shot sizes from {sel['name']} inspection.frames ({len(shots)} shots)")
        return lane.shot_grammar_report(
            [{"shot_type": r["shot_type"], "story_role": r.get("story_role")} for r in shots]), ""
    if stale:
        info.append("WARNING " + stale)
        return None, "not graded: shot sizes would come from a _state.json newer than the film"
    state = _load_json(os.path.join(job, "_state.json"))
    script = state.get("script") if isinstance(state.get("script"), dict) else {}
    scenes = script.get("scenes") or []
    if not scenes:
        return None, "not graded: no scene plan on disk"
    if film_scenes and film_scenes != len(scenes):
        return None, (f"not graded: _state.json has {len(scenes)} scenes but the film's contract "
                      f"shows {film_scenes}")
    info.append(f"shot sizes from _state.json script.scenes ({len(scenes)} scenes)")
    return lane.shot_grammar_report(scenes), ""


def audit_imagery(job: str, film: str, stale: str = "") -> dict:
    info = []
    sampled = False
    paths = _time_ordered_mid_frames(os.path.join(job, "rendered_gate_frames_full"))
    if paths:
        info.append(f"frames: {len(paths)} shot mid-frames from rendered_gate_frames_full, in shot order")
    elif os.path.isfile(film):
        tmp = os.path.join(job, "_audit_frames")
        os.makedirs(tmp, exist_ok=True)
        # ffmpeg -y overwrites f_0001.. upward but never deletes, so a shorter film audited after a
        # longer one in the same dir inherited the longer film's higher-numbered frames. Clear first.
        for old in glob.glob(os.path.join(tmp, "*.jp*g")):
            os.remove(old)
        subprocess.run([_binary("ffmpeg"), "-y", "-loglevel", "error", "-i", film, "-vf", "fps=1/3",
                        os.path.join(tmp, "f_%04d.jpg")], check=True)
        paths = _numeric_order(glob.glob(os.path.join(tmp, "*.jpg")))
        sampled = True
        info.append(f"frames: {len(paths)} sampled 1 per 3 s from {os.path.basename(film)} "
                    "(no rendered_gate_frames_full, so deltas are 3 s steps rather than cuts)")
    if not paths:
        return {"name": "Imagery", "score": 0, "checks": [], "note": "no frames", "info": info}
    sel = _contract_for_film(job, film)
    info.extend(sel["notes"])
    meta = _contract_frames(sel["contract"])
    stats = [_frame_stats(p) for p in paths]
    hues = [s["hue"] for s in stats if s["sat"] >= 0.08]
    sd = _circular_sd(hues)
    sectors = len({int(h % 360 // 30) for h in hues})
    deltas = [sum(abs(a - b) for a, b in zip(stats[i]["rgb"], stats[i + 1]["rgb"])) / 3
              for i in range(len(stats) - 1)]
    mean_delta = statistics.mean(deltas) if deltas else 0.0
    pos, timed = _time_positions(paths, meta)
    # The flattest run of consecutive cuts: where it sits in the runtime, and which shots it is.
    flat, i0, i1 = _flattest_window(deltas, mean_delta)
    shots = [_shot_index(p) for p in paths]
    where = (f"shots {shots[i0]}-{shots[i1]}" if None not in (shots[i0], shots[i1])
             else f"frames {i0}-{i1}")
    if timed:
        flat_detail = f"{flat:.1f} at {pos[i0]:.0%}-{pos[i1]:.0%} of runtime ({where})"
    else:
        flat_detail = (f"{flat:.1f} at {pos[i0]:.0%}-{pos[i1]:.0%} ({where}); positions are "
                       "frame-index shares (no contract timing)")
    # Within- vs across-scene change, when the contract says which scene each mid frame belongs to.
    scene = [(meta.get(os.path.basename(p)) or {}).get("scene_index") for p in paths]
    if deltas and all(s is not None for s in scene):
        within = [d for d, a, b in zip(deltas, scene, scene[1:]) if a == b]
        across = [d for d, a, b in zip(deltas, scene, scene[1:]) if a != b]
        info.append(f"mean |dRGB| within-scene {statistics.mean(within) if within else 0.0:.1f} "
                    f"(n={len(within)}; delivered film 13.3, n=44)")
        info.append(f"mean |dRGB| across-scene {statistics.mean(across) if across else 0.0:.1f} "
                    f"(n={len(across)}; delivered film 33.0, n=12) -- informational pending a calibration decision")
    else:
        info.append("mean |dRGB| within-scene / across-scene: n/a (no scene_index on frames)")
    opening = statistics.mean(deltas[:max(1, len(deltas) // 5)]) if deltas else 0.0
    sats = [s["sat"] for s in stats]
    grammar, grammar_note = _shot_grammar(job, sel, meta, stale, info)
    return _section("Imagery", [
        ("palette arc moves (circular hue SD >= 40 deg)", sd >= 40,
         f"{sd:.1f} deg (films measured {BASELINE['hue_sd']})", 3),
        ("hue occupies >= 4 of 12 sectors", sectors >= 4, f"{sectors}/12", 2),
        # Re-baselines slightly: deltas now run between consecutive shot mids in time order rather
        # than between files in name order (the delivered film: 16.3 filename order -> ~17.5 time
        # order). The within/across-scene split printed above is informational pending a
        # calibration decision; this single threshold is still the check. On 3 s samples the label
        # is false -- a step inside a held shot is not a cut -- so the number prints ungraded.
        ("cut-to-cut change >= 24", None if sampled else mean_delta >= 24,
         f"{mean_delta:.1f} (films measured {BASELINE['cut_delta']})"
         + ("; 3 s steps, not cuts: ungraded" if sampled else ""), 3),
        ("opening is not the flattest part", opening >= mean_delta * 0.9,
         f"opening {opening:.1f} vs film {mean_delta:.1f}", 2),
        ("no dead stretch (flattest window >= 8)", flat >= 8, flat_detail, 2),
        ("saturation range is wide", (max(sats) - min(sats)) >= 0.25,
         f"{min(sats):.2f}-{max(sats):.2f}", 1),
        ("shot grammar passes", grammar["passed"] if grammar else None,
         grammar_note if grammar is None else
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


def _clip_runs(x, level_dbfs: float = CLIP_LEVEL_DBFS) -> tuple:
    """(runs, longest, hot): runs of 2+ consecutive samples at or above `level_dbfs` on one channel,
    the longest such run, and how many samples sit at or above the level at all.

    A waveform that merely peaks near full scale spends one sample there; one that was cut off sits
    there for a run. So the clipping verdict is on runs, and the lone hot sample is reported but is
    the headroom check's business.
    """
    import numpy as np
    hot = np.abs(x) >= 10 ** (level_dbfs / 20)
    runs, longest = 0, 0
    for ch in range(hot.shape[1]):
        col = hot[:, ch].astype(np.int8)
        if not col.any():
            continue
        edges = np.diff(np.concatenate(([0], col, [0])))
        lengths = np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)
        runs += int(np.sum(lengths >= 2))
        longest = max(longest, int(lengths.max()))
    return runs, longest, int(hot.sum())


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
    runs, longest, hot = _clip_runs(x)
    mid = x.mean(axis=1) if channels > 1 else x[:, 0]
    seg = max(1, rate // 20)  # 50 ms windows, as the 800-sample windows were at 16 kHz
    n = len(mid) // seg
    rms = (20 * np.log10(np.sqrt(np.mean(mid[: n * seg].reshape(n, seg) ** 2, axis=1)) + 1e-9)
           if n else np.zeros(0))
    silence = float(np.mean(rms < -45)) if n else 0.0
    overall = 20 * math.log10(float(np.sqrt(np.mean(mid ** 2))) + 1e-9)
    # The -0.5 dBFS line was labelled "no clipping" and failed killerbees02 at a peak of -0.21 dBFS
    # with zero clipped samples. It is a headroom rule against the master's -1 dBTP loudnorm target
    # (worth keeping: it catches drift from that target), so it is named as one, and clipping is
    # measured separately as runs of samples pinned at or above -0.1 dBFS.
    return _section("Audio", [
        ("loudness in range", -20 <= overall <= -10, f"{overall:.1f} dBFS RMS", 2),
        (f"peak headroom (sample peak <= {PEAK_HEADROOM_DBFS} dBFS)", peak <= PEAK_HEADROOM_DBFS,
         f"peak {peak:.1f} dBFS sample peak; master targets {MASTER_TRUE_PEAK_DBTP} dBTP", 1),
        (f"no clipping (no run of samples >= {CLIP_LEVEL_DBFS} dBFS)", runs == 0,
         f"{runs} run(s) of 2+ samples at/above {CLIP_LEVEL_DBFS} dBFS, longest {longest}; "
         f"{hot} such sample(s)", 1),
        ("silence under 14%", silence <= 0.14, f"{silence:.1%}", 2),
    ], [f"{channels} ch @ {rate} Hz decoded natively; peak over every channel, RMS on 0.5*(L+R)"])


def audit_structure(job: str, film: str = "") -> dict:
    sel = _contract_for_film(job, film)
    contract, info = sel["contract"], list(sel["notes"])
    readiness = _load_json(os.path.join(job, "retention_readiness.json"))
    det = (contract.get("inspection") or {}).get("deterministic") or {}
    hard = contract.get("hard_failures") or []
    # The old label "rendered contract passes" printed PASS on a contract whose own verdict was
    # passed:false, publishable:false (bees_c: 87/100 AUTOMATED_PASS_AWAITING_HUMAN). The check
    # tests the score and the hard-failure list, so it is named for that, and the contract's own
    # verdict travels with it.
    review = contract.get("human_review") if isinstance(contract.get("human_review"), dict) else {}
    verdict = ""
    if contract:
        verdict = (f"passed={contract.get('passed')} publishable={contract.get('publishable')} "
                   f"review={review.get('status') or 'unrecorded'}")
        info.append(f"contract verdict: {contract.get('score')}/100 {contract.get('status', '')}; {verdict} "
                    f"({sel['name']} for {os.path.basename(film) or 'the film'}, {sel['identity']})")
    absent = "no rendered contract describes this film"

    def graded(ok):
        return None if not contract else ok

    def detail(text):
        return text if contract else absent

    return _section("Structure", [
        ("contract score >= 85 with no hard failures", graded(not hard and (contract.get("score") or 0) >= 85),
         detail(f"{contract.get('score')}/100 {contract.get('status', '')}"
                + (f"; hard {','.join(map(str, hard))}" if hard else "") + f"; {verdict}"), 3),
        ("no long visual hold", graded(not det.get("long_hold_count")),
         detail(f"{det.get('long_hold_count', '?')} holds over ceiling, max {det.get('max_visual_state_sec', '?')}s"), 2),
        ("cadence in band", graded(1.8 <= float(det.get("average_visual_state_sec") or 99) <= 3.2),
         detail(f"avg state {det.get('average_visual_state_sec', '?')}s over {det.get('shot_count', '?')} shots"), 2),
        ("retention readiness at or above 80", (readiness.get("score") or 0) >= 80,
         f"{readiness.get('score', '?')}/100 {readiness.get('grade', '')}", 2),
        ("every cut verified", graded(float(det.get("per_cut_verification_ratio") or 0) >= 0.95),
         detail(f"{det.get('per_cut_verification_ratio', '?')}"), 1),
    ], info)


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
    # Staleness is decided once, against the film being audited, and every section that reads
    # _state.json is told the same answer.
    stale = _state_staleness(job, film)
    sections = [audit_script(job, film, stale), audit_imagery(job, film, stale), audit_audio(film),
                audit_structure(job, film), audit_packaging(job)]
    overall = round(statistics.mean(s["score"] for s in sections))
    print(f"\n{'=' * 78}\nAUDIT  {os.path.basename(job)}   OVERALL {overall}/100\n{'=' * 78}")
    for sec in sections:
        print(f"\n{sec['name']:11} {sec['score']:3}/100" + (f"   ({sec['note']})" if sec.get("note") else ""))
        for line in sec.get("info") or []:
            print(f"   {line}")
        for c in sec["checks"]:
            mark = "N/A " if c["pass"] is None else ("PASS" if c["pass"] else "FAIL")
            print(f"   {mark}  {c['check']:46} {c['detail'][:120]}")
    failures = [f"{s['name']}: {c['check']}" for s in sections for c in s["checks"] if c["pass"] is False]
    ungraded = sum(1 for s in sections for c in s["checks"] if c["pass"] is None)
    print(f"\n{len(failures)} failing check(s)" + (f", {ungraded} ungraded" if ungraded else ""))
    out = {"job": job, "overall": overall, "sections": sections, "failures": failures}
    if args.json:
        json.dump(out, open(args.json, "w"), indent=1)
        print("wrote", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
