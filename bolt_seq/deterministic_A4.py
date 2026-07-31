"""A4 (collapse) DETERMINISTIC ANIMATIC — NO SPEND, no provider. Starts from the EXACT A3 final frame
(a4_collapse/A4_start_frame.png, sha b5ad0536…). Rigidly ROTATES the accepted Bolt cutout forward/down toward ~58deg
+ drops it to the corridor floor with impact deceleration (no bounce), fades the eyes toward off, and draws a
perspective-consistent floor shadow. Corridor + terminal are static (Bolt removed -> plate-filled bg). No plume, no
powered flight. A rigid rotate preserves ALL of Bolt (no legs/extra limbs/antenna loss). Status: A4_DETERMINISTIC_ANIMATIC
(NOT accepted/production). Run: python3 -m bolt_seq.deterministic_A4"""
import os, sys, json, subprocess
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

W, H, FPS = 1080, 1920, 30
DUR = 2.180                        # A4 slot 11.280-13.460
NF = int(round(FPS * DUR))         # 65 frames
T_FALL = 0.62                      # fraction of DUR over which the fall+rotate happens (then settled, no bounce)
ANGLE_END = 58.0                   # forward/down topple, degrees (plan.json block E rot 0->58)
FWD = -1.0                         # sign: clockwise (forward topple); tune by visual review
EYE_FADE_END = 0.12               # eye glow -> ~12% (fading toward off)
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"
OUT = f"{AT}/a4_collapse"; os.makedirs(OUT, exist_ok=True)
START = f"{OUT}/A4_start_frame.png"
PLATE = "renders/bolt_seq/oxygen_subscription/corridor_with_terminal.png"


def _arr(p): return np.asarray(Image.open(p).convert("RGB").resize((W, H)), float)
def smootherstep(x): x = np.clip(x, 0, 1); return x * x * x * (x * (x * 6 - 15) + 10)


a0 = _arr(START); plate = _arr(PLATE); gray = a0.mean(axis=2)
def _box(x0, y0, x1, y1):
    m = np.zeros((H, W), bool); m[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)] = True; return m
BOLT_BOX = _box(0.06, 0.26, 0.74, 0.82); TERM_BODY = _box(0.63, 0.26, 0.85, 0.53)
tone = float(np.median(a0[~BOLT_BOX].mean(1)) / max(1e-3, np.median(plate[~BOLT_BOX].mean(1))))
plate_toned = np.clip(plate * tone, 0, 255)
diff = np.abs(a0 - plate_toned).mean(2)
head_bright = (gray > 72) & _box(0.10, 0.30, 0.63, 0.60)
raw = ((diff > 20) | head_bright) & BOLT_BOX & ~TERM_BODY
raw = ndimage.binary_fill_holes(ndimage.binary_closing(raw, iterations=4))
lbl, n = ndimage.label(raw); sizes = ndimage.sum(np.ones_like(lbl), lbl, range(1, n + 1))
matte = ndimage.binary_fill_holes(ndimage.binary_closing(lbl == (int(np.argmax(sizes)) + 1), iterations=3))
alpha0 = np.clip(ndimage.gaussian_filter(matte.astype(float), 1.0), 0, 1)
ys, xs = np.where(matte); bb = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
base_cx = int((bb[0] + bb[2]) / 2); base_y = int(bb[3]); bolt_w = bb[2] - bb[0]
# corridor bg: A4 start with Bolt removed (plate-filled) -> static corridor+terminal
corridor_bg = a0.copy(); dm = ndimage.binary_dilation(matte, iterations=8)
for ch in range(3): corridor_bg[:, :, ch][dm] = plate_toned[:, :, ch][dm]
# eyes (visor cyan) for fade
from bolt_seq.providers import directed_video as DV
be = DV._blob_bbox(a0, 0, int(0.58 * W), int(0.26 * H), int(0.90 * H))
bwe, bhe = be[2] - be[0], be[3] - be[1]
eyerg = np.zeros((H, W), bool)
eyerg[int(be[1] + 0.30 * bhe):int(be[1] + 0.52 * bhe), int(be[0] + 0.22 * bwe):int(be[0] + 0.78 * bwe)] = True
eyerg &= (a0[:, :, 2] > a0[:, :, 0] + 18) & (a0[:, :, 2] > a0[:, :, 1] - 25)
# floor target: drop Bolt's base to the corridor floor plane at his depth
FLOOR_Y = min(H - 30, base_y + int(0.15 * H)); DROP_PX = FLOOR_Y - base_y


