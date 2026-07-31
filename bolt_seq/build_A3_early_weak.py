"""ZERO-SPEND deterministic EMISSIVE-OVERLAY A3_EARLY_WEAK (user-authorized: pipeline owns the weakening).
The Kling A3's eye/chest dim (5.0->3.06 energy) already lands on the frozen A4_start endpoint (3.06) — but at ~f60 (past
mid). This overlay ADVANCES that same dim to land by mid-A3 (~f42) and HOLDS it, monotonically, preserving BOTH boundary
states (f0 == Kling f0; f89 == A4_start). Emissive dim ONLY (eyes+chest cyan) — NO retime/drop/dup/speed/warp; posture is
inherited from the Kling clip. Then assembles HYBRID_SET2_EW = set2 A1[0:66] + set2 A2[0:76] + A3_EARLY_WEAK[0:90] = 232.
Run: python3 -m bolt_seq.build_A3_early_weak"""
import os, sys, json, subprocess
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image
W, H, FPS = 1080, 1920, 30
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"
A3SRC = f"{AT}/a3_accepted/A3_production_primitive.mp4"
OUT = f"{AT}/a1a3_hybrid/A3_EARLY_WEAK"; FR = f"{OUT}/_frames"; os.makedirs(FR, exist_ok=True)
yy, xx = np.mgrid[0:H, 0:W]
term_box = (yy > 560) & (yy < 1000) & (xx > 560) & (xx < 900)
# EYE band (head): the real weakness signal (eye cyan 5.0->3.06). Excludes the terminal + the lower chest/floor-reflection
# cyan that RISES as the Bolt slumps (which had masked the eye-dim in a broader region).
bolt_band = (yy < 1250) & (~term_box)
def ss(x): x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)

# decode the Kling A3 (90 frames)
src = f"{OUT}/_src"; os.makedirs(src, exist_ok=True); [os.remove(os.path.join(src, x)) for x in os.listdir(src)]
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", A3SRC, "-vf", f"scale={W}:{H}", "-start_number", "0", os.path.join(src, "a%04d.png")], check=True)
NF = len(os.listdir(src)); assert NF == 90, f"A3 has {NF} != 90 frames"


def emask(a):                                                          # emissive cyan (eyes + chest + bulb) in the Bolt band
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    return (B > R + 18) & (B > 90) & bolt_band
def energy(a): m = emask(a); return float(a[:, :, 2][m].sum())


A = [np.asarray(Image.open(os.path.join(src, f"a{i:04d}.png")).convert("RGB"), float) for i in range(NF)]
cur = [energy(a) for a in A]
E0, Eend = cur[0], cur[NF - 1]                                         # f0 (full) and f89 (== A4_start endpoint)
MIDF = 42                                                              # land the dim by ~mid-A3 (frame 42 of 90)
# monotonic target energy: E0 -> Eend by f42 (smoothstep), then HOLD Eend to f89
target = [E0 - (E0 - Eend) * ss(min(1.0, i / MIDF)) for i in range(NF)]
[os.remove(os.path.join(FR, x)) for x in os.listdir(FR)]
applied_energy = []
for i in range(NF):
    a = A[i].copy(); m = emask(a)
    fac = 1.0 if cur[i] <= 1e-6 else min(1.0, target[i] / cur[i])     # ONLY dim (never brighten); advances the eye/chest dim
    if fac < 0.999:
        for c in range(3): a[:, :, c][m] = np.clip(a[:, :, c][m] * fac, 0, 255)
    Image.fromarray(np.clip(a, 0, 255).astype("uint8")).save(os.path.join(FR, f"m{i:04d}.png"))
    applied_energy.append(energy(a))
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(FR, "m%04d.png"),
                "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS), f"{OUT}/A3_EARLY_WEAK.mp4"], check=True)

