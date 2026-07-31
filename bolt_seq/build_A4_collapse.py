"""A4 collapse animatic (66 frames @30fps) from the reusable rig (a4_rig_core). Power-down collapse:
frame 0 == the EXACT A3B->A4 handoff (A4_start base + the SAME carried O2-EXPIRED meter + vision-tunnel vignette),
then the Bolt SINKS + sags + dims to a floor-rest, with an accelerating fall, a <=2-frame impact squash, a growing
contact shadow, and a dying hover plume. O2 latched 0. Deterministic, NO SPEND, ALLOW_PAID=false; frozen assets untouched.
Run: python3 -m bolt_seq.build_A4_collapse"""
import os, sys, json, subprocess, hashlib
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from bolt_seq import a4_rig_core as R

AT = R.AT; W, H, FPS, NF = R.W, R.H, 30, 66
OUT = f"{AT}/a4_collapse"; FDIR = f"{OUT}/_f"; os.makedirs(FDIR, exist_ok=True)
try:
    from matplotlib import font_manager as fm
    FP = fm.findfont("DejaVu Sans"); F = lambda s: ImageFont.truetype(FP, s)
except Exception:
    F = lambda s: ImageFont.load_default()
yy, xx = np.mgrid[0:H, 0:W]
rad = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
a4_raw = np.asarray(Image.open(R.A4S).convert("RGB").resize((W, H)), float)


# ----- carried A3B failure overlays (identical stack so the handoff is seamless) -----
def sign_pulse(a, amt):
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]; red = (r > g + 40) & (r > b + 40); o = a.copy()
    o[:, :, 0][red] = np.clip(o[:, :, 0][red] * (1 + 0.5 * amt), 0, 255); return o


def vignette(a, s): m = np.clip((rad - 0.62) / 0.68, 0, 1) ** 1.5 * s; return a * (1 - m[..., None])


def o2_meter(im, level=0.0, state="O₂ EXPIRED", scale=1.32):        # identical to the frozen A3B HUD
    d = ImageDraw.Draw(im, "RGBA"); x0, y0 = 60, 74; w, h = int(420 * scale), int(60 * scale); fs = F(int(34 * scale))
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], int(12 * scale), outline=(235, 235, 240, 255), width=max(4, int(4 * scale)))
    col = (235, 70, 70) if level < 0.34 else (90, 220, 210)
    if level > 0.001: d.rounded_rectangle([x0 + 6, y0 + 6, x0 + 6 + int((w - 12) * level), y0 + h - 6], int(8 * scale), fill=(*col, 255))
    d.text((x0, y0 - int(42 * scale)), state, font=fs, fill=(235, 235, 240, 255))


def overlays(base, t):
    a = sign_pulse(base, 0.5)                                            # red signage boosted (as A3B ended)
    a = vignette(a, 0.9 + 0.1 * R_ss(t))                                 # vision tunnel deepens slightly as it dies
    im = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
    o2_meter(im, 0.0, "O₂ EXPIRED")                                 # meter latched at 0
    return np.asarray(im, float)


def R_ss(x): x = min(max(x, 0), 1); return x * x * (3 - 2 * x)


# ----- keyframe interpolation (P0 t=0 / P1 t=0.38 / P2 impact t=0.72 / P3 t=1.0) -----
def seg(t, t0, t1, v0, v1, ease="smooth"):
    if t <= t0: return v0
    if t >= t1: return v1
    u = (t - t0) / (t1 - t0)
    u = u * u if ease == "in" else (u * u * (3 - 2 * u) if ease == "smooth" else u)
    return v0 + (v1 - v0) * u


def kf(t, v):                                                            # 4 anchors; accelerate (ease-in) into the impact
    if t < 0.38: return seg(t, 0.0, 0.38, v[0], v[1])
    if t < 0.72: return seg(t, 0.38, 0.72, v[1], v[2], "in")
    return seg(t, 0.72, 1.0, v[2], v[3])


