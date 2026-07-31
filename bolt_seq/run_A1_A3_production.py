"""A1-A3 PRODUCTION PASS (authorized paid): ONE candidate-set per invocation = 3 Kling v3-pro i2v segments on the FROZEN
boundary frames (A1 6d90c136->511a3084, A2 511a3084->09137687, A3 09137687->5403cbce), assembled FRAME-EXACT to 232
(A1[0:66]+A2[0:76]+A3[0:90]) preserving the H0->A1 start and A3->A3B end handoffs. Deterministic hard gates run here;
the phone-size perceptual panel runs separately. HARD $3.50 cap across up to 2 sets via a persistent ledger; ALLOW_PAID
enabled ONLY in try/finally around each call, reset + asserted false after. Frozen beats untouched; no master edits here.
Run: python3 -m bolt_seq.run_A1_A3_production"""
import os, sys, json, subprocess, hashlib, traceback
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw
from dotenv import load_dotenv; load_dotenv()                          # load FAL key from .env
from bolt_seq.providers import directed_video as DV
W, H, FPS = 1080, 1920, 30
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"
OUT = f"{AT}/a1a3_production"; os.makedirs(OUT, exist_ok=True)
CAP, VCOST, SEGS, MAX_SETS, TIMEOUT = 3.50, 0.34, 3, 2, 600
TP = (0.62, 0.46)                                                     # normalized wall-terminal position (from the A3 runner)
NEG = ("legs, feet, boots, shoes, walking, running, striding, ground contact, standing, a second robot, duplicate robot, "
       "twin, clone, two robots, split screen, mirror image, camera pan, camera tilt, camera zoom, camera shake, scene cut, "
       "new corridor, different room, changing background, teleport, jump cut, backward motion, reversing, retreating, "
       "moving away from the terminal, lateral dodge, sideways reset, relaunch, thrust burst at the end, sudden recovery, "
       "re-energize, standing up, collapsing to the floor, lying down, overshooting the terminal, extra limbs, morphing body, "
       "changing shape, anatomy mutation, deformed, text, caption, watermark, logo, subtitles, "
       # set-2 anti-recovery (panel: eyes re-brightened mid-clip) + sustain thruster
       "eyes brightening, eyes re-lighting, brighter eyes later, re-energizing, perking up, second wind, regaining energy, "
       "chest-out upright pose, alert energetic pose in the second half, bobbing up, rising up, thruster turning off early, no thruster")
# id, start_png, start_sha, end_png, end_sha, take_frames, prompt
SEGSPEC = [
  ("A1", f"{AT}/h0_hook/A1_first_frame.png", "6d90c136568406da", f"{AT}/a2_accepted/A2_first_frame.png", "511a3084c0ff62c0", 66,
   "A small white and mint hovering robot (dark visor, two bright cyan oval eyes, cyan chest panel, antenna with cyan bulb, rounded hover base, no legs) immediately begins drifting forward down a dim industrial corridor toward a distant wall-mounted green oxygen terminal. A steady cyan thruster plume trails continuously beneath its rounded hover base the entire time. Eyes bright and alert. Locked camera, fixed corridor, single robot, continuous smooth forward motion, hovering."),
  ("A2", f"{AT}/a2_accepted/A2_first_frame.png", "511a3084c0ff62c0", f"{AT}/a2_accepted/A2_final_frame.png", "09137687c3dee3e6", 76,
   "The same white and mint hovering robot pushes steadily forward down the same dim corridor, closing distance toward the wall oxygen terminal; it strains with effort but its cyan eyes stay lit and alert (NOT yet dimming). A faint cyan thruster plume trails continuously beneath the rounded hover base. Locked camera, fixed corridor, single robot, continuous forward motion, hovering, no legs."),
  ("A3", f"{AT}/a3_accepted/A3_start_frame.png", "09137687c3dee3e6", f"{AT}/a3_accepted/A3_final_frame.png", "5403cbce68dc38ea", 90,
   "The same hovering robot's power fails as it nears the oxygen terminal: from the very first moment its cyan eyes dim steadily and CONTINUOUSLY toward near-dark and NEVER brighten again; the body sags lower and droops throughout; a faint cyan thruster plume sputters and fades under the base; it makes one last weak, failing reach toward the terminal and slumps. It keeps hovering (no legs), never touches the floor, never recovers or perks up. Locked camera, fixed corridor, single robot.")]


