"""A3 (weakening reach) — ONE FINAL authorized paid candidate. 3s, audio off, LOCKED camera, $0.60 all-in hard cap,
ONE candidate, NO auto-retry. Start = canonical A2 final/A3 start (sha 09137687…); End = canonical A3_end.png
(sha 7028d201…) as end-frame conditioning (the lever the deterministic rigid-sink lacked -> lets Kling interpolate
the drooped/retracted pose). New POSTURAL-DECAY prompt + the user's exact negatives. Evaluate the RAW clip; permitted
post = trim / codec / extend-clean-hold ONLY (NO mask surgery, limb warp, plume removal, anatomical reconstruction).
Deterministic-only gates (no paid VLM eval) so all-in ≈ generation (~$0.34); causal-read / identity / posture / endpoint
closeness are done by human+assistant VISUAL review afterward. ALLOW_PAID try/finally + assert reset. A1/A2 immutable;
reconciliation frozen. Stops after eval; NO assembly, NO promotion.
Run: python3 -m bolt_seq.run_A3_final_candidate      (paid, ONE candidate)
     DRY=1 python3 -m bolt_seq.run_A3_final_candidate (no spend; validates the eval path on the A2 window)"""
import os, sys, json, subprocess, traceback, hashlib
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from bolt_seq.providers import directed_video as DV
from bolt_seq import motion_registry as MR
from bolt_seq import run_A3_weakening_pilot as P3          # reuse frame_metrics / trajectories / seam / plot / contact
from bolt_seq import prepare_oxygen_shot_A_primitives as P

AT = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/atomic_shots")
OUT = os.path.join(AT, "a3_weakening", "final_candidate"); os.makedirs(OUT, exist_ok=True)
OX = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription")
A3_START = os.path.join(AT, "a3_weakening", "A3_start_frame.png")
A3_END = os.path.join(AT, "a3_weakening", "A3_end.png")
PLATE = os.path.join(OX, "corridor_with_terminal.png")
W, H, TERM, TP = 1080, 1920, 0.605, (0.62, 0.46)
CAP, VCOST, EVAL_EST, TIMEOUT = 0.60, 0.34, 0.0, 600      # deterministic-only eval -> EVAL_EST 0
START_SHA = "09137687c3dee3e6bde48c6b0f0384684849e4c775a6808fa9528056863fc2b9"
END_SHA = "7028d2010a6d80a8296cb05b9df921d32e7cf7be9a39c58fc5968574abdf9b3f"
DRY = os.environ.get("DRY") == "1"

PROMPT = ("Locked-off static camera. A small round white and mint-green hover robot floats in a dark industrial "
          "corridor, one arm stretched out toward a wall-mounted oxygen refill terminal. He holds still for an "
          "instant, then reaches out for the terminal, but his power drains away: his glowing cyan eyes dim smoothly "
          "and go dull, his head tips forward and downward, his shoulders and torso slump and go soft, his "
          "outstretched arm loses strength so the elbow bends and the hand droops and pulls back, and his whole body "
          "sinks slowly downward. He becomes weak and limp, no longer able to reach, and hangs there low and drained "
          "without recovering. Slow, heavy, failing motion; no energy, no flying, no diving. The camera never moves "
          "and the corridor and the oxygen terminal stay perfectly still.")
NEG = ("no thruster, no exhaust, no jet, no plume, no propulsion glow, no floor illumination, no particles, no smoke, "
       "no energy trail, no secondary cyan object, no humanoid legs, no extra limbs, no hand mutation, no camera "
       "movement, no terminal movement, no background morphing, no zoom, no text changes")


def _arr(p): return np.asarray(Image.open(p).convert("RGB").resize((W, H)), float)
def _sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()


# ---- tone-matched plate matte (isolate Bolt for endpoint-closeness; identical method to the reconciliation) ----
_plate = _arr(PLATE)
def _box(x0, y0, x1, y1):
    m = np.zeros((H, W), bool); m[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)] = True; return m
_BOLT = _box(0.06, 0.26, 0.74, 0.76); _TERMB = _box(0.63, 0.26, 0.85, 0.53)
def _matte(a):
    tone = float(np.median(a[~_BOLT].mean(1)) / max(1e-3, np.median(_plate[~_BOLT].mean(1))))
    d = np.abs(a - np.clip(_plate * tone, 0, 255)).mean(2)
    r = ndimage.binary_fill_holes(ndimage.binary_closing((d > 20) & _BOLT & ~_TERMB, iterations=4))
    l, n = ndimage.label(r)
    if n == 0: return r
    s = ndimage.sum(np.ones_like(l), l, range(1, n + 1)); return l == (int(np.argmax(s)) + 1)


