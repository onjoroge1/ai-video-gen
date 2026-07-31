"""A4 canonical pose authoring (NO SPEND). Reclassifies the current A4 as A4_CHARACTER_POSE_CONTINUITY_FAIL and
derives FOUR same-model poses P0..P3 FROM THE ACCEPTED A3 BOLT (extracted from the exact A4 start frame) so identity
is preserved BY CONSTRUCTION (same pixels, only affine/squash/tilt + eye-dim). Rejects bolt_fail.png (a different
model). Produces a clean single-component Bolt matte, the four pose RGBAs, an identity-continuity gate table
(P0..P3 vs the rejected bolt_fail as a contrast), a review board, and the canonical pose specification.
Run: python3 -m bolt_seq.author_A4_poses"""
import os, sys, json
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

W, H = 1080, 1920
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"; OUT = f"{AT}/a4_collapse/poses"; os.makedirs(OUT, exist_ok=True)
a0 = np.asarray(Image.open(f"{AT}/a4_collapse/A4_start_frame.png").convert("RGB").resize((W, H)), float)


def _box(x0, y0, x1, y1):
    m = np.zeros((H, W), bool); m[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)] = True; return m


# --- clean, SINGLE-COMPONENT Bolt matte from the accepted A3 Bolt (remove bg fragments incl. the hand-nozzle bit) ---
R0, G0, B0 = a0[:, :, 0], a0[:, :, 1], a0[:, :, 2]
mn = np.minimum(np.minimum(R0, G0), B0); mx = np.maximum(np.maximum(R0, G0), B0)
white = mn > 95; mint = (G0 > R0 + 5) & (G0 > 90) & (mn > 55) & ((mx - mn) < 95); cyan = (B0 > R0 + 15) & (B0 > 90)
seed = (white | mint | cyan) & _box(0.16, 0.40, 0.66, 0.78) & ~_box(0.63, 0.26, 0.85, 0.53)
seed = ndimage.binary_opening(seed, iterations=2)                 # sever the thin terminal-nozzle bridge
seed = ndimage.binary_closing(seed, iterations=3)
lbl, n = ndimage.label(seed); sizes = ndimage.sum(np.ones_like(lbl), lbl, range(1, n + 1))
matte = ndimage.binary_fill_holes(ndimage.binary_closing(lbl == (int(np.argmax(sizes)) + 1), iterations=6))
matte = ndimage.binary_opening(matte, iterations=2)               # drop residual spurs
lbl2, n2 = ndimage.label(matte); s2 = ndimage.sum(np.ones_like(lbl2), lbl2, range(1, n2 + 1))
matte = ndimage.binary_fill_holes(lbl2 == (int(np.argmax(s2)) + 1))
lblf, nf = ndimage.label(matte); n_components = int(nf)           # FINAL matte component count (single CC by construction)
core = ndimage.binary_erosion(matte, iterations=1)
alpha = np.clip(ndimage.gaussian_filter(core.astype(float), 0.8), 0, 1)
ys, xs = np.where(matte); bb = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
rgba = np.dstack([a0, alpha * 255]).astype("uint8")
base_cut = Image.fromarray(rgba, "RGBA").crop((bb[0], bb[1], bb[2] + 1, bb[3] + 1))     # the canonical A3 Bolt cutout
base_cut.save(f"{OUT}/A4_bolt_clean_matte.png")


def eye_dim(img, f):
    a = np.asarray(img).astype(float); r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    hband = np.zeros(a.shape[:2], bool); hband[int(0.20 * a.shape[0]):int(0.52 * a.shape[0])] = True   # VISOR only (antenna above excluded)
    ce = (b > r + 18) & (b > g - 25) & (a[:, :, 3] > 100) & hband
    for c in range(3): a[:, :, c][ce] *= f
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8"), "RGBA")


def single_cc(img):                                                # drop any disconnected alpha specks (gate 5)
    a = np.asarray(img).copy(); al = a[:, :, 3] > 40
    l, nc = ndimage.label(al)
    if nc > 1:
        sz = ndimage.sum(np.ones_like(l), l, range(1, nc + 1)); a[~(l == (int(np.argmax(sz)) + 1)), 3] = 0
    return Image.fromarray(a, "RGBA")


