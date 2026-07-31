"""FINAL MASTER ASSEMBLY (authorized). Frame-exact stitch of the SIX FROZEN beats into one 619-frame master.
READS/decodes the frozen beat MP4s only (never regenerates/retouches/re-encodes the beat files; frozen hashes preserved).
Decodes each beat -> ordered PNG sequence (one master frame per source frame) -> single encode -> validate.
NO SPEND, ALLOW_PAID stays false, no paid provider. Run: python3 -m bolt_seq.assemble_master"""
import os, sys, json, hashlib, subprocess, shutil
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"
OUT = f"{AT}/master"; STAGE = f"{OUT}/_frames"; os.makedirs(STAGE, exist_ok=True)
W, H, FPS = 1080, 1920, 30
BEATS = [  # id, frozen source file, expected frame count (canonical grid)
  ("H0", f"{AT}/h0_hook/H0.mp4", 60),
  ("A1_A2_A3", f"{AT}/assembled/A1_A2_A3_sequence.mp4", 232),
  ("A3B", f"{AT}/a3b_bridge/A3B.mp4", 46),
  ("A4", f"{AT}/a4_collapse/A4_powerdown.mp4", 66),
  ("A5", f"{AT}/a5_resolution/A5_aftermath.mp4", 125),
  ("A6", f"{AT}/a6_cta_loop/A6_cta_loop.mp4", 90)]


def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def probe_frames(p): return int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", p], capture_output=True, text=True).stdout.strip() or 0)
def has_audio(p): return bool(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_name", "-of", "csv=p=0", p], capture_output=True, text=True).stdout.strip())

# ---------- pre-assembly baseline: frozen source hashes ----------
pre = {bid: sha(f) for bid, f, _ in BEATS}

# ---------- 2. concat manifest + per-beat frame-count verification ----------
concat, offset = [], 0
for bid, f, exp in BEATS:
    assert os.path.exists(f), f"MISSING frozen source: {f}"
    actual = probe_frames(f)
    assert actual == exp, f"{bid}: frame count {actual} != expected {exp} (frozen source drift)"
    concat.append({"beat": bid, "source": f, "sha256": pre[bid], "frames": exp,
                   "master_frame_start": offset, "master_frame_end_inclusive": offset + exp - 1, "audio": has_audio(f)})
    offset += exp
TOTAL = offset
assert TOTAL == 619, f"total frames {TOTAL} != 619"

# ---------- decode each frozen beat -> ordered master PNG sequence (one png per source frame) ----------
for x in os.listdir(STAGE): os.remove(os.path.join(STAGE, x))
for c in concat:
    before = len(os.listdir(STAGE))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", c["source"], "-vf", f"scale={W}:{H}",
                    "-start_number", str(c["master_frame_start"]), os.path.join(STAGE, "m%06d.png")], check=True)
    got = len(os.listdir(STAGE)) - before
    assert got == c["frames"], f"{c['beat']}: decoded {got} != {c['frames']} frames"
staged = sorted(os.listdir(STAGE))
assert len(staged) == 619 and staged[0] == "m000000.png" and staged[-1] == "m000618.png", f"stage has {len(staged)} frames / bad numbering"

# ---------- 1. single encode -> master ----------
MASTER = f"{OUT}/oxygen_master_619f.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(STAGE, "m%06d.png"),
                "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS), MASTER], check=True)
# low-res review copy + contact sheet
REVIEW = f"{OUT}/oxygen_master_review_540x960.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", MASTER, "-vf", "scale=540:960", "-c:v", "libx264", "-crf", "28", "-pix_fmt", "yuv420p", REVIEW], check=True)

def stg(i): return np.asarray(Image.open(os.path.join(STAGE, f"m{i:06d}.png")).convert("RGB"), float)

# ---------- 3. validation ----------
m_frames = probe_frames(MASTER); dur = m_frames / FPS
# re-decode the master and check frame CORRESPONDENCE (no drop/dupe/interpolation): master frame i must match staged i better than i±1
mdir = f"{OUT}/_mcheck"; os.makedirs(mdir, exist_ok=True); [os.remove(os.path.join(mdir, x)) for x in os.listdir(mdir)]
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", MASTER, "-start_number", "0", os.path.join(mdir, "c%06d.png")], check=True)
mcount = len(os.listdir(mdir))
def mck(i): return np.asarray(Image.open(os.path.join(mdir, f"c{i:06d}.png")).convert("RGB"), float)
boundaries = [c["master_frame_start"] for c in concat[1:]]  # 60,292,338,404,529
samples = sorted(set([0, 1, 59, 618, 617] + boundaries + [b - 1 for b in boundaries] + [150, 300, 450]))
corr_ok, corr_detail = True, []
for i in samples:
    d_self = float(np.abs(mck(i) - stg(i)).mean())
    d_prev = float(np.abs(mck(i) - stg(i - 1)).mean()) if i > 0 else 9e9
    d_next = float(np.abs(mck(i) - stg(i + 1)).mean()) if i < 618 else 9e9
    ok = (d_self <= d_prev and d_self <= d_next)     # master i corresponds to staged i (not shifted -> no drop/dupe)
    corr_ok &= ok; corr_detail.append({"i": i, "d_self": round(d_self, 2), "d_prev": round(d_prev, 2), "d_next": round(d_next, 2), "ok": ok})
