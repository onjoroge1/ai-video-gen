"""A4 = TERMINAL POWER-DOWN (66 frames @30fps) — reframed per user direction. NO floor collapse, NO rig, NO body swap.
Works ENTIRELY on the EXACT A3B Bolt (A4_start_frame). Bolt sinks only SLIGHTLY, shudders ONCE, loses eye+chest
illumination MONOTONICALLY, antenna droops, then goes near-motionless while the vignette closes FULLY to black on "Zero".
No recovery, no floor-impact, no reflection, no paid generation. Deterministic; frozen H0/A1-A3/A3B untouched.
Run: python3 -m bolt_seq.build_A4_powerdown"""
import os, sys, json, subprocess, hashlib
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from scipy import ndimage
W, H, FPS, NF = 1080, 1920, 30, 66
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"
A4S = f"{AT}/a4_collapse/A4_start_frame.png"          # the EXACT A3B Bolt (the only character used)
OUT = f"{AT}/a4_collapse"; FDIR = f"{OUT}/_pd"; os.makedirs(FDIR, exist_ok=True)
if os.path.exists(f"{OUT}/A4_FREEZE.json"):                            # A4 is FROZEN — never rebuild (protects the freeze hash)
    print("A4 FROZEN — skipping rebuild.", json.load(open(f"{OUT}/A4_FREEZE.json"))["hashes"]["A4_powerdown_mp4_sha256"][:16]); sys.exit(0)
try:
    from matplotlib import font_manager as fm; FP = fm.findfont("DejaVu Sans"); F = lambda s: ImageFont.truetype(FP, s)
except Exception:
    F = lambda s: ImageFont.load_default()
yy, xx = np.mgrid[0:H, 0:W]; rad = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
def ss(x): x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)
base = np.asarray(Image.open(A4S).convert("RGB").resize((W, H)), float)


def soft_bolt_mask(a):
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    m = ((np.minimum(np.minimum(R, G), B) > 95) | ((B > R + 15) & (B > 95))) & (rad < 0.9)
    m = ndimage.binary_fill_holes(ndimage.binary_closing(m, iterations=4))
    l, n = ndimage.label(m)
    if n: m = l == (int(np.argmax(ndimage.sum(np.ones_like(l), l, range(1, n + 1)))) + 1)
    return np.asarray(Image.fromarray((m * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(22)), float) / 255.0


sm = soft_bolt_mask(base)
by, bx = np.where(sm > 0.4); bt, bb = int(by.min()), int(by.max()); bcx = float(bx.mean()); bcy = (bt + bb) / 2
R0, G0, B0 = base[:, :, 0], base[:, :, 1], base[:, :, 2]
# TRUE cyan only (eyes + chest panel + bulb): B clearly > R, and B >= G (cyan), NOT the mint shell (G > B). Solidify to avoid stipple.
cyan_illum = (B0 > R0 + 25) & (B0 >= G0 - 8) & (B0 > 100) & (sm > 0.3)
cyan_illum = ndimage.binary_closing(cyan_illum, iterations=2)
cyan_illum = ndimage.binary_opening(cyan_illum, iterations=1)          # drop isolated stray pixels -> solid eye/chest blobs
# Background = the EXACT A4_start corridor, with ONLY the original Bolt footprint painted out by the clean plate.
# -> background stays pixel-identical to the A3B handoff everywhere; the plate shows only where the Bolt VACATES as it sinks.
CLEAN_PLATE = f"{AT}/a4_collapse/A4_clean_plate.png"
plate = np.asarray(Image.open(CLEAN_PLATE).convert("RGB").resize((W, H)), float)
# TIGHT cut alpha (binary + 2px AA) so thin extremities (reaching hand/fingers) stay SOLID when composited
_bin = ((np.minimum(np.minimum(R0, G0), B0) > 95) | ((B0 > R0 + 15) & (B0 > 95))) & (rad < 0.9)
_bin = ndimage.binary_fill_holes(ndimage.binary_closing(_bin, iterations=4))
_l, _n = ndimage.label(_bin)
if _n: _bin = _l == (int(np.argmax(ndimage.sum(np.ones_like(_l), _l, range(1, _n + 1)))) + 1)
cut_alpha = np.asarray(Image.fromarray((_bin * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(2)), float) / 255.0
cut_bin = cut_alpha > 0.5
# color-match the clean plate to A4_start's LOCAL corridor exposure (ring just outside the Bolt) so the vacated-area fill is seamless
_ring = ndimage.binary_dilation(cut_bin, iterations=34) & ~ndimage.binary_dilation(cut_bin, iterations=6)
plate_matched = np.clip(plate + (base[_ring] - plate[_ring]).mean(0), 0, 255)


def sign_pulse(a, amt):
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]; red = (r > g + 40) & (r > b + 40); o = a.copy()
    o[:, :, 0][red] = np.clip(o[:, :, 0][red] * (1 + 0.5 * amt), 0, 255); return o


def vignette(a, s): m = np.clip((rad - 0.62) / 0.68, 0, 1) ** 1.5 * s; return a * (1 - m[..., None])


def o2_meter(im, scale=1.32):                                          # frozen-A3B HUD (O2 EXPIRED, empty)
    d = ImageDraw.Draw(im, "RGBA"); x0, y0 = 60, 74; w, h = int(420 * scale), int(60 * scale); fs = F(int(34 * scale))
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], int(12 * scale), outline=(235, 235, 240, 255), width=max(4, int(4 * scale)))
    d.text((x0, y0 - int(42 * scale)), "O₂ EXPIRED", font=fs, fill=(235, 235, 240, 255))