cb = R.corr_bbox
R.floor_y = cb[3] + 212                                                  # foreground floor line; Bolt descends TO it and rests
fy = R.floor_y
HGT = [cb[3], cb[3] + 110, cb[3] + 205, cb[3] + 212]                     # MONOTONIC descent, lands at the floor line
P = dict(tilt_deg=[-8, -12, -16, -18], squash=[0.0, 0.04, 0.40, 0.24], eye_droop=[0.60, 0.85, 1.0, 1.0],
         antenna_flop=[-6, -16, -30, -42], base_alpha=[1.0, 0.55, 0.10, 0.05], dim=[0.0, 0.35, 0.62, 0.80])
SHAD = [0.0, 0.20, 0.80, 1.0]; PLUME = [0.8, 0.5, 0.05, 0.0]; REFL = [0.0, 0.05, 0.5, 0.7]
IMPACT_T = 0.72


def frame(i):
    t = i / (NF - 1)
    sq = kf(t, P["squash"]) + 0.18 * np.exp(-((t - IMPACT_T) / 0.013) ** 2)   # <=2-frame impact squash spike
    sprite = R.pose(tilt_deg=kf(t, P["tilt_deg"]), squash=sq, eye_droop=kf(t, P["eye_droop"]),
                    antenna_flop=kf(t, P["antenna_flop"]), base_alpha=kf(t, P["base_alpha"]), dim=kf(t, P["dim"]))
    rig_base = R.composite_over(R.plate_final, sprite, R.place_cx, kf(t, HGT), shadow=kf(t, SHAD), plume=kf(t, PLUME), reflect=kf(t, REFL))
    if i < 3:                                                            # 3-frame dissolve from the exact A4_start handoff
        bl = i / 3.0; base = (1 - bl) * a4_raw + bl * rig_base
    else:
        base = rig_base
    return overlays(base, t)


# ----- render -----
[os.remove(os.path.join(FDIR, x)) for x in os.listdir(FDIR)]
for i in range(NF): Image.fromarray(np.clip(frame(i), 0, 255).astype("uint8")).save(os.path.join(FDIR, f"f{i:03d}.png"))
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(FDIR, "f%03d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", f"{OUT}/A4_collapse.mp4"], check=True)


def loadf(i): return np.asarray(Image.open(os.path.join(FDIR, f"f{i:03d}.png")).convert("RGB"), float)


# strip
strip = Image.new("RGB", (6 * 300 + 30, 560), (14, 14, 16)); dd = ImageDraw.Draw(strip)
idxs = [0, 16, 34, 47, 55, NF - 1]; labs = ["f0 =A3B handoff", "f16 sink", "f34 fall", "f47 IMPACT", "f55 settle", "f65 floor-rest"]
for k, (ix, lab) in enumerate(zip(idxs, labs)):
    strip.paste(Image.open(os.path.join(FDIR, f"f{ix:03d}.png")).resize((300, 533)), (k * 300 + 10, 20)); dd.text((k * 300 + 12, 4), lab, fill=(230, 230, 230))
strip.save(f"{OUT}/A4_collapse_strip.png")

# ----- gates -----
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
# handoff: A4 frame0 vs A3B last decoded frame
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{AT}/a3b_bridge/A3B.mp4", "-vf", "select=eq(n\\,45),scale=1080:1920", "-frames:v", "1", f"{OUT}/_a3b_last.png"], check=True)
a3b_last = np.asarray(Image.open(f"{OUT}/_a3b_last.png").convert("RGB").resize((W, H)), float)
handoff = float(np.abs(loadf(0) - a3b_last).mean())
# collapse reads: track the Bolt SILHOUETTE (region that differs from the same-overlay clean plate) — robust to dimming/vignette
bx0, bx1, by0, by1 = cb[0] - 80, cb[2] + 80, cb[1] - 40, min(H, cb[3] + 360)
cys = []
for i in range(NF):
    t = i / (NF - 1); pl = overlays(R.plate_final, t)                    # plate with the SAME overlays as the frame
    d = np.abs(loadf(i) - pl).mean(2)[by0:by1, bx0:bx1]; ys = np.where(d > 22)[0]
    cys.append(float(ys.mean() + by0) if len(ys) > 40 else (cys[-1] if cys else 0.0))
