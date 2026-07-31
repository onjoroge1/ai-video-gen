"""A4 master-matte REBUILD (NO SPEND). Produces a COMPLETE, hole-free, background-free Bolt master from the exact A4
start frame: opaque dark visor (explicit interior fill), both cyan eyes, full head shell + mint trim, both arms/hands/
fingers, antenna+bulb, torso/chest/hover-base — and NO corridor/terminal/floor/signage/nozzle. Verified on a BRIGHT
checkerboard so any missing visor pixel or matte hole is obvious. Run: python3 -m bolt_seq.rebuild_A4_master"""
import os, sys, json
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

W, H = 1080, 1920
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"; OUT = f"{AT}/a4_collapse/rig"; os.makedirs(OUT, exist_ok=True)
a0 = np.asarray(Image.open(f"{AT}/a4_collapse/A4_start_frame.png").convert("RGB").resize((W, H)), float)
plate = np.asarray(Image.open(f"{AT}/a4_collapse/A4_clean_plate.png").convert("RGB").resize((W, H)), float)
R, G, B = a0[:, :, 0], a0[:, :, 1], a0[:, :, 2]
mn = np.minimum(np.minimum(R, G), B); mx = np.maximum(np.maximum(R, G), B); gray = a0.mean(axis=2)


def _box(x0, y0, x1, y1):
    m = np.zeros((H, W), bool); m[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)] = True; return m


# terminal+nozzles come from the PLATE (Bolt is not in the plate) -> excluding plate-bright there removes the nozzle
# fragment while keeping Bolt's white hand (which sits over dark corridor, not over the plate's bright metal).
term_ex = ndimage.binary_dilation((plate.mean(axis=2) > 70) & _box(0.55, 0.50, 0.86, 0.64), iterations=2)  # LOWER nozzle band only (don't cut the head/visor/eyes)
GEN = _box(0.08, 0.28, 0.72, 0.80)                                # generous Bolt region incl. the reaching hand
white = mn > 90; mint = (G > R + 3) & (G > 85) & (mn > 50) & ((mx - mn) < 100); cyan = (B > R + 8) & (B > 68)  # lower thr -> DIM weakened eyes
seed = (white | mint | cyan) & GEN & ~term_ex
seed = ndimage.binary_closing(seed, iterations=3)
lbl, n = ndimage.label(seed); sz = ndimage.sum(np.ones_like(lbl), lbl, range(1, n + 1))
seed_cc = lbl == (int(np.argmax(sz)) + 1)
sy, sx = np.where(seed_cc); tb = [sx.min(), sy.min(), sx.max(), sy.max()]; bh = tb[3] - tb[1]
# opaque VISOR via SOLID HEAD-DOME fill: aggressively close the head-shell ring so the dark visor interior (which
# opens to the exterior and so is not an enclosed hole) becomes opaque; the cyan eyes sit on top of the solid dome.
head_band = np.zeros((H, W), bool); head_band[tb[1]:int(tb[1] + 0.60 * bh), tb[0]:tb[2]] = True
head_reg = np.zeros((H, W), bool); head_reg[tb[1]:int(tb[1] + 0.48 * bh), tb[0]:tb[2]] = True
head_solid = ndimage.binary_fill_holes(ndimage.binary_closing(seed_cc & head_reg, iterations=15))
grown = ndimage.binary_dilation(seed_cc, iterations=16)
dark_visor = (gray < 108) & grown & head_band & ~term_ex                 # explicit opaque dark visor interior
FLOOR_EX = _box(0.50, 0.71, 0.86, 0.86)                                  # corridor floor blob near the terminal (below/right of the hand)
matte = (seed_cc | head_solid | dark_visor) & ~FLOOR_EX & ~term_ex
matte = ndimage.binary_fill_holes(ndimage.binary_closing(matte, iterations=4))
matte = ndimage.binary_opening(matte, iterations=2)                      # sever thin floor/nozzle bridges
lbl2, n2 = ndimage.label(matte); sz2 = ndimage.sum(np.ones_like(lbl2), lbl2, range(1, n2 + 1))
matte = ndimage.binary_fill_holes(lbl2 == (int(np.argmax(sz2)) + 1))     # single CC + no internal holes
alpha = (matte * 255).astype("uint8")                                    # HARD alpha -> fully opaque interior (visor incl.)
rgba = np.dstack([a0, alpha]).astype("uint8")
master = Image.fromarray(rgba, "RGBA")
by, bx = np.where(matte); mbb = [int(bx.min()), int(by.min()), int(bx.max()), int(by.max())]
master.crop((mbb[0], mbb[1], mbb[2] + 1, mbb[3] + 1)).save(f"{OUT}/A4_bolt_master_rgba.png")
np.save(f"{OUT}/_master_matte.npy", matte)

