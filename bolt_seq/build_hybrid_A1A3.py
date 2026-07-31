"""ZERO-SPEND segment-level hybrid A1-A3 evaluation. NO Kling, NO provider, NO character surgery (no recolor/segment/warp/
repaint/animate). Reuse existing paid files only. Builds two temporary hybrids, each EXACTLY 232 frames:
  HYBRID_SET1 = paid set1 A1[0:66] + paid set1 A2[0:76] + original deterministic A3[0:90]
  HYBRID_SET2 = paid set2 A1[0:66] + paid set2 A2[0:76] + original deterministic A3[0:90]
Question: can the clean Kling forward-motion span (A1+A2) hand off directly to the already-approved deterministic weakening
A3? Deterministic gates here; adversarial phone panel + real-time compare run separately. Frozen master/beats untouched.
Run: python3 -m bolt_seq.build_hybrid_A1A3"""
import os, sys, json, subprocess, hashlib
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
W, H, FPS = 1080, 1920, 30
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"
OUT = f"{AT}/a1a3_hybrid"; os.makedirs(OUT, exist_ok=True)
TP = (0.62, 0.46)
A3_DET = f"{AT}/a3_accepted/A3_production_primitive.mp4"                # original frozen deterministic A3 (approved weakening)
CANDS = {
  "HYBRID_SET1": [(f"{AT}/a1a3_production/set1/A1.mp4", 66), (f"{AT}/a1a3_production/set1/A2.mp4", 76), (A3_DET, 90)],
  "HYBRID_SET2": [(f"{AT}/a1a3_production/set2/A1.mp4", 66), (f"{AT}/a1a3_production/set2/A2.mp4", 76), (A3_DET, 90)]}
BOUND = {"A1_A2": 66, "A2_A3": 142}                                     # assembled boundary frame indices (A1[0:66], A2[0:76], A3[0:90])


def decode(mp4, d):
    os.makedirs(d, exist_ok=True); [os.remove(os.path.join(d, x)) for x in os.listdir(d)]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp4, "-vf", f"scale={W}:{H}", "-start_number", "0", os.path.join(d, "s%04d.png")], check=True)
    return len(os.listdir(d))


def assemble(name, segs):
    FR = f"{OUT}/{name}/_frames"; os.makedirs(FR, exist_ok=True); [os.remove(os.path.join(FR, x)) for x in os.listdir(FR)]
    gi = 0
    for mp4, take in segs:
        tmp = f"{OUT}/{name}/_seg{gi}"; avail = decode(mp4, tmp)
        for k in range(take):
            Image.open(os.path.join(tmp, f"s{min(k, avail-1):04d}.png")).save(os.path.join(FR, f"m{gi:04d}.png")); gi += 1
    assert gi == 232, f"{name}: {gi} != 232"
    mp4 = f"{OUT}/{name}/{name}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(FR, "m%04d.png"),
                    "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS), mp4], check=True)
    return FR, mp4


def bolt_mask(a): R, Gc, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]; return ((np.minimum(np.minimum(R, Gc), B) > 95) | ((B > R + 15) & (B > 95)))
def centroid(a):
    m = bolt_mask(a); ys, xs = np.where(m); return (xs.mean() / W, ys.mean() / H) if len(xs) else (0.5, 0.5)
def term_dist(a): c = centroid(a); return ((c[0] - TP[0]) ** 2 + (c[1] - TP[1]) ** 2) ** 0.5
def eye_lum(a):
    R, Gc, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]; ey = (B > R + 20) & (B > 120); return float(a[ey].mean()) if ey.any() else 0.0
_yy, _xx = np.mgrid[0:H, 0:W]; _termbox = (_yy > 560) & (_yy < 1000) & (_xx > 560) & (_xx < 900)
def n_bolts(a):
    R, Gc, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]; shell = (np.minimum(np.minimum(R, Gc), B) > 120) & (~_termbox)
    shell = ndimage.binary_opening(shell, iterations=2); l, n = ndimage.label(shell)
    sizes = ndimage.sum(np.ones_like(l), l, range(1, n + 1)) if n else np.array([]); return int(sum(1 for s in sizes if s > 0.004 * H * W))


# frozen neighbours for the handoffs
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{AT}/h0_hook/H0.mp4", "-vf", "select=eq(n\\,59),scale=1080:1920", "-frames:v", "1", f"{OUT}/_h0_last.png"], check=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{AT}/a3b_bridge/A3B.mp4", "-vf", "select=eq(n\\,0),scale=1080:1920", "-frames:v", "1", f"{OUT}/_a3b_first.png"], check=True)
h0_last = np.asarray(Image.open(f"{OUT}/_h0_last.png").convert("RGB"), float); a3b_first = np.asarray(Image.open(f"{OUT}/_a3b_first.png").convert("RGB"), float)

