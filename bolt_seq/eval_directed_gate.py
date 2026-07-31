"""OFFLINE gate validation for directed_video (run BEFORE any paid spend). Synthesizes deterministic
motion controls, collects known-bad real clips, defines a positive control, evaluates each against a
single HERO spec ("Bolt must move RIGHT, on-model, sufficient motion, no reversal/disappearance"),
and writes a confusion matrix. Paid generation must not be enabled until the false-positive rate on the
known-failure set is ZERO. No video is generated here — this is VLM/ffmpeg evaluation only.
Run: python3 -m bolt_seq.eval_directed_gate"""
import os, sys, json, subprocess
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C, scene_graph as SG, effects as FX
from bolt_seq.providers import directed_video as DV

OUT = os.path.join(PROJ, "renders", "bolt_seq", "_directed_gate_eval"); os.makedirs(OUT, exist_ok=True)
BOLT = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/bolt_swim.png")   # clean magenta-keyed cutout


def _replacement_img():
    """An UNAMBIGUOUSLY non-Bolt object (solid red blob) for the mutation control — the oxygen hub.png
    turned out to contain a Bolt-like figure, so it wasn't a valid swap target."""
    from PIL import Image, ImageDraw
    p = os.path.join(OUT, "_notbolt_red.png")
    if not os.path.exists(p):
        img = Image.new("RGBA", (600, 600), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
        d.ellipse([60, 60, 540, 540], fill=(220, 30, 30, 255), outline=(255, 180, 0, 255), width=24)
        d.rectangle([250, 250, 350, 350], fill=(255, 240, 0, 255))
        img.save(p)
    return p


NOTBOLT = _replacement_img()                                                       # a NON-Bolt object (mutation)
PLATE = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/tunnel.png")
IDENT = ("the mascot robot Bolt: rounded matte-white body, mint-green accents, glossy black visor with two "
         "glowing cyan eyes and NO mouth, single hover-base, thin antenna")


def _env():
    return {"id": "env", "kind": "environment", "provider": "deterministic_2d", "z": 0, "base_h": 1920,
            "image": PLATE, "authored": ["x"], "tracks": {"scale": SG.const_track(1.05)}}


def _bolt(tracks, image=BOLT):
    return {"id": "bolt", "kind": "character", "provider": "deterministic_2d", "z": 50, "base_h": 720,
            "image": image, "tracks": tracks}


def synth(kind):
    out = os.path.join(OUT, f"synth_{kind}.mp4")
    if os.path.exists(out):
        return out
    env = _env()
    if kind == "right":
        ents = [env, _bolt({"x": SG.track([(0, 0.2), (1, 0.8)]), "y": SG.const_track(0.5)})]
    elif kind == "left":
        ents = [env, _bolt({"x": SG.track([(0, 0.8), (1, 0.2)]), "y": SG.const_track(0.5)})]
    elif kind == "up":
        ents = [env, _bolt({"x": SG.const_track(0.5), "y": SG.track([(0, 0.8), (1, 0.2)])})]
    elif kind == "down":
        ents = [env, _bolt({"x": SG.const_track(0.5), "y": SG.track([(0, 0.2), (1, 0.8)])})]
    elif kind == "stationary":
        ents = [env, _bolt({"x": SG.const_track(0.5), "y": SG.const_track(0.5)})]
    elif kind == "reverse":
        ents = [env, _bolt({"x": SG.track([(0, 0.2), (0.5, 0.8), (1, 0.2)]), "y": SG.const_track(0.5)})]
    elif kind == "movingbg":                      # background pans right; hero stays put
        env["tracks"]["x"] = SG.track([(0, 0.0), (1, 0.95)])
        ents = [env, _bolt({"x": SG.const_track(0.5), "y": SG.const_track(0.5)})]
    elif kind == "disappearing":
        ents = [env, _bolt({"x": SG.track([(0, 0.3), (1, 0.7)]), "y": SG.const_track(0.5),
                            "opacity": SG.track([(0, 1), (0.6, 1), (0.8, 0), (1, 0)])})]
    elif kind == "mutation":                      # Bolt (fades out) → a NON-Bolt object (fades in)
        b = _bolt({"x": SG.track([(0, 0.2), (1, 0.8)]), "y": SG.const_track(0.5),
                   "opacity": SG.track([(0, 1), (0.4, 1), (0.6, 0), (1, 0)])})
        other = {"id": "other", "kind": "prop", "provider": "deterministic_2d", "z": 51, "base_h": 720,
                 "image": NOTBOLT, "tracks": {"x": SG.track([(0, 0.2), (1, 0.8)]), "y": SG.const_track(0.5),
                 "opacity": SG.track([(0, 0), (0.4, 0), (0.6, 1), (1, 1)])}}
        ents = [env, b, other]
    else:
        raise ValueError(kind)
    C.render_scene_block(out, ents, 5.0, tmp_dir=OUT, draw_fn=FX.draw)
    return out


HERO_SPEC = {
    "entity": "bolt", "block": "eval", "identity_bible": IDENT,
    "motion_direction": "right", "motion_axis": "horizontal",
    "prohibited_events": ["bolt_reverses", "identity_change", "mutation", "character_swap"],
    "boundary": {},
}

# (name, builder, expected_verdict, set)
def build_cases():
    cases = []
    for k, exp in [("right", "pass"), ("left", "fail"), ("up", "fail"), ("down", "fail"),
                   ("stationary", "fail"), ("reverse", "fail"), ("movingbg", "fail"),
                   ("disappearing", "fail"), ("mutation", "fail")]:
        cases.append((f"synth_{k}", synth(k), exp, "synthetic" if k != "right" else "positive"))
    # vertical animatics → trim a 5s HERO segment so the gate judges CONTENT (not just over-length)
    verticals = [
        ("real_cloud_sticker_v2", "renders/bolt_cloud_experiment_package/phase2/cloud_animatic_v2.mp4", 0.15),
        ("real_cloud_landing", "renders/bolt_seq/cloud_landing/cloud_landing_animatic.mp4", 0.10),
        ("real_oxygen", "renders/bolt_seq/oxygen_subscription/oxygen_subscription_animatic.mp4", 0.45),
        ("real_gravity_degraded", "renders/bolt_seq/what_if_gravity_doubled_for_ten_seconds/what_if_gravity_doubled_for_ten_seconds_animatic.mp4", 0.30),
    ]
    for name, p, frac in verticals:
        if os.path.exists(p):
            cases.append((name, _seg(p, name, frac), "fail", "known_bad"))
    # a REAL generated i2v clip left at its native (landscape) shape — tests the technical gate on real video
    sun = "renders/sun_1pct_heavier_v2/i2v/scene_00.mp4"
    if os.path.exists(sun):
        cases.append(("real_kling_i2v_sun_landscape", sun, "fail", "known_bad"))
    return cases


def _seg(clip, name, start_frac):
    out = os.path.join(OUT, f"seg_{name}.mp4")
    if os.path.exists(out):
        return out
    dur = C.dur(clip); ss = max(0, min(dur - 5.0, dur * start_frac))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{ss:.2f}", "-i", clip, "-t", "5",
                    "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30",
                    "-an", out], check=True)
    return out


