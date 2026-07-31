"""Deterministic A3 (weakening reach) prototype — NO SPEND, no Kling. Animates the ACCEPTED Kling Bolt (segmented from
the accepted A2 final frame) via a RIGID single monotonic sink ease (translate) + a smooth uniform eye-glow dim. The
corridor + terminal are byte-stable (A2's own corridor with the Bolt matte plate-filled). No warp, no crossfade, no
tumble, no plume. Frame 0 is byte-identical to the accepted A2 final frame.
LIMITATION (see endpoint_vs_approved_A3_end in the result): the approved A3_end is NOT a rigid sink of A2_final — its
reaching arm RETRACTS/droops (fingertip ends ~0.043). A rigid sink keeps the arm extended (fingertip recedes to ~0.10,
gate 6 fails high); a 2D warp that could droop the arm shears the head/body. So this prototype is a clean weakening but
does not reproduce A3_end's arm geometry -> the user's stated fallback (consider one paid Kling retry) applies.
Run: python3 -m bolt_seq.deterministic_A3"""
import os, sys, json, subprocess; sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
from dotenv import load_dotenv; load_dotenv(".env", override=True)
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from bolt_seq.providers import directed_video as DV
from bolt_seq import prepare_oxygen_shot_A_primitives as P
W, H, TERM = 1080, 1920, 0.605; TERMINAL_POINT = (0.62, 0.55)   # == prepare_oxygen TERMINAL_POINT (hand-terminal ref)
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"; OUT = f"{AT}/a3_weakening/deterministic"; os.makedirs(OUT, exist_ok=True)
A2_FINAL = f"{AT}/a2_accepted/A2_final_frame.png"
FPS, DUR = 30, 3.0; NF = int(FPS * DUR)
SINK = 0.05                      # net base-centroid descent (target 0.04-0.06)
EYE_DIM_END = 0.655              # calibrated so the measured eye-glow reduction MATCHES the approved A3_end (~18.6% on
                                 # this ruler); the accepted endpoint is dimmed this much, so it reproduces its eye state
plate = np.asarray(P._bg().convert("RGB").resize((W, H)), float)
a2 = np.asarray(Image.open(A2_FINAL).convert("RGB").resize((W, H)), float); gray = a2.mean(axis=2)


def smoothstep(x): x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)


# --- tone-match the clean plate to A2's exposure (over corridor pixels: everything outside Bolt's generous box) ---
def _box(x0f, y0f, x1f, y1f):
    m = np.zeros((H, W), bool); m[int(y0f * H):int(y1f * H), int(x0f * W):int(x1f * W)] = True; return m
