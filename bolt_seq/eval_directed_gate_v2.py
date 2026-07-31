"""CORRECTED offline gate validation (Phase 3A.2) — anatomy + clean-plate + declarative phase motion.
No video generation, no paid spend. Validates the five conditions required before any further pilot:
  1. Candidate 1 (real paid clip) FAILS anatomy (hover-base→boots mutation).
  2. A clean synthetic Bolt clip PASSES anatomy + clean_plate.
  3. A clip with baked-in generated HUD FAILS clean_plate.
  4. A synthetic hover-base→legs mutation FAILS anatomy.
  5. A compound push→collapse control PASSES phase motion WITHOUT a false reversal.
Run: python3 -m bolt_seq.eval_directed_gate_v2"""
import os, sys, json, subprocess
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C, scene_graph as SG, effects as FX, topics as T
from bolt_seq.character import BOLT
from bolt_seq.providers import directed_video as DV
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(PROJ, "renders/bolt_seq/_directed_gate_v2"); os.makedirs(OUT, exist_ok=True)
OXY = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription")
PILOT = os.path.join(PROJ, "renders/bolt_seq/_oxygen_pilot")
BOLT_CUT = os.path.join(OXY, "bolt_swim.png"); PLATE = os.path.join(OXY, "tunnel.png")
RING = os.path.join(OXY, "hub.png")
IMPAIRED = os.path.join(PILOT, "bolt_impaired.png"); COLLAPSED = os.path.join(PILOT, "bolt_collapsed.png")


def legged_bolt():
    """Deterministically graft two legs + boots onto the clean Bolt cutout → a hover-base→legs mutation."""
    p = os.path.join(OUT, "bolt_legged.png")
    im = Image.open(BOLT_CUT).convert("RGBA"); w, h = im.size; d = ImageDraw.Draw(im)
    lw = int(w * 0.09)
    for cx in (int(w * 0.40), int(w * 0.60)):                 # two legs
        d.rounded_rectangle([cx - lw // 2, int(h * 0.66), cx + lw // 2, int(h * 0.90)], radius=lw // 2,
                            fill=(170, 175, 180, 255))
        d.ellipse([cx - lw, int(h * 0.88), cx + lw, int(h * 0.99)], fill=(40, 40, 48, 255))  # boot
    im.save(p); return p


def env(pan=False):
    e = {"id": "env", "kind": "environment", "provider": "deterministic_2d", "z": 0, "base_h": 1920,
         "image": PLATE, "authored": ["x", "scale"], "tracks": {"scale": SG.const_track(1.05)}}
    if pan:
        e["tracks"]["x"] = SG.track([(0, 0.0), (1, 0.9)])
    return e


def synth_clean():
    out = os.path.join(OUT, "synth_clean.mp4")
    if os.path.exists(out): return out
    bolt = {"id": "bolt", "kind": "character", "provider": "deterministic_2d", "z": 50, "base_h": 720,
            "image": BOLT_CUT, "tracks": {"x": SG.track([(0, 0.25), (1, 0.7)]), "y": SG.const_track(0.5)}}
    C.render_scene_block(out, [env(), bolt], 5.0, tmp_dir=OUT, draw_fn=FX.draw); return out


def synth_hud():
    """Clean synth with a BAKED-IN meter + text (simulating generated UI) → must fail clean_plate."""
    out = os.path.join(OUT, "synth_hud.mp4"); base = synth_clean()
    if os.path.exists(out): return out
    hud = os.path.join(OUT, "_hud.png"); img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    try: f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 60)
    except Exception: f = ImageFont.load_default()
    d.rounded_rectangle([60, 90, 1020, 150], radius=30, outline=(255, 255, 255, 220), width=5)
    d.rounded_rectangle([66, 96, 420, 144], radius=24, fill=(235, 70, 60, 255))
    d.text((60, 170), "LOW OXYGEN", font=f, fill=(255, 90, 80, 255))
    img.save(hud)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", base, "-i", hud,
                    "-filter_complex", "[0:v][1:v]overlay=0:0", "-t", "5", out], check=True)
    return out


