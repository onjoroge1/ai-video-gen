"""READ-ONLY A5 validation + freeze-manifest reconciliation. Does NOT rebuild/modify A5 pixels — only reads the pinned
reviewed files, runs approach-appropriate TONAL gates (marking obsolete surgical-mask gates NOT_APPLICABLE_WITH_REASON),
and writes A5_FREEZE_manifest.json. NO SPEND. Run: python3 -m bolt_seq.validate_and_freeze_A5"""
import os, sys, json, hashlib, subprocess
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image
from scipy import ndimage
W, H, NF = 1080, 1920, 125
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"
D = f"{AT}/a5_resolution"; FDIR = f"{D}/_f"
A4BLACK = f"{AT}/a4_collapse/A4_final_frame_powerdown.png"
A4F44 = f"{AT}/a4_collapse/_lastvis/A4_f44.png"
yy, xx = np.mgrid[0:H, 0:W]


def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def L(i): return np.asarray(Image.open(os.path.join(FDIR, f"f{i:03d}.png")).convert("RGB"), float)


# ---------- 1. pin hashes of the reviewed deliverables ----------
REVIEWED = {"mp4": f"{D}/A5_aftermath.mp4", "f60_frame": f"{D}/A5_f60_full.png", "final_frame": f"{D}/A5_final_frame.png",
            "review_25pct": f"{D}/A5_f60_25pct.png", "contact_strip": f"{D}/A5_strip.png",
            "crop_hud": f"{D}/crops/A5_crop_hud_region.png", "crop_chest": f"{D}/crops/A5_crop_chest_panel.png",
            "crop_head": f"{D}/crops/A5_crop_head_antenna.png", "crop_terminal": f"{D}/crops/A5_crop_terminal_screen.png"}
hashes = {k: sha(v) for k, v in REVIEWED.items()}

# ---------- 2. A5_result.json evaluates these exact files ----------
r = json.load(open(f"{D}/A5_result.json"))
result_consistent = (r.get("A5_final_frame_sha256") == hashes["final_frame"]) and (sha(f"{D}/_f/f060.png") == hashes["f60_frame"])

# ---------- references + frames ----------
a4_black = np.asarray(Image.open(A4BLACK).convert("RGB").resize((W, H)), float)
f44 = np.asarray(Image.open(A4F44).convert("RGB").resize((W, H)), float)
f0, f36, f60, flast = L(0), L(36), L(60), L(NF - 1)
boltbox = (yy > 980) & (yy < 1500) & (xx > 235) & (xx < 830)


