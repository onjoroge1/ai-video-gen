"""A3 (weakening reach) — SINGLE authorized paid candidate, 3s, $0.60 all-in guard. A3 is a CONTINUATION
primitive: retain + evaluate from t=0 (seam with the accepted A2 final; NO onset trim). Evaluate the RAW clip
FIRST; NO repair / plume-removal / clean-plate. One candidate; no auto-retry. ALLOW_PAID try/finally + assert.
A2/A1 immutable; A3 start byte-identical to the accepted A2 final frame. Stops after A3; no assembly.
Run: python3 -m bolt_seq.run_A3_weakening_pilot   (paid, one candidate)   |   DRY=1 ... (no spend eval-path check)"""
import os, sys, json, subprocess, traceback, hashlib
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
import numpy as np
from PIL import Image
from scipy import ndimage
from bolt_seq.providers import directed_video as DV
from bolt_seq import motion_registry as MR
from bolt_seq import run_primitive_chain_pilot as R

AT = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/atomic_shots")
OUT = os.path.join(AT, "a3_weakening", "pilot"); os.makedirs(OUT, exist_ok=True)
OX = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription")
PKG = json.load(open(os.path.join(AT, "a3_weakening_package.json")))
A3_START = os.path.join(AT, "a3_weakening", "A3_start_frame.png")
A2_FINAL = os.path.join(AT, "a2_accepted", "A2_final_frame.png")
A3_END = os.path.join(AT, "a3_weakening", "A3_end.png")
PLATE = os.path.join(OX, "corridor_with_terminal.png")
PROMPT = PKG["sanitized_request_no_keys"]["prompt"]; NEG = PKG["sanitized_request_no_keys"]["negative_prompt"]
BOLT_SPEC = R.BOLT_SPEC
CAP, VCOST, EVAL_EST, TIMEOUT = 0.60, 0.336, 0.18, 600
W, H, TERM = 1080, 1920, 0.605; TP = (0.62, 0.46)
DRY = os.environ.get("DRY") == "1"
A2_FINAL_SHA = "09137687c3dee3e6bde48c6b0f0384684849e4c775a6808fa9528056863fc2b9"


def _arr(p): return np.asarray(Image.open(p).convert("RGB").resize((W, H)), float)


def frame_metrics(a):
    """Per-frame deterministic weakening signals on a Kling frame (bright/cyan robust to re-tone)."""
    R_, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    bb = DV._blob_bbox(a, 0, int(0.58 * W), int(0.26 * H), int(0.90 * H))
    bc, _bot = DV._base_centroid_y(a, W, H)
    # hand = rightmost bright/cyan Bolt pixel left of the terminal column
    m = ((np.minimum(np.minimum(R_, G), B) > 150) | ((G > 140) & (B > 140) & (R_ < np.maximum(G, B))))
    m[:, int(0.72 * W):] = False; m[:int(0.16 * H)] = False; m[int(0.88 * H):] = False
    ys, xs = np.where(m); hx = xs.max() / W; hy = ys[xs == xs.max()].mean() / H
    hd = ((hx - TP[0]) ** 2 + (hy - TP[1]) ** 2) ** 0.5
    # eye glow lum in the central visor
    bw, bh = bb[2] - bb[0], bb[3] - bb[1]
    rg = np.zeros((H, W), bool); rg[int(bb[1] + 0.30 * bh):int(bb[1] + 0.52 * bh), int(bb[0] + 0.22 * bw):int(bb[0] + 0.78 * bw)] = True
    cye = (B > R_ + 18) & (B > G - 25) & rg
    eye_lum = float(((G[cye] + B[cye]) / 2).mean()) if cye.sum() else 0.0
    eeg = DV.eye_edge_integrity_gate(a, W, H, bb=bb)
    return {"base_cy": bc, "hand_terminal": round(hd, 4), "eye_lum": round(eye_lum, 1),
            "eye_edge_pass": bool(eeg["pass"]), "bbox": bb}


def trajectories(clip):
    tk = DV.bolt_tracker(clip, n=20)
    rows = []
    for s in tk["samples"]:
        if not s.get("frame"):
            continue
        a = np.asarray(Image.open(s["frame"]).convert("RGB"), float)
        m = frame_metrics(a); m["t"] = round(s["t"], 3); rows.append(m)
    return tk, rows


