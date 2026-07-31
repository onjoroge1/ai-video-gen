"""Reusable Bolt rig + collapse POSE LIBRARY from the APPROVED clean source (bolt_hover_run_dry.png).
Deterministic, NO SPEND, ALLOW_PAID=false, frozen H0/A1-A3/A3B untouched. Extracts clean keyable parts, tone-matches
to the dim teal corridor, authors P0 weak-hover / P1 fall / P2 impact / P3 floor-rest, and renders them on a bright
checkerboard (diagnostic) + composited in the corridor over a Bolt-removed plate. Identity + placement gates.
Run: python3 -m bolt_seq.build_A4_rig"""
import os, sys, json, hashlib
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"
OUT = f"{AT}/a4_collapse/rig"; os.makedirs(OUT, exist_ok=True)
SRC = "renders/bolt_seq/oxygen_subscription/bolt_hover_run_dry.png"
A4S = f"{AT}/a4_collapse/A4_start_frame.png"
W, H = 1080, 1920


def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()


# ---------- 1. load clean source, crop to content ----------
src = np.asarray(Image.open(SRC).convert("RGBA"), float)
sa = src[:, :, 3]
ys, xs = np.where(sa > 128); sy0, sy1, sx0, sx1 = ys.min(), ys.max(), xs.min(), xs.max()
src = src[sy0:sy1 + 1, sx0:sx1 + 1]; sa = src[:, :, 3]; srgb = src[:, :, :3]
sh, sw = sa.shape
mask = sa > 128
R, G, B = srgb[:, :, 0], srgb[:, :, 1], srgb[:, :, 2]

# ---------- 2. measure the corridor Bolt (placement + tone target) ----------
a4 = np.asarray(Image.open(A4S).convert("RGB").resize((W, H)), float)
# rough corridor-Bolt mask: teal/bright, lower-center, largest CC
ar, ag, ab = a4[:, :, 0], a4[:, :, 1], a4[:, :, 2]
cm = ((np.minimum(np.minimum(ar, ag), ab) > 55) | ((ab > ar + 8) & (ag > ar + 4) & (ab > 60)))
box = np.zeros((H, W), bool); box[850:1450, 150:820] = True; cm &= box
cm = ndimage.binary_closing(cm, iterations=3); cm = ndimage.binary_fill_holes(cm)
l, n = ndimage.label(cm); cm = l == (int(np.argmax(ndimage.sum(np.ones_like(l), l, range(1, n + 1)))) + 1)
cy, cx = np.where(cm); cby0, cby1, cbx0, cbx1 = cy.min(), cy.max(), cx.min(), cx.max()
corr_bbox = (int(cbx0), int(cby0), int(cbx1), int(cby1)); corr_w = cbx1 - cbx0; corr_h = cby1 - cby0
tgt_mean = [float(a4[:, :, c][cm].mean()) for c in range(3)]
tgt_std = [float(a4[:, :, c][cm].std()) for c in range(3)]
print("corridor Bolt bbox (x0,y0,x1,y1):", corr_bbox, "| w,h:", corr_w, corr_h)
print("corridor Bolt tone mean:", [round(v, 1) for v in tgt_mean], "std:", [round(v, 1) for v in tgt_std])

# ---------- 3. tone-match the clean source to the corridor (per-channel mean/std transfer) ----------
tone = srgb.astype(float).copy()
for c in range(3):
    v = srgb[:, :, c][mask]; m, s = v.mean(), v.std() + 1e-3
    tone[:, :, c][mask] = (v - m) / s * tgt_std[c] + tgt_mean[c]
tone = np.clip(0.85 * tone + 0.15 * srgb, 0, 255)                  # mostly corridor tone (dim) -> sits IN the scene
cyan_id = (B > R + 25) & (B > 120) & mask                          # keep identity cyan legible after dimming (as in the corridor original)
for c, k in ((0, 0.9), (1, 1.05), (2, 1.18)):
    tone[:, :, c][cyan_id] = np.clip(tone[:, :, c][cyan_id] * k, 0, 255)

