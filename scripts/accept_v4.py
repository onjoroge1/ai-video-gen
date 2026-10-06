#!/usr/bin/env python3
"""Does a delivered film meet the five things the operator asked for?

The audit in scripts/audit_film.py scores quality on five axes. This is narrower and blunter:
the four defects reported against the shipped killer bees film, plus the ~300 second runtime,
each as a single pass/fail with the measured number beside it. It exists because three of those
four defects were visible in the delivered artifact and none was caught before upload.

The hook and title are read the way the audit reads them (audit_film._script_sources: run_result.json
first, _state.json second) and the hook floor is the audit's HOOK_FLOOR, so the two scripts cannot
disagree about the film's opening again: this one said 68 and read _state.json while the audit and
the pipeline's degraded reason said 70 and read run_result.json.

    python3 scripts/accept_v4.py jobs/bees_a
"""
from __future__ import annotations

import base64
import json
import math
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:                                   # the API keys live in .env, not the shell
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

from scripts import audit_film  # noqa: E402  shared: hook/title sources, staleness, the hook floor


# Measured by THIS function on the delivered films, so the delta is like for like. An earlier
# 4.6-degree figure for "the delivered film" is quoted elsewhere in this project; it came from a
# different sample (scene images, not frames) and does not reproduce here, so it is not used as a
# baseline. V1 at 20.1 is the film the operator said had not improved.
_BASELINE_HUE = {"killerbees01": 20.1, "killerbees02": 36.4}


def _load(path):
    try:
        with open(path) as handle:
            return json.load(handle)
    except Exception:
        return {}


def _duration(mp4: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", mp4], capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def _hue_spread(paths: list) -> float:
    """Circular standard deviation of mean hue, in degrees.

    Linear stdev is wrong on a hue wheel: a run split between red at 2 deg and red at 358 deg
    reads as maximally varied. The delivered film measured 4.6 degrees -- eight scenes of the
    same ivory -- against 82.2 on the plate palette in isolation.
    """
    from PIL import Image
    angles = []
    for path in paths:
        try:
            img = Image.open(path).convert("HSV").resize((64, 64))
            px = list(img.getdata())
            sat = [p for p in px if p[1] > 40]
            if not sat:
                continue
            xs = sum(math.cos(p[0] / 255.0 * 2 * math.pi) for p in sat) / len(sat)
            ys = sum(math.sin(p[0] / 255.0 * 2 * math.pi) for p in sat) / len(sat)
            angles.append(math.atan2(ys, xs))
        except Exception:
            continue
    if len(angles) < 2:
        return 0.0
    xs = sum(math.cos(a) for a in angles) / len(angles)
    ys = sum(math.sin(a) for a in angles) / len(angles)
    r = max(1e-9, min(1.0, math.hypot(xs, ys)))
    return math.degrees(math.sqrt(max(0.0, -2.0 * math.log(r))))


def _film_frames(mp4: str, job: str, every: int = 12) -> list:
    """One frame every `every` seconds, written beside the film. What the viewer actually sees."""
    out_dir = os.path.join(job, "_accept_frames")
    os.makedirs(out_dir, exist_ok=True)
    for stale in os.listdir(out_dir):
        try:
            os.remove(os.path.join(out_dir, stale))
        except OSError:
            pass
    subprocess.run(["ffmpeg", "-v", "error", "-i", mp4, "-vf", f"fps=1/{every},scale=160:-1",
                    os.path.join(out_dir, "f_%03d.png")], capture_output=True)
    return sorted(os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.endswith(".png"))


def _ring_count(thumb: str) -> int | None:
    """How many crossed-out circles a viewer sees. One is the design; two was the complaint."""
    try:
        import explainer_pipeline as ep
        with open(thumb, "rb") as handle:
            b64 = base64.b64encode(handle.read()).decode()
        rsp = ep._claude().messages.create(
            model=ep.ANTHROPIC_MODEL, max_tokens=100,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": b64}},
                {"type": "text", "text":
                    "Count the prohibition symbols in this thumbnail: red or black circles, "
                    "rings or oval outlines used to cross something out, each usually with a "
                    "diagonal slash. Round objects belonging to the scene (a sun, a plate, a "
                    "honeycomb cell) do not count. "
                    'Return ONLY JSON: {"count": <integer>}.'}]}])
        out, _ = ep._parse_script_json(rsp.content[0].text)
        return int(out["count"]) if isinstance(out, dict) and "count" in out else None
    except Exception:
        return None