# ---- verify boundaries + monotonic advance ----
def L(i): return np.asarray(Image.open(os.path.join(FR, f"m{i:04d}.png")).convert("RGB"), float)
a4s = np.asarray(Image.open(f"{AT}/a4_collapse/A4_start_frame.png").convert("RGB").resize((W, H)), float)
f0_preserved = float(np.abs(L(0) - A[0]).mean())                       # f0 unchanged (factor 1)
f89_vs_a4start = float(np.abs(L(NF - 1) - a4s).mean())                 # endpoint still == A4_start
mono = all(applied_energy[i] <= applied_energy[i - 1] + 0.02 * E0 for i in range(1, NF))   # non-increasing (no recovery)
mid_drop_frac = round((E0 - applied_energy[MIDF]) / (E0 - Eend + 1e-6), 3)   # fraction of total dim achieved by mid-A3
onset = next((i for i in range(NF) if applied_energy[i] <= E0 - 0.5 * (E0 - Eend)), None)   # frame reaching 50% dim
verify = {"f0_preserved_meanabs": round(f0_preserved, 3), "f89_vs_A4start_meanabs": round(f89_vs_a4start, 3),
          "emissive_monotonic_no_recovery": bool(mono), "dim_onset_50pct_frame": onset, "mid_A3_frame": MIDF,
          "frac_dim_by_mid": mid_drop_frac, "E0": round(E0/1e6, 2), "Eend": round(Eend/1e6, 2),
          "kling_orig_onset_50pct": next((i for i in range(NF) if cur[i] <= E0 - 0.5*(E0-Eend)), None),
          "applied_energy_every10_Msum": [round(applied_energy[i]/1e6, 2) for i in range(0, NF, 10)]}

# ---- assemble HYBRID_SET2_EW = set2 A1[0:66] + set2 A2[0:76] + A3_EARLY_WEAK[0:90] ----
HY = f"{AT}/a1a3_hybrid/HYBRID_SET2_EW"; HFR = f"{HY}/_frames"; os.makedirs(HFR, exist_ok=True); [os.remove(os.path.join(HFR, x)) for x in os.listdir(HFR)]
segs = [(f"{AT}/a1a3_production/set2/A1.mp4", 66), (f"{AT}/a1a3_production/set2/A2.mp4", 76), (f"{OUT}/A3_EARLY_WEAK.mp4", 90)]
gi = 0
for mp4, take in segs:
    tmp = f"{HY}/_seg{gi}"; os.makedirs(tmp, exist_ok=True); [os.remove(os.path.join(tmp, x)) for x in os.listdir(tmp)]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp4, "-vf", f"scale={W}:{H}", "-start_number", "0", os.path.join(tmp, "s%04d.png")], check=True)
    av = len(os.listdir(tmp))
    for k in range(take): Image.open(os.path.join(tmp, f"s{min(k, av-1):04d}.png")).save(os.path.join(HFR, f"m{gi:04d}.png")); gi += 1
assert gi == 232, f"hybrid {gi} != 232"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(HFR, "m%04d.png"),
                "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS), f"{HY}/HYBRID_SET2_EW.mp4"], check=True)
# phone frames + strip
ph = f"{HY}/_phone"; os.makedirs(ph, exist_ok=True)
for i in [0, 29, 58, 87, 116, 141, 160, 187, 210, 231]: Image.open(os.path.join(HFR, f"m{i:04d}.png")).resize((270, 480)).save(os.path.join(ph, f"p{i:03d}.png"))
from PIL import ImageDraw
strip = Image.new("RGB", (9 * 190 + 20, 400), (12, 12, 14)); dd = ImageDraw.Draw(strip)
for k, (i, lb) in enumerate(zip([0, 66, 108, 142, 165, 187, 200, 215, 231], ["f0", "f66 A2", "f108", "f142 A3", "f165", "f187 midA3", "f200", "f215", "f231"])):
    strip.paste(Image.open(os.path.join(HFR, f"m{i:04d}.png")).resize((190, 338)), (k * 190 + 10, 40)); dd.text((k * 190 + 12, 6), lb, fill=(230, 230, 230))
strip.save(f"{HY}/HYBRID_SET2_EW_strip.png")
json.dump({"A3_EARLY_WEAK_verify": verify, "hybrid_mp4": f"{HY}/HYBRID_SET2_EW.mp4", "hybrid_strip": f"{HY}/HYBRID_SET2_EW_strip.png", "phone_dir": ph},
          open(f"{OUT}/A3_early_weak_result.json", "w"), indent=2, default=str)
print(json.dumps(verify, indent=1)); print("hybrid:", f"{HY}/HYBRID_SET2_EW.mp4"); print("DONE")