# ---------- 4. part layers (pragmatic collapse rig, all from the clean source => identity guaranteed) ----------
tR, tG, tB = tone[:, :, 0], tone[:, :, 1], tone[:, :, 2]
cyan = (B > R + 25) & (B > 120) & mask                                  # bright cyan (eyes + chest) on ORIGINAL
yy, xx = np.mgrid[0:sh, 0:sw]
eyes_m = cyan & (yy > 0.16 * sh) & (yy < 0.42 * sh) & (xx > 0.28 * sw) & (xx < 0.80 * sw)   # eyes: visor cyan, excl. antenna bulb + chest
eyes_m = ndimage.binary_closing(eyes_m, iterations=4)                   # merge each eye oval into one blob
chest_m = cyan & (yy > 0.46 * sh) & (yy < 0.80 * sh)                    # chest panel: cyan mid-torso
top_band = yy < 0.16 * sh                                               # antenna stalk+bulb
antenna_m = mask & top_band
base_m = mask & (yy > 0.86 * sh)                                        # hover base (bottom disc)
body_m = mask & ~antenna_m                                             # body = everything except the antenna (eyes/chest ride with body)


def layer(rgb, m):
    o = np.zeros((sh, sw, 4)); o[:, :, :3] = rgb; o[:, :, 3] = np.where(m, sa, 0); return o


L_body = layer(tone, body_m); L_antenna = layer(tone, antenna_m)
# identity self-checks
n_eyes_lbl, ne = ndimage.label(eyes_m); n_eyes = sum(1 for i in range(1, ne + 1) if (n_eyes_lbl == i).sum() > 30)
ident = {"cyan_chest_panel_px": int(chest_m.sum()), "n_eye_blobs": int(n_eyes), "antenna_px": int(antenna_m.sum()),
         "hover_base_px": int(base_m.sum()), "src_sha256": sha(SRC),
         "eyes_bbox": [int(np.where(eyes_m)[1].min()), int(np.where(eyes_m)[0].min()), int(np.where(eyes_m)[1].max()), int(np.where(eyes_m)[0].max())] if eyes_m.any() else None}
print("identity:", ident)


# ---------- 5. pose synthesis ----------
def spr(pil_rgba): return pil_rgba
def to_pil(arr4): return Image.fromarray(np.clip(arr4, 0, 255).astype("uint8"), "RGBA")


def pose(tilt_deg, squash, eye_droop, antenna_flop, base_alpha, dim=0.0):
    """Compose one pose sprite (RGBA, source resolution). Power-down collapse: modest tilt (sag), heavy dim + eye-out."""
    Lb = L_body.copy(); La = L_antenna.copy()
    if dim > 0:                                                         # power-down: whole Bolt darkens toward off
        Lb[:, :, :3] = np.clip(Lb[:, :, :3] * (1 - 0.5 * dim), 0, 255); La[:, :, :3] = np.clip(La[:, :, :3] * (1 - 0.5 * dim), 0, 255)
    body = to_pil(Lb)
    # eye droop: paint dark visor over the eyes, then draw compressed cyan lenses
    bd = np.asarray(body, float).copy()
    if eyes_m.any():
        ey, ex = np.where(eyes_m); ecx = ex.mean()
        # dim the eyes toward closed: scale their brightness down + compress via a dark overlay from top/bottom
        for c in range(3):
            bd[:, :, c][eyes_m] = np.clip(bd[:, :, c][eyes_m] * (1 - 0.55 * eye_droop), 0, 255)
        # draw slit lids (dark visor color) closing in from top and bottom
        e0, e1 = ey.min(), ey.max(); eh = e1 - e0
        lid = int(eh * 0.5 * eye_droop)
        visor_dark = np.array([18, 26, 30])
        for (yy0, yy1) in [(e0, e0 + lid), (e1 - lid, e1)]:
            reg = eyes_m.copy(); rr = np.zeros_like(reg); rr[yy0:yy1] = True; reg &= rr
            for c in range(3): bd[:, :, c][reg] = visor_dark[c]
    body = to_pil(bd)
    # squash (vertical) on impact
    if squash > 0.01:
        nh = int(sh * (1 - 0.32 * squash)); nw = int(sw * (1 + 0.14 * squash))
        body = body.resize((nw, nh), Image.BICUBIC)
    # tilt (whole-body rotation, expand)
    body = body.rotate(tilt_deg, resample=Image.BICUBIC, expand=True)
    # antenna: flop + follow tilt
    ant = to_pil(La).rotate(tilt_deg + antenna_flop, resample=Image.BICUBIC, expand=True)
    # base: separate alpha (fades as it lifts off / hits floor)
    canvas = Image.new("RGBA", body.size, (0, 0, 0, 0))
    canvas.alpha_composite(body)
    # composite antenna centered-top (approx: same center)
    ax = (canvas.width - ant.width) // 2; canvas.alpha_composite(ant, (ax, 0))
    if base_alpha < 0.99:
        arr = np.asarray(canvas, float); by = np.mgrid[0:canvas.height, 0:canvas.width][0]
        lowf = by > canvas.height * 0.84
        arr[:, :, 3][lowf] = arr[:, :, 3][lowf] * base_alpha; canvas = to_pil(arr)
    return canvas