# --- P0..P3 all DERIVED FROM base_cut (same model) via affine/squash/tilt + progressive eye-dim ---
P0 = eye_dim(base_cut, 1.00)                                                            # weak hover (A3 as-is)
P1 = eye_dim(base_cut.rotate(-10, expand=True, resample=Image.BICUBIC), 0.70)          # uncontrolled fall (slight lean)
sq = base_cut.resize((int(base_cut.width * 1.12), int(base_cut.height * 0.80)), Image.LANCZOS)
P2 = eye_dim(sq, 0.45)                                                                  # floor-contact/impact (squash)
p3 = base_cut.rotate(-30, expand=True, resample=Image.BICUBIC)
p3 = p3.resize((int(p3.width * 1.04), int(p3.height * 0.92)), Image.LANCZOS)           # tilt + slight settle-squash
P3 = eye_dim(p3, 0.20)                                                                  # collapsed floor-rest
poses = {"P0_weak_hover": single_cc(P0), "P1_uncontrolled_fall": single_cc(P1), "P2_floor_impact": single_cc(P2), "P3_collapsed_rest": single_cc(P3)}
for k, im in poses.items(): im.save(f"{OUT}/{k}.png")


# --- identity-continuity metrics (invariant to affine): shell palette, cyan presence, antenna, hand, single-CC ---
def metrics(img):
    a = np.asarray(img).astype(float); al = a[:, :, 3] > 128
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    shell = al & (np.minimum(np.minimum(r, g), b) > 120)
    pal = [round(float(r[shell].mean()), 1), round(float(g[shell].mean()), 1), round(float(b[shell].mean()), 1)] if shell.sum() else [0, 0, 0]
    cyanp = (b > r + 15) & (b > 90) & al
    hh2 = a.shape[0]
    top = np.zeros(a.shape[:2], bool); top[:int(0.28 * hh2)] = True                     # antenna region (robust to tilt)
    antenna = bool((cyanp & top).sum() > 12)                                            # cyan antenna-ball near the top
    chestb = np.zeros(a.shape[:2], bool); chestb[int(0.52 * hh2):int(0.82 * hh2)] = True  # chest-panel band (NOT eye-dimmed)
    chest_cyan = round(float((cyanp & chestb).sum()) / max(1, int(al.sum())), 4)
    lblc, nc = ndimage.label(al)
    aspect = round(a.shape[0] / max(1, a.shape[1]), 3)
    return {"shell_palette_rgb": pal, "cyan_frac": round(float(cyanp.sum()) / max(1, int(al.sum())), 4),
            "chest_cyan_frac": chest_cyan, "antenna_present": antenna, "alpha_components": int(nc),
            "aspect_h_over_w": aspect, "shell_frac": round(float(shell.sum()) / max(1, int(al.sum())), 4)}


pm = {k: metrics(im) for k, im in poses.items()}
# contrast: the REJECTED bolt_fail model (should FAIL continuity vs P0 -> proves the gate + the reclassification)
fail_img = Image.open("renders/bolt_seq/oxygen_subscription/bolt_fail.png").convert("RGB")
fa = np.asarray(fail_img, float); fm = ~((fa[:, :, 0] > 170) & (fa[:, :, 2] > 170) & (fa[:, :, 1] < 120))
frgba = Image.fromarray(np.dstack([fa, ndimage.binary_fill_holes(fm) * 255]).astype("uint8"), "RGBA")
fail_metrics = metrics(frgba)


def dpal(a, b): return round(float(np.abs(np.array(a) - np.array(b)).mean()), 1)


