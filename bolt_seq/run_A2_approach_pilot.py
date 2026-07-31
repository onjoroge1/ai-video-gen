"""A2 (effortful approach) — SINGLE authorized paid candidate, $0.60 all-in cap (gen + every VLM/eval call).
Body-only per the A2 acceptance criteria (no plume this turn). A1 is immutable; A2 start = the exact frozen A1
final clean-body frame. Budget discipline: ONE candidate (never a 2nd automatically); estimate refuses to enable
ALLOW_PAID if projected > cap; VLM battery runs ONCE (persisted); deterministic gates re-run free; ALLOW_PAID
try/finally + asserted False after. Stops after A2. Returns one classification.
Run: python3 -m bolt_seq.run_A2_approach_pilot        (paid, one candidate)
     DRY=1 ...                                          (no spend: dry eval-path check)"""
import os, sys, json, subprocess, traceback
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
import numpy as np
from PIL import Image
from bolt_seq.providers import directed_video as DV
from bolt_seq import motion_registry as MR
from bolt_seq import run_primitive_chain_pilot as R

AT = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/atomic_shots")
FROZEN = os.path.join(AT, "a1_accepted"); OUT = os.path.join(AT, "a2_approach", "pilot"); os.makedirs(OUT, exist_ok=True)
OX = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription")
PKG = json.load(open(os.path.join(AT, "a2_approach_package.json")))
A2_START = os.path.join(FROZEN, "A1_final_clean_body_frame.png")
A2_END = os.path.join(AT, "a2_approach", "A2_end.png")
PLATE = os.path.join(OX, "corridor_with_terminal.png")
PROMPT = PKG["sanitized_request_no_keys"]["prompt"]; NEG = PKG["sanitized_request_no_keys"]["negative_prompt"]
AUTHORED = PKG["authored_forward_displacement"]
BOLT_SPEC = R.BOLT_SPEC
CAP, VCOST, EVAL_EST, TIMEOUT = 0.60, 0.336, 0.18, 600
W, H, TERM_LEFT = 1080, 1920, 0.605
DRY = os.environ.get("DRY") == "1"


def displacement(clip, tracker):
    det = [s for s in tracker["samples"] if s.get("cx") is not None]
    cx = [s["cx"] for s in det]
    if len(cx) < 2:
        return {"net_forward": 0.0, "ratio": 0.0, "idle": 1.0, "reversals": 9, "progressive": False}
    steps = [cx[i + 1] - cx[i] for i in range(len(cx) - 1)]
    net = round(cx[-1] - cx[0], 4)
    idle = round(sum(1 for d in steps if abs(d) < 0.004) / max(1, len(steps)), 3)
    rev = sum(1 for d in steps if d < -0.02); i60 = int(0.6 * len(cx))
    prog = net > 0 and len(cx) > i60 and (cx[i60] - cx[0]) >= 0.4 * net
    return {"net_forward": net, "ratio": round(net / AUTHORED, 3) if AUTHORED else 0, "idle": idle,
            "reversals": rev, "progressive": bool(prog)}


def bolt_bb(path):
    a = np.asarray(Image.open(path).convert("RGB").resize((W, H)), float)
    return DV._blob_bbox(a, 0, int(0.58 * W), int(0.26 * H), int(0.86 * H))


def seam_compat(win_first_png):
    """First retained A2 frame vs the accepted A1 endpoint (A2_START): Bolt centroid delta + region pixel diff."""
    a = np.asarray(Image.open(A2_START).convert("RGB").resize((W, H)), float)
    b = np.asarray(Image.open(win_first_png).convert("RGB").resize((W, H)), float)
    ba, bb = bolt_bb(A2_START), bolt_bb(win_first_png)
    if not ba or not bb:
        return {"pass": False, "reason": "no bbox"}
    cxa = (ba[0] + ba[2]) / 2 / W; cxb = (bb[0] + bb[2]) / 2 / W
    cya = (ba[1] + ba[3]) / 2 / H; cyb = (bb[1] + bb[3]) / 2 / H
    dcx = round(abs(cxa - cxb), 4); dcy = round(abs(cya - cyb), 4)
    x0, y0, x1, y1 = min(ba[0], bb[0]), min(ba[1], bb[1]), max(ba[2], bb[2]), max(ba[3], bb[3])
    region_diff = round(float(np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]).mean()), 2)
    ok = dcx <= 0.03 and dcy <= 0.03 and region_diff <= 55
    return {"pass": bool(ok), "centroid_dx": dcx, "centroid_dy": dcy, "region_mean_diff": region_diff}


def contact(clip, out, cols=8):
    dur = DV._probe(clip).get("dur", 3.0) or 3.0
    fps = max(0.5, round((cols - 0.5) / max(0.3, dur), 3))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf", f"fps={fps},scale=220:-1,tile={cols}x1", "-frames:v", "1", out], check=False)