def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
LED = f"{OUT}/spend_ledger.json"
led = json.load(open(LED)) if os.path.exists(LED) else {"confirmed_usd": 0.0, "sets_done": 0, "cap_usd": CAP}
setn = led["sets_done"] + 1
SD = f"{OUT}/set{setn}"; os.makedirs(SD, exist_ok=True)

# ---- preflight guards (no spend) ----
assert DV.disk_allow_paid() is False, "ABORT: ALLOW_PAID true on disk before start"
if led["sets_done"] >= MAX_SETS:
    print(json.dumps({"status": "STOP_MAX_SETS", "sets_done": led["sets_done"], "max": MAX_SETS})); sys.exit(0)
if round(led["confirmed_usd"] + SEGS * VCOST, 2) > CAP:
    print(json.dumps({"status": "STOP_CAP", "would_be": round(led["confirmed_usd"] + SEGS * VCOST, 2), "cap": CAP})); sys.exit(0)
for _id, sp, ssha, ep, esha, _n, _pr in SEGSPEC:
    assert sha(sp)[:16] == ssha, f"{_id} start sha mismatch {sha(sp)[:16]} != {ssha}"
    assert sha(ep)[:16] == esha, f"{_id} end sha mismatch {sha(ep)[:16]} != {esha}"
print(f"preflight OK | set {setn}/{MAX_SETS} | ledger ${led['confirmed_usd']:.2f} | this set ${SEGS*VCOST:.2f} | cap ${CAP:.2f}", flush=True)

# ---- generate the 3 segments (paid) ----
confirmed = 0.0; seg_files = {}; err = None
for _id, sp, ssha, ep, esha, take, prompt in SEGSPEC:
    if round(led["confirmed_usd"] + confirmed + VCOST, 2) > CAP:
        err = f"cap would be exceeded before {_id}"; break
    spec = {"model": "kling-v3-pro", "seed_image": sp, "end_image": ep, "prompt": prompt,
            "negative_prompt": NEG, "cfg_scale": 0.6, "generate_audio": False, "duration": "3", "use_elements": False}
    raw = f"{SD}/{_id}_raw.mp4"; norm = f"{SD}/{_id}.mp4"
    DV.ALLOW_PAID = True
    try:
        print(f"submitting {_id} ({sp.split('/')[-1]} -> {ep.split('/')[-1]}, 3s locked)...", flush=True)
        adapter = DV.FalKlingAdapter(); job = adapter.submit(spec, TIMEOUT); adapter.poll_and_download(job, raw, TIMEOUT)
        confirmed += VCOST
        DV._normalize_media(raw, norm)
        seg_files[_id] = {"mp4": norm, "request_id": job.get("request_id"), "frames": None}
    except Exception as e:
        err = f"{_id}: {type(e).__name__}: {e}\n{traceback.format_exc()[:300]}"; break
    finally:
        DV.ALLOW_PAID = False

led["confirmed_usd"] = round(led["confirmed_usd"] + confirmed, 2); led["sets_done"] = setn
json.dump(led, open(LED, "w"), indent=2)
auth = DV.assert_allow_paid_reset()
print(f"generation done | confirmed this run ${confirmed:.2f} | ledger ${led['confirmed_usd']:.2f} | allow_paid_reset {auth} | disk {DV.disk_allow_paid()}", flush=True)
if err or len(seg_files) < 3:
    json.dump({"status": "GENERATION_INCOMPLETE", "error": err, "segs": list(seg_files), "ledger": led,
               "allow_paid_disk_after": DV.disk_allow_paid(), "allow_paid_reset": auth}, open(f"{SD}/set{setn}_result.json", "w"), indent=2, default=str)
    print("STATUS: GENERATION_INCOMPLETE |", err); sys.exit(0)