# POWER-DOWN collapse: primary motion = SINK (drop) + DIM + eyes-out; tilt is only a modest forward SAG (not a tumble)
POSES = {
  "P0_weak_hover":  dict(tilt_deg=-10, squash=0.00, eye_droop=0.55, antenna_flop=-6,  base_alpha=1.00, dim=0.00),
  "P1_sink":        dict(tilt_deg=-16, squash=0.04, eye_droop=0.80, antenna_flop=-16, base_alpha=0.55, dim=0.28),
  "P2_impact":      dict(tilt_deg=-22, squash=0.40, eye_droop=1.00, antenna_flop=-30, base_alpha=0.10, dim=0.50),
  "P3_floor_rest":  dict(tilt_deg=-24, squash=0.24, eye_droop=1.00, antenna_flop=-40, base_alpha=0.05, dim=0.62),
}
# note: negative tilt = modest nose-down forward sag (facing right)

# ---------- 6. placement/scale to the corridor bbox ----------
scale = corr_h / sh                                       # match the corridor Bolt on-screen height
place_cx = (corr_bbox[0] + corr_bbox[2]) / 2
floor_y = corr_bbox[3] + 40                               # collapse settles near the corridor floor line


def place(sprite, cx, bottom_y):
    s = sprite.resize((int(sprite.width * scale), int(sprite.height * scale)), Image.BICUBIC)
    x = int(cx - s.width / 2); y = int(bottom_y - s.height)
    return s, x, y


# ---------- 7. clean corridor plate (Bolt removed, directional corridor fill) ----------
plate = a4.copy(); fillm = ndimage.binary_dilation(cm, iterations=12)
idx = ndimage.distance_transform_edt(fillm, return_indices=True)[1]   # nearest corridor pixel for each hole pixel (NN inpaint)
plate_nn = plate.copy(); plate_nn[fillm] = plate[idx[0][fillm], idx[1][fillm]]
pb = np.asarray(Image.fromarray(plate_nn.astype("uint8")).filter(ImageFilter.GaussianBlur(9)), float)
plate_final = plate.copy(); plate_final[fillm] = pb[fillm]
Image.fromarray(plate_final.astype("uint8")).save(f"{OUT}/A4_clean_plate.png")


def composite_over(bg, sprite, cx, bottom_y, shadow=0.0):
    base = Image.fromarray(bg.astype("uint8")).convert("RGBA")
    if shadow > 0.01:                                                 # tracked floor contact shadow (grows P2->P3)
        shim = Image.new("RGBA", base.size, (0, 0, 0, 0)); sd = ImageDraw.Draw(shim)
        sw2 = int(corr_w * scale * 0.5 * (0.7 + 0.6 * shadow))
        sd.ellipse([cx - sw2, floor_y - 24, cx + sw2, floor_y + 46], fill=(0, 0, 0, int(150 * shadow)))
        base.alpha_composite(shim.filter(ImageFilter.GaussianBlur(22)))
    s, x, y = place(sprite, cx, bottom_y); base.alpha_composite(s, (x, y))
    return np.asarray(base.convert("RGB"), float)