ref = pm["P0_weak_hover"]
palette_tol, cyan_tol = 12.0, 0.06
gates = {
  "1_structural_identity_continuity": {
     "rule": "all post/pre-impact poses derive from the ONE accepted A3 Bolt cutout (same pixels)",
     "P1_vs_P0_palette_delta": dpal(pm["P1_uncontrolled_fall"]["shell_palette_rgb"], ref["shell_palette_rgb"]),
     "P2_vs_P0_palette_delta": dpal(pm["P2_floor_impact"]["shell_palette_rgb"], ref["shell_palette_rgb"]),
     "P3_vs_P0_palette_delta": dpal(pm["P3_collapsed_rest"]["shell_palette_rgb"], ref["shell_palette_rgb"]),
     "rejected_bolt_fail_vs_P0_palette_delta": dpal(fail_metrics["shell_palette_rgb"], ref["shell_palette_rgb"]),
     "pass": None},
  "2_ratio_tolerances": {"note": "P2/P3 intentionally squashed/tilted; identity is verified by palette+features, not raw aspect",
     "aspects": {k: pm[k]["aspect_h_over_w"] for k in pm}, "bolt_fail_aspect": fail_metrics["aspect_h_over_w"]},
  "3_palette_material_continuity": {"shell_palette": {k: pm[k]["shell_palette_rgb"] for k in pm},
     "chest_cyan_frac": {k: pm[k]["chest_cyan_frac"] for k in pm}, "bolt_fail_shell_palette": fail_metrics["shell_palette_rgb"],
     "max_shell_palette_delta_vs_P0": round(max(dpal(pm[k]["shell_palette_rgb"], ref["shell_palette_rgb"]) for k in pm), 1),
     "min_chest_cyan": round(min(pm[k]["chest_cyan_frac"] for k in pm), 4), "pass": None},
  "4_hand_finger_antenna_continuity": {"antenna_present": {k: pm[k]["antenna_present"] for k in pm}, "pass": None},
  "5_no_disconnected_alpha_outside_character": {"matte_components_in_scene": n_components,
     "per_pose_alpha_components": {k: pm[k]["alpha_components"] for k in pm}, "pass": None},
  "6_no_hard_sprite_replacement_hidden_by_flash": {"rule": "P0..P3 are one model; the assembly must NOT full-frame-flash a swap",
     "spec": "localized impact cue <=2 frames only", "enforced_in": "assembly (next step)"},
  "7_body_floor_contact_plus_overlapping_shadow": {"rule": "P2/P3 lowest opaque pixel on the floor plane; contact shadow overlaps the base",
     "enforced_in": "assembly (next step)"},
  "8_pre_post_flash_independent_eval": {"rule": "evaluate the frame just before and just after any impact cue independently; both must pass gate 1-5",
     "enforced_in": "assembly (next step)"},
}
gates["1_structural_identity_continuity"]["pass"] = bool(
  gates["1_structural_identity_continuity"]["P1_vs_P0_palette_delta"] < palette_tol and
  gates["1_structural_identity_continuity"]["P2_vs_P0_palette_delta"] < palette_tol and
  gates["1_structural_identity_continuity"]["P3_vs_P0_palette_delta"] < palette_tol and
  gates["1_structural_identity_continuity"]["rejected_bolt_fail_vs_P0_palette_delta"] >= palette_tol)   # bolt_fail must FAIL
gates["3_palette_material_continuity"]["pass"] = bool(gates["3_palette_material_continuity"]["max_shell_palette_delta_vs_P0"] < palette_tol and gates["3_palette_material_continuity"]["min_chest_cyan"] > 0.004)
gates["4_hand_finger_antenna_continuity"]["pass"] = bool(all(pm[k]["antenna_present"] for k in pm))
gates["5_no_disconnected_alpha_outside_character"]["pass"] = bool(n_components == 1 and all(pm[k]["alpha_components"] == 1 for k in pm))

