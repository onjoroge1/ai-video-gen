"""END-TO-END production render on the FROZEN master (NO Kling, NO paid provider; frozen beats untouched).
Offline audio: narration (macOS `say`), deterministic SFX + suspense music (numpy), dialogue ducking + SILENCE on "Zero",
-14 LUFS / <-1 dBTP (ffmpeg loudnorm 2-pass), burned phone-safe captions (PIL overlays) + matching SRT, final muxed
1080x1920 H.264/AAC + a lightweight review copy + a delivery report. Run: python3 -m bolt_seq.render_production"""
import os, sys, json, subprocess, hashlib, shutil
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from scipy.io import wavfile
from PIL import Image, ImageDraw, ImageFont
from matplotlib import font_manager as fm
FPS, NF, SR = 30, 619, 48000
DUR = NF / FPS
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"
MASTER = f"{AT}/master/oxygen_master_619f.mp4"
OUT = f"{AT}/final"; os.makedirs(OUT, exist_ok=True)
FP = fm.findfont("DejaVu Sans"); FPB = fm.findfont("DejaVu Sans:bold") if os.path.exists(fm.findfont("DejaVu Sans")) else FP
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()

# locked narration (start, end, text)
LINES = [(0.00, 1.85, "What if every breath required a subscription?"),
         (2.05, 5.65, "Bolt has one small oxygen reserve — and the refill terminal is far away."),
         (5.70, 8.10, "The meter drops as he pushes toward it."),
         (8.15, 11.20, "His vision tunnels; his motors begin to fail."),
         (11.30, 12.30, "He's almost there —"),
         (12.65, 13.05, "Zero."),
         (13.55, 17.20, "Oxygen isn't stored — every breath renews the subscription.")]
N = int(round(DUR * SR))

# ---------------- helpers ----------------
def env(n, a=0.01, r=0.05):
    e = np.ones(n); ai = int(a * SR); ri = int(r * SR)
    if ai: e[:ai] = np.linspace(0, 1, ai)
    if ri: e[-ri:] = np.linspace(1, 0, ri)
    return e
def sine(f, n, ph=0.0): t = np.arange(n) / SR; return np.sin(2 * np.pi * f * t + ph)
def saw(f, n): t = np.arange(n) / SR; return 2 * (t * f - np.floor(0.5 + t * f))
def noise(n): return np.random.default_rng(7).standard_normal(n)
def lp(x, a=0.02):
    y = np.zeros_like(x); acc = 0.0
    for i in range(len(x)): acc += a * (x[i] - acc); y[i] = acc
    return y
def sweep(f0, f1, n):
    t = np.arange(n) / SR; k = (f1 / f0) ** (1 / (n / SR)); ph = 2 * np.pi * f0 * ((k ** t - 1) / np.log(k)); return np.sin(ph)
def place(bed, clip, t, g=1.0):
    s = int(round(t * SR)); e = min(len(bed), s + len(clip))
    if s < len(bed) and e > s: bed[s:e] += g * clip[:e - s]

# ---------------- A. narration (offline `say`) ----------------
voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
VOICE = next((v for v in ["Samantha", "Alex", "Daniel", "Tom", "Fred"] if f"{v} " in voices), None)
narr = np.zeros(N); caps_meta = []
tmp = f"{OUT}/_tts"; os.makedirs(tmp, exist_ok=True)
for i, (t0, t1, txt) in enumerate(LINES):
    aiff = f"{tmp}/l{i}.aiff"; wav = f"{tmp}/l{i}.wav"
    cmd = ["say"] + (["-v", VOICE] if VOICE else []) + ["-o", aiff, txt]
    subprocess.run(cmd, check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", aiff, "-ar", str(SR), "-ac", "1", wav], check=True)
    sr, a = wavfile.read(wav); a = a.astype(np.float32); a /= (np.abs(a).max() + 1e-9)
    win = t1 - t0; dur = len(a) / SR
    if dur > win * 1.02:                                             # speed up to fit the locked window (keeps sync)
        fac = min(2.0, dur / (win * 0.98)); wav2 = f"{tmp}/l{i}_f.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-filter:a", f"atempo={fac:.3f}", wav2], check=True)
        sr, a = wavfile.read(wav2); a = a.astype(np.float32); a /= (np.abs(a).max() + 1e-9)
    a *= env(len(a), 0.01, 0.04)
    place(narr, a, t0, 0.95)
    caps_meta.append((t0, t1, txt))                                  # captions use the LOCKED window