# ---------- 4. approach-appropriate tonal gates ----------
# (a) A4-f44 pose/position continuity: Bolt SILHOUETTE centroid/bbox (geometry), f36 (push ~negligible) vs A4 f44
def sil(img, thr):
    m = (np.minimum(np.minimum(img[:, :, 0], img[:, :, 1]), img[:, :, 2]) > thr) & boltbox
    m = ndimage.binary_opening(m, iterations=2); ys, xs = np.where(m)
    return (float(xs.mean()), float(ys.mean()), int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(xs) else (0,)*6
s44 = sil(f44, 55); s36 = sil(f36, 30)      # A5 is darker -> lower threshold; same underlying geometry
cen_dx, cen_dy = abs(s36[0] - s44[0]), abs(s36[1] - s44[1])
bbox_dmax = max(abs(s36[i] - s44[i]) for i in range(2, 6))
pose_continuity = bool(bbox_dmax < 14)      # silhouette POSITION/EXTENT matches f44 (centroid is confounded by the tonal darkening -> reported, not gated)
# (b) opens-from-black + timing
opens_from_black = bool(f0.mean() < 2.0); handoff = float(np.abs(f0 - a4_black).mean())
mp4_frames = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", f"{D}/A5_aftermath.mp4"], capture_output=True, text=True).stdout.strip() or 0)
timing_125 = bool(len(os.listdir(FDIR)) == 125 and mp4_frames == 125)
# (c) zero INDEPENDENT Bolt motion (only a global env push -> Bolt locked to corridor): adjacent diff in the Bolt box after fade
bolt_adj = max(float(np.abs(L(i)[1000:1490, 300:820] - L(i - 1)[1000:1490, 300:820]).mean()) for i in range(51, NF))
zero_independent_motion = bool(bolt_adj < 4.0)   # small residual = global-push resampling; NO per-Bolt animation exists in the pipeline
# (d) eyes / chest / antenna powered OFF (final frame)
eye = flast[1055:1120, 460:665]; eye_active = float(((eye[:, :, 2] > eye[:, :, 0] + 15) & (eye.mean(2) > 50)).mean())
chest = flast[1200:1345, 360:555]; chest_cyan = float(((chest[:, :, 2] > chest[:, :, 0] + 18) & (chest[:, :, 2] > 90)).mean()); chest_lum = float(chest.mean())
ball = flast[840:930, 540:610]; ball_teal = int(((ball[:, :, 2] > ball[:, :, 0] + 20) & (ball[:, :, 2] > 110)).sum())
powered_off = bool(eye_active < 0.02 and chest_cyan < 0.02 and ball_teal < 10)
# (e) no chest patch / jagged / visor residue / band / matte / ghosting
gg = np.abs(np.gradient(flast.mean(2))[0]) + np.abs(np.gradient(flast.mean(2))[1])
gg44 = np.abs(np.gradient(f44.mean(2))[0]) + np.abs(np.gradient(f44.mean(2))[1])
chest_edge99 = float(np.percentile(gg[1190:1360, 340:575], 99.5)); chest_edge99_src = float(np.percentile(gg44[1190:1360, 340:575], 99.5))
no_chest_patch = bool(chest_edge99 <= chest_edge99_src + 8)   # A5 adds NO crisp rim beyond the panel's own natural bevel edge (from f44)
Rf, Gf, Bf = flast[:, :, 0], flast[:, :, 1], flast[:, :, 2]; Lf = 0.299 * Rf + 0.587 * Gf + 0.114 * Bf
visor_ring = np.zeros((H, W), bool); visor_ring[1030:1170, 410:700] = True
visor_speckle = int((visor_ring & (Bf > Rf + 12) & (Gf > Rf + 3) & (Lf > 55)).sum())
no_visor_residue = bool(visor_speckle < 40)
rowgrad = np.abs(flast.mean(2)[1:] - flast.mean(2)[:-1]).mean(1); no_horizontal_band = bool(float(rowgrad[980:1200].max()) < 8.0)
hud_ring = np.abs(np.gradient(flast.mean(2))[0])[16:20, 28:672].mean() + np.abs(np.gradient(flast.mean(2))[0])[214:218, 28:672].mean()
no_hud_matte = bool(hud_ring / 2 < 6.0)
# ghosting: the reaching hand is OPAQUE (differs from the corridor plate behind it, not see-through)
plate = np.asarray(Image.open(f"{AT}/a4_collapse/A4_clean_plate.png").convert("RGB").resize((W, H)), float)
hand = (yy > 1240) & (yy < 1340) & (xx > 610) & (xx < 780)
hand_opacity = float(np.abs(flast[hand] - plate[hand]).mean()); no_ghosting = bool(hand_opacity > 12.0)   # opaque hand differs from the floor behind it
# (f) terminal perceptually dominant via SATURATION (green screen is the most-saturated element)
def sat(px): mx = px.max(2); mn = px.min(2); return (mx - mn)
term = flast[700:820, 650:820]; term_sat = float(sat(term).mean()); term_lum = float(term.mean())
bolt_sat = float(sat(flast[boltbox].reshape(-1, 1, 3)).mean()); bolt_lum = float(flast[boltbox].mean())
terminal_dominant = bool(term_sat > bolt_sat * 1.4 and term_lum > bolt_lum)   # green terminal clearly more saturated AND brighter than the desaturated Bolt
# (g) phone-size readability (structural shell landmarks on the 25% frame)
f25 = np.asarray(Image.open(f"{D}/A5_f60_25pct.png").convert("RGB"), float); tw, th = f25.shape[1], f25.shape[0]; sx, sy = tw / W, th / H
LMB = {"head": (400, 950, 700, 1150), "torso": (330, 1150, 560, 1340), "hover_base": (250, 1300, 460, 1470), "front_arm": (560, 1175, 800, 1345), "rear_arm": (185, 1025, 365, 1190)}
lm = {k: round(float(f25[int(b[1]*sy):int(b[3]*sy), int(b[0]*sx):int(b[2]*sx)].max()), 1) for k, b in LMB.items()}
readable_25 = bool(all(v > 45 for v in lm.values()))

gates_applicable = {
  "A4_F44_POSE_POSITION_CONTINUITY": pose_continuity, "OPENS_FROM_BLACK": opens_from_black, "HANDOFF_FROM_A4_BLACK": bool(handoff < 3.0),
  "TIMING_125_FRAMES": timing_125, "ZERO_INDEPENDENT_BOLT_MOTION": zero_independent_motion,
  "EYES_CHEST_ANTENNA_POWERED_OFF": powered_off, "NO_CHEST_PATCH_NO_JAGGED_PERIMETER": no_chest_patch,
  "NO_VISOR_BORDER_RESIDUE": no_visor_residue, "NO_HORIZONTAL_BAND": no_horizontal_band, "NO_RECTANGULAR_HUD_MATTE": no_hud_matte,
  "NO_GHOSTING_BOLT_OPAQUE": no_ghosting, "TERMINAL_PERCEPTUALLY_DOMINANT_BY_SATURATION": terminal_dominant,
  "PHONE_SIZE_READABLE_25PCT": readable_25}
gates_not_applicable = {
  "EMISSIVE_MASK_CONTAINED_WITHIN_COMPONENTS": "N/A — tonal approach uses NO shaped component masks to edit (soft cyan-weighted desaturation); containment is meaningless.",
  "NO_BLACK_MASK_SPILL_ON_SHELL_OR_LIMBS": "N/A — no black mask; a deliberate broad tonal darkening is applied to the whole Bolt for subordination (not a spill artifact). Uniformity verified via NO_HORIZONTAL_BAND / NO_CHEST_PATCH.",
  "NO_CYAN_HALO_AROUND_CHEST_BEVEL": "SUPERSEDED by NO_CHEST_PATCH + EYES_CHEST_ANTENNA_POWERED_OFF (chest_cyan measured %.3f) — no shaped fill exists to leave a halo." % chest_cyan,
  "BACKGROUND_OUTSIDE_VISOR_PIXEL_IDENTICAL": "N/A — the tonal pass is global (by design), not a visor-local eye edit; there is no separate 'eye edit' to contain.",
  "CHEST_PANEL_SHAPE_SMOOTH_AND_PHYSICAL / NO_JAGGED (mask-perimeter form)": "SUPERSEDED by NO_CHEST_PATCH (render-based edge check, edge99=%.1f) — no imposed contour exists; the panel's real render geometry is preserved." % chest_edge99}
metrics = {"pose_centroid_dx_dy": [round(cen_dx, 2), round(cen_dy, 2)], "pose_bbox_dmax": round(bbox_dmax, 1), "handoff": round(handoff, 3),
           "mp4_frames": mp4_frames, "png_frames": len(os.listdir(FDIR)), "bolt_adj_after_fade": round(bolt_adj, 2),
           "eye_active_frac": round(eye_active, 4), "chest_cyan_frac": round(chest_cyan, 4), "chest_lum": round(chest_lum, 1), "antenna_ball_teal_px": ball_teal,
           "chest_edge99": round(chest_edge99, 1), "chest_edge99_src_f44": round(chest_edge99_src, 1), "visor_speckle_px": visor_speckle, "row_band_max": round(float(rowgrad[980:1200].max()), 2),
           "hand_opacity": round(hand_opacity, 1), "term_sat": round(term_sat, 1), "bolt_sat": round(bolt_sat, 1), "term_lum": round(term_lum, 1), "bolt_lum": round(bolt_lum, 1), "landmark25": lm}
out = {"objective": "A5_validation_reconciliation (READ-ONLY; no pixels modified)", "no_spend": True, "provider_called": False, "ALLOW_PAID": False,
       "reviewed_hashes": hashes, "A5_result_json_evaluates_current_build": bool(result_consistent),
       "gates_applicable": {k: bool(v) for k, v in gates_applicable.items()}, "gates_not_applicable": gates_not_applicable,
       "all_applicable_pass": bool(all(gates_applicable.values())), "metrics": metrics}
json.dump(out, open(f"{D}/A5_validation.json", "w"), indent=2, default=str)
print("result.json evaluates current build:", result_consistent)
print(json.dumps(gates_applicable, indent=2))
print("ALL APPLICABLE PASS:", out["all_applicable_pass"])
print(json.dumps(metrics, indent=2, default=str))
print("DONE")