BOLT_BOX = _box(0.06, 0.26, 0.74, 0.76)          # generous region containing ALL of Bolt (body + both arms + reaching hand)
TERM_BOX = _box(0.55, 0.26, 0.84, 0.52)          # oxygen terminal region — KEPT from A2 so it never pops at t=0.20
tone = float(np.median(a2[~BOLT_BOX].mean(axis=1)) / max(1e-3, np.median(plate[~BOLT_BOX].mean(axis=1))))
plate_toned = np.clip(plate * tone, 0, 255)
# --- segment the WHOLE Bolt by DIFFERENCE from the tone-matched plate: captures the reaching arm AND the head (the old
#     bright-blob matte clipped the arm at the terminal column, and a rectangular terminal-exclusion clipped the head);
#     the corridor + terminal cancel out (identical content in A2 and the plate), so the diff isolates only Bolt ---
diff = np.abs(a2 - plate_toned).mean(axis=2)
# The terminal drifts ~17/px between Kling's A2 and the static plate, so diff>20 grabs the terminal BODY (and largest-CC
# welds it to Bolt -> a ghost terminal that sinks with the cutout). But Bolt's white head OVERLAPS the terminal's bright
# left edge, where diff is LOW (white-on-bright) -> a plain diff matte notches the head. So: capture Bolt by diff OR by
# head-brightness (left of the terminal body), and exclude ONLY the terminal body (x>0.63, right of Bolt's head).
TERM_BODY = _box(0.63, 0.26, 0.85, 0.53)          # the terminal's bulk (right of where Bolt's head reaches)
head_bright = (gray > 72) & _box(0.26, 0.30, 0.63, 0.56)   # Bolt's white head/shoulders, left of the terminal body
raw = ((diff > 20) | head_bright) & BOLT_BOX & ~TERM_BODY
raw = ndimage.binary_fill_holes(ndimage.binary_closing(raw, iterations=4))
lbl, n = ndimage.label(raw); sizes = ndimage.sum(np.ones_like(lbl), lbl, range(1, n + 1))
matte = ndimage.binary_fill_holes(ndimage.binary_closing(lbl == (int(np.argmax(sizes)) + 1), iterations=3))
alpha0 = np.clip(ndimage.gaussian_filter(matte.astype(float), 1.2), 0, 1)
ys, xs = np.where(matte); bb = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
# --- byte-stable corridor background = A2's OWN corridor+terminal with the (clean, terminal-free) Bolt matte removed
#     and filled from the tone-matched plate. The static corridor/terminal stay byte-equal to the A2 hold (zero drift,
#     no terminal pop); only Bolt's own vacated region is plate-filled, and that region is inside the excluded Bolt-motion
#     band. Because the matte now captures ALL of Bolt (and none of the terminal), nothing is left behind (no shred). ---
corridor_bg = a2.copy(); dm = ndimage.binary_dilation(matte, iterations=6)
for ch in range(3): corridor_bg[:, :, ch][dm] = plate_toned[:, :, ch][dm]
# --- eyes: the two cyan eye-glows in the visor, defined EXACTLY as the A3 measurement region (DV._blob_bbox visor)
#     so the applied dim and the measured dim use the same pixels (antenna above + chest emblem below are excluded) ---
bb_e = DV._blob_bbox(a2, 0, int(0.58 * W), int(0.26 * H), int(0.90 * H))
bw_e, bh_e = bb_e[2] - bb_e[0], bb_e[3] - bb_e[1]
eyerg0 = np.zeros((H, W), bool)
eyerg0[int(bb_e[1] + 0.30 * bh_e):int(bb_e[1] + 0.52 * bh_e), int(bb_e[0] + 0.22 * bw_e):int(bb_e[0] + 0.78 * bw_e)] = True
eyerg0 &= (a2[:, :, 2] > a2[:, :, 0] + 18) & (a2[:, :, 2] > a2[:, :, 1] - 25)   # cyan glow only
SAG = 0                          # rigid sink (no warp): the approved A3 endpoint is the SAME pose sunk+dimmed, so the
                                 # reach-slip is delivered by the sink; a 2D warp would shear the head/body (arm shares it).


def make_bolt(p):
    """RGBA Bolt cutout with only a SMOOTH uniform eye-dim on the cyan eye-glow (no warp: the whole cutout is rigid
    and gets translated by compose_frame, so the head/body/arm keep their exact accepted geometry)."""
    rgb = a2.copy(); al = alpha0.copy()
    R, G, B = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]; cyan = (B > R + 18) & (B > G - 25) & eyerg0
    f = 1 - (1 - EYE_DIM_END) * p
    for ch in range(3): rgb[:, :, ch][cyan] = rgb[:, :, ch][cyan] * f
    return rgb, al


def compose_frame(p, sink_px):
    rgb, al = make_bolt(p)
    if sink_px > 0:                                   # sink = translate the whole Bolt layer down
        rgb2 = np.zeros_like(rgb); a2l = np.zeros_like(al)
        rgb2[sink_px:] = rgb[:-sink_px]; a2l[sink_px:] = al[:-sink_px]; rgb, al = rgb2, a2l
    out = corridor_bg * (1 - al[..., None]) + rgb * al[..., None]
    return np.clip(out, 0, 255).astype("uint8")