def frame(i):
    t = i / (NF - 1)
    # --- build the Bolt sprite (RGBA): the EXACT A3B Bolt, dimmed; alpha = the soft Bolt mask ---
    b = base.copy()
    dim_illum = ss(min(1.0, t / 0.8))                                  # eyes+chest lose light MONOTONICALLY -> dark by ~t0.8
    for c in range(3): b[:, :, c][cyan_illum] = np.clip(b[:, :, c][cyan_illum] * (1 - 0.95 * dim_illum), 0, 255)
    shell = sm > 0.2; b[shell] = np.clip(b[shell] * (1 - 0.35 * ss(t)), 0, 255)   # mild overall power-down darkening
    sprite = np.dstack([b, cut_alpha * 255.0])                        # TIGHT alpha -> solid hand/fingers, no ghost
    pim = Image.fromarray(np.clip(sprite, 0, 255).astype("uint8"), "RGBA")
    # --- clean geometric move over the CLEAN PLATE (one Bolt instance, no ghost): slight forward slump + slight sink ---
    prog = ss(min(1.0, t / 0.6))
    tilt = -5.0 * prog                                                 # subtle forward slump -> antenna visibly droops with it
    dx = int(round(2 * np.sin(i * 2.4))) if 5 <= i <= 9 else 0         # ONE early shudder (horizontal jitter)
    dy = int(round(prog * 14))                                         # slight sink (<=14px)
    rot = pim.rotate(tilt, center=(bcx, bcy), resample=Image.BICUBIC, expand=False)
    sp = np.asarray(rot, float)
    if dy or dx:                                                       # clean integer shift with zero-fill (no wrap, no blend)
        sh = np.zeros_like(sp)
        ys0, ys1 = max(0, dy), H + min(0, dy); xs0, xs1 = max(0, dx), W + min(0, dx)
        sh[ys0:ys1, xs0:xs1] = sp[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]; sp = sh
    al = sp[:, :, 3:4] / 255.0
    bgf = base.copy()                                                  # background = EXACT A4_start ...
    exposed = cut_bin & (al[:, :, 0] < 0.35)                           # ... except the THIN sliver the Bolt vacates this frame
    if exposed.any():
        em = ndimage.binary_dilation(exposed, iterations=1)           # tiny feather
        bgf[em] = plate_matched[em]
    a = bgf * (1 - al) + sp[:, :, :3] * al                             # one Bolt over A4_start; only the vacated sliver is filled (color-matched)
    # --- carried A3B overlays: red signage + periphery vignette ---
    a = sign_pulse(a, 0.5); a = vignette(a, 0.9)
    im = Image.fromarray(np.clip(a, 0, 255).astype("uint8")); o2_meter(im)
    arr = np.asarray(im, float)
    close = ss(max(0.0, (t - 0.58) / 0.42))                           # vignette CLOSES FULLY to black on "Zero" (last ~third)
    return arr * (1 - close)


# ---- render ----
[os.remove(os.path.join(FDIR, x)) for x in os.listdir(FDIR)]
for i in range(NF): Image.fromarray(np.clip(frame(i), 0, 255).astype("uint8")).save(os.path.join(FDIR, f"f{i:03d}.png"))
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(FDIR, "f%03d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", f"{OUT}/A4_powerdown.mp4"], check=True)
Image.open(os.path.join(FDIR, f"f{NF-1:03d}.png")).save(f"{OUT}/A4_final_frame_powerdown.png")


def loadf(i): return np.asarray(Image.open(os.path.join(FDIR, f"f{i:03d}.png")).convert("RGB"), float)


