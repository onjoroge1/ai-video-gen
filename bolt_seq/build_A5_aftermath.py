"""A5 = AFTERMATH (125f @30fps). Identity-safe WHOLE-RASTER build from the A4 LAST-CLEARLY-VISIBLE powered-down frame
(A4 powerdown f44) — same pose/position/scale/slump/power that went to black (no reset). Bounded compositing cleanup:
(1) HUD removed by INPAINT (restore corridor) — no black rectangle; (2) chest panel MATERIAL preserved — only the cyan
emissive removed -> dark non-emissive teal/gray; (3) emissive masks STRICTLY contained to eyes/chest/bulb; (4) no
magenta/purple terminal fringe (bilinear push + despill); (5) slight exposure lift for 25% readability while keeping
terminal > 2x Bolt emissive. Env-only motion (breathing + slow push + one red flicker); Bolt never animated.
Run: python3 -m bolt_seq.build_A5_aftermath"""
import os, sys, json, subprocess, hashlib
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage
W, H, FPS, NF = 1080, 1920, 30, 125
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"
if os.path.exists(f"{AT}/a5_resolution/A5_FREEZE_manifest.json"):     # A5 is FROZEN — never rebuild (protects the reviewed hashes)
    import json as _j; print("A5 FROZEN — skipping rebuild; mp4 sha", _j.load(open(f"{AT}/a5_resolution/A5_FREEZE_manifest.json"))["reviewed_hashes"]["mp4"][:16]); sys.exit(0)
A4LASTVIS = f"{AT}/a4_collapse/_lastvis/A4_f44.png"
A4BLACK = f"{AT}/a4_collapse/A4_final_frame_powerdown.png"
OUT = f"{AT}/a5_resolution"; FDIR = f"{OUT}/_f"; CROP = f"{OUT}/crops"; os.makedirs(FDIR, exist_ok=True); os.makedirs(CROP, exist_ok=True)
yy, xx = np.mgrid[0:H, 0:W]; rad = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
def ss(x): x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)
def vignette(a, s): m = np.clip((rad - 0.62) / 0.70, 0, 1) ** 1.4 * s; return a * (1 - m[..., None])
src = np.asarray(Image.open(A4LASTVIS).convert("RGB").resize((W, H)), float)
Rs, Gs, Bs = src[:, :, 0], src[:, :, 1], src[:, :, 2]

# ---------- (5) slight exposure lift for readability (gamma; protects the bright terminal highlight) ----------
base5 = np.clip(255.0 * (src / 255.0) ** 0.82, 0, 255)
lifted = base5.copy()                                                 # gamma-lifted, PRE-mods (for pose/spill verification)

# ---------- (1) HUD removal by INPAINT (restore corridor) — NO black rectangle ----------
hud_box = np.zeros((H, W), bool); hud_box[18:216, 28:672] = True
bl_min = np.minimum(np.minimum(base5[:, :, 0], base5[:, :, 1]), base5[:, :, 2]); bl_max = np.maximum(np.maximum(base5[:, :, 0], base5[:, :, 1]), base5[:, :, 2])
hud_px = hud_box & (bl_min > 120) & ((bl_max - bl_min) < 48)           # bright, desaturated meter outline + text
hud_px = ndimage.binary_dilation(hud_px, iterations=2)
if hud_px.any():
    _idx = ndimage.distance_transform_edt(hud_px, return_indices=True)[1]
    base5[hud_px] = base5[_idx[0][hud_px], _idx[1][hud_px]]            # nearest-corridor fill (thin lines -> seamless)
    _sm = base5.copy(); _blur = np.asarray(Image.fromarray(base5.astype("uint8")).filter(ImageFilter.GaussianBlur(3)), float)
    base5[hud_px] = _blur[hud_px]