# --- render timeline ---
fdir = f"{OUT}/_f"; os.makedirs(fdir, exist_ok=True); [os.remove(os.path.join(fdir, x)) for x in os.listdir(fdir)]
for i in range(NF):
    t = i / FPS
    if t < 0.20:
        frame = a2.astype("uint8")                    # byte-identical hold of the accepted A2 final
    else:
        p = smoothstep((t - 0.20) / 1.60) if t <= 1.80 else 1.0
        frame = compose_frame(p, int(SINK * H * p))
    Image.fromarray(frame).save(os.path.join(fdir, f"f{i:03d}.png"))
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(fdir, "f%03d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", f"{OUT}/A3_deterministic.mp4"], check=True)


# --- measure trajectories on a CLEAN per-frame Bolt mask (diff vs the tone-matched plate, terminal + floor excluded,
#     largest CC). This isolates only Bolt, so the sink is measured honestly (DV._base_centroid_y is contaminated by
#     static bright floor pixels low in the frame, which pins its band and understates a rigid translation). ---
def _bolt_isolate(a):
    d = (np.abs(a - plate_toned).mean(axis=2) > 20) & BOLT_BOX & ~TERM_BODY
    d = ndimage.binary_fill_holes(ndimage.binary_closing(d, iterations=3))
    lbl, n = ndimage.label(d)
    if n == 0:
        return d
    sizes = ndimage.sum(np.ones_like(lbl), lbl, range(1, n + 1))
    return lbl == (int(np.argmax(sizes)) + 1)


def measure(frame):
    a = frame.astype(float); m = _bolt_isolate(a); ys, xs = np.where(m)
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
    band = ys >= (y1 - 0.25 * (y1 - y0)); base_cy = float(ys[band].mean() / H)     # lowest-25% centroid of Bolt only
    # reaching hand = the actual reaching FINGERTIP (rightmost matte point), not the bbox-midpoint proxy: as Bolt sinks
    # the extended hand recedes from the terminal (reach fails -> distance INCREASES), which the midpoint proxy inverts.
    hxi = int(xs.max()); hyi = float(np.median(ys[xs >= hxi - 6]))
    hd = float(DV.target_anchor_distance([x0, y0, x1, y1], TERMINAL_POINT, W, H, reaching_hand=(hxi / W, hyi / H))["euclidean"])
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    be = DV._blob_bbox(a, 0, int(0.58 * W), int(0.26 * H), int(0.90 * H))   # HEAD bbox (excl. arm) == eyerg0's basis
    bwe, bhe = be[2] - be[0], be[3] - be[1]
    rg = np.zeros((H, W), bool)                                          # visor region == make_bolt's eye-dim target
    rg[int(be[1] + 0.30 * bhe):int(be[1] + 0.52 * bhe), int(be[0] + 0.22 * bwe):int(be[0] + 0.78 * bwe)] = True
    c = (B > R + 18) & (B > G - 25) & rg                                 # relative cyan -> stable under uniform dim (no truncation)
    eye = float(((G[c] + B[c]) / 2).mean()) if c.sum() else 0.0
    sh = int(((np.minimum(np.minimum(R, G), B) > 95) & ((np.maximum(np.maximum(R, G), B) - np.minimum(np.minimum(R, G), B)) < 85) & m).sum())
    eeg = DV.eye_edge_integrity_gate(a, W, H, bb=[x0, y0, x1, y1])
    return {"base_cy": round(base_cy, 4), "hand_terminal": round(hd, 4), "eye_lum": round(eye, 1), "shell": sh, "eye_edge": bool(eeg["pass"])}
rows = []
for i in range(0, NF, 2):
    fr = np.asarray(Image.open(os.path.join(fdir, f"f{i:03d}.png")).convert("RGB"), float)
    m = measure(fr); m["t"] = round(i / FPS, 3); rows.append(m)