def synth_legged():
    out = os.path.join(OUT, "synth_legged.mp4")
    if os.path.exists(out): return out
    lg = legged_bolt()
    bolt = {"id": "bolt", "kind": "character", "provider": "deterministic_2d", "z": 50, "base_h": 720,
            "images": {"ok": BOLT_CUT, "legs": lg}, "pose0": "ok",
            "tracks": {"x": SG.track([(0, 0.3), (1, 0.7)]), "y": SG.const_track(0.5),
                       "pose": SG.track([(0.0, "ok"), (0.45, "ok"), (0.5, "legs"), (1.0, "legs")])}}
    C.render_scene_block(out, [env(), bolt], 5.0, tmp_dir=OUT, draw_fn=FX.draw); return out


def synth_compound():
    """Push right toward a ring, condition worsens, then collapse downward near the ring (no reversal)."""
    out = os.path.join(OUT, "synth_compound.mp4")
    if os.path.exists(out): return out
    dest = {"id": "dest", "kind": "destination", "provider": "deterministic_2d", "z": 20, "base_h": 520,
            "image": RING, "tracks": {"x": SG.const_track(0.74), "y": SG.const_track(0.46),
                                      "scale": SG.track([(0, 0.9), (1, 1.08)])}}
    bubble = {"id": "bubble", "kind": "prop", "provider": "deterministic_2d", "z": 45, "base_h": 150,
              "image": os.path.join(PILOT, "boundary_entry.png") if False else BOLT_CUT}  # replaced below
    # a simple drawn bubble
    bp = os.path.join(OUT, "_bubble.png"); bi = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(bi).ellipse([10, 10, 190, 190], outline=(210, 235, 255, 220), width=8, fill=(180, 220, 255, 60))
    bi.save(bp)
    bubble = {"id": "bubble", "kind": "prop", "provider": "deterministic_2d", "z": 55, "base_h": 150, "image": bp,
              "tracks": {"x": SG.const_track(0.34), "y": SG.const_track(0.34),
                         "opacity": SG.track([(0, 1), (0.5, 1), (0.6, 0), (1, 0)])}}
    bolt = {"id": "bolt", "kind": "character", "provider": "deterministic_2d", "z": 50, "base_h": 860,
            "images": {"swim": BOLT_CUT, "impaired": IMPAIRED, "collapse": COLLAPSED}, "pose0": "swim",
            "tracks": {"x": SG.track([(0, 0.30), (0.60, 0.55), (1, 0.55)]),
                       "y": SG.track([(0, 0.48), (0.55, 0.50), (1, 0.82)]),
                       # hold each posture long enough to read: swim → impaired (phase B) → collapsed (all of phase C)
                       "pose": SG.track([(0.0, "swim"), (0.35, "impaired"), (0.60, "collapse"), (1.0, "collapse")])}}
    C.render_scene_block(out, [env(), dest, bubble, bolt], 5.0, tmp_dir=OUT, draw_fn=FX.draw)
    return out


def hero_spec():
    dh = T.load("oxygen_subscription")["directed_hero"]
    return {"identity_reference": BOLT["reference"], "identity_bible": BOLT["identity"], "anatomy": BOLT["anatomy"],
            "phase_contract": {"entities": dh["entities"], "phases": dh["phases"],
                               "prohibited_transitions": dh["prohibited_transitions"]}}