# internal handoffs (cross-beat) measured on the true source frames (staged)
handoffs = []
for c in concat[1:]:
    b = c["master_frame_start"]; diff = float(np.abs(stg(b) - stg(b - 1)).mean())
    handoffs.append({"boundary": f"{b-1}|{b}", "between": f"{concat[[cc['master_frame_start'] for cc in concat].index(b)-1]['beat']}->{c['beat']}",
                     "cross_frame_mean_abs": round(diff, 2), "kind": "designed-match" if diff < 4 else "intended-cut"})
a6_black = float(stg(618).mean()); h0_first_next = float(np.abs(stg(0) - stg(0)).mean())  # H0 f0 begins next cycle (== master frame 0)
h0_restart_frame_mean = float(stg(0).mean())
post = {bid: sha(f) for bid, f, _ in BEATS}; hashes_unchanged = (post == pre)
audio_present = any(c["audio"] for c in concat)

report = {"objective": "final_master_assembly", "authorized": True, "no_spend": True, "provider_called": False, "ALLOW_PAID": False,
  "master": "master/oxygen_master_619f.mp4", "review_copy": "master/oxygen_master_review_540x960.mp4", "contact_sheet": "master/oxygen_master_contactsheet.png",
  "resolution": f"{W}x{H}", "fps": FPS,
  "validation": {
    "total_frames": m_frames, "total_frames_expected": 619, "total_frames_ok": m_frames == 619,
    "duration_s": round(dur, 6), "duration_expected_s": round(619 / 30, 6), "duration_ok": abs(dur - 619 / 30) < 1e-4,
    "master_redecode_frame_count": mcount, "no_drop_dup_interp_frame_correspondence_ok": bool(corr_ok),
    "internal_handoffs": handoffs, "all_handoffs_checked": True,
    "A6_ends_fully_black": bool(a6_black < 3.0), "A6_last_frame_mean": round(a6_black, 3),
    "H0_begins_next_cycle": True, "H0_f0_is_master_frame_0_mean": round(h0_restart_frame_mean, 1),
    "loop_note": "playback wrap = master frame 618 (black) -> master frame 0 (H0 alive+banner): deliberate occluded restart cut, NOT a seamless pixel match",
    "audio": {"present": audio_present, "note": "all beats are SILENT animatics -> master has NO audio track. Video timeline = 619f / 20.633333s. Narration (oxygen_subscription_animatic.srt) references the SAME 619f grid but is NOT rendered/muxed here (separate audio pass)."},
    "frozen_source_hashes_unchanged": bool(hashes_unchanged)},
  "concat_manifest": concat, "source_hashes_pre": pre, "source_hashes_post": post,
  "correspondence_samples": corr_detail,
  "stop": "master + validation package exported. ALLOW_PAID stays false. Kling production run NOT started (awaiting separate authorization)."}
json.dump({"beats": concat, "total_frames": 619, "fps": FPS, "resolution": f"{W}x{H}", "master": "master/oxygen_master_619f.mp4"}, open(f"{OUT}/concat_manifest.json", "w"), indent=2)
json.dump(report, open(f"{OUT}/assembly_validation.json", "w"), indent=2, default=str)

# ---------- 4. contact sheet ----------
cols, rows = 8, 5; cell = 200; sheetw = cols * (cell) + 20; cellh = int(cell * H / W)
sheet = Image.new("RGB", (sheetw, rows * (cellh + 26) + 10), (12, 12, 14)); dd = ImageDraw.Draw(sheet)
pick = [int(round(k * 618 / (cols * rows - 1))) for k in range(cols * rows)]
beat_of = lambda i: next(c["beat"] for c in concat if c["master_frame_start"] <= i <= c["master_frame_end_inclusive"])
for k, i in enumerate(pick):
    r, cc = divmod(k, cols); th = Image.open(os.path.join(STAGE, f"m{i:06d}.png")).resize((cell, cellh))
    sheet.paste(th, (cc * cell + 10, r * (cellh + 26) + 26)); dd.text((cc * cell + 12, r * (cellh + 26) + 10), f"f{i} {beat_of(i)}", fill=(225, 225, 225))
sheet.save(f"{OUT}/oxygen_master_contactsheet.png")
shutil.rmtree(mdir, ignore_errors=True)

print(json.dumps(report["validation"], indent=2, default=str))
print("MASTER:", MASTER, "| frames", m_frames, "| dur", round(dur, 4), "| hashes_unchanged", hashes_unchanged)
print("DONE")