# ---------------- B. SFX (deterministic synth) ----------------
sfx = np.zeros(N)
# 1 subscription denial (~t0.95): two descending harsh buzzes
for k, f in enumerate([420, 300]):
    c = (0.6 * np.sign(sine(f, int(0.16 * SR))) ) * env(int(0.16 * SR), 0.005, 0.06); place(sfx, c, 0.95 + k * 0.19, 0.28)
# 2 thruster (t~2.0, fades over ~2s): filtered noise whoosh + low rumble
th = int(2.2 * SR); tn = lp(noise(th), 0.05) * np.linspace(1, 0.0, th) ** 1.5 + 0.4 * sine(70, th) * np.linspace(1, 0, th); place(sfx, tn, 2.0, 0.22)
# 3 meter warning beeps (t2.6..9.4, intensifying)
tt = 2.6
while tt < 9.5:
    f = 820 + (tt - 2.6) * 22; b = sine(f, int(0.09 * SR)) * env(int(0.09 * SR), 0.004, 0.03); place(sfx, b, tt, 0.14)
    tt += max(0.55, 1.3 - (tt - 2.6) * 0.08)
# 4 motor weakening (t8.2..11.25): wavering detuning low tone
mw = int(3.05 * SR); tw = np.arange(mw) / SR; wob = 150 * (1 - 0.35 * tw / 3.05) + 6 * np.sin(2 * np.pi * 5 * tw)
mwv = np.sin(2 * np.pi * np.cumsum(wob) / SR) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * tw)) * np.linspace(0.5, 0.9, mw); place(sfx, mwv, 8.2, 0.16)
# 5 power-down (t11.3..13.4): descending whine to ~silence at "Zero"
pd = int(2.1 * SR); pdv = sweep(520, 42, pd) * np.linspace(0.9, 0.0, pd) ** 1.3; place(sfx, pdv, 11.3, 0.20)
# 6 terminal hum (steady bed t0..20.6, louder during A5 13.5-17.8)
hum = (0.5 * sine(64, N) + 0.25 * sine(128, N)) * 0.4
hg = np.full(N, 0.5); hg[int(13.5 * SR):int(17.8 * SR)] = 0.85
sfx += hum * hg
# 7 warning flare (t17.6, rising alarm)
wf = int(0.9 * SR); wfv = sweep(320, 780, wf) * (0.6 + 0.4 * np.sin(2 * np.pi * 7 * np.arange(wf) / SR)) * env(wf, 0.02, 0.2); place(sfx, wfv, 17.6, 0.18)
# 8 occlusion (t18.6..20.4): low rumble swell into black
oc = int(1.8 * SR); ocv = lp(noise(oc), 0.02) * (np.linspace(0, 1, oc) ** 2) + 0.5 * sine(48, oc) * np.linspace(0, 1, oc); place(sfx, ocv, 18.6, 0.24)
# 9 restart sting (t~20.35): short bright hit (cycle renews)
rs = int(0.3 * SR); rsv = (sine(660, rs) + 0.5 * sine(990, rs)) * env(rs, 0.002, 0.25); place(sfx, rsv, 20.33, 0.22)

# ---------------- C. music (restrained suspense bed) ----------------
mus = 0.0 * np.zeros(N)
root = 55.0                                                          # A1 drone
drone = 0.5 * saw(root, N) + 0.4 * saw(root * 1.5, N) + 0.3 * saw(root * 2.02, N)
drone = lp(drone, 0.006)                                            # heavy lowpass -> warm bed
swell = 0.6 + 0.4 * np.sin(2 * np.pi * 0.05 * np.arange(N) / SR)    # slow swell
mus = drone * swell * 0.5
# sparse tension notes (minor) at beat moments
for tt, f in [(2.0, 220.0), (6.0, 262.0), (9.0, 247.0), (13.6, 175.0), (17.7, 208.0)]:
    n = int(1.6 * SR); note = (sine(f, n) + 0.3 * sine(f * 2, n)) * env(n, 0.05, 1.2); place(mus, note, tt, 0.10)

