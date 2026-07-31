"""oxygen_salvage_v2 — EDITORIAL RECUT ONLY (no Kling, no paid provider, no regeneration, no character surgery).
Reads frozen beat mp4s READ-ONLY, re-edits into a punchy 455f/15.17s Short: frame-selection per beat + continuous camera
motion (Ken-Burns, <=12-frame static rule) + information-bearing PUNCH-INS (crop-zooms of existing frames) + hard cuts +
A5 restructured into wide/terminal-CU/bolt-CU + A6 rapid close-to-black. New 7-line narration (temporary offline TTS),
adapted SFX/music with 'Zero' isolated, SHORT phrase-group captions (no duplicate of the frozen banner). Frozen sources
untouched; NOT frozen; no validation panel. Run: python3 -m bolt_seq.build_salvage_v2"""
import os, sys, json, subprocess, hashlib
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from scipy.io import wavfile
from PIL import Image, ImageDraw, ImageFont
from matplotlib import font_manager as fm
W, H, FPS, SR = 1080, 1920, 30, 48000
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"
OUT = f"{AT}/salvage_v2"; FR = f"{OUT}/_frames"; os.makedirs(FR, exist_ok=True)
FP = fm.findfont("DejaVu Sans"); FPB = fm.findfont("DejaVu Sans:bold")
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()

BEATS = {"H0": f"{AT}/h0_hook/H0.mp4", "A": f"{AT}/assembled/A1_A2_A3_sequence.mp4", "A3B": f"{AT}/a3b_bridge/A3B.mp4",
         "A4": f"{AT}/a4_collapse/A4_powerdown.mp4", "A5": f"{AT}/a5_resolution/A5_aftermath.mp4", "A6": f"{AT}/a6_cta_loop/A6_cta_loop.mp4"}
FD = {}
for k, mp in BEATS.items():
    d = f"{OUT}/_src_{k}"; os.makedirs(d, exist_ok=True); [os.remove(os.path.join(d, x)) for x in os.listdir(d)]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp, "-vf", f"scale={W}:{H}", "-start_number", "0", os.path.join(d, "f%04d.png")], check=True)
    FD[k] = d
def SRC(k, i): return np.asarray(Image.open(f"{FD[k]}/f{i:04d}.png").convert("RGB"), float)

def crop(fr, cx, cy, zoom):
    w = int(round(W / zoom)); h = int(round(H / zoom))
    x = max(0, min(W - w, int(round(cx - w / 2)))); y = max(0, min(H - h, int(round(cy - h / 2))))
    return np.asarray(Image.fromarray(fr[y:y + h, x:x + w].astype("uint8")).resize((W, H), Image.BICUBIC), float)
def cen(fr):
    R, G, B = fr[:, :, 0], fr[:, :, 1], fr[:, :, 2]
    m = ((np.minimum(np.minimum(R, G), B) > 90) | ((B > R + 15) & (B > 90)))
    m[:, :100] = False  # drop left red sign
    ys, xs = np.where(m); return (float(xs.mean()), float(ys.mean())) if len(xs) > 200 else (500.0, 1150.0)
def ss(x): x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)

# ---------- EDL: build 455 output frames (beat, src_idx, cx, cy, zoom) ----------
edl = []
def push(beat, s0, s1, n, z0=1.0, z1=1.08, c=(W/2, H/2)):
    for k in range(n): edl.append((beat, s0 + round((s1 - s0) * k / max(1, n - 1)), c[0], c[1], z0 + (z1 - z0) * k / max(1, n - 1)))
