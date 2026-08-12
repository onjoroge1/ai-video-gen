"""Retention grader: measure what a file can prove, refuse to guess the rest.

THE RUBRIC HAS TWO KINDS OF CATEGORY AND THEY MUST NOT BLEND.

Roughly 55 of the rubric's 120 points are properties of the FILE -- cadence, motion, dead air,
black frames, loudness, whether the first frame carries a readable subject. Those are computed
here, from measurements this repo already trusts (video_audit gates, build_report cuts).

The other ~65 points -- hook clarity, curiosity, propulsion, explanation order, payoff -- are
properties of a VIEWER'S EXPERIENCE. The 48/100 external review caught a mountain goat, a
premise-shaped hook and an unearned payoff while every mechanical gate was green. A model or a
formula scoring "curiosity: 7/10" from pixels would be the exact failure this repo keeps finding
in its own gates: a check that guesses, laundering opinion into a green number. So the judged
section is a STRUCTURED FORM that stays empty until a human or an external review fills it in,
and the composite score refuses to exist until both halves do.

WHY PERSIST JUDGED SCORES: once a video ships, hook% and held% arrive from the platform. Stored
next to the rubric, a few videos are enough to see which categories actually PREDICT retention --
then the weights stop being taste. That closes the loop the finished-videos tab was built for.
"""
from __future__ import annotations
import json
import os
import subprocess

import numpy as np

# ---------------------------------------------------------------- rubric definition
# (key, weight, measured?, what it grades)
RUBRIC = [
    ("first_frame",     8,  True,  "subject readable and striking in frame one"),
    ("hook_clarity",   10,  False, "premise understood within 1-3 seconds"),
    ("curiosity",      10,  False, "viewer holds a specific question they want answered"),
    ("propulsion",     15,  False, "each beat creates a reason to watch the next"),
    ("explanation",    10,  False, "things are introduced before they matter"),
    ("visual_relevance", 10, False, "every image illustrates the narration at that moment"),
    ("visual_energy",  10,  True,  "motion, composition change, absence of prolonged stills"),
    ("credibility",     7,  False, "AI artifacts, anatomy, character consistency"),
    ("pacing",          8,  True,  "dead air, repetition, rushed narration"),
    ("audio",           5,  True,  "loudness, rhythm, intelligibility"),
    ("payoff",          5,  False, "answers the question the hook promised"),
    ("ending_loop",     2,  True,  "ends decisively or loops to the open"),
]
MEASURED_TOTAL = sum(w for _, w, m, _ in RUBRIC if m)      # 33
JUDGED_TOTAL = sum(w for _, w, m, _ in RUBRIC if not m)    # 57