def bolt_rgba(p):
    """eye-dimmed RGBA Bolt cutout (numpy HxWx4 uint8), pre-rotation."""
    rgb = a0.copy(); R, G, B = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    cyan = (B > R + 18) & (B > G - 25) & eyerg
    f = 1 - (1 - EYE_FADE_END) * p
    for ch in range(3): rgb[:, :, ch][cyan] = rgb[:, :, ch][cyan] * f
    al = (alpha0 * 255).astype("uint8")
    return np.dstack([np.clip(rgb, 0, 255).astype("uint8"), al])


def compose(p):
    ang = FWD * ANGLE_END * p
    dy = int(round(DROP_PX * p))
    layer = Image.fromarray(bolt_rgba(p), "RGBA").rotate(ang, center=(base_cx, base_y), resample=Image.BICUBIC, expand=False)
    la = np.asarray(layer, float)                                   # rotate around the base pivot -> topple
    if dy > 0:                                                      # then drop the whole layer to the floor
        sh = np.zeros_like(la); sh[dy:] = la[:H - dy]; la = sh
    out = corridor_bg.copy()
    # perspective floor shadow (flat ellipse on the floor under the current base)
    if p > 0.02:
        sw = int(bolt_w * (0.55 + 0.55 * p)); shh = int(bolt_w * 0.13)
        cyf = min(H - 6, base_y + dy + int(0.02 * H))
        ov = Image.new("L", (W, H), 0); dd = ImageDraw.Draw(ov)
        dd.ellipse([base_cx - sw, cyf - shh, base_cx + sw, cyf + shh], fill=int(150 * min(1.0, p * 1.1)))
        sm = np.asarray(ov, float) / 255.0 * 0.6
        out = out * (1 - sm[..., None])
    al = la[:, :, 3:4] / 255.0
    out = out * (1 - al) + la[:, :, :3] * al
    return np.clip(out, 0, 255).astype("uint8"), ang, base_y + dy


# --- render ---
fdir = f"{OUT}/_f"; os.makedirs(fdir, exist_ok=True); [os.remove(os.path.join(fdir, x)) for x in os.listdir(fdir)]
rows = []
for i in range(NF):
    t = i / FPS
    p = smootherstep(t / (T_FALL * DUR)) if t < T_FALL * DUR else 1.0    # ease-out into impact; hold after (no bounce)
    frame, ang, base_now = compose(p)
    Image.fromarray(frame).save(os.path.join(fdir, f"f{i:03d}.png"))
    if i % 2 == 0:
        # measure eye lum on the (rotated) frame within a generous visor band that follows the base
        a = frame.astype(float); Rr, Gg, Bb = a[:, :, 0], a[:, :, 1], a[:, :, 2]
        reg = np.zeros((H, W), bool); reg[max(0, bb[1] + int(0.10 * bhe)):min(H, base_now), max(0, bb[0] - 40):min(W, bb[2] + 40)] = True
        c = (Bb > Rr + 18) & (Bb > Gg - 25) & reg
        eye = float(((Gg[c] + Bb[c]) / 2).mean()) if c.sum() else 0.0
        rows.append({"t": round(t, 3), "p": round(p, 3), "angle_deg": round(abs(ang), 2), "base_y_frac": round(base_now / H, 4), "eye_lum": round(eye, 1)})
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(fdir, "f%03d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", f"{OUT}/A4_deterministic_animatic.mp4"], check=True)
# end frame
end_frame = np.asarray(Image.open(os.path.join(fdir, f"f{NF-1:03d}.png")).convert("RGB"), np.uint8)
Image.fromarray(end_frame).save(f"{OUT}/A4_collapse_end.png")
# contact sheet (labeled)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{OUT}/A4_deterministic_animatic.mp4",
                "-vf", f"fps={round((8-0.001)/DUR,3)},scale=220:-1,tile=8x1", "-frames:v", "1", f"{OUT}/A4_contact.png"], check=False)