# dialogue ducking + SILENCE on "Zero"
duck = np.zeros(N)
for (t0, t1, _) in LINES: duck[int(t0 * SR):int(t1 * SR)] = 1.0
duck = lp(duck, 0.01); duck = duck / (duck.max() + 1e-9)
mgain = 1.0 - 0.6 * duck                                            # music ducks ~ -8dB under narration
mgain[int(12.35 * SR):int(13.25 * SR)] = 0.0                        # SILENCE emphasis around "Zero"
mus = mus * mgain

# ---------------- D. mix + write ----------------
mix = 0.55 * mus + 0.9 * sfx + 1.0 * narr
mix = mix / (np.abs(mix).max() + 1e-9) * 0.89
st = np.stack([mix, mix], 1)                                        # (music slight width could be added; keep mono-safe)
mixwav = f"{OUT}/mix_raw.wav"; wavfile.write(mixwav, SR, (st * 32767).astype(np.int16))

# 2-pass loudnorm -> -14 LUFS / -1 dBTP
meas = subprocess.run(["ffmpeg", "-hide_banner", "-i", mixwav, "-af", "loudnorm=I=-14:TP=-1.0:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True).stderr
mj = json.loads(meas[meas.rfind("{"):meas.rfind("}") + 1])
mixnorm = f"{OUT}/mix_norm.wav"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mixwav, "-af",
                f"loudnorm=I=-14:TP=-1.0:LRA=11:measured_I={mj['input_i']}:measured_TP={mj['input_tp']}:measured_LRA={mj['input_lra']}:measured_thresh={mj['input_thresh']}:offset={mj['target_offset']}:linear=true",
                "-ar", str(SR), "-ac", "2", mixnorm], check=True)