# --- completeness self-checks ---
al = matte
holes = int((ndimage.binary_fill_holes(al) & ~al).sum())                 # internal transparent holes (want 0)
# visor: dark region inside the head is OPAQUE now
visor = (gray < 100) & al & head_band; visor_frac = round(float(visor.sum()) / max(1, int(al.sum())), 4)
# eyes: cyan blobs inside the visor region
eyemask = (B > R + 15) & (B > 90) & al & head_band
el, en = ndimage.label(eyemask); esz = [int((el == i).sum()) for i in range(1, en + 1)]
n_eyes = int(sum(1 for s in esz if s > 30))
# antenna: cyan bulb in the top band
antenna = bool(((B > R + 15) & (B > 90) & al & _box(0.0, 0.0, 1.0, 0.02 + (tb[1] + 0.10 * bh) / H)).sum() > 12) or \
          bool(((B > R + 15) & (B > 90) & al)[:int(tb[1] + 0.12 * bh)].sum() > 12)
# arms present on both sides of the torso centre
cxm = (mbb[0] + mbb[2]) // 2
left_arm = int((al[:, :cxm - int(0.02 * W)]).sum()); right_arm = int((al[:, cxm + int(0.02 * W):]).sum())
# background contamination inside the matte (terminal-green / red-signage / plate-match, excluding the legit dark visor)
plate_like = (np.abs(a0 - plate).mean(axis=2) < 14) & al & ~visor
term_green = (G > R + 25) & (G > B + 15) & (G > 90) & al
red_sign = (R > G + 40) & (R > B + 40) & al
checks = {
  "matte_area_px": int(al.sum()), "single_component": bool(n2 >= 1 and int((ndimage.label(al)[1])) == 1),
  "internal_holes_px": holes, "no_internal_holes": bool(holes == 0),
  "visor_opaque_frac": visor_frac, "visor_present": bool(visor_frac > 0.02),
  "n_eyes_in_visor": n_eyes, "exactly_two_eyes": bool(n_eyes == 2),
  "antenna_present": antenna,
  "left_arm_px": left_arm, "right_arm_px": right_arm, "both_arms_present": bool(left_arm > 1500 and right_arm > 1500),
  "bg_plate_like_frac": round(float(plate_like.sum()) / max(1, int(al.sum())), 4),
  "bg_terminal_green_frac": round(float(term_green.sum()) / max(1, int(al.sum())), 4),
  "bg_red_signage_frac": round(float(red_sign.sum()) / max(1, int(al.sum())), 4),
  "bbox": mbb,
}
checks["no_foreign_bg"] = bool(checks["bg_plate_like_frac"] < 0.03 and checks["bg_terminal_green_frac"] < 0.003 and checks["bg_red_signage_frac"] < 0.003)

# --- BRIGHT checkerboard diagnostic (missing pixels/holes cannot hide) ---
sqp = 40; cb = np.zeros((H, W, 3), float)
yy, xx = np.mgrid[0:H, 0:W]
chk = ((xx // sqp + yy // sqp) % 2)
cb[chk == 0] = [235, 235, 235]; cb[chk == 1] = [175, 200, 235]         # bright light/blue checker
al_f = alpha[..., None] / 255.0
comp = cb * (1 - al_f) + a0 * al_f
comp = comp.astype("uint8")
# crop to a padded bbox for the review
pad = 40; cy0, cy1 = max(0, mbb[1] - pad), min(H, mbb[3] + pad); cx0, cx1 = max(0, mbb[0] - pad), min(W, mbb[2] + pad)
diag = Image.fromarray(comp[cy0:cy1, cx0:cx1]); dd = ImageDraw.Draw(diag)
dd.text((8, 6), f"MASTER on bright checker | holes {holes} | eyes {n_eyes} | visor {visor_frac} | arms L{left_arm} R{right_arm}", fill=(200, 0, 0))
dd.text((8, 26), f"no_holes={checks['no_internal_holes']} 2eyes={checks['exactly_two_eyes']} antenna={antenna} arms={checks['both_arms_present']} no_bg={checks['no_foreign_bg']}", fill=(180, 0, 0))
diag.save(f"{OUT}/A4_master_checkerboard_diag.png")

json.dump({"objective": "a4_master_matte_rebuild", "no_spend": True, "provider_called": False, "ALLOW_PAID": False,
           "completeness_checks": checks,
           "all_complete": bool(checks["no_internal_holes"] and checks["visor_present"] and checks["exactly_two_eyes"] and checks["antenna_present"] and checks["both_arms_present"] and checks["no_foreign_bg"]),
           "artifacts": {"master_rgba": "a4_collapse/rig/A4_bolt_master_rgba.png", "checkerboard_diag": "a4_collapse/rig/A4_master_checkerboard_diag.png"}},
          open(f"{AT}/a4_master_rebuild_result.json", "w"), indent=2, default=str)
print(json.dumps(checks, indent=2)); print("DONE")