def _motion_series(path, w=480, h=854):
    """Per-frame PEAK delta, matching spec.gap_gate (480x854 -- coarse decodes blur thin rain into stillness)'s definition of 'still' exactly. The first
    version used mean delta, which is a second, stricter definition of the same word -- it scored a
    reveal-animated diagram as frozen while the gap gate passed it, and two gates disagreeing about
    what 'still' means is precisely the kind of drift this repo documents elsewhere."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf",
                          f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    a = np.frombuffer(out, dtype=np.uint8)
    fr = a[:len(a) // (w * h) * (w * h)].reshape(-1, h, w).astype(np.float32)
    return np.abs(np.diff(fr, axis=0)).max(axis=(1, 2)), fr


def grade_measured(video, build_report=None, fps=30):
    """The measured half. Every number here is traceable to pixels or the build report."""
    d, frames = _motion_series(video)
    dur = (len(d) + 1) / fps
    rep = json.load(open(build_report)) if build_report and os.path.exists(build_report) else {}
    cuts = [c["t"] for c in rep.get("cuts", [])]
    out, notes = {}, {}

    # --- first_frame (8): a readable first frame has contrast structure and is not dark or blank.
    # This measures STRIKING, not SUBJECT -- whether frame one shows the right thing is judgment.
    f0 = frames[0]
    contrast = float(f0.std())
    luma = float(f0.mean())
    s = 8.0
    if contrast < 28:
        s -= 3; notes["first_frame"] = f"flat first frame (std {contrast:.0f})"
    if not 25 <= luma <= 215:
        s -= 3; notes["first_frame"] = f"first frame too dark/bright (luma {luma:.0f})"
    out["first_frame"] = max(0.0, s)

    # --- visual_energy (10): fraction of frames moving + worst static run + cut cadence.
    moving = float((d > 30).mean())
    worst_still = 0
    cur = 0
    for m in (d <= 30):
        cur = cur + 1 if m else 0
        worst_still = max(worst_still, cur)
    worst_s = worst_still / fps
    mean_shot = dur / max(len(cuts), 1)
    s = 10.0
    if moving < 0.85:
        s -= min(4, (0.85 - moving) * 20)
    if worst_s > 1.0:
        s -= min(4, worst_s - 1.0)
    if mean_shot > 4.0:
        s -= 2
    notes["visual_energy"] = (f"{moving*100:.0f}% frames moving, worst still {worst_s:.1f}s, "
                              f"mean shot {mean_shot:.1f}s")
    out["visual_energy"] = max(0.0, s)

    # --- pacing (8): dead air in the AUDIO (silence while the video runs) + black frames.
    sil = subprocess.run(["ffmpeg", "-v", "info", "-i", video, "-af",
                          "silencedetect=noise=-38dB:d=0.9", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    dead = sil.count("silence_start")
    blk = subprocess.run(["ffmpeg", "-v", "info", "-i", video, "-vf",
                          "blackdetect=d=0.02:pix_th=0.08", "-an", "-f", "null", "-"],
                         capture_output=True, text=True).stderr.count("blackdetect")
    s = 8.0 - min(4, dead * 1.0) - min(4, blk * 0.5)
    notes["pacing"] = f"{dead} silent gaps >0.9s, {blk} black-frame events"
    out["pacing"] = max(0.0, s)

    # --- audio (5): integrated loudness near the -14 LUFS target, true peak under -1.
    ln = subprocess.run(["ffmpeg", "-v", "info", "-i", video, "-af",
                         "loudnorm=print_format=json", "-f", "null", "-"],
                        capture_output=True, text=True).stderr
    s = 5.0
    try:
        j = json.loads(ln[ln.rindex("{"):ln.rindex("}") + 1])
        lufs, tp = float(j["input_i"]), float(j["input_tp"])
        if abs(lufs + 14) > 2.5:
            s -= 2
        if tp > -0.5:
            s -= 1
        notes["audio"] = f"{lufs:.1f} LUFS, peak {tp:.1f} dBTP"
    except Exception:
        s = 2.5
        notes["audio"] = "loudness unreadable"
    out["audio"] = max(0.0, s)

    # --- ending_loop (2): the close must not be the longest-held still in the video, and a loop
    # bonus when the last second resembles the first (Shorts replay).
    tail = d[-int(2 * fps):]
    s = 2.0 if float((tail > 30).mean()) > 0.5 else 1.0
    sim01 = float(np.abs(frames[-1] - frames[0]).mean())
    if sim01 < 18:
        notes["ending_loop"] = f"loops visually (first/last diff {sim01:.0f})"
    out["ending_loop"] = s

    got = sum(out.values())
    return {"scores": out, "notes": notes, "measured_points": round(got, 1),
            "measured_max": MEASURED_TOTAL,
            "duration_s": round(dur, 2), "cuts": len(cuts)}


def judged_form():
    """The judgment half, as a form. Fill from a human watch or an external review -- never
    from a formula. Each entry: score 0..weight, plus the observation that justifies it."""
    return {k: {"weight": w, "grades": g, "score": None, "evidence": ""}
            for k, w, m, g in RUBRIC if not m}


def composite(measured, judged):
    """Total out of 90 (33 measured + 57 judged). None until every judged score exists --
    a partial rubric published as a number is how a 48/100 video looks like a 75."""
    missing = [k for k, v in judged.items() if v.get("score") is None]
    if missing:
        return {"total": None, "missing": missing}
    j = sum(v["score"] for v in judged.values())
    return {"total": round(measured["measured_points"] + j, 1),
            "measured": measured["measured_points"], "judged": j,
            "max": MEASURED_TOTAL + JUDGED_TOTAL}


def report(measured):
    L = [f"MEASURED {measured['measured_points']}/{measured['measured_max']}  "
         f"({measured['duration_s']}s, {measured['cuts']} cuts)"]
    for k, v in measured["scores"].items():
        L.append(f"  {k:14s} {v:4.1f}  {measured['notes'].get(k, '')}")
    L.append(f"  judged categories ({JUDGED_TOTAL} pts) require a viewer -- see judged_form()")
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    v = sys.argv[1] if len(sys.argv) > 1 else "renders/survives_the_fall/survives_the_fall.mp4"
    br = os.path.join(os.path.dirname(v), "build_report.json")
    print(report(grade_measured(v, br)))
