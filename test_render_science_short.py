"""REAL end-to-end test of the Phase-0/1 fixes: does a Short now actually MOVE and have audio?

Spends real API money (~$2-4). Verifies, in one run:
  * the action-style i2v prompt (movement instead of "subtle restrained... locked-off")
  * I2V_SECONDS=5 (we now use the clip length we're billed for)
  * tpad freeze instead of -stream_loop jump
  * music bed + SFX with sidechain ducking (previously: narration on silence)
  * motion_density_gate on the finished file (previously: nothing ever audited the MP4)

Run: /opt/homebrew/bin/python3 test_render_science_short.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# .env is not auto-loaded by the pipeline; app.py does it. Do the same here.
for line in open(".env", encoding="utf8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

import explainer_pipeline as ep
import video_audit

QUESTION = os.environ.get("TEST_QUESTION", "Why Can't You Remember Being A Baby?")
DURATION = int(os.environ.get("TEST_DURATION", "42"))       # data: the 37-52s shorts retained best
CAP = float(os.environ.get("TEST_CAP_USD", "6.00"))
OUT = os.path.abspath(os.environ.get("TEST_OUT", "renders/science_short_test"))

os.makedirs(OUT, exist_ok=True)
t0 = time.time()
print(f"topic     : {QUESTION}")
print(f"format    : social 1080x1920, ~{DURATION}s, cap ${CAP:.2f}")
print(f"i2v       : provider={os.environ.get('I2V_PROVIDER')}  I2V_SECONDS={ep.I2V_SECONDS}")
print(f"out       : {OUT}\n")


def log(m):
    print(f"  [{time.time()-t0:6.1f}s] {m}", flush=True)


res = ep.run_explainer_pipeline(
    question=QUESTION,
    output_dir=OUT,
    duration_sec=DURATION,
    video_format="social",
    max_cost_usd=CAP,
    i2v=True,
    progress_cb=log,
)

print("\n" + "=" * 78)
print("RESULT")
print("=" * 78)
for k in ("status", "video_path", "actual_cost_usd", "i2v_requested", "i2v_animated",
          "degraded_reasons", "scenes"):
    if k in res:
        v = res[k]
        if k == "scenes" and isinstance(v, list):
            v = f"{len(v)} scenes"
        print(f"  {k:18s}: {v}")

vp = res.get("video_path") or os.path.join(OUT, "explainer.mp4")
if os.path.exists(vp):
    print("\n--- MOTION GATE (the audit that never existed) ---")
    r = video_audit.motion_density_gate(vp)
    print(f"  {'PASS' if r.passed else 'FAIL'}  frames={r.frames} dur={r.duration_s}s  "
          f"moving={r.frac_moving*100:.1f}%  longest_hold={r.max_static_run}f")
    for f in r.failures:
        print(f"    -> {f}")
    print("\n--- AUDIO (music bed should be present; was silence before) ---")
    import subprocess
    a = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                        "-show_entries", "stream=codec_name,channels,duration",
                        "-of", "default=noprint_wrappers=1", vp],
                       capture_output=True, text=True).stdout.strip()
    print("  " + a.replace("\n", "  "))
    m = subprocess.run(["ffmpeg", "-hide_banner", "-i", vp, "-af",
                        "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    try:
        j = json.loads(m[m.rfind("{"):m.rfind("}") + 1])
        print(f"  integrated={j.get('input_i')} LUFS   true_peak={j.get('input_tp')} dBTP")
    except Exception:
        pass
    print(f"\n  sfx bed built: {os.path.exists(os.path.join(OUT,'_sfx.wav'))}")
    json.dump(r.as_dict(), open(os.path.join(OUT, "motion_report.json"), "w"), indent=2)
else:
    print("  NO VIDEO PRODUCED")
print(f"\nwall clock: {(time.time()-t0)/60:.1f} min")