def trajectory_plot(tracker, out):
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        det = [s for s in tracker["samples"] if s.get("cx") is not None]
        ts = [s["t"] for s in det]; cx = [s["cx"] for s in det]
        plt.figure(figsize=(6, 3)); plt.plot(ts, cx, "-o", ms=3)
        plt.axhline(TERM_LEFT, color="r", ls="--", lw=1, label="terminal")
        plt.xlabel("t (s)"); plt.ylabel("Bolt centroid cx"); plt.title("A2 trajectory"); plt.legend(); plt.tight_layout()
        plt.savefig(out, dpi=90); plt.close()
    except Exception as e:
        open(out.replace(".png", ".txt"), "w").write(f"plot error: {e}")


def eval_body(clip, is_window, cost, run_vlm):
    """Deterministic gates always; VLM gates only when run_vlm (budget: run VLM once, on the window)."""
    tk = DV.bolt_tracker(clip)
    vfx = DV.generated_vfx_absence_gate(clip, plate_path=PLATE, tracker=tk)          # deterministic
    path = DV.path_monotonicity_gate(clip, tracker=tk)                               # deterministic
    disp = displacement(clip, tk)
    pr = DV._probe(clip); dur = pr.get("dur", 0) or 0
    tech = (0.5 <= dur) if is_window else (2.5 <= dur <= 3.6)
    out = {"vfx_absent": bool(vfx["pass"]), "path": path, "displacement": disp, "technical": bool(tech), "vfx": vfx}
    if run_vlm:
        lb = DV.lower_body_integrity_gate(clip, tracker=tk, cost=cost)               # hover-base integrity
        ep = DV.endpoint_geometry_gate(clip, A2_END, tracker=tk, cost=cost)
        anat = DV.check_anatomy_temporal(clip, BOLT_SPEC, cost=cost)
        cam = DV.camera_model_gate(clip, cost=cost)
        attach = DV.destination_attachment_gate(clip, cost=cost)
        out.update({"lower_body": lb, "endpoint": ep, "anatomy": anat, "camera": cam, "attachment": attach})
    return out


def classify(win, seam):
    """Apply the 10 A2 pass criteria to the trimmed window. Returns (checks, first_fail)."""
    d = win["displacement"]
    c = {
        "net_forward_ge_0.11": bool(d["net_forward"] >= 0.11),
        "realized_ratio_ge_0.65": bool(d["ratio"] >= 0.65),
        "progressive_not_morph": bool(d["progressive"]),
        "no_backward_reversal": bool(d["reversals"] == 0),
        "not_idle_most_of_window": bool(d["idle"] <= 0.35),
        "first_frame_seam_compatible": bool(seam["pass"]),
        "endpoint_geometry_match": bool(win["endpoint"]["pass"]),
        "identity_anatomy_stable": bool(len(win["anatomy"].get("other_prohibited", [])) == 0 and win["lower_body"]["pass"]),
        "no_provider_vfx": bool(win["vfx_absent"]),
        "camera_terminal_fixed": bool(win["camera"].get("pass") and win["attachment"].get("pass")),
    }
    first_fail = next((k for k, v in c.items() if not v), None)
    return c, first_fail