def plot(rows, key, ylabel, out, hline=None):
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        ts = [r["t"] for r in rows]; ys = [r[key] for r in rows]
        plt.figure(figsize=(6, 3)); plt.plot(ts, ys, "-o", ms=3)
        if hline is not None: plt.axhline(hline, color="r", ls="--", lw=1)
        plt.xlabel("t (s)"); plt.ylabel(ylabel); plt.title(ylabel + " over A3"); plt.tight_layout(); plt.savefig(out, dpi=90); plt.close()
    except Exception as e:
        open(out.replace(".png", ".txt"), "w").write(f"{e}")


def seam(win_first_png):
    a = _arr(A2_FINAL); b = _arr(win_first_png)
    ba = DV._blob_bbox(a, 0, int(0.58 * W), int(0.26 * H), int(0.90 * H)); bb = DV._blob_bbox(b, 0, int(0.58 * W), int(0.26 * H), int(0.90 * H))
    dcx = abs((ba[0] + ba[2]) / 2 / W - (bb[0] + bb[2]) / 2 / W); dcy = abs((ba[1] + ba[3]) / 2 / H - (bb[1] + bb[3]) / 2 / H)
    x0, y0, x1, y1 = min(ba[0], bb[0]), min(ba[1], bb[1]), max(ba[2], bb[2]), max(ba[3], bb[3])
    rd = round(float(np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]).mean()), 2)
    return {"pass": bool(dcx <= 0.03 and dcy <= 0.03 and rd <= 50), "centroid_dx": round(dcx, 4), "centroid_dy": round(dcy, 4), "region_diff": rd}


def contact(clip, out, cols=6):
    dur = DV._probe(clip).get("dur", 3.0) or 3.0
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf", f"fps={max(0.5, round((cols-0.5)/dur,3))},scale=240:-1,tile={cols}x1", "-frames:v", "1", out], check=False)