def punch(beat, s0, s1, n, z, mode="fixed", cxy=(W/2, H/2), dz=0.06):
    for k in range(n):
        si = s0 + round((s1 - s0) * k / max(1, n - 1)); zz = z + dz * k / max(1, n - 1)
        if mode == "bolt": bx, by = cen(SRC(beat, si)); cx, cy = bx, by
        elif mode == "eyes": bx, by = cen(SRC(beat, si)); cx, cy = bx, by - 0.10 * H / zz
        elif mode == "green":                                          # follow the green refill terminal (the goal)
            fr = SRC(beat, si); R, G, B = fr[:, :, 0], fr[:, :, 1], fr[:, :, 2]; g = (G > R + 25) & (G > B + 15) & (G > 90)
            ys, xs = np.where(g); cx, cy = (float(xs.mean()), float(ys.mean())) if len(xs) > 50 else cxy
        else: cx, cy = cxy
        edl.append((beat, si, cx, cy, zz))

# H0 (src 15-59): push-in hook (45)
push("H0", 15, 59, 45, 1.0, 1.10)
# A1-A3 (src 0-231, 232): wide push with thruster/meter/eyes punch-ins (hard cuts)
push("A", 0, 14, 15, 1.0, 1.03)
punch("A", 15, 27, 13, 2.2, "bolt", dz=0.05)                    # THRUSTER (bolt-follow; base+plume in the 9:16 crop)
push("A", 28, 199, 172, 1.03, 1.09)                            # continuous approach push (no forced mid-punch; terminal is punched in A5; meter arc = H0 LOCKED + A3B EXPIRED)
punch("A", 200, 214, 15, 2.9, "eyes")                          # EYES punch (dimming)
push("A", 215, 231, 17, 1.05, 1.09)
# A3B (src 0-45, 46): push + EXPIRED-display punch
push("A3B", 0, 19, 20, 1.0, 1.05)
punch("A3B", 20, 34, 15, 2.2, "fixed", (330, 320))            # O2 EXPIRED display
push("A3B", 35, 45, 11, 1.05, 1.08)
# A4 (src 0-65, 66): push + eyes(dimming) punch + fade
push("A4", 0, 14, 15, 1.0, 1.04)
punch("A4", 15, 28, 14, 2.9, "eyes")                          # EYES powering down
push("A4", 29, 65, 37, 1.04, 1.10)
# A5 (src 0-53, 54): RESTRUCTURE -> wide reveal / terminal CU / powered-off Bolt CU
push("A5", 0, 17, 18, 1.0, 1.06)                               # wide aftermath reveal
punch("A5", 18, 35, 18, 2.4, "fixed", (740, 790), dz=0.05)    # TERMINAL close-up
punch("A5", 36, 53, 18, 2.2, "bolt", dz=0.05)                # powered-off BOLT close-up
# A6 (src 78-89, 12): rapid close-to-black
push("A6", 78, 89, 12, 1.02, 1.08)
NF = len(edl); assert NF == 455, f"{NF} != 455"

# render output frames
[os.remove(os.path.join(FR, x)) for x in os.listdir(FR)]
for oi, (beat, si, cx, cy, z) in enumerate(edl):
    Image.fromarray(np.clip(crop(SRC(beat, si), cx, cy, z), 0, 255).astype("uint8")).save(f"{FR}/o{oi:04d}.png")
VID = f"{OUT}/_video_noaudio.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", f"{FR}/o%04d.png", "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), VID], check=True)
DUR = NF / FPS

# ---------- audio (TEMPORARY offline) ----------
Nn = int(round(DUR * SR))
def envf(n, a=0.01, r=0.05):
    e = np.ones(n); ai, ri = int(a * SR), int(r * SR)
    if ai: e[:ai] = np.linspace(0, 1, ai)
    if ri: e[-ri:] = np.linspace(1, 0, ri)
    return e
def sine(f, n): return np.sin(2 * np.pi * f * np.arange(n) / SR)
def saw(f, n): t = np.arange(n) / SR; return 2 * (t * f - np.floor(0.5 + t * f))
def noise(n): return np.random.default_rng(5).standard_normal(n)
def lp(x, a=0.02):
    y = np.zeros_like(x); acc = 0.0
    for i in range(len(x)): acc += a * (x[i] - acc); y[i] = acc
    return y