# ---- assemble FRAME-EXACT 232 (A1[0:66]+A2[0:76]+A3[0:90]) ----
FR = f"{SD}/_frames"; os.makedirs(FR, exist_ok=True); [os.remove(os.path.join(FR, x)) for x in os.listdir(FR)]
gi = 0
for s in SEGSPEC:
    _id, take = s[0], s[5]
    tmp = f"{SD}/_seg_{_id}"; os.makedirs(tmp, exist_ok=True); [os.remove(os.path.join(tmp, x)) for x in os.listdir(tmp)]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", seg_files[_id]["mp4"], "-vf", f"scale={W}:{H}", "-start_number", "0", os.path.join(tmp, "s%04d.png")], check=True)
    avail = sorted(os.listdir(tmp)); seg_files[_id]["frames"] = len(avail)
    for k in range(take):
        src = os.path.join(tmp, f"s{min(k, len(avail)-1):04d}.png")   # hold last frame if the gen is short of `take`
        Image.open(src).save(os.path.join(FR, f"m{gi:04d}.png")); gi += 1
assert gi == 232, f"assembled {gi} != 232"
CAND = f"{SD}/A1_A3_candidate_set{setn}.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(FR, "m%04d.png"),
                "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS), CAND], check=True)


def L(i): return np.asarray(Image.open(os.path.join(FR, f"m{i:04d}.png")).convert("RGB"), float)
def bolt_mask(a):
    R, Gc, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    return ((np.minimum(np.minimum(R, Gc), B) > 95) | ((B > R + 15) & (B > 95)))
def centroid(a):
    m = bolt_mask(a); ys, xs = np.where(m)
    return (xs.mean() / W, ys.mean() / H) if len(xs) else (0.5, 0.5)
def term_dist(a): c = centroid(a); return ((c[0] - TP[0]) ** 2 + (c[1] - TP[1]) ** 2) ** 0.5
def eye_lum(a):
    R, Gc, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]; ey = (B > R + 20) & (B > 120)
    return float(a[ey].mean()) if ey.any() else 0.0
_yy, _xx = np.mgrid[0:H, 0:W]; _termbox = (_yy > 560) & (_yy < 1000) & (_xx > 560) & (_xx < 900)   # fixed terminal housing -> exclude
def n_bolts(a):                                                       # CORRECTED: count large WHITE-SHELL blobs (Bolt), not terminal/signs/reflections
    from scipy import ndimage
    R, Gc, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    shell = (np.minimum(np.minimum(R, Gc), B) > 120) & (~_termbox)
    shell = ndimage.binary_opening(shell, iterations=2)
    l, n = ndimage.label(shell); sizes = ndimage.sum(np.ones_like(l), l, range(1, n + 1)) if n else np.array([])
    return int(sum(1 for s in sizes if s > 0.004 * H * W))