def main():
    cost = []
    cases = build_cases()
    print(f"evaluating {len(cases)} clips against HERO_SPEC (must move RIGHT, on-model)...", flush=True)
    rows = []
    for name, clip, expected, group in cases:
        ev = DV.evaluate_candidate(clip, HERO_SPEC, gates=DV.DEFAULT_GATES, cost=cost, log=lambda *_: None)
        actual = "pass" if ev["pass"] else "fail"
        rows.append({"name": name, "group": group, "expected": expected, "actual": actual,
                     "ok": expected == actual, "reasons": ev["reasons"],
                     "direction": ev.get("trajectory", {}).get("direction"),
                     "displacement": ev.get("trajectory", {}).get("displacement"),
                     "reversals": ev.get("trajectory", {}).get("reversals"),
                     "flow": ev.get("flow", {}).get("direction"),
                     "scores": {k: ev.get("scores", {}).get(k) for k in ("identity", "slop", "semantic")}})
        print(f"  {name:26} exp={expected:4} act={actual:4} {'OK' if expected==actual else 'MISMATCH'} "
              f"| dir={rows[-1]['direction']} disp={rows[-1]['displacement']} flow={rows[-1]['flow']} "
              f"| {ev['reasons'][:2]}", flush=True)

    known_fail = [r for r in rows if r["expected"] == "fail"]
    fp = [r for r in known_fail if r["actual"] == "pass"]        # bad clip that PASSED (dangerous)
    fn = [r for r in rows if r["expected"] == "pass" and r["actual"] == "fail"]  # good clip rejected
    matrix = {
        "n": len(rows), "true_fail": sum(1 for r in known_fail if r["actual"] == "fail"),
        "false_positive": len(fp), "false_positive_names": [r["name"] for r in fp],
        "false_negative": len(fn), "false_negative_names": [r["name"] for r in fn],
        "false_positive_rate_known_fail": round(len(fp) / max(1, len(known_fail)), 3),
        "safe_to_enable_paid": len(fp) == 0, "rows": rows, "cost_usd": round(sum(cost), 3),
    }
    json.dump(matrix, open(os.path.join(OUT, "confusion_matrix.json"), "w"), indent=2, default=str)
    md = ["# directed_video offline gate — confusion matrix", "",
          f"- clips: {matrix['n']} · known-fail correctly rejected: {matrix['true_fail']}/{len(known_fail)}",
          f"- **false positives (bad clip passed): {matrix['false_positive']}** {matrix['false_positive_names']}",
          f"- false negatives (good clip rejected): {matrix['false_negative']} {matrix['false_negative_names']}",
          f"- **SAFE TO ENABLE PAID: {matrix['safe_to_enable_paid']}** (requires FP=0 on known-fail)",
          f"- eval cost (VLM only, no video gen): ${matrix['cost_usd']}", "",
          "| clip | group | expected | actual | dir | disp | flow | reasons |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['name']} | {r['group']} | {r['expected']} | {r['actual']} | {r['direction']} | "
                  f"{r['displacement']} | {r['flow']} | {'; '.join(r['reasons'][:2]) or 'accepted'} |")
    open(os.path.join(OUT, "confusion_matrix.md"), "w").write("\n".join(md))
    print(f"\nFALSE POSITIVES (known-bad that passed): {matrix['false_positive']} → SAFE_TO_ENABLE_PAID={matrix['safe_to_enable_paid']}")
    print(f"cost ${matrix['cost_usd']} | report: {OUT}/confusion_matrix.md")


if __name__ == "__main__":
    main()