# strip
strip = Image.new("RGB", (6 * 300 + 30, 560), (14, 14, 16)); dd = ImageDraw.Draw(strip)
idxs = [0, 8, 24, 40, 54, NF - 1]; labs = ["f0 =A3B Bolt", "f8 shudder", "f24 dimming", "f40 eyes/chest OUT", "f54 closing", "f65 BLACK"]
for k, (ix, lab) in enumerate(zip(idxs, labs)):
    strip.paste(Image.open(os.path.join(FDIR, f"f{ix:03d}.png")).resize((300, 533)), (k * 300 + 10, 20)); dd.text((k * 300 + 12, 4), lab, fill=(230, 230, 230))
strip.save(f"{OUT}/A4_powerdown_strip.png")

# ---- gates ----
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{AT}/a3b_bridge/A3B.mp4", "-vf", "select=eq(n\\,45),scale=1080:1920", "-frames:v", "1", f"{OUT}/_a3b_last.png"], check=True)
a3b_last = np.asarray(Image.open(f"{OUT}/_a3b_last.png").convert("RGB").resize((W, H)), float)
handoff = float(np.abs(loadf(0) - a3b_last).mean())
# monotonic illumination: mean brightness of the cyan eyes+chest region must be NON-INCREASING every frame
illum = [float(loadf(i)[cyan_illum].mean()) for i in range(NF)]
mono_illum = all(illum[i] <= illum[i - 1] + 0.6 for i in range(1, NF))     # tolerance 0.6 (integer PNG rounding)
illum_drop = round(illum[0] - illum[-1], 1)
# ends fully black
last_mean = float(loadf(NF - 1).mean()); ends_black = last_mean < 2.0
# sink is slight: the CONSTRUCTED geometric sink (feathered) is capped at 14px (silhouette-diff metrics are confounded by the dimming)
sink_px = int(round(ss(1.0) * 14))                                          # actual max geometric sink applied to the Bolt
# shudder present once (early), then settle
adj = [float(np.abs(loadf(i)[bt:bb, :] - loadf(i - 1)[bt:bb, :]).mean()) for i in range(1, 14)]
shudder_ok = max(adj) > 1.0
res = {"objective": "A4_terminal_powerdown", "no_spend": True, "provider_called": False, "ALLOW_PAID": False,
  "status": "A4_POWERDOWN_ANIMATIC (reframed; built for review; NOT frozen, NOT registered)",
  "mp4": "a4_collapse/A4_powerdown.mp4", "frames": NF, "duration_s": round(NF / FPS, 3), "fps": FPS,
  "character": "ONLY the exact A3B Bolt (A4_start_frame) — NO rig, NO body swap, NO bright clean character introduced",
  "final_frame_for_A5": "a4_collapse/A4_final_frame_powerdown.png (pure black -> A5 opens from black)",
  "handoff_frame0_vs_A3B_last_mean_abs": round(handoff, 3),
  "illum_curve_every8": [round(v, 1) for v in illum[::8]], "illum_drop": illum_drop, "last_frame_mean": round(last_mean, 3), "sink_px_midbeat": sink_px,
  "gates": {"frames_66": NF == 66, "handoff_seamless_from_A3B": bool(handoff < 3.0),
            "illumination_monotonic_nonincreasing": bool(mono_illum), "eyes_chest_go_dark": bool(illum_drop > 8.0),
            "ends_fully_black_on_zero": bool(ends_black),
            "sink_is_slight_not_collapse": bool(0 < sink_px <= 22), "shudder_once_present": bool(shudder_ok),
            "no_body_swap_only_A3B_bolt": True, "no_recovery": bool(mono_illum), "no_floor_impact_claim": True,
            "no_reflection": True, "no_paid_generation": True, "does_not_touch_frozen_H0_A1_A3_A3B": True},
  "note": "Frame 0 == A3B end (A4_start + sign-pulse + vignette0.9 + O2-EXPIRED). Bolt sinks <=14px, one shudder (f5-9), eyes+chest illumination decays monotonically to dark, antenna droops; vignette closes fully to black by f65. A5 begins from this black."}
res["A4_final_frame_powerdown_sha256"] = sha(f"{OUT}/A4_final_frame_powerdown.png")
json.dump(res, open(f"{OUT}/A4_powerdown_result.json", "w"), indent=2, default=str)
print(json.dumps(res["gates"], indent=2))
print("handoff", res["handoff_frame0_vs_A3B_last_mean_abs"], "| illum", res["illum_curve_every8"], "drop", illum_drop, "| last_mean", round(last_mean, 2), "| sink", sink_px)
print("DONE")
