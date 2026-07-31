"""A4 Bolt extraction — ONE disciplined SEEDED-SEGMENTATION method (NO API SPEND, NO color-threshold whack-a-mole).
OpenCV GrabCut is not installable here (no cp314 wheel + PEP668 externally-managed env), so this uses scipy's
marker-based watershed (ndimage.watershed_ift) — a genuine seeded segmentation over an edge/gradient landscape with
EXPLICIT foreground/background seed regions (the GrabCut-equivalent available locally). Seeds: visor + eyes + shell +
mint + antenna + reaching hand = FOREGROUND; terminal/nozzle (from the plate) + floor + far-corridor + red signage =
BACKGROUND. Validates visor/eyes/hand/fingers/antenna/torso/chest/base; displays on a bright checkerboard AND a
saturated solid. Stops after this one method. Run: python3 -m bolt_seq.extract_A4_seeded"""
import os, sys, json
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

W, H = 1080, 1920
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"; OUT = f"{AT}/a4_collapse/seeded"; os.makedirs(OUT, exist_ok=True)
a0 = np.asarray(Image.open(f"{AT}/a4_collapse/A4_start_frame.png").convert("RGB").resize((W, H)), float)
plate = np.asarray(Image.open(f"{AT}/a4_collapse/A4_clean_plate.png").convert("RGB").resize((W, H)), float)
R, G, B = a0[:, :, 0], a0[:, :, 1], a0[:, :, 2]
mn = np.minimum(np.minimum(R, G), B); mx = np.maximum(np.maximum(R, G), B); gray = a0.mean(axis=2)


def _box(x0, y0, x1, y1):
    m = np.zeros((H, W), bool); m[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)] = True; return m


# --- edge/gradient landscape for the watershed (flood within flat regions, stop at silhouette edges) ---
gy = ndimage.sobel(gray, axis=0); gx = ndimage.sobel(gray, axis=1)
grad = np.hypot(gx, gy); grad = (grad / max(1e-3, grad.max()) * 255).astype("uint8")
grad = np.maximum(grad, 1)                                            # 0 is reserved semantics; keep >=1

BOLT_REG = _box(0.10, 0.30, 0.72, 0.80)
term_full = ndimage.binary_dilation((plate.mean(axis=2) > 70) & _box(0.55, 0.26, 0.86, 0.62), iterations=2)

# ---- FOREGROUND seeds ----
white = mn > 115; cyan = (B > R + 8) & (B > 65); mint = (G > R + 8) & (G > 95) & (mn > 60) & ((mx - mn) < 95)
fg = (white | cyan | mint) & BOLT_REG & ~term_full
lbl, n = ndimage.label(ndimage.binary_closing(fg, iterations=2)); sz = ndimage.sum(np.ones_like(lbl), lbl, range(1, n + 1))
fg_body = lbl == (int(np.argmax(sz)) + 1)
by, bx = np.where(fg_body); bb = [bx.min(), by.min(), bx.max(), by.max()]; bh = bb[3] - bb[1]
# explicit VISOR foreground seed: the largest dark blob inside the head, confined to the body's neighbourhood
head_reg = np.zeros((H, W), bool); head_reg[bb[1]:int(bb[1] + 0.46 * bh), bb[0]:bb[2]] = True
darkhead = (gray < 112) & head_reg & ndimage.binary_dilation(fg_body, iterations=10) & ~term_full
vl, vn = ndimage.label(darkhead)
visor_seed = np.zeros((H, W), bool)
if vn:
    vsz = ndimage.sum(np.ones_like(vl), vl, range(1, vn + 1)); visor_seed = vl == (int(np.argmax(vsz)) + 1)
# explicit reaching-HAND foreground seed (Bolt-colour in the hand area, not the nozzle)
hand_seed = (white | mint) & _box(0.55, 0.57, 0.70, 0.70) & ~term_full
fg_seed = ndimage.binary_erosion(fg_body, iterations=2) | ndimage.binary_erosion(visor_seed, iterations=1) | hand_seed

# ---- BACKGROUND seeds ----
border = np.ones((H, W), bool); border[8:H - 8, 8:W - 8] = False       # frame border = corridor
far = ~ndimage.binary_dilation(BOLT_REG, iterations=1)
floor = _box(0.0, 0.80, 1.0, 1.0)
red_sign = (R > G + 40) & (R > B + 40)
bg_seed = (term_full | border | far | floor | red_sign) & ~fg_seed
bg_seed = bg_seed & ~ndimage.binary_dilation(fg_seed, iterations=2)

markers = np.zeros((H, W), np.int16)
markers[bg_seed] = 1; markers[fg_seed] = 2
res = ndimage.watershed_ift(grad, markers)
matte = res == 2
matte = ndimage.binary_fill_holes(ndimage.binary_closing(matte, iterations=2))
ml, mnn = ndimage.label(matte); msz = ndimage.sum(np.ones_like(ml), ml, range(1, mnn + 1))
matte = ndimage.binary_fill_holes(ml == (int(np.argmax(msz)) + 1))
alpha = (matte * 255).astype("uint8")
rgba = np.dstack([a0, alpha]).astype("uint8")
my, mx2 = np.where(matte); mbb = [int(mx2.min()), int(my.min()), int(mx2.max()), int(my.max())]
Image.fromarray(rgba, "RGBA").crop((mbb[0], mbb[1], mbb[2] + 1, mbb[3] + 1)).save(f"{OUT}/A4_bolt_seeded_rgba.png")