def swp(f0, f1, n):
    t = np.arange(n) / SR; k = (f1 / f0) ** (1 / (n / SR)); return np.sin(2 * np.pi * f0 * ((k ** t - 1) / np.log(k)))
def place(bed, clip, t, g=1.0):
    s = int(round(t * SR)); e = min(len(bed), s + len(clip))
    if s < len(bed) and e > s: bed[s:e] += g * clip[:e - s]

LINES = [(0.10, 1.40, "What if every breath required a subscription?"),
         (1.65, 3.90, "Bolt has one reserve—and the refill terminal is ahead."),
         (4.20, 6.10, "But his access meter is draining."),
         (6.40, 9.60, "His vision narrows. His motors begin to fail."),
         (10.85, 11.70, "He's almost there—"),
         (12.20, 12.60, "Zero."),
         (13.10, 14.90, "The oxygen never ran out. His subscription did.")]
voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
VOICE = next((v for v in ["Samantha", "Alex", "Daniel"] if f"{v} " in voices), None)
narr = np.zeros(Nn); tmp = f"{OUT}/_tts"; os.makedirs(tmp, exist_ok=True)
for i, (t0, t1, txt) in enumerate(LINES):
    aiff, wav = f"{tmp}/l{i}.aiff", f"{tmp}/l{i}.wav"
    subprocess.run(["say"] + (["-v", VOICE] if VOICE else []) + ["-o", aiff, txt], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", aiff, "-ar", str(SR), "-ac", "1", wav], check=True)
    _, a = wavfile.read(wav); a = a.astype(np.float32); a /= (np.abs(a).max() + 1e-9)
    win = t1 - t0
    if len(a) / SR > win * 1.02:
        fac = min(2.0, (len(a) / SR) / (win * 0.98)); w2 = f"{tmp}/l{i}f.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-filter:a", f"atempo={fac:.3f}", w2], check=True)
        _, a = wavfile.read(w2); a = a.astype(np.float32); a /= (np.abs(a).max() + 1e-9)
    a *= envf(len(a), 0.01, 0.04); place(narr, a, t0, 0.95)

sfx = np.zeros(Nn)
for k, f in enumerate([420, 300]): place(sfx, np.sign(sine(f, int(0.15 * SR))) * envf(int(0.15 * SR), 0.005, 0.06), 0.45 + k * 0.18, 0.26)   # denial
th = int(1.6 * SR); place(sfx, (lp(noise(th), 0.05) * np.linspace(1, 0, th) ** 1.5 + 0.4 * sine(70, th) * np.linspace(1, 0, th)), 1.55, 0.22)  # thruster
tt = 2.1
while tt < 8.9:
    place(sfx, sine(820 + (tt - 2.1) * 26, int(0.09 * SR)) * envf(int(0.09 * SR), 0.004, 0.03), tt, 0.14); tt += max(0.5, 1.2 - (tt - 2.1) * 0.09)
mw = int(1.5 * SR); tw = np.arange(mw) / SR; place(sfx, np.sin(2 * np.pi * np.cumsum(150 * (1 - 0.35 * tw / 1.5) + 6 * np.sin(2 * np.pi * 5 * tw)) / SR) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * tw)), 9.2, 0.16)  # motor weakening
pd = int(2.0 * SR); place(sfx, swp(520, 42, pd) * np.linspace(0.9, 0, pd) ** 1.3, 10.8, 0.20)   # power-down -> silence at Zero
hum = (0.5 * sine(64, Nn) + 0.25 * sine(128, Nn)) * 0.4; hg = np.full(Nn, 0.45); hg[int(12.97 * SR):int(14.9 * SR)] = 0.85; sfx += hum * hg
wf = int(0.4 * SR); place(sfx, swp(320, 780, wf) * envf(wf, 0.02, 0.15), 14.77, 0.18)           # warning flare
oc = int(0.4 * SR); place(sfx, (lp(noise(oc), 0.02) * np.linspace(0, 1, oc) ** 2 + 0.5 * sine(48, oc) * np.linspace(0, 1, oc)), 14.9, 0.26)  # occlusion