def evaluate(winclip, rows, cost):
    """A3 gates 1-9 on the t=0-retained window (deterministic trajectories + one VLM pass)."""
    n = len(rows); third = max(1, n // 3)
    base = [r["base_cy"] for r in rows]; hand = [r["hand_terminal"] for r in rows]; eye = [r["eye_lum"] for r in rows]
    dur = DV._probe(winclip).get("dur", 3.0) or 3.0
    # 3 base sink
    net_sink = round(base[-1] - base[0], 4)
    i60 = int(0.6 * n); gradual = (base[i60] - base[0]) >= 0.4 * net_sink if net_sink > 0 else False
    last035 = [r for r in rows if r["t"] >= dur - 0.35] or rows[-2:]
    persists = (max(x["base_cy"] for x in last035) - min(x["base_cy"] for x in last035)) <= 0.03 and min(x["base_cy"] for x in last035) >= base[0] + 0.03
    sink_ok = bool(0.04 <= net_sink <= 0.07 and gradual and persists)
    # 4 reach failure
    hd_final = hand[-1]; hd_incr = hd_final > hand[0] + 0.01
    final_third_min = min(hand[-third:]); no_renewed_reach = final_third_min >= hd_final - 0.02
    reach_ok = bool(hd_incr and hd_final >= 0.045 and no_renewed_reach)
    # 5 eye weakening
    lum_drop = 1 - (eye[-1] / eye[0]) if eye[0] else 0
    eye_smooth_all = all(r["eye_edge_pass"] for r in rows)
    eye_ok = bool(0.15 <= lum_drop <= 0.35 and eye_smooth_all)
    # 6 no recovery: base no rebound, eye no rebrighten, hand no reapproach
    base_rebound = any(base[i] < base[i - 1] - 0.02 for i in range(i60, n))   # moving UP (smaller cy) after mid
    eye_rebright = any(eye[i] > eye[i - 1] * 1.10 for i in range(1, n))
    hand_reapproach = any(hand[i] < hand[i - 1] - 0.02 for i in range(i60, n))
    norecov_ok = bool(not base_rebound and not eye_rebright and not hand_reapproach)
    # 2 weakening progression (composite)
    weak_ok = bool(net_sink > 0.02 and lum_drop > 0.10 and hd_incr and hd_final >= 0.045)
    # 9 generated VFX (deterministic)
    tk = DV.bolt_tracker(winclip); vfx = DV.generated_vfx_absence_gate(winclip, plate_path=PLATE, tracker=tk)
    # 8 environment (plate + camera + terminal) ; 7 identity/anatomy + base rigid  (VLM once)
    plate_c = DV.plate_consistency_gate(winclip, tracker=tk)
    cam = DV.camera_model_gate(winclip, cost=cost); attach = DV.destination_attachment_gate(winclip, cost=cost)
    anat = DV.check_anatomy_temporal(winclip, BOLT_SPEC, cost=cost); lb = DV.lower_body_integrity_gate(winclip, tracker=tk, cost=cost)
    env_ok = bool(plate_c["pass"] and cam.get("pass") and attach.get("pass"))
    ident_ok = bool(len(anat.get("other_prohibited", [])) == 0 and lb["pass"])
    gates = {
        "1_seam": None,  # filled by caller
        "2_weakening_progression": weak_ok,
        "3_base_sink": sink_ok, "3_net_sink": net_sink, "3_gradual": bool(gradual), "3_persists_last_0.35s": bool(persists),
        "4_reach_failure": reach_ok, "4_hand_terminal_final": hd_final, "4_hand_increased": bool(hd_incr), "4_no_renewed_reach": bool(no_renewed_reach),
        "5_eye_weakening": eye_ok, "5_lum_drop": round(lum_drop, 3), "5_eye_smooth_all_frames": bool(eye_smooth_all),
        "6_no_recovery": norecov_ok, "6_base_rebound": bool(base_rebound), "6_eye_rebrighten": bool(eye_rebright), "6_hand_reapproach": bool(hand_reapproach),
        "7_identity_anatomy": ident_ok, "8_environment": env_ok, "9_generated_vfx_absent": bool(vfx["pass"]),
        "reports": {"vfx": vfx, "plate": plate_c, "camera": cam, "attachment": attach, "anatomy_other": anat.get("other_prohibited"), "lower_body": lb["pass"]},
    }
    return gates


def main():
    if DRY:
        clip = os.path.join(AT, "a2_approach", "pilot", "a2_window_t0.mp4"); cost = []
        tk, rows = trajectories(clip); g = evaluate(clip, rows, cost)
        print("DRY ok | rows", len(rows), "| net_sink", g["3_net_sink"], "| lum_drop", g["5_lum_drop"], "| VLM $%.2f" % sum(cost), "| ALLOW_PAID", DV.ALLOW_PAID)
        return

    # PRE-SPEND: seam frame byte-identical to accepted A2 final
    start_sha = hashlib.sha256(open(A3_START, "rb").read()).hexdigest()
    cost = []; confirmed = potential = 0.0; err = None; status = None; norm = winclip = None; request_id = payload = raw_response = None
    rows = None; g = None; sm = None; window = None
    if start_sha != A2_FINAL_SHA:
        status = "EXECUTION_ERROR"; err = f"A3 start not byte-identical to accepted A2 final ({start_sha[:12]} != {A2_FINAL_SHA[:12]})"
    elif VCOST + EVAL_EST > CAP:
        status = "EXECUTION_ERROR"; err = f"estimate ${VCOST+EVAL_EST} > cap ${CAP}"
    else:
        DV.ALLOW_PAID = True
        try:
            adapter = DV.FalKlingAdapter()
            spec = {"model": "kling-v3-pro", "seed_image": A3_START, "end_image": A3_END, "prompt": PROMPT,
                    "negative_prompt": NEG, "cfg_scale": 0.6, "generate_audio": False, "duration": "3", "use_elements": False}
            raw = os.path.join(OUT, "raw.mp4"); norm = os.path.join(OUT, "a3_raw.mp4")
            print("submitting ONE A3 candidate (3s)...", flush=True)
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
            # continuation: retain from t=0 to action_end (no onset trim)
            window = DV.detect_usable_action_window(norm, n=30)
            end_t = min(DV._probe(norm).get("dur", 3.0) or 3.0, window["action_end_t"] + 0.05)
            winclip = os.path.join(OUT, "a3_window_t0.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-to", f"{end_t:.3f}", "-i", norm,
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", winclip], check=True)
            wf = os.path.join(OUT, "a3_window_first.png")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", winclip, "-frames:v", "1", "-vf", f"scale={W}:{H}", wf], check=True)
            sm = seam(wf)
            tk, rows = trajectories(winclip)
            g = evaluate(winclip, rows, cost); g["1_seam"] = bool(sm["pass"])
            # artifacts
            contact(winclip, os.path.join(OUT, "a3_contact.jpg"))
            plot(rows, "base_cy", "base-centroid y (sink)", os.path.join(OUT, "traj_base_centroid.png"))
            plot(rows, "hand_terminal", "hand->terminal dist", os.path.join(OUT, "traj_hand_terminal.png"), hline=0.045)
            plot(rows, "eye_lum", "eye luminance", os.path.join(OUT, "traj_eye_lum.png"))
            # seam comparison image
            comp = Image.new("RGB", (2 * 360 + 30, 660), (12, 12, 14)); from PIL import ImageDraw
            d = ImageDraw.Draw(comp)
            for i, (t, p) in enumerate([("accepted A2 final", A2_FINAL), ("A3 first retained (t=0)", wf)]):
                comp.paste(Image.open(p).convert("RGB").resize((360, 640)), (i * 360 + 10, 16)); d.text((i * 360 + 12, 3), t, fill=(230, 230, 230))
            comp.save(os.path.join(OUT, "a3_seam_comparison.jpg"), quality=92)
            # classify
            order = [("1_seam", "A3_SEAM_FAIL"), ("9_generated_vfx_absent", "A3_PROVIDER_VFX_FAIL"),
                     ("7_identity_anatomy", "A3_IDENTITY_ANATOMY_FAIL"), ("8_environment", "A3_ENVIRONMENT_FAIL"),
                     ("6_no_recovery", "A3_RECOVERY_FAIL"), ("3_base_sink", "A3_SINK_FAIL"),
                     ("4_reach_failure", "A3_REACH_FAIL"), ("5_eye_weakening", "A3_EYE_WEAKENING_FAIL"),
                     ("2_weakening_progression", "A3_WEAKENING_FAIL")]
            fail = next((rej for k, rej in order if not g.get(k)), None)
            status = "A3_PASS_STOP_FOR_REVIEW" if fail is None else fail
    except Exception as e:
        err = (err or "") + f" | eval: {type(e).__name__}: {e}\n{traceback.format_exc()[:400]}"; status = status or "EXECUTION_ERROR"

    auth = DV.assert_allow_paid_reset(); eval_spend = round(sum(cost), 2)
    ledger = {"confirmed_video_usd": round(confirmed, 2), "potential_unretrieved_usd": round(potential, 2),
              "evaluation_usd": eval_spend, "all_in_usd": round(confirmed + potential + eval_spend, 2), "cap_usd": CAP,
              "within_cap": (confirmed + potential + eval_spend) <= CAP, "candidates": 1 if confirmed else 0}
    MR.register("bolt.weakening", status="a3_pilot_" + (status or "none").lower(),
                clip=(winclip if status == "A3_PASS_STOP_FOR_REVIEW" else None),
                description=f"A3 weakening pilot: {status}. Continuation (t=0). Not promoted; pending manual review.", not_accepted_reason=status)
    out = {"objective": "a3_weakening", "status": status, "error": err,
           "provider": {"request_id": request_id, "sanitized_request": payload, "raw_response": raw_response},
           "seam": sm, "gates": g, "trajectories": rows,
           "detected_window": {k: window.get(k) for k in ("onset_t", "action_end_t")} if window else None,
           "spend_ledger": ledger, "allow_paid_disk_after": DV.disk_allow_paid(), "allow_paid_runtime_after": DV.ALLOW_PAID,
           "allow_paid_reset_assertion": auth, "no_repair_no_plume_removal": True, "auto_retry": False, "assembled": False,
           "artifacts": {"raw": "pilot/a3_raw.mp4", "window_t0": "pilot/a3_window_t0.mp4", "contact": "pilot/a3_contact.jpg",
                         "seam_comparison": "pilot/a3_seam_comparison.jpg", "traj_base": "pilot/traj_base_centroid.png",
                         "traj_hand": "pilot/traj_hand_terminal.png", "traj_eye": "pilot/traj_eye_lum.png"}}
    json.dump(out, open(os.path.join(AT, "a3_weakening_pilot_result.json"), "w"), indent=2, default=str)
    print("\n=== A3 WEAKENING PILOT ===")
    print("request:", request_id, "| spend confirmed $%.2f + eval $%.2f = $%.2f (cap $%.2f) within=%s" % (confirmed, eval_spend, ledger["all_in_usd"], CAP, ledger["within_cap"]))
    if sm: print("seam:", sm)
    if g: print("gates:", {k: v for k, v in g.items() if k[0].isdigit() and isinstance(v, bool)})
    print("STATUS:", status, "| ALLOW_PAID disk", DV.disk_allow_paid(), "runtime", DV.ALLOW_PAID)
    if err: print("note:", err[:300])


if __name__ == "__main__":
    main()