def main():
    if DRY:
        clip = os.path.join(AT, "a1_body_only", "pilot", "bodyonly_window.mp4"); cost = []
        ev = eval_body(clip, True, cost, run_vlm=True); seam = seam_compat(A2_START)
        print("DRY eval OK — vfx", ev["vfx_absent"], "disp", ev["displacement"], "seam", seam, "VLM $%.2f" % sum(cost), "ALLOW_PAID", DV.ALLOW_PAID)
        return

    # PRE-SPEND: boundary must pass every criterion (refuse to spend otherwise)
    bc = PKG["boundary_checks"]
    # terminal-contact is intentionally RELAXED (user chose "fingers reach the refill"); not a boundary gate here.
    boundary_ok = all([bc.get("start_byte_identical_to_A1_final"), bc.get("vfx_absent_both"), bc.get("hover_base_present_both"),
                       bc.get("displacement_ge_0.11"), bc.get("scale_stable_0.97_1.03"), bc.get("minimal_vertical_drift")])
    est = VCOST + EVAL_EST
    cost = []; confirmed = 0.0; potential = 0.0; err = None; status = None
    raw_eval = win_eval = window = seam = checks = first_fail = None; norm = winclip = None; request_id = payload = raw_response = None
    if not boundary_ok:
        status = "A2_LOCALIZED_FAILURE"; err = f"boundary did not pass: {bc}"
    elif est > CAP:
        status = "EXECUTION_ERROR"; err = f"estimate ${est} > cap ${CAP} — not enabling ALLOW_PAID"
    else:
        DV.ALLOW_PAID = True
        try:
            adapter = DV.FalKlingAdapter()
            spec = {"model": "kling-v3-pro", "seed_image": A2_START, "end_image": A2_END, "prompt": PROMPT,
                    "negative_prompt": NEG, "cfg_scale": 0.6, "generate_audio": False, "duration": "3", "use_elements": False}
            raw = os.path.join(OUT, "raw.mp4"); norm = os.path.join(OUT, "a2_bodyonly.mp4")
            print("submitting ONE A2 candidate (3s)...", flush=True)
            potential += VCOST
            job = adapter.submit(spec, TIMEOUT); adapter.poll_and_download(job, raw, TIMEOUT)
            confirmed += VCOST; potential -= VCOST
            DV._normalize_media(raw, norm)
            request_id = job.get("request_id"); raw_response = job.get("raw_response"); payload = job.get("submitted_payload_sanitized")
        except Exception as e:
            err = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:400]}"; status = "EXECUTION_ERROR"
        finally:
            DV.ALLOW_PAID = False

    # PHASES 2-3 (no further provider calls). VLM runs ONCE, on the window.
    try:
        if norm and os.path.exists(norm) and status is None:
            raw_eval = eval_body(norm, False, cost, run_vlm=False)               # raw: deterministic verdict (free)
            contact(norm, os.path.join(OUT, "raw_contact.jpg"))
            window = DV.detect_usable_action_window(norm, n=30)
            winclip = os.path.join(OUT, "a2_window.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{window['onset_t']:.3f}", "-to", f"{window['action_end_t']+0.05:.3f}",
                            "-i", norm, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", winclip], check=True)
            wf = os.path.join(OUT, "a2_window_first.png")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", winclip, "-frames:v", "1", "-vf", f"scale={W}:{H}", wf], check=True)
            seam = seam_compat(wf)
            win_eval = eval_body(winclip, True, cost, run_vlm=True)              # window: full battery (VLM once)
            contact(winclip, os.path.join(OUT, "window_contact.jpg"))
            trajectory_plot(DV.bolt_tracker(winclip), os.path.join(OUT, "a2_trajectory.png"))
            checks, first_fail = classify(win_eval, seam)
            status = "A2_PASS_STOP_FOR_REVIEW" if first_fail is None else "A2_LOCALIZED_FAILURE"
    except Exception as e:
        err = (err or "") + f" | eval: {type(e).__name__}: {e}\n{traceback.format_exc()[:400]}"; status = status or "EXECUTION_ERROR"

    auth = DV.assert_allow_paid_reset()
    eval_spend = round(sum(cost), 2)
    ledger = {"confirmed_video_usd": round(confirmed, 2), "potential_unretrieved_usd": round(potential, 2),
              "evaluation_usd": eval_spend, "all_in_usd": round(confirmed + potential + eval_spend, 2),
              "cap_usd": CAP, "within_cap": (confirmed + potential + eval_spend) <= CAP, "candidates_generated": 1 if confirmed else 0}
    # A2 is NOT promoted/inserted; pending manual review
    MR.register("bolt.approach", status="a2_pilot_" + (status or "none").lower(), clip=(winclip if status == "A2_PASS_STOP_FOR_REVIEW" else None),
                description=f"A2 approach pilot: {status}. Body-only; not promoted; awaiting manual review.", not_accepted_reason=status)
    out = {"objective": "a2_effortful_approach", "status": status, "first_failed_criterion": first_fail, "error": err,
           "boundary_checks": bc, "lower_body_requirement": PKG.get("lower_body_authority_correction") or "hover_base_integrity",
           "provider": {"request_id": request_id, "sanitized_request": payload, "raw_response": raw_response},
           "raw_clip_deterministic_eval": raw_eval,
           "detected_window": {k: window.get(k) for k in ("onset_t", "action_end_t", "onset_frame", "action_end_frame")} if window else None,
           "window_eval": win_eval, "seam_compat": seam, "a2_pass_criteria": checks,
           "spend_ledger": ledger, "allow_paid_disk_after": DV.disk_allow_paid(), "allow_paid_runtime_after": DV.ALLOW_PAID,
           "allow_paid_reset_assertion": auth, "second_candidate_generated": False, "inserted_into_short": False, "auto_promoted": False,
           "A3_or_assembly_started": False,
           "artifacts": {"raw": "pilot/a2_bodyonly.mp4", "window": "pilot/a2_window.mp4", "raw_contact": "pilot/raw_contact.jpg",
                         "window_contact": "pilot/window_contact.jpg", "trajectory": "pilot/a2_trajectory.png"}}
    json.dump(out, open(os.path.join(AT, "a2_approach_pilot_result.json"), "w"), indent=2, default=str)
    print("\n=== A2 APPROACH PILOT ===")
    print("request:", request_id, "| spend: confirmed $%.2f + eval $%.2f = $%.2f (cap $%.2f) within=%s" % (confirmed, eval_spend, ledger["all_in_usd"], CAP, ledger["within_cap"]))
    if raw_eval: print("raw (deterministic): vfx_absent", raw_eval["vfx_absent"], "| disp", raw_eval["displacement"])
    if window: print("window:", round(window["onset_t"], 2), "-", round(window["action_end_t"], 2))
    if seam: print("seam_compat:", seam)
    if checks: print("A2 criteria:", checks)
    print("STATUS:", status, "| first_fail:", first_fail, "| ALLOW_PAID disk", DV.disk_allow_paid(), "runtime", DV.ALLOW_PAID)
    if err: print("note:", err[:300])


if __name__ == "__main__":
    main()