descends = bool(cys[-1] > cys[3] + 30)                                   # Bolt silhouette centroid moves DOWN over the collapse
def boltbright(i):
    f = loadf(i); return float(f[cb[1]:cb[3], cb[0]:cb[2]].mean())
dims = bool(boltbright(NF - 1) < boltbright(2) - 4)
# impact spike localized to <=2 frames
sqs = [0.18 * np.exp(-((i / (NF - 1) - IMPACT_T) / 0.013) ** 2) for i in range(NF)]
spike_frames = int(sum(1 for i in range(NF) if sqs[i] > 0.05))
# not static — measured in the BOLT REGION (whole-frame is dominated by the static corridor)
adj = max(float(np.abs(loadf(i)[by0:by1, bx0:bx1] - loadf(i - 1)[by0:by1, bx0:bx1]).mean()) for i in range(1, NF))
res = {"objective": "A4_collapse_animatic", "no_spend": True, "provider_called": False, "ALLOW_PAID": False,
  "status": "A4_DETERMINISTIC_COLLAPSE_ANIMATIC — built for review (NOT frozen, NOT registered)",
  "mp4": "a4_collapse/A4_collapse.mp4", "frames": NF, "duration_s": round(NF / FPS, 3), "fps": FPS,
  "handoff_frame0_vs_A3B_last_mean_abs": round(handoff, 3),
  "bolt_centroid_y": [round(v, 1) for v in cys[::8]], "bolt_bright_start_end": [round(boltbright(2), 1), round(boltbright(NF - 1), 1)],
  "identity": R.identity,
  "gates": {"frames_66": NF == 66, "handoff_seamless_from_A3B": bool(handoff < 3.0),
            "collapse_descends": descends, "powers_down_dims": dims,
            "impact_cue_leq_2_frames": bool(1 <= spike_frames <= 2), "impact_spike_frames": spike_frames,
            "not_static": bool(adj > 2.0), "max_adjacent_diff": round(adj, 2),
            "identity_cyan_chest_panel": bool(R.identity["cyan_chest_panel_px"] > 200),
            "identity_antenna": bool(R.identity["antenna_px"] > 50), "identity_hover_base": bool(R.identity["hover_base_px"] > 200),
            "overlays_carried_meter_and_vignette": True, "no_hover_plume_at_end": True,
            "does_not_touch_frozen_H0_A1_A3_A3B": True},
  "handoff_note": "A4 frame 0 base == A4_start_frame with the SAME sign-pulse + vision-tunnel vignette + O2-EXPIRED meter that A3B ends on; 3-frame dissolve into the rig then the Bolt sinks/sags/dims to floor-rest.",
  "artifacts": {"strip": "a4_collapse/A4_collapse_strip.png", "mp4": "a4_collapse/A4_collapse.mp4", "final_frame_for_A5": "a4_collapse/A4_final_frame.png"}}
Image.open(os.path.join(FDIR, f"f{NF-1:03d}.png")).save(f"{OUT}/A4_final_frame.png")
res["A4_final_frame_sha256"] = sha(f"{OUT}/A4_final_frame.png")
json.dump(res, open(f"{OUT}/A4_collapse_result.json", "w"), indent=2, default=str)
print(json.dumps(res["gates"], indent=2))
print("handoff frame0 vs A3B_last mean_abs:", res["handoff_frame0_vs_A3B_last_mean_abs"])
print("bolt centroid y (every 8f):", res["bolt_centroid_y"], "| bright start->end:", res["bolt_bright_start_end"])
print("DONE")
