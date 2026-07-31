"""A6 = CTA / LOOP via OCCLUSION (90 frames @30fps), final beat. NO crossfade/dissolve. Holds the FROZEN A5 aftermath,
then a story-motivated occlusion (red warning FLARE + terminal destabilize + rapid vignette CLOSE TO BLACK) fully
obscures the frame BEFORE the loop boundary. The H0 alive-Bolt frame is NEVER composited inside A6 — it appears only at
the playback loop wrap (A6 f89 near-black -> cut to H0 f0). No SUBSCRIPTION banner inside A6 (that belongs to H0 after the
loop). At no frame are two Bolts visible. Deterministic, NO SPEND; frozen H0/A1-A3/A3B/A4/A5 untouched.
Run: python3 -m bolt_seq.build_A6_cta_loop"""
import os, sys, json, subprocess, hashlib
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw
W, H, FPS, NF = 1080, 1920, 30, 90
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"
A5END = f"{AT}/a5_resolution/A5_final_frame.png"          # FROZEN A5 aftermath end (the ONLY character in A6)
H0MP4 = f"{AT}/h0_hook/H0.mp4"                            # for the loop-demo ONLY (never composited into A6)
OUT = f"{AT}/a6_cta_loop"; FDIR = f"{OUT}/_f"; os.makedirs(FDIR, exist_ok=True)
if os.path.exists(f"{OUT}/A6_FREEZE_manifest.json"):                       # A6 is FROZEN — never rebuild (protects the reviewed hashes)
    print("A6 FROZEN — skipping rebuild; mp4 sha", json.load(open(f"{OUT}/A6_FREEZE_manifest.json"))["reviewed_hashes"]["mp4"][:16]); sys.exit(0)
yy, xx = np.mgrid[0:H, 0:W]; rad = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
def ss(x): x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def vignette(a, s): m = np.clip((rad - 0.30) / 0.85, 0, 1) ** 1.3 * s; return a * (1 - np.clip(m, 0, 1)[..., None])

aftermath = np.asarray(Image.open(A5END).convert("RGB").resize((W, H)), float)
Ra, Ga, Ba = aftermath[:, :, 0], aftermath[:, :, 1], aftermath[:, :, 2]
term = np.zeros((H, W), bool); term[620:960, 600:880] = True
green = (Ga > Ra + 12) & (Ga > Ba + 4) & (aftermath[:, :, 1] > 40) & term
red_sign = (Ra > Ga + 28) & (Ra > Ba + 28) & (Ra > 45)                    # diegetic red SUBSCRIPTION-EXPIRED wall signs (for the warning flare)


def frame(i):
    a = aftermath.copy(); t = i / (NF - 1)
    # ---- f0-59: HOLD the aftermath; terminal breathing only ----
    br = 0.5 + 0.5 * np.sin(t * 7.0)
    a[green] = np.clip(a[green] * (1 + 0.08 * br), 0, 255)
    if i >= 60:                                                           # ---- f60-78: DESTABILIZE (warning flare + terminal flicker) ----
        d = ss(np.clip((i - 60) / 18.0, 0, 1))
        flare = d * (0.5 + 0.5 * np.sin(i * 1.5))                         # escalating red warning flare
        a[red_sign] = np.clip(a[red_sign] * (1 + 1.1 * flare), 0, 255)
        a[green] = np.clip(a[green] * (1 - 0.55 * d * (0.5 + 0.5 * np.sin(i * 2.7))), 0, 255)   # terminal destabilizes (flicker/dim)
    # ---- occlusion: vignette CLOSES inward + rapid fade to black -> fully obscured by f88/89 (no readable Bolt) ----
    vclose = ss(np.clip((i - 60) / 28.0, 0, 1)); a = vignette(a, 0.0 + 2.4 * vclose)
    gblack = ss(np.clip((i - 78) / 10.0, 0, 1)); a = a * (1 - 0.985 * gblack)
    return np.clip(a, 0, 255)


[os.remove(os.path.join(FDIR, x)) for x in os.listdir(FDIR)]
for i in range(NF): Image.fromarray(frame(i).astype("uint8")).save(os.path.join(FDIR, f"f{i:03d}.png"))
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(FDIR, "f%03d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", f"{OUT}/A6_cta_loop.mp4"], check=True)
Image.open(os.path.join(FDIR, f"f{NF-1:03d}.png")).save(f"{OUT}/A6_final_frame.png")


def loadf(i): return np.asarray(Image.open(os.path.join(FDIR, f"f{i:03d}.png")).convert("RGB"), float)


# ---- H0 first frame (for the loop-demo ONLY; NOT part of A6) ----
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", H0MP4, "-vf", f"select=eq(n\\,0),scale={W}:{H}", "-frames:v", "1", f"{OUT}/_H0_first.png"], check=True)
h0_first = np.asarray(Image.open(f"{OUT}/_H0_first.png").convert("RGB").resize((W, H)), float)

# ---- contact strip at f55/60/65/70/75/80/85/88/89 ----
idxs = [55, 60, 65, 70, 75, 80, 85, 88, 89]
strip = Image.new("RGB", (len(idxs) * 210 + 20, 400), (14, 14, 16)); dd = ImageDraw.Draw(strip)
for k, ix in enumerate(idxs):
    strip.paste(Image.open(os.path.join(FDIR, f"f{ix:03d}.png")).resize((200, 356)), (k * 210 + 10, 30)); dd.text((k * 210 + 12, 8), f"f{ix}", fill=(230, 230, 230))