results = {}
for name, segs in CANDS.items():
    FR, mp4 = assemble(name, segs)
    def L(i): return np.asarray(Image.open(os.path.join(FR, f"m{i:04d}.png")).convert("RGB"), float)
    dists = [term_dist(L(i)) for i in range(0, 232, 4)]
    eyes_idx = list(range(0, 232, 3)); eyes = [eye_lum(L(i)) for i in eyes_idx]
    nb = max(n_bolts(L(i)) for i in range(0, 232, 6))
    b12, b23 = BOUND["A1_A2"], BOUND["A2_A3"]
    # A2->A3 seam (the key): cross-frame diff + eye + centroid + terminal-distance continuity
    seam_meanabs = float(np.abs(L(b23) - L(b23 - 1)).mean())
    seam_eye = abs(eye_lum(L(b23)) - eye_lum(L(b23 - 1)))
    c1, c2 = centroid(L(b23 - 1)), centroid(L(b23)); seam_centroid = ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2) ** 0.5
    seam_dist = abs(term_dist(L(b23)) - term_dist(L(b23 - 1)))
    a12_meanabs = float(np.abs(L(b12) - L(b12 - 1)).mean())
    start_h = float(np.abs(L(0) - h0_last).mean()); end_h = float(np.abs(L(231) - a3b_first).mean())
    mono_reverse = max((dists[i] - dists[i - 1]) for i in range(1, len(dists)))
    # weakness AFTER A3 start (142): eyes must monotonically dim, no re-brighten; readable by mid-A3 (~187)
    a3_eyes = [(i, eye_lum(L(i))) for i in range(142, 232, 3)]
    a3_vals = [v for _, v in a3_eyes]
    a3_max_rebright = max((a3_vals[k] - a3_vals[k - 1]) for k in range(1, len(a3_vals)))
    eye142 = eye_lum(L(142)); eye_midA3 = eye_lum(L(187)); eye231 = eye_lum(L(231))
    gates = {
      "frames_232": True,
      "start_handoff_H0": bool(start_h < 6.0), "start_handoff_meanabs": round(start_h, 2),
      "A1_A2_motion_continuity": bool(a12_meanabs < 22.0), "A1_A2_meanabs": round(a12_meanabs, 2),
      "A2_A3_no_seam_pop": bool(seam_meanabs < 22.0 and seam_centroid < 0.05 and seam_eye < 22.0),
      "A2_A3_seam_meanabs": round(seam_meanabs, 2), "A2_A3_seam_centroid_shift": round(seam_centroid, 4),
      "A2_A3_seam_eye_jump": round(seam_eye, 2), "A2_A3_seam_dist_jump": round(seam_dist, 4),
      "end_handoff_A3B": bool(end_h < 6.0), "end_handoff_meanabs": round(end_h, 2),
      "monotonic_forward_no_reverse": bool(mono_reverse < 0.03), "max_backward_step": round(mono_reverse, 3),
      "one_bolt_max": bool(nb <= 1), "n_bolts_max": nb,
      "no_eye_rebrighten_after_weakening": bool(a3_max_rebright < 10.0), "A3_max_eye_rebright": round(a3_max_rebright, 2),
      "weakness_readable_by_mid_A3": bool(eye_midA3 < eye142 - 12), "A3_eye_start_mid_end": [round(eye142, 1), round(eye_midA3, 1), round(eye231, 1)]}
    hard = ["frames_232", "start_handoff_H0", "A1_A2_motion_continuity", "A2_A3_no_seam_pop", "end_handoff_A3B",
            "monotonic_forward_no_reverse", "one_bolt_max", "no_eye_rebrighten_after_weakening", "weakness_readable_by_mid_A3"]
    det_pass = all(gates[k] for k in hard)
    # strip (marks the seams) + phone frames
    strip = Image.new("RGB", (9 * 190 + 20, 400), (12, 12, 14)); dd = ImageDraw.Draw(strip)
    marks = [0, 33, 65, 66, 108, 141, 142, 187, 231]
    labs = ["f0", "f33", "f65 A1|", "f66 A2", "f108", "f141 A2|", "f142 A3", "f187 midA3", "f231"]
    for k, (i, lb) in enumerate(zip(marks, labs)):
        strip.paste(Image.open(os.path.join(FR, f"m{i:04d}.png")).resize((190, 338)), (k * 190 + 10, 40)); dd.text((k * 190 + 12, 6), lb, fill=(230, 230, 230))
        if "|" in lb or "A3" in lb: dd.rectangle([k*190+10, 40, k*190+200, 378], outline=(230,120,60), width=3)
    strip.save(f"{OUT}/{name}_strip.png")
    ph = f"{OUT}/{name}/_phone"; os.makedirs(ph, exist_ok=True)
    for i in [0, 29, 58, 87, 116, 141, 160, 187, 210, 231]:
        Image.open(os.path.join(FR, f"m{i:04d}.png")).resize((270, 480)).save(os.path.join(ph, f"p{i:03d}.png"))
    results[name] = {"mp4": mp4, "strip": f"{OUT}/{name}_strip.png", "phone_dir": ph, "det_gates": gates, "det_gates_pass": det_pass}
    print(f"\n=== {name} | DET PASS: {det_pass} ===")
    print(json.dumps({k: gates[k] for k in gates}, indent=1))

# real-time side-by-side comparison
sbs = f"{OUT}/hybrid_compare_sbs.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", results["HYBRID_SET1"]["mp4"], "-i", results["HYBRID_SET2"]["mp4"],
                "-filter_complex", "[0:v]scale=540:960[a];[1:v]scale=540:960[b];[a][b]hstack", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", sbs], check=False)
json.dump({"objective": "hybrid_A1A3_zero_spend_eval", "no_spend": True, "provider_called": False, "ALLOW_PAID": False,
           "candidates": {k: {"mp4": v["mp4"], "det_gates": v["det_gates"], "det_gates_pass": v["det_gates_pass"]} for k, v in results.items()},
           "compare_sbs": sbs, "note": "no character surgery; segment-level concat only. Panel + real-time review next; select only if every hard gate passes."},
          open(f"{OUT}/hybrid_eval.json", "w"), indent=2, default=str)
print("\ncompare:", sbs); print("DONE")