def endpoint_closeness(final_png):
    mf = _matte(_arr(final_png)); me = _matte(_arr(A3_END))
    inter = int((mf & me).sum()); union = int((mf | me).sum())
    iou = round(inter / max(1, union), 3)
    yf, xf = np.where(mf); ye, xe = np.where(me)
    dcx = abs(xf.mean() - xe.mean()) / W; dcy = abs(yf.mean() - ye.mean()) / H
    return {"iou": iou, "centroid_dx": round(float(dcx), 4), "centroid_dy": round(float(dcy), 4),
            "area_ratio_final_over_end": round(mf.sum() / max(1, me.sum()), 3),
            "close": bool(iou >= 0.75 and dcx <= 0.03 and dcy <= 0.04)}


def evaluate_det(clip, rows):
    """Deterministic gates ONLY (no paid VLM). Identity/anatomy + causal-read done by visual review afterward."""
    n = len(rows); third = max(1, n // 3); i60 = int(0.6 * n)
    base = [r["base_cy"] for r in rows]; hand = [r["hand_terminal"] for r in rows]; eye = [r["eye_lum"] for r in rows]
    dur = DV._probe(clip).get("dur", 3.0) or 3.0
    net_sink = round(base[-1] - base[0], 4)
    gradual = (base[i60] - base[0]) >= 0.4 * net_sink if net_sink > 0 else False
    last08 = [r for r in rows if r["t"] >= dur - 0.8] or rows[-3:]
    persists = (max(x["base_cy"] for x in last08) - min(x["base_cy"] for x in last08)) <= 0.03 and min(x["base_cy"] for x in last08) >= base[0] + 0.03
    sink_ok = bool(0.04 <= net_sink <= 0.06 and gradual and persists)
    hd_final = hand[-1]; hd_incr = hd_final > hand[0] + 0.005
    reach_ok = bool(hd_incr and min(hand[-third:]) >= hd_final - 0.02)     # reach fails and does not re-approach
    lum_drop = 1 - (eye[-1] / eye[0]) if eye[0] else 0
    eye_smooth_all = all(r["eye_edge_pass"] for r in rows)
    eye_ok = bool(0.15 <= lum_drop <= 0.45 and eye_smooth_all)
    base_rebound = any(base[i] < base[i - 1] - 0.02 for i in range(i60, n))
    eye_rebright = any(eye[i] > eye[i - 1] * 1.10 for i in range(1, n))
    hand_reapproach = any(hand[i] < hand[i - 1] - 0.02 for i in range(i60, n))
    norecov_ok = bool(not base_rebound and not eye_rebright and not hand_reapproach)
    weak_ok = bool(net_sink > 0.02 and lum_drop > 0.10 and hd_incr)
    tk = DV.bolt_tracker(clip); vfx = DV.generated_vfx_absence_gate(clip, plate_path=PLATE, tracker=tk)
    plate_c = DV.plate_consistency_gate(clip, tracker=tk)          # deterministic env/camera/terminal drift
    return {
        "2_weakening_progression": weak_ok,
        "3_base_sink_0.04_0.06": sink_ok, "3_net_sink": net_sink, "3_gradual": bool(gradual), "3_persists_last_0.8s": bool(persists),
        "4_reach_failure": reach_ok, "4_hand_terminal_start": hand[0], "4_hand_terminal_final": hd_final, "4_hand_increased": bool(hd_incr),
        "5_eye_weakening": eye_ok, "5_lum_drop": round(lum_drop, 3), "5_eye_smooth_all_frames": bool(eye_smooth_all),
        "6_no_recovery": norecov_ok, "6_base_rebound": bool(base_rebound), "6_eye_rebrighten": bool(eye_rebright), "6_hand_reapproach": bool(hand_reapproach),
        "9_generated_vfx_absent": bool(vfx["pass"]),
        "8_environment_plate_camera_terminal": bool(plate_c["pass"]),
        "reports": {"vfx": {k: vfx.get(k) for k in ("pass", "max_jet_frac", "frames_flagged")},
                    "plate": {k: plate_c.get(k) for k in ("pass", "frames_bg_relit_or_drifted", "frames_terminal_moved", "max_bg_changed_frac")}},
    }


def gif(clip, out):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf",
                    "fps=15,scale=460:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse", out], check=False)