# ---------- 8. render pose board: checker row + in-corridor row ----------
def checker(sprite):
    cw, ch = sprite.size; sq = 28; g0, g1 = np.mgrid[0:ch, 0:cw]
    chk = (((g0 // sq + g1 // sq) % 2)[..., None] * np.array([60, 60, 66]) + (1 - (g0 // sq + g1 // sq) % 2)[..., None] * np.array([210, 210, 216]))
    bg = Image.fromarray(chk.astype("uint8")).convert("RGBA"); bg.alpha_composite(sprite); return bg.convert("RGB")


poses_rgba = {k: pose(**v) for k, v in POSES.items()}
# in-corridor: P0 at hover height; P1..P3 SINK progressively to the floor
heights = {"P0_weak_hover": corr_bbox[3], "P1_sink": corr_bbox[3] + 135, "P2_impact": floor_y + 55, "P3_floor_rest": floor_y + 60}
shadows = {"P0_weak_hover": 0.0, "P1_sink": 0.15, "P2_impact": 0.70, "P3_floor_rest": 1.0}
incorr = {k: composite_over(plate_final, poses_rgba[k], place_cx, heights[k], shadows[k]) for k in POSES}

# save individual in-corridor poses + a comparison board
for k in POSES: Image.fromarray(incorr[k].astype("uint8")).save(f"{OUT}/{k}_in_corridor.png")
cell = 300
board = Image.new("RGB", (5 * cell + 30, 2 * 533 + 90), (14, 14, 16)); dd = ImageDraw.Draw(board)
# top row: A4_start (reference) + P0..P3 in corridor
dd.text((12, 4), "IN-CORRIDOR (over Bolt-removed plate):  A4_start (ref) | P0 weak-hover | P1 sink | P2 impact | P3 floor-rest", fill=(230, 230, 230))
board.paste(Image.fromarray(a4.astype("uint8")).resize((cell, 533)), (10, 24))
for i, k in enumerate(POSES): board.paste(Image.fromarray(incorr[k].astype("uint8")).resize((cell, 533)), ((i + 1) * cell + 10, 24))
# bottom row: checker diagnostics
dd.text((12, 24 + 533 + 20), "CHECKERBOARD DIAGNOSTIC (clean sprite alpha):  P0 | P1 | P2 | P3", fill=(230, 230, 230))
for i, k in enumerate(POSES):
    t = checker(poses_rgba[k]); t.thumbnail((cell - 8, 533)); tile = Image.new("RGB", (cell, 533), (40, 40, 44))
    tile.paste(t, ((cell - t.width) // 2, (533 - t.height) // 2)); board.paste(tile, (i * cell + 10, 24 + 533 + 44))
board.save(f"{OUT}/A4_rig_pose_board.png")

# ---------- 9. P0-vs-A4_start placement/tone match score ----------
p0_reg = incorr["P0_weak_hover"]; diff = np.abs(p0_reg[cby0:cby1, cbx0:cbx1] - a4[cby0:cby1, cbx0:cbx1]).mean()
result = {"objective": "A4_reusable_rig_and_pose_library", "no_spend": True, "provider_called": False, "ALLOW_PAID": False,
  "status": "RIG_BUILT — pose library P0-P3 rendered for review (NOT frozen; A4 collapse animatic next)",
  "canonical_source": {"path": SRC, "sha256": sha(SRC), "approved": "2026-07-29"},
  "corridor_placement": {"corr_bolt_bbox": corr_bbox, "corr_w_h": [int(corr_w), int(corr_h)], "scale": round(scale, 3), "place_cx": int(place_cx), "floor_y": int(floor_y)},
  "tone_target": {"mean": [round(v, 1) for v in tgt_mean], "std": [round(v, 1) for v in tgt_std]},
  "identity": ident,
  "poses": POSES,
  "P0_vs_A4start_region_mean_abs": round(float(diff), 2),
  "gates": {"identity_cyan_chest_panel": bool(ident["cyan_chest_panel_px"] > 200),
            "identity_two_eyes": bool(ident["n_eye_blobs"] == 2),
            "identity_antenna": bool(ident["antenna_px"] > 50),
            "identity_hover_base": bool(ident["hover_base_px"] > 200),
            "pose_count_4": len(POSES) == 4},
  "artifacts": {"pose_board": "a4_collapse/rig/A4_rig_pose_board.png", "clean_plate": "a4_collapse/rig/A4_clean_plate.png",
                "poses_in_corridor": [f"a4_collapse/rig/{k}_in_corridor.png" for k in POSES]}}
json.dump(result, open(f"{AT}/a4_collapse/A4_rig_result.json", "w"), indent=2, default=str)
print(json.dumps(result["gates"], indent=2))
print("P0-vs-A4_start region mean_abs:", result["P0_vs_A4start_region_mean_abs"])
print("DONE")