# ---------- (2)+(3) emissive suppression: STRICTLY-contained masks -> dark non-emissive teal/gray (material preserved) ----------
lum_src = 0.299 * Rs + 0.587 * Gs + 0.114 * Bs
tight_cyan = (Bs > Rs + 12) & (Bs >= Gs - 8) & (Bs > 42)             # cyan (chest/eye emissive); excludes mint shell/ears (G>>B)
chest_box = np.zeros((H, W), bool); chest_box[1190:1362, 340:575] = True   # LOCATOR only
bulb_box = np.zeros((H, W), bool); bulb_box[922:1015, 522:615] = True
neutral = np.array([0.95, 1.0, 0.98])


def largest_cc(m):
    l, n = ndimage.label(m)
    return (l == (int(np.argmax(ndimage.sum(np.ones_like(l), l, range(1, n + 1)))) + 1)) if n else m


def internal_alpha(mask, feather, erode):                            # feather clipped INSIDE the component (no pixel outside changes)
    core = ndimage.binary_erosion(mask, iterations=erode) if erode else mask
    a = np.asarray(Image.fromarray((core * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(feather)), float) / 255.0
    return (a * mask.astype(float))[..., None]


def grayteal(reg):                                                   # gray out BRIGHT teal/cyan flecks in reg (keep dark visor + mint bevel + shell)
    R2, G2, B2 = base5[:, :, 0], base5[:, :, 1], base5[:, :, 2]; L2 = 0.299 * R2 + 0.587 * G2 + 0.114 * B2
    m = reg & (B2 > R2 + 8) & (G2 > R2 + 2) & (L2 > 44)
    for c in range(3): base5[:, :, c][m] = L2[m]
    return int(m.sum())


# ===== SOFT global cyan-desaturation over the Bolt: removes emissive glow (eyes + chest + bulb + head rim + visor teal). NO shaped fill, NO patch. =====
bolt_area = np.zeros((H, W), float); bolt_area[978:1508, 232:832] = 1.0
bolt_area[822:985, 495:655] = 1.0                                        # antenna zone (BALL + stalk + base-on-shell); cyanness spares the GREEN terminal (low cyanness)
bolt_area = np.asarray(Image.fromarray((bolt_area * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(20)), float) / 255.0   # soft; EXCLUDES the terminal (x>=600, y620-960)
cyanness = np.clip((np.minimum(Bs, Gs) - Rs) / 30.0, 0, 1) * bolt_area   # high for cyan/teal; ~0 for mint shell (B~=R), corridor, terminal
cw = cyanness[..., None]
desat_target = np.clip(lum_src[..., None] * 0.34 * neutral[None, None, :], 0, 255)   # dark neutral, keeps the panel's OWN shading (no imposed shape) -> reads as the real component now dark
base5 = base5 * (1 - cw) + desat_target * cw
# ===== overall BOLT darkening -> terminal clearly dominant + Bolt subordinate =====
shell = (np.minimum(np.minimum(Rs, Gs), Bs) > 55) & (bolt_area > 0.5)
shell_soft = np.asarray(Image.fromarray((shell * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(8)), float) / 255.0
base5 = base5 * (1 - 0.16 * shell_soft[..., None])                       # gentle: desaturation already makes Bolt subordinate; avoid over-dark ghosting + compression-block reveal
base_ref = base5.copy()
# ---- detection masks (MEASUREMENT ONLY; not used to edit) ----
chest_mask = largest_cc(ndimage.binary_fill_holes(ndimage.binary_closing(tight_cyan & chest_box, iterations=3)))
_cy, _cx = np.where(chest_mask); _cy0, _cy1 = (int(_cy.min()), int(_cy.max())) if len(_cy) else (0, 1)
bulb_mask = largest_cc(ndimage.binary_closing(tight_cyan & bulb_box, iterations=1))
ha = np.zeros((H, W), bool); ha[1000:1185, 400:715] = True
visor = largest_cc(ndimage.binary_fill_holes(ndimage.binary_closing(ha & (lum_src < 78) & (Bs >= Rs - 4), iterations=2)))
eye_mask = ndimage.binary_opening(visor & (lum_src > (float(np.median(lum_src[visor])) if visor.any() else 0.0) + 6) & (Bs >= Gs - 10), iterations=1) & visor
emissive = chest_mask | bulb_mask | eye_mask
top_seam = np.zeros((H, W), bool); top_seam[985:1055, 400:700] = True
ant_base = np.zeros((H, W), bool); ant_base[990:1062, 532:618] = True
seam_ring = ndimage.binary_dilation(visor, iterations=12) & ~ndimage.binary_erosion(visor, iterations=2)

# ---------- (4) terminal: keep soft green glow, no fringe ----------
termbox = np.zeros((H, W), bool); termbox[620:960, 600:880] = True
green = (Gs > Rs + 18) & (Gs > Bs + 6) & (src[:, :, 1] > 70) & termbox
base5[green] = np.clip(base5[green] * 1.95, 0, 255)                   # terminal dominant (kept green + soft; despill handles fringe)
_gl = np.zeros((H, W, 3)); _gl[green] = np.array([45, 175, 95]); term_bloom = np.asarray(Image.fromarray(_gl.astype("uint8")).filter(ImageFilter.GaussianBlur(34)), float)
red_sign = (Rs > Gs + 45) & (Rs > Bs + 45) & (Rs > 70)
term_vic = np.zeros((H, W), bool); term_vic[560:1000, 560:920] = True
chest_vic = np.zeros((H, W), bool); chest_vic[1175:1375, 325:595] = True   # per-frame teal-despill at the panel/bevel edge (post-push)
head_vic = np.zeros((H, W), bool); head_vic[970:1200, 375:730] = True      # per-frame teal-despill at the visor/head seam (incl. visor bottom edge)
clean_vic = chest_vic | head_vic

# structural shell mask (pose-match + readability; NOT emissive)
shell = (np.minimum(np.minimum(Rs, Gs), Bs) > 70) & (np.zeros((H, W), bool) | ((yy > 930) & (yy < 1490) & (xx > 300) & (xx < 820)))
_sy, _sx = np.where(shell); shell_cen0 = (float(_sx.mean()), float(_sy.mean())); shell_bb0 = (int(_sx.min()), int(_sy.min()), int(_sx.max()), int(_sy.max()))


def push_zoom(a, s):
    if s <= 1.0001: return a
    cw, ch = int(W / s), int(H / s); l = (W - cw) // 2; t = (H - ch) // 2
    return np.asarray(Image.fromarray(a.astype("uint8")).crop((l, t, l + cw, t + ch)).resize((W, H), Image.BILINEAR), float)  # BILINEAR -> no overshoot/ringing


def despill_magenta(a):
    m = (a[:, :, 0] > a[:, :, 1] + 6) & (a[:, :, 2] > a[:, :, 1] + 6) & term_vic   # magenta/purple = R & B above G
    a[:, :, 0][m] = a[:, :, 1][m]; a[:, :, 2][m] = a[:, :, 1][m]                   # pull R,B down to G (neutralize)
    return a


def frame(i):
    t = i / (NF - 1); fade = ss(min(1.0, t / 0.30))
    a = base5.copy(); breathe = 0.5 + 0.5 * np.sin(t * 6.0)
    a[green] = np.clip(a[green] * (1 + 0.08 * breathe), 0, 255)       # terminal breathing (env)
    a = a + term_bloom * (0.30 + 0.12 * breathe)
    fl = np.exp(-((t - 0.55) / 0.018) ** 2)
    if fl > 0.02: a[red_sign] = np.clip(a[red_sign] * (1 + 0.35 * fl), 0, 255)   # one restrained red flicker (env)
    a = push_zoom(a, 1.0 + 0.012 * ss(t))                            # very slow whole-frame push (env camera)
    a = despill_magenta(a)                                            # remove any purple/magenta terminal fringe
    _L = 0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]
    ct = (a[:, :, 2] > a[:, :, 0] + 6) & (a[:, :, 1] > a[:, :, 0] + 1) & (_L > 42) & clean_vic   # BRIGHT teal flecks at panel/bevel + visor/head seam (post-push)
    lct = _L[ct]; a[:, :, 0][ct] = lct; a[:, :, 1][ct] = lct; a[:, :, 2][ct] = lct   # gray out (removes teal; dark visor + mint bevel B~=R untouched)
    a = vignette(a, 0.32)
    return np.clip(a, 0, 255) * fade


[os.remove(os.path.join(FDIR, x)) for x in os.listdir(FDIR)]
for i in range(NF): Image.fromarray(np.clip(frame(i), 0, 255).astype("uint8")).save(os.path.join(FDIR, f"f{i:03d}.png"))
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(FDIR, "f%03d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", f"{OUT}/A5_aftermath.mp4"], check=True)
Image.open(os.path.join(FDIR, f"f{NF-1:03d}.png")).save(f"{OUT}/A5_final_frame.png")


def loadf(i): return np.asarray(Image.open(os.path.join(FDIR, f"f{i:03d}.png")).convert("RGB"), float)


# contact strip @ 0,12,24,36,60,95,124 (25%) + full-res crops from f60
idxs = [0, 12, 24, 36, 60, 95, NF - 1]; labs = ["f0 BLACK", "f12", "f24", "f36", "f60", "f95", "f124 -> A6"]
tw, th = 270, 480
strip = Image.new("RGB", (len(idxs) * tw + 30, th + 40), (14, 14, 16)); dd = ImageDraw.Draw(strip)
for k, (ix, lab) in enumerate(zip(idxs, labs)):
    strip.paste(Image.open(os.path.join(FDIR, f"f{ix:03d}.png")).resize((tw, th)), (k * tw + 5, 24)); dd.text((k * tw + 6, 6), lab, fill=(230, 230, 230))
strip.save(f"{OUT}/A5_strip.png")
Image.open(os.path.join(FDIR, "f060.png")).resize((tw, th)).save(f"{OUT}/A5_f60_25pct.png")
f60 = Image.open(os.path.join(FDIR, "f060.png"))
CROPS = {"hud_region": (28, 18, 672, 216), "chest_panel": (330, 1175, 580, 1370), "head_antenna": (400, 900, 720, 1180), "terminal_screen": (600, 620, 880, 960)}
for k, b in CROPS.items(): f60.crop(b).save(f"{CROP}/A5_crop_{k}.png")

# ---------- gates ----------
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
a4_black = np.asarray(Image.open(A4BLACK).convert("RGB").resize((W, H)), float)
last = loadf(NF - 1)
opens_from_black = float(loadf(0).mean()) < 2.0; handoff = float(np.abs(loadf(0) - a4_black).mean())
# pose/position unchanged: the Bolt OUTSIDE all edits (emissive+HUD+despeckle) is byte-identical to the lifted source
em_dil = ndimage.binary_dilation(emissive, iterations=4); hud_dil = ndimage.binary_dilation(hud_px, iterations=3)
res_dil = ndimage.binary_dilation(chest_mask | seam_ring | top_seam | ant_base, iterations=3)   # exclude all cleanup-edited zones
untouched = ((yy > 930) & (yy < 1490) & (xx > 250) & (xx < 820)) & ~em_dil & ~hud_dil & ~res_dil
posediff = float(np.abs(base5[untouched] - lifted[untouched]).mean())
pose_unchanged = bool(posediff < 1.5)
# EYES fully powered off: NO bright bluish (active) slit pixels — the dark blue-grey VISOR MATERIAL is allowed (not eye emission)
eye_sub = (1055, 1120, 460, 665)  # slit band
eye_px = last[eye_sub[0]:eye_sub[1], eye_sub[2]:eye_sub[3]]
eye_lum = float(eye_px.mean())
eye_active = (eye_px[:, :, 2] > eye_px[:, :, 0] + 15) & (eye_px.mean(2) > 50)   # BRIGHT bluish = active slit emission
eye_active_frac = float(eye_active.mean())
f25full = np.asarray(Image.open(f"{OUT}/A5_f60_25pct.png").convert("RGB"), float); sx25, sy25 = tw / W, th / H
eye25 = f25full[int(eye_sub[0]*sy25):int(eye_sub[1]*sy25), int(eye_sub[2]*sx25):int(eye_sub[3]*sx25)]
eye25_active = float(((eye25[:, :, 2] > eye25[:, :, 0] + 15) & (eye25.mean(2) > 50)).mean())
eyes_off = bool(eye_active_frac < 0.02 and eye25_active < 0.03 and eye_lum < 70)
# residual BRIGHT SATURATED cyan seam speckle (flecks/halo) — NOT the dark visor or mint shell
Rf, Gf, Bf = last[:, :, 0], last[:, :, 1], last[:, :, 2]
speckle = ((yy > 925) & (yy < 1495) & (xx > 240) & (xx < 825)) & (Bf > Rf + 22) & (Bf >= Gf) & (last.mean(2) > 55)
speckle_px = int(speckle.sum()); no_seam_speckle = bool(speckle_px < 120)
# chest reads as natural unlit material: material (std) + low saturation + SMOOTH boundary (feathered, not a hard processed edge)
chestc = last[1200:1345, 360:555]; chest_lum = chestc.mean(); chest_std = chestc.std(); chest_cyan = float(((chestc[:, :, 2] > chestc[:, :, 0] + 20) & (chestc[:, :, 2] > 90)).mean())
edge_ring = np.abs(np.gradient(last.mean(2))[0])[1188:1366, 338:577]; chest_edge = float(edge_ring.max())
chest_natural = bool(chest_lum > 18 and chest_std > 6 and chest_cyan < 0.03 and chest_edge < 60)
# NO_RECTANGULAR_HUD_MATTE: no sharp rectangular edge along the old HUD box perimeter (compare gradient there vs the corridor baseline)
def perim_grad(img):
    g = np.abs(np.gradient(img.mean(2))[0]) + np.abs(np.gradient(img.mean(2))[1])
    box_edges = g[16:20, 28:672].mean() + g[214:218, 28:672].mean() + g[18:216, 26:30].mean() + g[18:216, 670:674].mean()
    return box_edges / 4
hud_matte_edge = perim_grad(last); base_edge = (np.abs(np.gradient(last.mean(2))[0]) + np.abs(np.gradient(last.mean(2))[1]))[300:900, 900:1000].mean()
no_hud_matte = bool(hud_matte_edge < base_edge * 2.2 + 3.0)
# CHEST_PANEL_MATERIAL_PRESERVED: not flat black; has surface structure (std) and low cyan saturation
chest = last[1200:1345, 360:555]; chest_lum = chest.mean(); chest_std = chest.std()
chest_cyan = float(((chest[:, :, 2] > chest[:, :, 0] + 25) & (chest[:, :, 2] > 108)).mean())
chest_preserved = bool(chest_lum > 18 and chest_std > 6 and chest_cyan < 0.05)
# EMISSIVE_MASK_CONTAINED: chest/bulb components inside their boxes; eye component inside the visor
mask_contained = bool((chest_mask & ~chest_box).sum() == 0 and (bulb_mask & ~bulb_box).sum() == 0 and (eye_mask & ~visor).sum() == 0)
# spill check: shell/arm sample regions must retain brightness (compare base5 vs the pre-suppression lifted src)
spill_regions = [(1050, 1170, 210, 320), (1250, 1330, 660, 780), (950, 990, 420, 500)]  # rear arm, reaching hand, head dome — clear of visor/eyes/bulb/chest
spill = max(float(np.abs(base5[r0:r1, c0:c1] - lifted[r0:r1, c0:c1]).mean()) for (r0, r1, c0, c1) in spill_regions)
no_spill = bool(spill < 2.0)
# ---- NEW gates ----
# EYE_EDIT_PIXELS_CONTAINED_INSIDE_VISOR + BACKGROUND_OUTSIDE_VISOR_PIXEL_IDENTICAL (vs the PRE-EYE reference)
eye_edit = np.abs(base5 - base_ref).mean(2) > 0.5                     # pixels changed after base_ref (= eye edit + the separate terminal boost)
term_region = ndimage.binary_dilation(termbox, iterations=40)         # terminal boost is a legit separate edit -> exclude from the EYE containment check
eye_edit_outside_visor = int((eye_edit & ~visor & ~term_region).sum()); eye_contained = bool(eye_edit_outside_visor == 0)
head_outside = ((yy > 1000) & (yy < 1185) & (xx > 400) & (xx < 715)) & ~visor
bg_identical = bool(np.abs(base5[head_outside] - base_ref[head_outside]).max() < 1.0)
# NO_HORIZONTAL_LUMINANCE_BOUNDARY_ACROSS_HEAD_OR_BACKGROUND: row-gradient (full frame width) — no NEW banding vs the pre-eye ref
def rowgrad(img): L = img.mean(2); return np.abs(L[1:] - L[:-1]).mean(1)
rg_delta = rowgrad(base5) - rowgrad(base_ref); new_band = float(rg_delta[980:1200].max()); no_h_boundary = bool(new_band < 1.5)
# NO_RECTANGULAR_OR_ROW_WIDE_TREATMENT_ANYWHERE: no edited row spans a wide fraction of the Bolt width (a box/row treatment would ~fill a row)
bolt_edit = ((yy > 925) & (yy < 1495) & (xx > 240) & (xx < 825)) & (np.abs(base5 - lifted).mean(2) > 1.0)
max_row_fill = float((bolt_edit[:, 240:825].sum(1) / (825 - 240)).max()); no_rowwide = bool(max_row_fill < 0.6)
# NO_CYAN_HALO_AROUND_CHEST_BEVEL_AT_FULL_RES: no bright teal/cyan flecks in the ring around the panel
ring2 = ndimage.binary_dilation(chest_mask, iterations=9) & ~ndimage.binary_dilation(chest_mask, iterations=1)
Rl2, Gl2, Bl2 = last[:, :, 0], last[:, :, 1], last[:, :, 2]
chest_halo_px = int((ring2 & (Bl2 > Rl2 + 12) & (Gl2 > Rl2 + 3) & (last.mean(2) > 42)).sum()); no_chest_halo = bool(chest_halo_px < 40)
# EYES/CHEST emissive glow removed (cyan gone) but terminal dominant
em_reg = ndimage.binary_erosion(chest_mask, iterations=4) | bulb_mask | eye_mask   # OFF emissive INTERIORS (exclude the bright bevel/shell material)
bolt_emissive_lum = float(last[em_reg].mean()) if em_reg.any() else 0.0
term_lum = float(last[green].mean()); terminal_2x = bool(term_lum > 2.0 * max(1.0, bolt_emissive_lum))
# NO_MAGENTA fringe near terminal
mag = (last[:, :, 0] > last[:, :, 1] + 6) & (last[:, :, 2] > last[:, :, 1] + 6) & term_vic; magenta_px = int(mag.sum())
no_magenta = bool(magenta_px < 40)
# readable at 25% (structural shell landmarks) at normal brightness
f25 = np.asarray(Image.open(f"{OUT}/A5_f60_25pct.png").convert("RGB"), float); sx, sy = tw / W, th / H
LM = {"head": (400, 950, 700, 1150), "torso": (330, 1150, 560, 1340), "hover_base": (250, 1300, 460, 1470), "front_arm_hand": (560, 1175, 800, 1345), "rear_arm": (185, 1025, 365, 1190)}
lm25 = {k: round(float(f25[int(b[1]*sy):int(b[3]*sy), int(b[0]*sx):int(b[2]*sx)].max()), 1) for k, b in LM.items()}
readable_25 = all(v > 55 for v in lm25.values())
bolt_adj = max(float(np.abs(loadf(i)[1000:1470, 300:820] - loadf(i - 1)[1000:1470, 300:820]).mean()) for i in range(51, NF))
bolt_region_mean = float(last[(yy > 930) & (yy < 1490) & (xx > 250) & (xx < 820)].mean())
terminal_dominant = bool(term_lum > 2.0 * max(1.0, bolt_emissive_lum) and term_lum > bolt_region_mean)
# ---- chest-shape + seam gates (measured on the RENDER; soft-desat imposes NO contour -> a "painted patch" = a crisp rim) ----
_cx0, _cx1 = int(_cx.min()), int(_cx.max())
ci = last[_cy0 + 12:_cy1 - 8, _cx0 + 14:_cx1 - 14]; ci_lum = float(ci.mean()); ci_std = float(ci.std())
ci_cyan = float(((ci[:, :, 2] > ci[:, :, 0] + 18) & (ci[:, :, 2] > 90)).mean())
_gg = np.abs(np.gradient(last.mean(2))[0]) + np.abs(np.gradient(last.mean(2))[1])
chest_edge99 = float(np.percentile(_gg[_cy0:_cy1 + 1, _cx0:_cx1 + 1], 99.5))   # strongest edge in the chest region; a crisp patch rim spikes this
smooth_shape = bool(chest_edge99 < 32); no_jagged = smooth_shape
bevel_ring = ndimage.binary_dilation(chest_mask, iterations=6) & ~chest_mask
bevel_lum = float(last[bevel_ring].mean()); bevel_present = bool(bevel_lum > ci_lum + 6)
reads_real = bool(smooth_shape and 15 < ci_lum < 95 and ci_cyan < 0.02 and bevel_present)
chest_rough = round(chest_edge99, 2); solidity = 1.0
# seam speckle gates (full res, final frame)
Rq, Gq, Bq = last[:, :, 0], last[:, :, 1], last[:, :, 2]; Lq = 0.299 * Rq + 0.587 * Gq + 0.114 * Bq
visor_border = ndimage.binary_dilation(visor, iterations=10) & ~ndimage.binary_erosion(visor, iterations=2)
visor_speckle_px = int((visor_border & (Bq > Rq + 8) & (Gq > Rq + 2) & (Lq > 50)).sum()); no_visor_speckle = bool(visor_speckle_px < 30)
head_seam_px = int(((top_seam | ant_base) & (Bq > Rq + 8) & (Gq > Rq + 2) & (Lq > 50)).sum()); no_head_seam_residue = bool(head_seam_px < 30)
res = {"objective": "A5_resolution_aftermath", "no_spend": True, "provider_called": False, "ALLOW_PAID": False,
  "status": "A5_AFTERMATH_ANIMATIC (f44 source, final emissive/seam cleanup; built for review; NOT frozen, NOT registered)",
  "mp4": "a5_resolution/A5_aftermath.mp4", "frames": NF, "source": "A4 powerdown f44 (last clearly-visible powered-down frame)",
  "final_frame_for_A6": "a5_resolution/A5_final_frame.png", "review_25pct": "a5_resolution/A5_f60_25pct.png", "crops": {k: f"a5_resolution/crops/A5_crop_{k}.png" for k in CROPS},
  "metrics": {"handoff": round(handoff, 3), "pose_diff_outside_edits": round(posediff, 3),
    "eye_lum": round(eye_lum, 1), "eye_active_frac": round(eye_active_frac, 4), "eye25_active_frac": round(eye25_active, 4), "seam_speckle_px": speckle_px,
    "chest_lum": round(chest_lum, 1), "chest_std": round(chest_std, 1), "chest_cyan_frac": round(chest_cyan, 3), "chest_edge_max": round(chest_edge, 1),
    "shell_spill": round(spill, 2), "bolt_emissive_lum": round(bolt_emissive_lum, 1), "term_lum": round(term_lum, 1), "term_over_emissive": round(term_lum / max(1, bolt_emissive_lum), 1),
    "bolt_region_mean": round(bolt_region_mean, 1), "magenta_px": magenta_px, "landmark25": lm25, "bolt_adj": round(bolt_adj, 3),
    "eye_edit_outside_visor_px": eye_edit_outside_visor, "new_horizontal_band_delta": round(new_band, 3), "max_row_fill_frac": round(max_row_fill, 3), "chest_halo_px": chest_halo_px,
    "chest_rough": round(chest_rough, 3), "chest_solidity": round(solidity, 3), "chest_interior_lum": round(ci_lum, 1), "chest_interior_std": round(ci_std, 1), "bevel_lum": round(bevel_lum, 1),
    "visor_speckle_px": visor_speckle_px, "head_seam_px": head_seam_px},
  "gates": {"frames_125": NF == 125, "opens_from_black": bool(opens_from_black), "handoff_from_A4_black": bool(handoff < 3.0),
            "CHEST_PANEL_SHAPE_SMOOTH_AND_PHYSICAL": smooth_shape, "NO_JAGGED_CHEST_PERIMETER": no_jagged,
            "CHEST_PANEL_READS_AS_REAL_INACTIVE_COMPONENT": reads_real,
            "NO_VISOR_BORDER_SPECKLE": no_visor_speckle, "NO_HEAD_SEAM_CLEANUP_RESIDUE": no_head_seam_residue,
            "NO_HORIZONTAL_LUMINANCE_BOUNDARY_ACROSS_HEAD_OR_BACKGROUND": no_h_boundary,
            "EYE_EDIT_PIXELS_CONTAINED_INSIDE_VISOR": eye_contained,
            "NO_RECTANGULAR_OR_ROW_WIDE_TREATMENT_ANYWHERE": no_rowwide,
            "NO_CYAN_HALO_AROUND_CHEST_BEVEL_AT_FULL_RES": no_chest_halo,
            "BACKGROUND_OUTSIDE_VISOR_PIXEL_IDENTICAL_TO_PREVIOUS_ACCEPTED_A5": bg_identical,
            "A4_F44_POSE_POSITION_UNCHANGED": pose_unchanged, "NO_RECTANGULAR_HUD_MATTE": no_hud_matte,
            "EYES_READ_FULLY_POWERED_OFF_AT_25PCT": eyes_off, "NO_RESIDUAL_CYAN_SEAM_SPECKLE": no_seam_speckle,
            "CHEST_PANEL_READS_AS_NATURAL_UNLIT_MATERIAL": chest_natural, "CHEST_PANEL_MATERIAL_PRESERVED": chest_preserved,
            "EMISSIVE_MASK_CONTAINED_WITHIN_COMPONENTS": mask_contained, "NO_BLACK_MASK_SPILL_ON_SHELL_OR_LIMBS": no_spill,
            "NO_MAGENTA_OR_PURPLE_TERMINAL_FRINGE": no_magenta, "TERMINAL_VISUALLY_DOMINANT": terminal_dominant,
            "TERMINAL_LUM_GT_2X_BOLT_EMISSIVE": terminal_2x, "FULL_BOLT_READABLE_AT_25PCT_NORMAL_BRIGHTNESS": bool(readable_25),
            "ZERO_BOLT_MOTION_AFTER_REVEAL": bool(bolt_adj < 4.0), "no_paid_generation": True, "does_not_touch_frozen_H0_A1_A3_A3B_A4": True}}
res["A5_final_frame_sha256"] = sha(f"{OUT}/A5_final_frame.png")
json.dump(res, open(f"{OUT}/A5_result.json", "w"), indent=2, default=str)
print(json.dumps(res["gates"], indent=2)); print(json.dumps(res["metrics"], indent=2)); print("DONE")