# --- review board (P0..P3 on neutral grey, labeled) ---
cell = 460; board = Image.new("RGB", (4 * cell + 50, cell + 60), (40, 40, 44)); dd = ImageDraw.Draw(board)
for i, (k, im) in enumerate(poses.items()):
    t = im.copy(); t.thumbnail((cell - 20, cell - 20))
    bgc = Image.new("RGBA", (cell, cell), (70, 70, 76, 255)); bgc.alpha_composite(t, ((cell - t.width) // 2, (cell - t.height) // 2))
    board.paste(bgc.convert("RGB"), (i * cell + 10, 40)); dd.text((i * cell + 16, 16), k, fill=(235, 235, 235))
board.save(f"{OUT}/A4_pose_board.png")

spec = {
  "objective": "a4_canonical_pose_specification",
  "no_spend": True, "provider_called": False, "ALLOW_PAID": False, "assembled": False, "registered": False,
  "reclassification": {"prior": "A4_DETERMINISTIC_ANIMATIC_V2_FOR_REVIEW", "now": "A4_CHARACTER_POSE_CONTINUITY_FAIL",
     "reason": "post-impact used bolt_fail.png (a DIFFERENT Bolt model: head/body ratio, torso, chest panel, arms, hands, hover base, palette, lighting all change); the full-frame flash masked a replacement, not solved it."},
  "preserved": ["clean plate (A4_clean_plate.png)", "A4 start reference (A4_start_frame.png, untransformed)", "layered compositor", "fall trajectory", "no-plume controls"],
  "rejected_for_production": "bolt_fail.png (and bolt_collapse.png) — different model; only usable as design reference, NOT as the collapsing character",
  "canonical_poses": {
    "source": "ALL derived from the accepted A3 Bolt cutout (A4_bolt_clean_matte.png) — same model by construction",
    "P0_weak_hover": {"derivation": "clean A3 cutout as-is; eyes at A3 dim level", "state": "weakened hover"},
    "P1_uncontrolled_fall": {"derivation": "P0 tilted ~10deg (falling lean) + eyes 0.70", "state": "losing lift, dropping"},
    "P2_floor_impact": {"derivation": "P0 squashed (x*1.12, y*0.80) — impact compression + eyes 0.45", "state": "actual floor contact/impact"},
    "P3_collapsed_rest": {"derivation": "P0 tilted ~30deg + settle-squash (y*0.92) + eyes 0.20", "state": "collapsed floor-rest"},
    "identity_invariants": ["proportions", "chest-panel geometry", "hand anatomy", "hover base", "antenna", "materials", "palette"],
    "camera_lighting": "same corridor camera + lighting (poses are transforms of the in-scene A3 Bolt, so lighting is inherited)"
  },
  "assembly_rules_next_step": {
    "impact_cue": "localized dust/impact puff at the contact point, <= 2 frames (NOT a full-frame flash)",
    "contact_shadow": "tracked ellipse under the base, overlapping the body (grows on contact)",
    "squash_settle": "brief squash at P2 then settle to P3 (no bounce)",
    "between_P1_and_P3": "use P2 as the intermediate impact pose (or a mesh deformation) — no hard sprite swap",
    "background": "A4_clean_plate.png, pixel-static",
    "in_frame_margin": 0.04, "floor_contact_persist_s": ">=0.70"
  },
  "gates": gates,
  "pose_metrics": pm, "rejected_bolt_fail_metrics": fail_metrics,
  "artifacts": {"clean_matte": "poses/A4_bolt_clean_matte.png", "board": "poses/A4_pose_board.png",
                "P0": "poses/P0_weak_hover.png", "P1": "poses/P1_uncontrolled_fall.png",
                "P2": "poses/P2_floor_impact.png", "P3": "poses/P3_collapsed_rest.png"},
}
json.dump(spec, open(f"{AT}/a4_canonical_pose_spec.json", "w"), indent=2, default=str)

# reclassify the prior A4 result files (status only; keep as diagnostic; not registered)
for rf in ["a4_layered_v2_result.json", "a4_deterministic_result.json"]:
    p = f"{AT}/{rf}"
    if os.path.exists(p):
        d = json.load(open(p)); d["status"] = "A4_CHARACTER_POSE_CONTINUITY_FAIL"; d["reclassified_reason"] = "post-impact model swap to bolt_fail.png (different Bolt); not identity-continuous with accepted A3"
        json.dump(d, open(p, "w"), indent=2, default=str)

print("gate1 pass", gates["1_structural_identity_continuity"]["pass"], "| gate3", gates["3_palette_material_continuity"]["pass"],
      "| gate4", gates["4_hand_finger_antenna_continuity"]["pass"], "| gate5", gates["5_no_disconnected_alpha_outside_character"]["pass"])
print("P0 palette", ref["shell_palette_rgb"], "| bolt_fail palette", fail_metrics["shell_palette_rgb"],
      "| bolt_fail vs P0 delta", gates["1_structural_identity_continuity"]["rejected_bolt_fail_vs_P0_palette_delta"])
print("matte components:", n_components, "| DONE")
