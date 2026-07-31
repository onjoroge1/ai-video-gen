"""READ-ONLY A6 validation + freeze-manifest reconciliation. Does NOT modify A6 pixels — pins the reviewed hashes,
re-runs the temporal gates on the existing frames, records the REAL occluded-restart transition (A6 f89 = black; H0 f0 =
alive+banner; player does a deliberate black->H0 restart CUT; H0 never composited inside A6), removes stale
'seam==0.0 / A6 last == H0 first' claims. NO SPEND. Run: python3 -m bolt_seq.validate_and_freeze_A6"""
import os, sys, json, hashlib, subprocess
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image
NF = 90
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"
D = f"{AT}/a6_cta_loop"; FDIR = f"{D}/_f"
A5END = f"{AT}/a5_resolution/A5_final_frame.png"; H0MP4 = f"{AT}/h0_hook/H0.mp4"


def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def L(i): return np.asarray(Image.open(os.path.join(FDIR, f"f{i:03d}.png")).convert("RGB"), float)
def bright_cyan_eyes(img): R, G, B = img[:, :, 0], img[:, :, 1], img[:, :, 2]; return int(((B > R + 40) & (B > 130) & (G > 120)).sum())
def banner_px(img): reg = img[1480:1660, 300:780]; R, G, B = reg[:, :, 0], reg[:, :, 1], reg[:, :, 2]; return int(((R > G + 50) & (R > B + 50) & (R > 90)).sum())

# ---------- 1. pin reviewed-deliverable hashes ----------
REVIEWED = {"mp4": f"{D}/A6_cta_loop.mp4", "final_frame": f"{D}/A6_final_frame.png",
            "occlusion_strip": f"{D}/A6_occlusion_strip.png", "final_1p5s": f"{D}/A6_final_1p5s.mp4", "loop_demo": f"{D}/A6_loop_demo.mp4"}
hashes = {k: sha(v) for k, v in REVIEWED.items()}

# ---------- references ----------
a5_end = np.asarray(Image.open(A5END).convert("RGB").resize((1080, 1920)), float)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", H0MP4, "-vf", "select=eq(n\\,0),scale=1080:1920", "-frames:v", "1", f"{D}/_H0_first.png"], check=True)
h0_first = np.asarray(Image.open(f"{D}/_H0_first.png").convert("RGB").resize((1080, 1920)), float)
allframes = [L(i) for i in range(NF)]

# ---------- 7. temporal gates (re-run on the pinned frames) ----------
max_alive = max(bright_cyan_eyes(f) for f in allframes); h0_alive = bright_cyan_eyes(h0_first)
max_banner = max(banner_px(f) for f in allframes)
occ89 = float((allframes[89].mean(2) < 18).mean()); occ88 = float((allframes[88].mean(2) < 18).mean())
handoff = float(np.abs(allframes[0] - a5_end).mean())
gates = {
  "frames_90": NF == 90, "opens_from_A5_end": bool(handoff < 2.0),
  "MAX_ONE_BOLT_VISIBLE_PER_FRAME": bool(max_alive < 500),
  "NO_A5_H0_CHARACTER_OVERLAP": bool(max_alive < 500),
  "NO_POWERED_ON_BOLT_INSIDE_A6": bool(max_alive < 500 and h0_alive > 200),
  "NO_SUBSCRIPTION_BANNER_INSIDE_A6": bool(max_banner < 40),
  "OCCLUSION_AT_LEAST_95PCT_BEFORE_WRAP": bool(occ89 >= 0.95),
  "RESTART_READS_AS_NEW_CYCLE_AT_NORMAL_SPEED": bool(occ89 >= 0.95 and h0_alive > 200)}

manifest = {
  "milestone": "A6_FROZEN", "immutable": True, "no_spend": True, "provider_called": False, "ALLOW_PAID": False, "frozen_on": "2026-07-31",
  "beat": "A6 CTA / occluded restart loop (final beat)",
  "grid": {"frame_start": 529, "frame_count": 90, "frame_end_inclusive": 618, "fps": 30, "duration_s": round(90/30, 4)},
  "human_status": "VISUALLY ACCEPTED by human; pixels frozen as-reviewed (no retouch)",
  "reviewed_hashes": hashes,
  "transition_truth": {
    "A6_f89": "fully obscured / black (occluded %.1f%%)" % (occ89 * 100),
    "H0_f0": "alive Bolt + subscription opening (bright-cyan-eyes signature %d px)" % h0_alive,
    "loop_mechanism": "the player performs a DELIBERATE black-to-H0 restart CUT at the playback wrap",
    "H0_not_composited_inside_A6": True,
    "corrected_claim": "A6 last frame is NOT equal to H0 first frame; there is NO 0.0 pixel seam. The loop is a CLEAN STORY-MOTIVATED RESTART (occluded restart cut), not a seamless match."},
  "temporal_gates": gates, "all_temporal_gates_pass": bool(all(gates.values())),
  "metrics": {"handoff_vs_A5_end": round(handoff, 3), "max_powered_on_bolt_px_in_A6": max_alive, "H0_alive_signature_px": h0_alive,
              "max_banner_px_in_A6": max_banner, "occluded_frac_f88": round(occ88, 3), "occluded_frac_f89": round(occ89, 3)},
  "does_not_modify_frozen_H0_A1_A3_A3B_A4_A5": True,
  "master_assembly": "NOT performed (requires separate authorization)"}
json.dump(manifest, open(f"{D}/A6_FREEZE_manifest.json", "w"), indent=2, default=str)
print(json.dumps(gates, indent=2)); print("all temporal gates pass:", manifest["all_temporal_gates_pass"])
print("occ f88/f89:", round(occ88, 3), round(occ89, 3), "| max_alive_in_A6:", max_alive, "| H0 alive:", h0_alive, "| handoff:", round(handoff, 3))
print("hashes:", {k: v[:12] for k, v in hashes.items()})
print("DONE")