def main(job: str) -> int:
    import hook_patterns
    import illustrated_story

    # run_result.json is written once by the attempt that produced the film; _state.json is
    # rewritten by every attempt in the dir, so the scenes below may describe a later one. The
    # staleness test is the audit's, against the same film, and each row that reads the scenes
    # says so when it fires.
    src = audit_film._script_sources(job)
    script = src["script"] or {}
    manifest = _load(os.path.join(job, "generation_manifest.json"))
    board = _load(os.path.join(job, "illustrated_storyboard.json"))
    scenes = script.get("scenes") or []
    mp4 = os.path.join(job, "explainer.mp4")
    stale = audit_film._state_staleness(job, mp4)
    state_note = " (from a _state.json newer than the film)" if stale else ""
    rows = []

    # 1 --- the template, and the runtime it was sized for
    seconds = _duration(mp4) if os.path.exists(mp4) else 0.0
    rows.append(("runtime ~300s", 270 <= seconds <= 330, f"{seconds:.0f}s"))
    rows.append(("built from the scene template", bool(manifest.get("story_template")),
                 f"story_template={manifest.get('story_template')!r}"))
    per = seconds / max(1, len(scenes))
    rows.append(("scene length matches the template", len(scenes) >= 16 and 10 <= per <= 22,
                 f"{len(scenes)} scenes, {per:.1f}s each{state_note}"))

    # 2 --- the hook, as it went out with the film
    hook = src["hook"]
    graded = hook_patterns.score_hook(hook)
    devices = [d for d, ok in graded["patterns"].items() if ok]
    rows.append(("hook puts the viewer in it", graded["patterns"]["viewer_present"],
                 f"second person {'present' if graded['patterns']['viewer_present'] else 'ABSENT'}"))
    rows.append(("hook withholds the outcome", graded["patterns"]["outcome_withheld"], ""))
    rows.append(("hook is not an institution", graded["patterns"]["no_institution"], ""))
    rows.append((f"hook scores >= {audit_film.HOOK_FLOOR} ({graded['score']}/100)",
                 graded["score"] >= audit_film.HOOK_FLOOR, ", ".join(devices)))
    rows.append(("hook within 18 words", graded["words"] <= 18, f"{graded['words']} words"))

    # 3 --- the imagery, SAMPLED FROM THE FILM
    # Measuring jobs/<job>/images measures every candidate the run ever generated -- 93 files for a
    # 20-scene film -- including rejects and evidence frames that never reach the screen. It scored
    # the delivered film at 56.6 degrees while the film the operator watched measured 4.6. The only
    # honest sample is the frames a viewer actually sees.
    frames = _film_frames(mp4, job) if os.path.exists(mp4) else []
    spread = _hue_spread(frames)
    rows.append(("palette varies across scenes", spread >= 25.0,
                 f"hue SD {spread:.1f} deg over {len(frames)} sampled frames "
                 f"(same measure: V1 {_BASELINE_HUE['killerbees01']}, "
                 f"V2 {_BASELINE_HUE['killerbees02']})"))
    # SHOT SIZE LIVES ON THE SCRIPT SCENES, not on the storyboard beats. Reading the beats
    # reported 0% close-ups for a film that is 55% close-ups, which would have been published as
    # "the imagery never improved" -- the exact claim this script exists to settle.
    graded_scenes = [sc for sc in scenes if sc.get("shot_type")]
    grammar = illustrated_story.shot_grammar_report(
        graded_scenes or [b for b in (board.get("beats") or []) if b.get("shot_type")] or scenes)
    close = grammar.get("close_ratio", 0.0)
    wide = grammar.get("wide_ratio", 0.0)
    rows.append(("close-ups carry the film", close >= 0.40, f"{close:.0%} close{state_note}"))
    rows.append(("wides are rationed", wide <= 0.28, f"{wide:.0%} wide{state_note}"))

    # 4 --- the thumbnail
    thumb = os.path.join(job, "thumbnail.jpg")
    count = _ring_count(thumb) if os.path.exists(thumb) else None
    rows.append(("thumbnail has exactly one crossed-out circle", count == 1,
                 "could not check" if count is None else f"{count} counted"))

    width = max(len(name) for name, _, _ in rows)
    print(f"\nACCEPTANCE — {job}\n" + "=" * (width + 30))
    if stale:
        print(f"  WARNING  {stale}")
    for name, ok, note in rows:
        print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {note}")
    failed = [name for name, ok, _ in rows if not ok]
    print("=" * (width + 30))
    print(f"  {len(rows) - len(failed)}/{len(rows)} met" + (f"; FAILING: {'; '.join(failed)}" if failed else ""))
    print(f"  hook: {hook!r} (from {src['hook_from'] or 'nowhere on disk'})")
    print(f"  title: {src['title']!r} (from {src['title_from'] or 'nowhere on disk'})\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "jobs/bees_a"))