# ---------------- E. SRT ----------------
def ts(s): h = int(s // 3600); m = int(s % 3600 // 60); sec = s % 60; return f"{h:02d}:{m:02d}:{sec:06.3f}".replace(".", ",")
srt = f"{OUT}/oxygen_captions.srt"
with open(srt, "w") as f:
    for i, (t0, t1, txt) in enumerate(caps_meta, 1): f.write(f"{i}\n{ts(t0)} --> {ts(t1)}\n{txt}\n\n")

# ---------------- F. phone-safe caption PNGs (transparent overlays) ----------------
def wrap(txt, font, maxw, draw):
    words = txt.split(); lines = []; cur = ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= maxw: cur = t
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines
capfont = ImageFont.truetype(FPB, 58)
cappngs = []
for i, (t0, t1, txt) in enumerate(caps_meta):
    im = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    lines = wrap(txt, capfont, 960, d); lh = 74; total = len(lines) * lh; y0 = 1400 - total  # lower-third, ABOVE H0's baked 'SUBSCRIPTION REQUIRED' banner (~y1500) and below the terminal (<y960)
    for j, ln in enumerate(lines):
        w = d.textlength(ln, font=capfont); x = (1080 - w) / 2; y = y0 + j * lh
        d.rounded_rectangle([x - 22, y - 8, x + w + 22, y + 66], 14, fill=(0, 0, 0, 150))
    for j, ln in enumerate(lines):
        w = d.textlength(ln, font=capfont); x = (1080 - w) / 2; y = y0 + j * lh
        d.text((x, y), ln, font=capfont, fill=(255, 255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
    p = f"{OUT}/_cap{i}.png"; im.save(p); cappngs.append((p, t0, t1))

# ---------------- G. final mux (captions overlay + audio) ----------------
FINAL = f"{OUT}/oxygen_final_1080x1920.mp4"
inputs = ["-i", MASTER]
for p, _, _ in cappngs: inputs += ["-i", p]
inputs += ["-i", mixnorm]
fc = []; cur = "0:v"
for k, (_, t0, t1) in enumerate(cappngs, start=1):
    nxt = f"v{k}"; fc.append(f"[{cur}][{k}:v]overlay=0:0:enable='between(t,{t0:.3f},{t1:.3f})'[{nxt}]"); cur = nxt
audio_idx = len(cappngs) + 1
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(fc),
                "-map", f"[{cur}]", "-map", f"{audio_idx}:a", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", FINAL], check=True)
REVIEW = f"{OUT}/oxygen_review_540x960.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", FINAL, "-vf", "scale=540:960", "-c:v", "libx264", "-crf", "28", "-c:a", "aac", "-b:a", "128k", REVIEW], check=True)

# ---------------- H. delivery report ----------------
def probe(p, s): return subprocess.run(["ffprobe", "-v", "error", "-select_streams", s[0], "-show_entries", s, "-of", "csv=p=0", p], capture_output=True, text=True).stdout.strip()
vframes = probe(FINAL, "v:0=nb_read_frames") if False else subprocess.run(["ffprobe","-v","error","-count_frames","-select_streams","v:0","-show_entries","stream=nb_read_frames","-of","csv=p=0",FINAL],capture_output=True,text=True).stdout.strip()
vdur = subprocess.run(["ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=duration","-of","csv=p=0",FINAL],capture_output=True,text=True).stdout.strip()
adur = subprocess.run(["ffprobe","-v","error","-select_streams","a:0","-show_entries","stream=duration","-of","csv=p=0",FINAL],capture_output=True,text=True).stdout.strip()
# verify final loudness
meas2 = subprocess.run(["ffmpeg","-hide_banner","-i",FINAL,"-af","loudnorm=I=-14:TP=-1.0:LRA=11:print_format=json","-f","null","-"],capture_output=True,text=True).stderr
mj2 = json.loads(meas2[meas2.rfind("{"):meas2.rfind("}")+1])
frozen = {b: sha(f"{AT}/{p}")[:16] for b, p in {"H0":"h0_hook/H0.mp4","A1_A2_A3":"assembled/A1_A2_A3_sequence.mp4","A3B":"a3b_bridge/A3B.mp4","A4":"a4_collapse/A4_powerdown.mp4","A5":"a5_resolution/A5_aftermath.mp4","A6":"a6_cta_loop/A6_cta_loop.mp4","MASTER":"master/oxygen_master_619f.mp4"}.items()}
report = {"objective": "end_to_end_production_render", "no_spend": True, "provider_called": False, "ALLOW_PAID": False,
  "audio_source": "OFFLINE pipeline-test: macOS `say` TTS (voice=%s) + deterministic numpy SFX/music. NOT neural TTS / licensed music (separate paid step)." % (VOICE or "default"),
  "deliverables": {"final_mp4": FINAL, "review_mp4": REVIEW, "srt": srt, "mix_norm_wav": mixnorm},
  "video": {"resolution": "1080x1920", "fps": FPS, "frame_count": int(vframes) if vframes else None, "frame_count_expected": NF, "duration_s": round(float(vdur), 3) if vdur else None, "duration_expected_s": round(DUR, 3)},
  "audio": {"duration_s": round(float(adur), 3) if adur else None, "target_LUFS": -14.0, "measured_output_I_LUFS": mj2.get("input_i"), "target_TP_dBTP": -1.0, "measured_output_TP_dBTP": mj2.get("input_tp"), "measured_LRA": mj2.get("input_lra")},
  "narration_windows": [{"line": i, "start": t0, "end": t1, "text": txt} for i, (t0, t1, txt) in enumerate(LINES)],
  "caption_timing": [{"i": i + 1, "start": round(t0, 3), "end": round(t1, 3), "text": txt} for i, (t0, t1, txt) in enumerate(caps_meta)],
  "sound_design": ["subscription_denial@0.95", "thruster@2.0", "meter_warning@2.6-9.5", "motor_weakening@8.2", "power_down@11.3", "terminal_hum(bed,louder A5)", "warning_flare@17.6", "occlusion@18.6", "restart_sting@20.33"],
  "music": "restrained suspense drone bed; dialogue ducking (-8dB under VO); SILENCE emphasis 12.35-13.25 on 'Zero'",
  "captions": "burned-in phone-safe (bottom safe band, bold 58px, dark bar + stroke) + matching SRT",
  "source_hashes_frozen_unchanged": frozen,
  "final_mp4_sha256": sha(FINAL), "srt_sha256": sha(srt),
  "note": "A4 = the FROZEN power-down clip (used as-is). Frozen beats + master byte-unchanged; captions/audio muxed into a NEW deliverable. NOT frozen as a new master (awaiting end-to-end human review)."}
json.dump(report, open(f"{OUT}/delivery_report.json", "w"), indent=2, default=str)
shutil.rmtree(tmp, ignore_errors=True)
print(json.dumps({"video": report["video"], "audio": report["audio"], "final": FINAL, "review": REVIEW}, indent=2))
print("VOICE:", VOICE, "| frozen unchanged:", frozen["MASTER"]); print("DONE")