# start/end/seam comparison
cmp = Image.new("RGB", (3 * 300 + 40, 560), (12, 12, 14)); d = ImageDraw.Draw(cmp)
for i, (t, im) in enumerate([("A3 final == A4 start", Image.open(START).convert("RGB")),
                             ("A4 mid (falling)", Image.open(os.path.join(fdir, f"f{NF//2:03d}.png")).convert("RGB")),
                             ("A4 end (collapsed)", Image.open(f"{OUT}/A4_collapse_end.png").convert("RGB"))]):
    cmp.paste(im.resize((300, 533)), (i * 300 + 10, 20)); d.text((i * 300 + 12, 4), t, fill=(230, 230, 230))
cmp.save(f"{OUT}/A4_start_end_seam.png")
# trajectory report
traj = {"altitude_base_y_frac": [r["base_y_frac"] for r in rows], "angle_deg": [r["angle_deg"] for r in rows], "eye_lum": [r["eye_lum"] for r in rows], "samples": rows}
base = [r["base_y_frac"] for r in rows]; ang = [r["angle_deg"] for r in rows]; eye = [r["eye_lum"] for r in rows]
last08 = [r for r in rows if r["t"] >= DUR - 0.8]
checks = {
  "monotonic_altitude_loss": all(base[i] >= base[i - 1] - 0.002 for i in range(1, len(base))),
  "net_altitude_drop": round(base[-1] - base[0], 4),
  "rotation_reaches_~58": bool(ang[-1] >= 55),
  "rotation_monotonic": all(ang[i] >= ang[i - 1] - 0.5 for i in range(1, len(ang))),
  "no_bounce_settled": (max(x["base_y_frac"] for x in last08) - min(x["base_y_frac"] for x in last08)) <= 0.01,
  "eye_fades": round(1 - eye[-1] / max(1e-3, eye[0]), 3),
  "floor_reached_frac": base[-1],
}
out = {"objective": "a4_collapse_deterministic_animatic", "status": "A4_DETERMINISTIC_ANIMATIC",
       "no_spend": True, "provider_called": False, "ALLOW_PAID": False, "registered": False, "accepted": False,
       "start_frame": "a4_collapse/A4_start_frame.png", "start_frame_sha256": "b5ad053604e6d3a03abdb6df9ee22b122d59567dea7807cebae23edc2cab7424",
       "duration_s": DUR, "params": {"angle_end": ANGLE_END, "fwd_sign": FWD, "t_fall_frac": T_FALL, "eye_fade_end": EYE_FADE_END, "drop_px": int(DROP_PX), "floor_y_frac": round(FLOOR_Y / H, 4)},
       "deterministic_checks": checks, "trajectory": traj,
       "method": "rigid rotate (around base pivot) + monotonic drop to floor with ease-out impact + eye fade + perspective floor shadow; corridor/terminal static; NO plume; rigid rotate preserves all parts (no legs/extra limbs/antenna loss)",
       "visual_review_questions": ["involuntary?", "has weight?", "visibly contacts floor?", "avoids pasted-cutout look?", "reads as collapse (not landing/dive/bow)?"],
       "artifacts": {"mp4": "a4_collapse/A4_deterministic_animatic.mp4", "end": "a4_collapse/A4_collapse_end.png", "contact": "a4_collapse/A4_contact.png", "seam": "a4_collapse/A4_start_end_seam.png"}}
json.dump(out, open(f"{AT}/a4_deterministic_result.json", "w"), indent=2, default=str)
print(json.dumps(checks, indent=2)); print("STATUS: A4_DETERMINISTIC_ANIMATIC | frames", NF, "| DONE")