strip.save(f"{OUT}/A6_occlusion_strip.png")
# ---- real-time preview of the final 1.5s (frames 44..89) ----
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-start_number", "44", "-i", os.path.join(FDIR, "f%03d.png"),
                "-frames:v", str(NF - 44), "-c:v", "libx264", "-pix_fmt", "yuv420p", f"{OUT}/A6_final_1p5s.mp4"], check=True)
# ---- loop demo: A6 f72..89 (occlude to black) then H0 f0..17 (the loop CUT to the fresh cycle) ----
LD = f"{OUT}/_ld"; os.makedirs(LD, exist_ok=True); [os.remove(os.path.join(LD, x)) for x in os.listdir(LD)]
n = 0
for i in range(72, 90): Image.open(os.path.join(FDIR, f"f{i:03d}.png")).save(os.path.join(LD, f"d{n:03d}.png")); n += 1
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", H0MP4, "-vf", "scale=1080:1920", "-frames:v", "18", "-start_number", "0", f"{LD}/h%03d.png"], check=True)
for j in range(18): Image.open(f"{LD}/h{j:03d}.png").save(os.path.join(LD, f"d{n:03d}.png")); n += 1
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(LD, "d%03d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", f"{OUT}/A6_loop_demo.mp4"], check=True)

# ---------- temporal gates ----------
def bright_cyan_eyes(img):   # signature of a POWERED-ON Bolt (H0's alive eyes) anywhere in frame
    R, G, B = img[:, :, 0], img[:, :, 1], img[:, :, 2]
    return int(((B > R + 40) & (B > 130) & (G > 120)).sum())
def banner_present(img):     # red text in the H0 banner region (center-bottom)
    reg = img[1480:1660, 300:780]; R, G, B = reg[:, :, 0], reg[:, :, 1], reg[:, :, 2]
    return int(((R > G + 50) & (R > B + 50) & (R > 90)).sum())
h0_alive = bright_cyan_eyes(h0_first)                                     # confirm the detector fires on the real H0 alive Bolt
allframes = [loadf(i) for i in range(NF)]
max_alive = max(bright_cyan_eyes(f) for f in allframes)                   # A6 must NEVER show a powered-on Bolt
max_banner = max(banner_present(f) for f in allframes)                    # A6 must NEVER show the subscription banner
handoff = float(np.abs(allframes[0] - aftermath).mean())
f88, f89 = allframes[88], allframes[89]
occ89 = float((f89.mean(2) < 18).mean()); occ88 = float((f88.mean(2) < 18).mean())   # fraction obscured (near-black)
# ONE bolt per frame: A6 only ever contains the single A5 aftermath Bolt (never H0). Verified via no-alive-signature + no crossfade blend.
res = {"objective": "A6_cta_loop_occlusion", "no_spend": True, "provider_called": False, "ALLOW_PAID": False,
  "status": "A6_CTA_LOOP_ANIMATIC v2 (occlusion, no crossfade; built for review; NOT frozen, NOT registered)",
  "mp4": "a6_cta_loop/A6_cta_loop.mp4", "final_1p5s": "a6_cta_loop/A6_final_1p5s.mp4", "loop_demo": "a6_cta_loop/A6_loop_demo.mp4",
  "occlusion_strip": "a6_cta_loop/A6_occlusion_strip.png", "frames": NF, "duration_s": round(NF / FPS, 3),
  "structure": "f0-59 hold A5 aftermath (terminal breathing) | f60-78 destabilize (red warning flare + terminal flicker) + vignette begins closing | f79-88 rapid vignette-close-to-black -> fully obscured | f89 near-black. LOOP: player cuts A6 f89 (black) -> H0 f0 (alive+banner). H0 NEVER composited inside A6.",
  "metrics": {"handoff_vs_A5_end": round(handoff, 3), "max_powered_on_bolt_px_in_A6": max_alive, "H0_alive_signature_px": h0_alive,
              "max_banner_px_in_A6": max_banner, "occluded_frac_f88": round(occ88, 3), "occluded_frac_f89": round(occ89, 3)},
  "gates": {"frames_90": NF == 90, "opens_from_A5_end": bool(handoff < 2.0),
            "MAX_ONE_BOLT_VISIBLE_PER_FRAME": bool(max_alive < 500),          # 42px stray = terminal-screen highlight; a real alive Bolt is ~17k px
            "NO_A5_H0_CHARACTER_OVERLAP": bool(max_alive < 500),              # no crossfade -> H0 Bolt never blended in
            "NO_POWERED_ON_BOLT_BEFORE_LOOP_BOUNDARY": bool(max_alive < 500 and h0_alive > 200),
            "NO_SUBSCRIPTION_BANNER_BEFORE_LOOP_BOUNDARY": bool(max_banner < 40),
            "TRANSITION_OCCLUSION_REACHES_95PCT_BEFORE_STATE_SWAP": bool(occ89 >= 0.95),
            "LOOP_RESTART_READS_AS_NEW_CYCLE": bool(occ89 >= 0.95 and h0_alive > 200),   # cut from black -> fresh alive opening
            "no_paid_generation": True, "no_rig": True, "does_not_touch_frozen_H0_A1_A3_A3B_A4_A5": True}}
res["A6_final_frame_sha256"] = sha(f"{OUT}/A6_final_frame.png")
json.dump(res, open(f"{OUT}/A6_result.json", "w"), indent=2, default=str)
print(json.dumps(res["gates"], indent=2)); print(json.dumps(res["metrics"], indent=2)); print("DONE")