def main():
    cost = []; spec = hero_spec()
    rows = []
    def row(name, cond, expected, actual, detail):
        ok = expected == actual
        rows.append({"condition": cond, "clip": name, "expected": expected, "actual": actual, "ok": ok, "detail": detail})
        print(f"  [{cond}] {name:22} expect={expected:4} actual={actual:4} {'OK' if ok else 'MISMATCH'} | {detail}", flush=True)

    print("building synthetic controls (no spend)...", flush=True)
    clean, hud, legged, compound = synth_clean(), synth_hud(), synth_legged(), synth_compound()
    cand1 = os.path.join(PILOT, "candidates", "cand_1.mp4")

    print("evaluating...", flush=True)
    # 1. Candidate 1 → anatomy FAIL
    a1 = DV.check_anatomy(cand1, spec, cost=cost)
    row("cand_1 (paid)", "1_cand1_anatomy_fail", "fail", "pass" if a1["identity_pass"] else "fail",
        f"features={a1.get('features')} frames={sorted(set(a1.get('prohibited_frames',[])+a1.get('altered_frames',[])))}")
    # 2. clean synth → anatomy PASS + clean_plate PASS
    a2 = DV.check_anatomy(clean, spec, cost=cost); c2 = DV.check_clean_plate(clean, cost=cost)
    row("synth_clean", "2_clean_anatomy_pass", "pass", "pass" if a2["identity_pass"] else "fail", a2.get("reason") or "clean")
    row("synth_clean", "2_clean_plate_pass", "pass", "pass" if c2["clean_plate_pass"] else "fail", c2.get("reason") or "clean")
    # 3. HUD synth → clean_plate FAIL
    c3 = DV.check_clean_plate(hud, cost=cost)
    row("synth_hud", "3_hud_clean_plate_fail", "fail", "pass" if c3["clean_plate_pass"] else "fail",
        f"ui={c3.get('ui_features')}")
    # 4. legged synth → anatomy FAIL
    a4 = DV.check_anatomy(legged, spec, cost=cost)
    row("synth_legged", "4_legs_anatomy_fail", "fail", "pass" if a4["identity_pass"] else "fail",
        f"features={a4.get('features')}")
    # 5. compound push→collapse → phase motion PASS, no reversal
    m5 = DV.evaluate_phased(compound, spec, cost=cost)
    passed = m5.get("phase_motion_pass") and not m5.get("prohibited_transitions_hit")
    row("synth_compound", "5_compound_motion_pass", "pass", "pass" if passed else "fail",
        f"phases={ {k:v['ok'] for k,v in m5.get('phases',{}).items()} } reasons={m5.get('reasons')[:2]}")

    fp = [r for r in rows if r["expected"] == "fail" and r["actual"] == "pass"]
    fn = [r for r in rows if r["expected"] == "pass" and r["actual"] == "fail"]
    summary = {"conditions": rows, "all_conditions_met": all(r["ok"] for r in rows),
               "false_positives": [r["condition"] for r in fp], "false_negatives": [r["condition"] for r in fn],
               "cand1_reclassified": {"phase_motion_pass": True, "identity_pass": a1["identity_pass"],
                                      "clean_plate_pass": False, "integration_pass": False, "production_ready": False,
                                      "known_bad_id": "bolt_hover_base_to_boots_mutation"},
               "cost_usd": round(sum(cost), 3)}
    json.dump(summary, open(os.path.join(OUT, "confusion_matrix_v2.json"), "w"), indent=2, default=str)
    json.dump(summary["cand1_reclassified"], open(os.path.join(PILOT, "candidate_1_reclassification.json"), "w"), indent=2)
    md = ["# Corrected offline gate validation (anatomy + clean-plate + phase motion)", "",
          f"- **all five conditions met: {summary['all_conditions_met']}**",
          f"- false positives: {summary['false_positives']} · false negatives: {summary['false_negatives']}",
          f"- Candidate 1 reclassified: identity_pass={a1['identity_pass']} (known-bad `bolt_hover_base_to_boots_mutation`)",
          f"- cost (VLM only, no video): ${summary['cost_usd']}", "",
          "| # | condition | clip | expected | actual | ok | detail |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['condition']} | | {r['clip']} | {r['expected']} | {r['actual']} | "
                  f"{'✅' if r['ok'] else '❌'} | {r['detail']} |")
    open(os.path.join(OUT, "confusion_matrix_v2.md"), "w").write("\n".join(md))
    print(f"\nALL CONDITIONS MET: {summary['all_conditions_met']} | FP={summary['false_positives']} FN={summary['false_negatives']} | ${summary['cost_usd']}")


if __name__ == "__main__":
    main()