mus = lp(0.5 * saw(55, Nn) + 0.4 * saw(82.5, Nn) + 0.3 * saw(110, Nn), 0.006) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.06 * np.arange(Nn) / SR)) * 0.5
for tt, f in [(1.6, 220.0), (4.3, 247.0), (6.5, 175.0), (13.1, 208.0)]:
    n = int(1.4 * SR); place(mus, (sine(f, n) + 0.3 * sine(f * 2, n)) * envf(n, 0.05, 1.1), tt, 0.10)
duck = np.zeros(Nn)
for (t0, t1, _) in LINES: duck[int(t0 * SR):int(t1 * SR)] = 1.0
duck = lp(duck, 0.01); duck /= (duck.max() + 1e-9); mg = 1.0 - 0.6 * duck; mg[int(11.9 * SR):int(12.85 * SR)] = 0.0   # SILENCE on Zero
mus *= mg
mix = 0.55 * mus + 0.9 * sfx + 1.0 * narr; mix = mix / (np.abs(mix).max() + 1e-9) * 0.89
mraw = f"{OUT}/mix_raw.wav"; wavfile.write(mraw, SR, (np.stack([mix, mix], 1) * 32767).astype(np.int16))
meas = subprocess.run(["ffmpeg", "-hide_banner", "-i", mraw, "-af", "loudnorm=I=-14:TP=-1.0:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True).stderr
mj = json.loads(meas[meas.rfind("{"):meas.rfind("}") + 1]); mnorm = f"{OUT}/mix_norm.wav"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mraw, "-af", f"loudnorm=I=-14:TP=-1.0:LRA=11:measured_I={mj['input_i']}:measured_TP={mj['input_tp']}:measured_LRA={mj['input_lra']}:measured_thresh={mj['input_thresh']}:offset={mj['target_offset']}:linear=true", "-ar", str(SR), "-ac", "2", mnorm], check=True)

# ---------- SHORT phrase-group captions (L1 suppressed: banner carries the hook) ----------
CAPS = [(1.65, 2.70, "One reserve."), (2.80, 3.90, "Terminal ahead."), (4.20, 6.10, "Meter draining."),
        (6.40, 8.00, "Vision narrowing."), (8.10, 9.60, "Motors failing."), (10.85, 11.70, "Almost there—"),
        (12.20, 12.60, "Zero."), (13.10, 14.00, "The oxygen never ran out."), (14.05, 14.90, "His subscription did.")]
def tsr(s): return f"{int(s//3600):02d}:{int(s%3600//60):02d}:{s%60:06.3f}".replace(".", ",")
srt = f"{OUT}/oxygen_salvage_v2.srt"
with open(srt, "w") as f:
    for i, (t0, t1, txt) in enumerate(CAPS, 1): f.write(f"{i}\n{tsr(t0)} --> {tsr(t1)}\n{txt}\n\n")
capfont = ImageFont.truetype(FPB, 66); cappngs = []
for i, (t0, t1, txt) in enumerate(CAPS):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    w = d.textlength(txt, font=capfont); x = (W - w) / 2; y = 1360
    d.rounded_rectangle([x - 26, y - 10, x + w + 26, y + 84], 16, fill=(0, 0, 0, 150))
    d.text((x, y), txt, font=capfont, fill=(255, 255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
    p = f"{OUT}/_cap{i}.png"; im.save(p); cappngs.append((p, t0, t1))

# ---------- mux ----------
FINAL = f"{OUT}/oxygen_salvage_v2_1080x1920.mp4"
inp = ["-i", VID]
for p, _, _ in cappngs: inp += ["-i", p]
inp += ["-i", mnorm]
fc = []; cur = "0:v"
for k, (_, t0, t1) in enumerate(cappngs, 1): fc.append(f"[{cur}][{k}:v]overlay=0:0:enable='between(t,{t0:.3f},{t1:.3f})'[v{k}]"); cur = f"v{k}"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inp, "-filter_complex", ";".join(fc), "-map", f"[{cur}]", "-map", f"{len(cappngs)+1}:a",
                "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", FINAL], check=True)