start = rows[0]; end = rows[-1]
base = [r["base_cy"] for r in rows]; hand = [r["hand_terminal"] for r in rows]; eye = [r["eye_lum"] for r in rows]
anim = [r for r in rows if r["t"] >= 0.20]                       # after the initial hold
bnet = round(base[-1] - base[0], 4)
mono_after_hold = all(anim[i]["base_cy"] >= anim[i - 1]["base_cy"] - 0.005 for i in range(1, len(anim)))
max_up_reversal = round(max([0] + [anim[i - 1]["base_cy"] - anim[i]["base_cy"] for i in range(1, len(anim))]), 4)
hand_mono = all(hand[i] >= hand[i - 1] - 0.005 for i in range(1, len(rows)))
last08 = [r for r in rows if r["t"] >= DUR - 0.8]
persist = (max(x["base_cy"] for x in last08) - min(x["base_cy"] for x in last08)) <= 0.01
# byte-identical frame 0
f0 = np.asarray(Image.open(os.path.join(fdir, "f000.png")).convert("RGB"), float)
byte0 = bool(np.array_equal(f0.astype("uint8"), a2.astype("uint8")))
scale_ratio = round(end["shell"] / max(1, start["shell"]), 3)
vfx = DV.generated_vfx_absence_gate(f"{OUT}/A3_deterministic.mp4", plate_path=f"{AT}/../corridor_with_terminal.png")
term = DV.plate_consistency_gate(f"{OUT}/A3_deterministic.mp4")
# CORRECTED corridor/terminal fixedness: plate_consistency's tracker caps Bolt's bbox at the terminal column and misses
# the reaching hand (right edge ~0.57W), so it counts Bolt's OWN hand motion as background drift. Exclude the UNION of
# Bolt's true matte across every sink position (hand included) and compare each frame's STATIC corridor+terminal to
# frame 0 (== A2). corridor_bg is A2 outside Bolt, so a truly-fixed corridor reads ~0 drift here.
sink_max = int(SINK * H); bolt_union = np.zeros_like(matte)
for s in range(0, sink_max + 1, 6):
    shm = np.zeros_like(matte); shm[s:] = matte[:H - s]; bolt_union |= shm
static = ~ndimage.binary_dilation(bolt_union, iterations=12)
ref0 = np.asarray(Image.open(os.path.join(fdir, "f000.png")).convert("RGB"), float)
max_static_drift = 0.0
for i in range(0, NF, 2):
    frx = np.asarray(Image.open(os.path.join(fdir, f"f{i:03d}.png")).convert("RGB"), float)
    ch = (np.abs(frx - ref0).mean(axis=2) > 16) & static
    max_static_drift = max(max_static_drift, float(ch.sum()) / max(1, int(static.sum())))
corridor_fixed = bool(max_static_drift <= 0.002 and term["frames_terminal_moved"] == 0)
gates = {
 "1_first_frame_byte_identical": byte0,
 "2_base_monotonic_after_hold": bool(mono_after_hold),
 "3_net_base_descent_0.04_0.06": bool(0.04 <= bnet <= 0.06), "3_value": bnet,
 "4_max_up_reversal_lt_0.005": bool(max_up_reversal < 0.005), "4_value": max_up_reversal,
 "5_hand_monotonic_up": bool(hand_mono),
 "6_final_hand_terminal_0.05_0.08": bool(0.05 <= hand[-1] <= 0.08), "6_value": hand[-1],
 "7_eye_lum_reduction_15_30": bool(0.15 <= (1 - eye[-1] / eye[0]) <= 0.30), "7_value": round(1 - eye[-1] / eye[0], 3),
 "8_eye_smooth_all_frames": bool(all(r["eye_edge"] for r in rows)),
 "9_structural_scale_0.97_1.03": bool(0.97 <= scale_ratio <= 1.03), "9_value": scale_ratio,
 "10_zero_propulsion_vfx": bool(vfx["pass"]),
 "11_corridor_terminal_fixed": corridor_fixed, "11_static_drift_frac": round(max_static_drift, 5),
 "11_tracker_gate_pass": bool(term["pass"]), "11_tracker_note": "tracker misses reaching hand -> counts Bolt motion as drift; corrected metric excludes true matte union",
 "12_weakened_state_persists_last_0.8s": bool(persist),
}
gates["ALL_PASS"] = all(v for k, v in gates.items() if k[0].isdigit() and isinstance(v, bool))
# artifacts
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{OUT}/A3_deterministic.mp4", "-vf", "fps=2,scale=240:-1,tile=6x1", "-frames:v", "1", f"{OUT}/A3_contact.jpg"], check=False)
def plot(key, ylabel, out, hlo=None, hhi=None):
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        plt.figure(figsize=(6, 3)); plt.plot([r["t"] for r in rows], [r[key] for r in rows], "-o", ms=3)
        if hlo is not None: plt.axhline(hlo, color="g", ls="--", lw=1)
        if hhi is not None: plt.axhline(hhi, color="g", ls="--", lw=1)
        plt.xlabel("t (s)"); plt.ylabel(ylabel); plt.title(ylabel); plt.tight_layout(); plt.savefig(out, dpi=90); plt.close()
    except Exception as e: open(out.replace(".png", ".txt"), "w").write(str(e))
