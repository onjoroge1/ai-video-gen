"""Shared reusable Bolt rig core built from the APPROVED clean source (bolt_hover_run_dry.png).
Imported by build_A4_rig (pose board) and build_A4_collapse (66-frame animatic) so both use the EXACT same rig.
Deterministic, NO SPEND. Exposes: pose(), place(), composite_over(), plate_final, corr_bbox, scale, place_cx,
floor_y, identity, POSES_REF, sha(). All frozen H0/A1-A3/A3B assets are untouched."""
import os, sys, hashlib
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"
SRC = "renders/bolt_seq/oxygen_subscription/bolt_hover_run_dry.png"
A4S = f"{AT}/a4_collapse/A4_start_frame.png"
W, H = 1080, 1920


def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()


# 1. clean source, cropped to content
src = np.asarray(Image.open(SRC).convert("RGBA"), float)
_ys, _xs = np.where(src[:, :, 3] > 128)
src = src[_ys.min():_ys.max() + 1, _xs.min():_xs.max() + 1]
sa = src[:, :, 3]; srgb = src[:, :, :3]; sh, sw = sa.shape; mask = sa > 128
R, G, B = srgb[:, :, 0], srgb[:, :, 1], srgb[:, :, 2]

# 2. corridor Bolt (placement + tone target)
a4 = np.asarray(Image.open(A4S).convert("RGB").resize((W, H)), float)
ar, ag, ab = a4[:, :, 0], a4[:, :, 1], a4[:, :, 2]
cm = ((np.minimum(np.minimum(ar, ag), ab) > 55) | ((ab > ar + 8) & (ag > ar + 4) & (ab > 60)))
_box = np.zeros((H, W), bool); _box[850:1450, 150:820] = True; cm &= _box
cm = ndimage.binary_fill_holes(ndimage.binary_closing(cm, iterations=3))
_l, _n = ndimage.label(cm); cm = _l == (int(np.argmax(ndimage.sum(np.ones_like(_l), _l, range(1, _n + 1)))) + 1)
_cy, _cx = np.where(cm); corr_bbox = (int(_cx.min()), int(_cy.min()), int(_cx.max()), int(_cy.max()))
corr_w = corr_bbox[2] - corr_bbox[0]; corr_h = corr_bbox[3] - corr_bbox[1]
tgt_mean = [float(a4[:, :, c][cm].mean()) for c in range(3)]; tgt_std = [float(a4[:, :, c][cm].std()) for c in range(3)]

# 3. tone-match to corridor (dim/teal) + keep identity cyan legible
tone = srgb.astype(float).copy()
for c in range(3):
    v = srgb[:, :, c][mask]; m, s = v.mean(), v.std() + 1e-3
    tone[:, :, c][mask] = (v - m) / s * tgt_std[c] + tgt_mean[c]
tone = np.clip(0.85 * tone + 0.15 * srgb, 0, 255)
cyan_id = (B > R + 25) & (B > 120) & mask
for c, k in ((0, 0.92), (1, 1.0), (2, 1.06)):        # gentle: keep chest legible but do NOT over-brighten the eyes (they must DIM on power-down)
    tone[:, :, c][cyan_id] = np.clip(tone[:, :, c][cyan_id] * k, 0, 255)

# 4. part layers
yy, xx = np.mgrid[0:sh, 0:sw]
cyan = (B > R + 25) & (B > 120) & mask
eyes_m = cyan & (yy > 0.16 * sh) & (yy < 0.42 * sh) & (xx > 0.28 * sw) & (xx < 0.80 * sw)
eyes_m = ndimage.binary_closing(eyes_m, iterations=4)
chest_m = cyan & (yy > 0.46 * sh) & (yy < 0.80 * sh)
antenna_m = mask & (yy < 0.16 * sh)
base_m = mask & (yy > 0.86 * sh)
body_m = mask & ~antenna_m
_ne_l, _ne = ndimage.label(eyes_m); n_eyes = sum(1 for i in range(1, _ne + 1) if (_ne_l == i).sum() > 30)
identity = {"cyan_chest_panel_px": int(chest_m.sum()), "n_eye_blobs": int(n_eyes), "antenna_px": int(antenna_m.sum()),
            "hover_base_px": int(base_m.sum()), "src_sha256": sha(SRC)}


def _layer(rgb, m):
    o = np.zeros((sh, sw, 4)); o[:, :, :3] = rgb; o[:, :, 3] = np.where(m, sa, 0); return o


L_body = _layer(tone, body_m); L_antenna = _layer(tone, antenna_m)


def _to_pil(a4arr): return Image.fromarray(np.clip(a4arr, 0, 255).astype("uint8"), "RGBA")