# ---- deterministic hard gates on the assembled 232f ----
dists = [term_dist(L(i)) for i in range(0, 232, 4)]
eyes = [eye_lum(L(i)) for i in range(0, 232, 4)]                      # dense sampling for the TEMPORAL weakness gate
nb = max(n_bolts(L(i)) for i in range(0, 232, 6))
# temporal monotonic weakness (panel exposed the endpoint-only gap): eyes must not RE-BRIGHTEN mid-clip + be clearly weaker by mid-clip
_mid = len(eyes) // 2
max_rebright = max((eyes[i] - eyes[i - 1]) for i in range(1, len(eyes)))
weak_monotonic = bool(max_rebright < 10 and np.mean(eyes[_mid:_mid + 4]) < np.mean(eyes[:4]) - 5 and np.mean(eyes[-4:]) < np.mean(eyes[:4]) - 12)
# handoffs (visual, vs the frozen neighbours)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{AT}/h0_hook/H0.mp4", "-vf", "select=eq(n\\,59),scale=1080:1920", "-frames:v", "1", f"{SD}/_h0_last.png"], check=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{AT}/a3b_bridge/A3B.mp4", "-vf", "select=eq(n\\,0),scale=1080:1920", "-frames:v", "1", f"{SD}/_a3b_first.png"], check=True)
h0_last = np.asarray(Image.open(f"{SD}/_h0_last.png").convert("RGB"), float); a3b_first = np.asarray(Image.open(f"{SD}/_a3b_first.png").convert("RGB"), float)
start_handoff = float(np.abs(L(0) - h0_last).mean()); end_handoff = float(np.abs(L(231) - a3b_first).mean())
# corridor fixed (no camera reset): background corners stable frame-to-frame
bg = lambda a: np.concatenate([a[80:300, 60:300].ravel(), a[80:300, 780:1020].ravel()])
cam = max(float(np.abs(bg(L(i)) - bg(L(i - 4))).mean()) for i in range(4, 232, 4))
mono_reverse = max((dists[i] - dists[i - 1]) for i in range(1, len(dists)))   # largest backward step (should be tiny)
gates = {
  "frames_232": gi == 232,
  "start_handoff_H0": bool(start_handoff < 6.0), "start_handoff_meanabs": round(start_handoff, 2),
  "end_handoff_A3B": bool(end_handoff < 6.0), "end_handoff_meanabs": round(end_handoff, 2),
  "terminal_distance_decreases": bool(dists[-1] < dists[0] - 0.05), "dist_start_end": [round(dists[0], 3), round(dists[-1], 3)],
  "monotonic_forward_no_reverse": bool(mono_reverse < 0.03), "max_backward_step": round(mono_reverse, 3),
  "one_bolt_max": bool(nb <= 1), "n_bolts_max": nb,
  "no_camera_reset_corridor_fixed": bool(cam < 12.0), "corridor_bg_max_adjdiff": round(cam, 2),
  "progressive_weakness_eye_dim": bool(np.mean(eyes[-3:]) < np.mean(eyes[:3]) - 3), "eye_lum_first3_last3": [round(float(np.mean(eyes[:3])), 1), round(float(np.mean(eyes[-3:])), 1)],
  "weakness_monotonic_no_rebrighten": weak_monotonic, "max_eye_rebright_step": round(max_rebright, 1), "eye_lum_early_mid_late": [round(float(np.mean(eyes[:4])), 1), round(float(np.mean(eyes[_mid:_mid+4])), 1), round(float(np.mean(eyes[-4:])), 1)]}
det_order = ["frames_232", "start_handoff_H0", "end_handoff_A3B", "terminal_distance_decreases", "monotonic_forward_no_reverse", "one_bolt_max", "no_camera_reset_corridor_fixed", "progressive_weakness_eye_dim", "weakness_monotonic_no_rebrighten"]
det_pass = all(gates[k] for k in det_order)
# strip for review
strip = Image.new("RGB", (8 * 200 + 20, 400), (12, 12, 14)); dd = ImageDraw.Draw(strip)
for k, i in enumerate([0, 33, 66, 99, 132, 165, 198, 231]):
    strip.paste(Image.open(os.path.join(FR, f"m{i:04d}.png")).resize((200, 356)), (k * 200 + 10, 30)); dd.text((k * 200 + 12, 8), f"f{i}", fill=(230, 230, 230))
strip.save(f"{SD}/A1_A3_candidate_set{setn}_strip.png")
res = {"objective": "a1a3_production_set", "set": setn, "status": "A1A3_DET_GATES_PASS_PENDING_PANEL" if det_pass else "A1A3_DET_GATES_FAIL",
       "candidate_mp4": CAND, "strip": f"{SD}/A1_A3_candidate_set{setn}_strip.png", "frames": 232,
       "seg_frames": {k: seg_files[k]["frames"] for k in seg_files}, "seg_request_ids": {k: seg_files[k]["request_id"] for k in seg_files},
       "det_gates": gates, "det_gates_pass": det_pass,
       "spend": {"this_run_usd": round(confirmed, 2), "ledger_confirmed_usd": led["confirmed_usd"], "cap_usd": CAP, "within_cap": led["confirmed_usd"] <= CAP, "sets_done": led["sets_done"]},
       "allow_paid_disk_after": DV.disk_allow_paid(), "allow_paid_reset_assertion": auth,
       "next": "run phone-size perceptual panel on the candidate; select ONLY if det gates AND panel pass; else (within cap) run set 2"}
json.dump(res, open(f"{SD}/set{setn}_result.json", "w"), indent=2, default=str)
print(json.dumps(gates, indent=2)); print("DET PASS:", det_pass, "| spend $%.2f (ledger $%.2f/$%.2f)" % (confirmed, led["confirmed_usd"], CAP))
print("candidate:", CAND); print("DONE")