plot("base_cy", "base-centroid (sink)", f"{OUT}/traj_base.png")
plot("hand_terminal", "hand->terminal dist", f"{OUT}/traj_hand.png", 0.05, 0.08)
plot("eye_lum", "eye luminance", f"{OUT}/traj_eye.png")
mont = [np.asarray(Image.open(os.path.join(fdir, f"f{i:03d}.png")).convert("RGB")) for i in [0, NF // 2, NF - 1]]
sh = Image.new("RGB", (3 * 300 + 40, 560), (12, 12, 14)); dd = ImageDraw.Draw(sh)
for i, (im, l) in enumerate(zip(mont, ["t=0 (=A2 final)", "MID", "END (weakened)"])):
    sh.paste(Image.fromarray(im).resize((300, 533)), (i * 300 + 10, 22)); dd.text((i * 300 + 12, 4), l, fill=(230, 230, 230))
sh.save(f"{OUT}/A3_montage.png")
out = {"objective": "deterministic_a3_prototype", "no_spend": True, "provider_called": False,
       "method": "segment the accepted Kling Bolt (diff-from-plate matte, terminal-body excluded) -> RIGID monotonic sink ease (single smoothstep translate) + smooth uniform eye-glow dim; corridor_bg = A2's own corridor+terminal with the Bolt matte plate-filled (byte-stable static bg); NO warp, NO crossfade, NO tumble, NO plume",
       "gates": gates, "start": start, "end": end, "trajectory_samples": rows,
       "endpoint_vs_approved_A3_end": {
           "matches_A2_final_start_byte_identical": bool(byte0),
           "reproduces_A3_end_arm_geometry": False,
           "finding": "A3_end is NOT a rigid sink of A2_final: its full silhouette area is ~78% of A2, its reaching-arm right edge pulls IN ~58px and the fingertip DROOPS (fingertip-terminal ends ~0.043). A rigid 2D sink keeps the arm extended (fingertip recedes to ~0.101 -> gate 6 fails high); a 2D warp that could retract/droop the arm shears the head/body (arm shares that region). So the deterministic prototype delivers a CLEAN weakening (sink+dim+reach-slip, identity byte-preserved) but does NOT match A3_end's retracted-arm endpoint.",
           "decision": "ACCEPT the rigid-sink endpoint (extended-arm slip, clean) OR authorize ONE paid Kling retry for the drooped-arm A3_end motion. No spend without explicit authorization."},
       "artifacts": {"mp4": "deterministic/A3_deterministic.mp4", "contact": "deterministic/A3_contact.jpg", "montage": "deterministic/A3_montage.png", "traj_base": "deterministic/traj_base.png", "traj_hand": "deterministic/traj_hand.png", "traj_eye": "deterministic/traj_eye.png"}}
json.dump(out, open(f"{AT}/a3_deterministic_result.json", "w"), indent=2, default=str)
print(json.dumps(gates, indent=2, default=str)); print("start", start, "end", end); print("DONE")