# --- validation ---
holes = int((ndimage.binary_fill_holes(matte) & ~matte).sum())
visor_opaque = bool(visor_seed.sum() > 0 and (visor_seed & ~matte).sum() == 0)
eyes = (B > R + 12) & (B > 90) & matte & head_reg
el, en = ndimage.label(eyes); esz = [int((el == i).sum()) for i in range(1, en + 1)]
n_eyes = int(sum(1 for s in esz if s > 40))
antenna = bool(((B > R + 10) & (B > 80) & matte)[:int(bb[1] + 0.10 * bh)].sum() > 10)
hand_area = int((matte & _box(0.55, 0.55, 0.72, 0.72)).sum()); hand_present = bool(hand_area > 3000)
fingertip_x = round(float(mbb[2]) / W, 3)                             # reaching-hand extent
cxm = (mbb[0] + mbb[2]) // 2
both_arms = bool(int(matte[:, :cxm - int(0.02 * W)].sum()) > 1500 and int(matte[:, cxm + int(0.02 * W):].sum()) > 1500)
chest = (B > R + 12) & (B > 90) & matte & _box(0.0, (bb[1] + 0.50 * bh) / H, 1.0, (bb[1] + 0.80 * bh) / H)
chest_present = bool(chest.sum() > 800)
base_present = bool(int(matte[int(bb[1] + 0.80 * bh):, :].sum()) > 2000)
# foreign background inside the matte (exclude the legit dark visor)
non_visor = matte & ~ndimage.binary_dilation(visor_seed, iterations=3)
plate_like = (np.abs(a0 - plate).mean(axis=2) < 13) & non_visor
term_green = (G > R + 30) & (G > B + 25) & (G > 110) & non_visor      # tight terminal-screen green (not Bolt mint)
foreign = plate_like | term_green | (red_sign & matte)
foreign_frac = round(float(foreign.sum()) / max(1, int(matte.sum())), 4)
checks = {
  "method": "scipy.ndimage.watershed_ift (seeded segmentation; GrabCut unavailable on cp314/PEP668)",
  "matte_area_px": int(matte.sum()), "internal_holes_px": holes, "no_internal_holes": bool(holes == 0),
  "visor_opaque": visor_opaque, "n_eyes": n_eyes, "exactly_two_eyes": bool(n_eyes == 2),
  "antenna_present": antenna, "hand_present": hand_present, "fingertip_x_frac": fingertip_x,
  "both_arms": both_arms, "chest_present": chest_present, "base_present": base_present,
  "foreign_bg_frac": foreign_frac, "zero_foreign_bg": bool(foreign_frac < 0.01), "bbox": mbb,
}
checks["all_requirements_met"] = bool(checks["no_internal_holes"] and visor_opaque and checks["exactly_two_eyes"]
                                      and antenna and hand_present and both_arms and chest_present and base_present
                                      and checks["zero_foreign_bg"])


def on_bg(bg_rgb):
    bg = np.zeros((H, W, 3), float); bg[:] = bg_rgb
    return (bg * (1 - alpha[..., None] / 255.0) + a0 * (alpha[..., None] / 255.0)).astype("uint8")


sqp = 40; yy, xx = np.mgrid[0:H, 0:W]; chk = ((xx // sqp + yy // sqp) % 2)
cbimg = np.where(chk[..., None] == 0, np.array([235, 235, 235]), np.array([170, 200, 235])).astype(float)
comp_chk = (cbimg * (1 - alpha[..., None] / 255.0) + a0 * (alpha[..., None] / 255.0)).astype("uint8")
comp_sat = on_bg([255, 110, 0])                                      # saturated orange solid
pad = 40; c = [max(0, mbb[0] - pad), max(0, mbb[1] - pad), min(W, mbb[2] + pad), min(H, mbb[3] + pad)]
board = Image.new("RGB", (2 * (c[2] - c[0]) + 30, (c[3] - c[1]) + 60), (20, 20, 22)); d = ImageDraw.Draw(board)
board.paste(Image.fromarray(comp_chk[c[1]:c[3], c[0]:c[2]]), (10, 46))
board.paste(Image.fromarray(comp_sat[c[1]:c[3], c[0]:c[2]]), (20 + (c[2] - c[0]), 46))
d.text((10, 6), f"SEEDED watershed | holes {holes} | visor_opaque {visor_opaque} | eyes {n_eyes} | hand {hand_present} | foreign {foreign_frac}", fill=(255, 220, 0))
d.text((10, 26), f"ALL_REQ_MET={checks['all_requirements_met']}  (left: bright checker | right: saturated solid)", fill=(120, 255, 120) if checks["all_requirements_met"] else (255, 120, 120))
board.save(f"{OUT}/A4_seeded_diag.png")

json.dump({"objective": "a4_seeded_extraction_one_method", "no_spend": True, "provider_called": False, "ALLOW_PAID": False,
           "opencv_grabcut": "unavailable (no cp314 wheel + PEP668); used scipy watershed_ift seeded segmentation instead",
           "checks": checks, "artifacts": {"rgba": "a4_collapse/seeded/A4_bolt_seeded_rgba.png", "diag": "a4_collapse/seeded/A4_seeded_diag.png"}},
          open(f"{AT}/a4_seeded_result.json", "w"), indent=2, default=str)
print(json.dumps(checks, indent=2, default=str)); print("DONE")