REVIEW = f"{OUT}/oxygen_salvage_v2_review_540x960.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", FINAL, "-vf", "scale=540:960", "-c:v", "libx264", "-crf", "28", "-c:a", "aac", "-b:a", "128k", REVIEW], check=True)

# motion check (prove the <=12-frame static rule)
def OF(i): return np.asarray(Image.open(f"{FR}/o{i:04d}.png").convert("RGB").resize((270, 480)), float)
mot = [0.0] + [float(np.abs(OF(i) - OF(i - 1)).mean()) for i in range(1, NF)]
run = mx = 0
for m in mot:
    run = run + 1 if m < 0.5 else 0; mx = max(mx, run)
vframes = subprocess.run(["ffprobe","-v","error","-count_frames","-select_streams","v:0","-show_entries","stream=nb_read_frames","-of","csv=p=0",FINAL],capture_output=True,text=True).stdout.strip()
adur = subprocess.run(["ffprobe","-v","error","-select_streams","a:0","-show_entries","stream=duration","-of","csv=p=0",FINAL],capture_output=True,text=True).stdout.strip()
report = {"objective": "oxygen_salvage_v2_editorial_recut", "no_spend": True, "provider_called": False, "ALLOW_PAID": False,
  "note": "EDITORIAL RECUT of frozen beats (read-only). No Kling/regeneration/surgery. Temporary offline audio. NOT frozen; no validation panel.",
  "structure": {"H0": "src15-59 (45)", "A1_A2_A3": "all 232", "A3B": "all 46", "A4": "all 66", "A5": "first54 -> wide/terminalCU/boltCU", "A6": "src78-89 (12)", "total_frames": NF, "duration_s": round(DUR, 3)},
  "video": {"frame_count": int(vframes) if vframes else None, "expected": 455, "duration_s": round(DUR, 3), "resolution": "1080x1920", "fps": FPS},
  "audio": {"duration_s": round(float(adur), 3) if adur else None, "temporary_offline_TTS": VOICE, "target_LUFS": -14, "note": "temporary; paid neural TTS + music is a separate step"},
  "editorial": {"max_static_run_frames": mx, "static_rule_<=12_ok": bool(mx <= 12), "punch_ins": ["thruster", "meter", "eyes", "expired_display", "terminal", "powered_off_bolt"], "cuts": "hard cuts only (no dissolves)", "captions": "short phrase groups; L1 hook caption SUPPRESSED (banner carries it)", "zero_isolated": "music silenced 11.9-12.85"},
  "narration": [{"line": i + 1, "start": t0, "end": t1, "text": txt} for i, (t0, t1, txt) in enumerate(LINES)],
  "caption_phrases": [{"start": t0, "end": t1, "text": txt} for (t0, t1, txt) in CAPS],
  "deliverables": {"final": FINAL, "review": REVIEW, "srt": srt}, "final_sha256": sha(FINAL),
  "frozen_sources_readonly": {k: sha(v)[:16] for k, v in BEATS.items()}}
json.dump(report, open(f"{OUT}/salvage_v2_report.json", "w"), indent=2, default=str)
import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(json.dumps({"total_frames": NF, "duration_s": round(DUR, 3), "max_static_run": mx, "static_rule_ok": mx <= 12, "final_frames": vframes, "audio_s": adur, "voice": VOICE}, indent=2))
print("FINAL:", FINAL); print("DONE")