def labeled_contact(clip, out, cols=8):
    dur = DV._probe(clip).get("dur", 3.0) or 3.0
    tmp = os.path.join(OUT, "_ctile.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf",
                    f"fps={max(0.5, round((cols-0.001)/dur,3))},scale=220:-1,tile={cols}x1", "-frames:v", "1", tmp], check=False)
    if not os.path.exists(tmp): return
    im = Image.open(tmp).convert("RGB"); dd = ImageDraw.Draw(im); cw = im.width // cols
    for i in range(cols):
        dd.text((i * cw + 4, 4), f"t={min(dur, i*dur/(cols-1)):.2f}s", fill=(255, 255, 120))
    im.save(out); os.remove(tmp)


def main():
    if DRY:
        clip = os.path.join(AT, "a2_approach", "pilot", "a2_window_t0.mp4")
        tk, rows = P3.trajectories(clip); g = evaluate_det(clip, rows)
        print("DRY ok | rows", len(rows), "| net_sink", g["3_net_sink"], "| lum_drop", g["5_lum_drop"],
              "| vfx", g["9_generated_vfx_absent"], "| ALLOW_PAID", DV.ALLOW_PAID, "disk", DV.disk_allow_paid())
        print("start_sha_ok", _sha(A3_START) == START_SHA, "| end_sha_ok", _sha(A3_END) == END_SHA)
        return

    cost = []; confirmed = potential = 0.0; err = None; status = None
    norm = winclip = request_id = payload = raw_response = rows = g = sm = ep = window = None
    s_sha, e_sha = _sha(A3_START), _sha(A3_END)
    if s_sha != START_SHA:
        status, err = "EXECUTION_ERROR", f"start sha mismatch {s_sha[:12]} != {START_SHA[:12]}"
    elif e_sha != END_SHA:
        status, err = "EXECUTION_ERROR", f"end sha mismatch {e_sha[:12]} != {END_SHA[:12]}"
    elif VCOST + EVAL_EST > CAP:
        status, err = "EXECUTION_ERROR", f"estimate ${VCOST+EVAL_EST} > cap ${CAP}"
    else:
        DV.ALLOW_PAID = True
        try:
            adapter = DV.FalKlingAdapter()
            spec = {"model": "kling-v3-pro", "seed_image": A3_START, "end_image": A3_END, "prompt": PROMPT,
                    "negative_prompt": NEG, "cfg_scale": 0.6, "generate_audio": False, "duration": "3", "use_elements": False}
            raw = os.path.join(OUT, "raw.mp4"); norm = os.path.join(OUT, "a3_final_raw.mp4")
            print("submitting ONE final A3 candidate (3s, locked camera)...", flush=True)
            potential += VCOST
            job = adapter.submit(spec, TIMEOUT); adapter.poll_and_download(job, raw, TIMEOUT)
            confirmed += VCOST; potential -= VCOST
            DV._normalize_media(raw, norm)
            request_id = job.get("request_id"); raw_response = job.get("raw_response"); payload = job.get("submitted_payload_sanitized")
        except Exception as e:
            err = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:400]}"; status = "EXECUTION_ERROR"
        finally:
            DV.ALLOW_PAID = False

    try:
        if norm and os.path.exists(norm) and status is None:
            winclip = norm                                          # evaluate the FULL 3s arc (hold + decay + persist)
            wf = os.path.join(OUT, "a3_final_first.png")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", winclip, "-frames:v", "1", "-vf", f"scale={W}:{H}", wf], check=True)
            lf = os.path.join(OUT, "a3_final_last.png")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.1", "-i", winclip, "-frames:v", "1", "-vf", f"scale={W}:{H}", lf], check=True)
            sm = P3.seam(wf); ep = endpoint_closeness(lf)
            tk, rows = P3.trajectories(winclip); g = evaluate_det(winclip, rows); g["1_seam"] = bool(sm["pass"])
            g["G_endpoint_closeness"] = bool(ep["close"])
            labeled_contact(winclip, os.path.join(OUT, "a3_final_contact.png"))
            gif(winclip, os.path.join(OUT, "a3_final.gif"))
            P3.plot(rows, "base_cy", "base-centroid y (sink)", os.path.join(OUT, "traj_base.png"))
            P3.plot(rows, "hand_terminal", "hand->terminal dist", os.path.join(OUT, "traj_hand.png"), hline=0.045)
            P3.plot(rows, "eye_lum", "eye luminance", os.path.join(OUT, "traj_eye.png"))
            # seam + endpoint comparison strips
            comp = Image.new("RGB", (4 * 300 + 50, 560), (12, 12, 14)); d = ImageDraw.Draw(comp)
            for i, (t, p) in enumerate([("A2 final (start ref)", os.path.join(AT, "a2_accepted", "A2_final_frame.png")),
                                        ("A3 clip first (t=0)", wf), ("A3 clip last", lf), ("approved A3_end", A3_END)]):
                comp.paste(Image.open(p).convert("RGB").resize((300, 533)), (i * 300 + 10, 20)); d.text((i * 300 + 12, 3), t, fill=(230, 230, 230))
            comp.save(os.path.join(OUT, "a3_final_boundaries.png"))
            order = [("1_seam", "A3_SEAM_FAIL"), ("9_generated_vfx_absent", "A3_PROVIDER_VFX_FAIL"),
                     ("8_environment_plate_camera_terminal", "A3_ENVIRONMENT_FAIL"), ("6_no_recovery", "A3_RECOVERY_FAIL"),
                     ("3_base_sink_0.04_0.06", "A3_SINK_FAIL"), ("5_eye_weakening", "A3_EYE_WEAKENING_FAIL"),
                     ("4_reach_failure", "A3_REACH_FAIL"), ("2_weakening_progression", "A3_WEAKENING_FAIL"),
                     ("G_endpoint_closeness", "A3_ENDPOINT_FAR")]
            fail = next((rej for k, rej in order if not g.get(k)), None)
            status = "A3_DET_GATES_PASS_PENDING_VISUAL" if fail is None else fail
    except Exception as e:
        err = (err or "") + f" | eval: {type(e).__name__}: {e}\n{traceback.format_exc()[:400]}"; status = status or "EXECUTION_ERROR"

    auth = DV.assert_allow_paid_reset(); eval_spend = round(sum(cost), 2)
    all_in = round(confirmed + potential + eval_spend, 2)
    ledger = {"confirmed_video_usd": round(confirmed, 2), "potential_unretrieved_usd": round(potential, 2),
              "evaluation_usd": eval_spend, "all_in_usd": all_in, "cap_usd": CAP, "within_cap": all_in <= CAP,
              "candidates": 1 if confirmed else 0, "eval_mode": "deterministic_only (no paid VLM)"}
    out = {"objective": "a3_final_candidate", "status": status, "error": err,
           "authorized": {"start_sha256": START_SHA, "end_sha256": END_SHA, "duration_s": 3, "audio": False,
                          "camera": "locked", "cap_usd": CAP, "max_candidates": 1},
           "prompt": PROMPT, "negative_prompt": NEG,
           "provider": {"request_id": request_id, "sanitized_request": payload, "raw_response": raw_response},
           "seam_vs_A2_final": sm, "endpoint_closeness_vs_A3_end": ep, "det_gates": g, "trajectories": rows,
           "spend_ledger": ledger, "allow_paid_disk_after": DV.disk_allow_paid(), "allow_paid_runtime_after": DV.ALLOW_PAID,
           "allow_paid_reset_assertion": auth, "post_processing": "normalize+contact+gif only; NO mask surgery/warp/plume-removal/reconstruction",
           "auto_retry": False, "assembled": False, "promoted": False,
           "artifacts": {"raw": "final_candidate/a3_final_raw.mp4", "first": "final_candidate/a3_final_first.png",
                         "last": "final_candidate/a3_final_last.png", "contact": "final_candidate/a3_final_contact.png",
                         "gif": "final_candidate/a3_final.gif", "boundaries": "final_candidate/a3_final_boundaries.png",
                         "traj_base": "final_candidate/traj_base.png", "traj_hand": "final_candidate/traj_hand.png",
                         "traj_eye": "final_candidate/traj_eye.png"}}
    json.dump(out, open(os.path.join(AT, "a3_final_candidate_result.json"), "w"), indent=2, default=str)
    MR.register("bolt.weakening", status="a3_final_" + (status or "none").lower(), clip=None,
                description=f"A3 final paid candidate: {status}. Deterministic gates only; NOT promoted; pending human causal-read review.",
                not_accepted_reason=status)
    print("\n=== A3 FINAL CANDIDATE ===")
    print("request:", request_id, "| all-in $%.2f (cap $%.2f) within=%s" % (all_in, CAP, ledger["within_cap"]))
    if sm: print("seam vs A2:", sm)
    if ep: print("endpoint closeness vs A3_end:", ep)
    if g: print("det gates:", {k: v for k, v in g.items() if (k[0].isdigit() or k[0] == "G") and isinstance(v, bool)})
    print("STATUS:", status, "| ALLOW_PAID disk", DV.disk_allow_paid(), "runtime", DV.ALLOW_PAID, "| reset_ok", auth)
    if err: print("note:", err[:300])


if __name__ == "__main__":
    main()