def pose(tilt_deg, squash, eye_droop, antenna_flop, base_alpha, dim=0.0):
    """One power-down pose sprite (RGBA, source res). Modest sag tilt; heavy dim + eyes-out on power loss."""
    Lb = L_body.copy(); La = L_antenna.copy()
    if dim > 0:
        Lb[:, :, :3] = np.clip(Lb[:, :, :3] * (1 - 0.62 * dim), 0, 255); La[:, :, :3] = np.clip(La[:, :, :3] * (1 - 0.62 * dim), 0, 255)
    bd = np.asarray(_to_pil(Lb), float).copy()
    if eyes_m.any() and eye_droop > 0.01:                              # eyes power down: dim cores toward OFF + close lids from top/bottom
        for c in range(3): bd[:, :, c][eyes_m] = np.clip(bd[:, :, c][eyes_m] * (1 - 0.92 * eye_droop), 0, 255)
        ey = np.where(eyes_m)[0]; e0, e1 = ey.min(), ey.max(); lid = int((e1 - e0) * 0.5 * eye_droop)
        for (y0, y1) in [(e0, e0 + lid), (e1 - lid, e1)]:
            reg = eyes_m.copy(); rr = np.zeros_like(reg); rr[y0:y1] = True; reg &= rr
            for c, cv in enumerate((18, 26, 30)): bd[:, :, c][reg] = cv
    body = _to_pil(bd)
    if squash > 0.01:
        body = body.resize((int(sw * (1 + 0.14 * squash)), int(sh * (1 - 0.32 * squash))), Image.BICUBIC)
    body = body.rotate(tilt_deg, resample=Image.BICUBIC, expand=True)
    ant = _to_pil(La).rotate(tilt_deg + antenna_flop, resample=Image.BICUBIC, expand=True)
    canvas = Image.new("RGBA", body.size, (0, 0, 0, 0)); canvas.alpha_composite(body)
    canvas.alpha_composite(ant, ((canvas.width - ant.width) // 2, 0))
    if base_alpha < 0.99:
        arr = np.asarray(canvas, float); by = np.mgrid[0:canvas.height, 0:canvas.width][0]
        low = by > canvas.height * 0.84; arr[:, :, 3][low] = arr[:, :, 3][low] * base_alpha; canvas = _to_pil(arr)
    return canvas


scale = corr_h / sh
place_cx = (corr_bbox[0] + corr_bbox[2]) / 2
floor_y = corr_bbox[3] + 40


def place(sprite, cx, bottom_y):
    s = sprite.resize((int(sprite.width * scale), int(sprite.height * scale)), Image.BICUBIC)
    return s, int(cx - s.width / 2), int(bottom_y - s.height)


# 5. clean corridor plate — use the pre-existing INTACT Bolt-free plate (root); fall back to NN-inpaint only if missing
CLEAN_PLATE = f"{AT}/a4_collapse/A4_clean_plate.png"
if os.path.exists(CLEAN_PLATE):
    plate_final = np.asarray(Image.open(CLEAN_PLATE).convert("RGB").resize((W, H)), float)
else:
    _plate = a4.copy(); fillm = ndimage.binary_dilation(cm, iterations=12)
    _idx = ndimage.distance_transform_edt(fillm, return_indices=True)[1]
    _nn = _plate.copy(); _nn[fillm] = _plate[_idx[0][fillm], _idx[1][fillm]]
    _pb = np.asarray(_to_pil(np.dstack([_nn, np.full((H, W), 255)])).convert("RGB").filter(ImageFilter.GaussianBlur(9)), float)
    plate_final = _plate.copy(); plate_final[fillm] = _pb[fillm]


def composite_over(bg, sprite, cx, bottom_y, shadow=0.0, plume=0.0, reflect=0.0):
    base = Image.fromarray(bg.astype("uint8")).convert("RGBA")
    s, x, y = place(sprite, cx, bottom_y)
    if shadow > 0.01:                                                   # contact shadow tracks the Bolt's base (grounds it)
        shim = Image.new("RGBA", base.size, (0, 0, 0, 0)); sd = ImageDraw.Draw(shim)
        sw2 = int(s.width * 0.55 * (0.7 + 0.6 * shadow))
        sd.ellipse([cx - sw2, bottom_y - 22, cx + sw2, bottom_y + 42], fill=(0, 0, 0, int(195 * shadow)))
        base.alpha_composite(shim.filter(ImageFilter.GaussianBlur(20)))
    if reflect > 0.02:                                                  # faint reflection on the wet metal deck
        refl = s.transpose(Image.FLIP_TOP_BOTTOM); ra = np.asarray(refl, float); ra[:, :, 3] = ra[:, :, 3] * 0.22 * reflect; base.alpha_composite(_to_pil(ra), (int(x), int(bottom_y)))
    if plume > 0.02:                                                    # dying hover plume under the base
        pim = Image.new("RGBA", base.size, (0, 0, 0, 0)); pd = ImageDraw.Draw(pim)
        pw = int(30 * plume); py = y + s.height
        pd.ellipse([cx - pw, py - 6, cx + pw, py + int(70 * plume)], fill=(120, 220, 235, int(120 * plume)))
        base.alpha_composite(pim.filter(ImageFilter.GaussianBlur(10)))
    base.alpha_composite(s, (x, y))
    return np.asarray(base.convert("RGB"), float)


POSES_REF = {
  "P0_weak_hover":  dict(tilt_deg=-10, squash=0.00, eye_droop=0.55, antenna_flop=-6,  base_alpha=1.00, dim=0.00),
  "P1_sink":        dict(tilt_deg=-16, squash=0.04, eye_droop=0.80, antenna_flop=-16, base_alpha=0.55, dim=0.28),
  "P2_impact":      dict(tilt_deg=-22, squash=0.40, eye_droop=1.00, antenna_flop=-30, base_alpha=0.10, dim=0.50),
  "P3_floor_rest":  dict(tilt_deg=-24, squash=0.24, eye_droop=1.00, antenna_flop=-40, base_alpha=0.05, dim=0.62),
}
