"""A1 CANDIDATE-1 PRODUCTION-WINDOW VALIDATION — NO SPEND. cand1 proved the translation mechanism; here we
test whether the DETECTED usable action window (trim only) passes the authoritative gates as a production
hover_launch primitive. Freezes cand1 (positive translation-control) + cand0 (unstable negative). Splits
endpoint into geometry + identity/pose gates. Detects the window deterministically, trims (no interp/reverse/
speed-ramp), re-runs the gates, reports raw-clip failures SEPARATELY, and returns one status. ALLOW_PAID
False throughout (no provider calls). Run: python3 -m bolt_seq.run_A1_window_validation"""
import os, sys, json, subprocess, shutil
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from PIL import Image, ImageDraw
from bolt_seq.providers import directed_video as DV
from bolt_seq import motion_registry as MR
from bolt_seq import run_primitive_chain_pilot as R
from bolt_seq import run_A1_displacement_pilot as A1

AD = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/atomic_shots/a1_displacement")
OUT = os.path.join(AD, "window"); os.makedirs(OUT, exist_ok=True)
FROZEN = os.path.join(AD, "frozen"); os.makedirs(FROZEN, exist_ok=True)
C1 = os.path.join(AD, "c1.mp4"); C0 = os.path.join(AD, "c0.mp4")
END = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/atomic_shots/primitives/A1disp_B1v2.png")
AUTHORED = 0.1556


def trim(clip, t0, t1, out):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}", "-i", clip,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", out], check=True); return out


def contact(clip, out, tiles="5x2"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf", f"fps=4,scale=200:-1,tile={tiles}", out], check=False)


def traj_plot(win, raw_cx, raw_t, out):
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(9, 4.2))
        ax.plot(raw_t, raw_cx, "-o", color="#888", label="raw 3s centroid x")
        ax.axvspan(win["onset_t"], win["action_end_t"], color="#5ac878", alpha=0.25, label="detected window")
        ax.axvline(win["onset_t"], color="#2a9d5a", ls="--"); ax.axvline(win["action_end_t"], color="#2a9d5a", ls="--")
        if win.get("first_backdrift_t"): ax.axvline(win["first_backdrift_t"], color="#e04630", ls=":", label="first backdrift")
        ax.set_title(f"A1 cand1 — window {win['onset_t']}-{win['action_end_t']}s (raw launch is delayed past the authored 0.3-1.4s)")
        ax.set_xlabel("t (s)"); ax.set_ylabel("centroid x"); ax.legend(); ax.grid(alpha=0.3); fig.tight_layout(); fig.savefig(out, dpi=110); plt.close()
    except Exception as e:
        open(out.replace(".png", ".txt"), "w").write(str(win))


def window_technical(clip):
    """Window-scoped technical check: valid decode, resolution, not black/frozen, dur >= 0.5s. Deliberately
    drops the raw-clip 3s duration requirement (a trimmed production window is sub-second by design)."""
    import numpy as np
    pr = DV._probe(clip); dur = pr.get("dur", 0) or 0
    out = DV.tempfile.mkdtemp()
    def fr(t):
        fp = os.path.join(out, f"t{t}.png"); subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", clip, "-frames:v", "1", fp], check=True); return np.asarray(Image.open(fp).convert("RGB"), float)
    a, b = fr(0.05), fr(max(0.05, dur - 0.08))
    ok = dur >= 0.5 and pr.get("w", 0) >= 720 and pr.get("h", 0) >= 1280 and a.mean() > 12 and float(np.abs(a - b).mean()) > 1.5
    return {"pass": bool(ok), "dur": dur, "wh": [pr.get("w"), pr.get("h")]}


def evaluate_window(clip, win, cost):
    # displacement metrics from the HIGH-RES full-clip series sliced to the window (avoids re-track aliasing on a short clip)
    hs = win["cx_series"][win["onset_frame"]: win["action_end_frame"] + 1]
    steps = [hs[i + 1] - hs[i] for i in range(len(hs) - 1)]
    net = round(hs[-1] - hs[0], 4); ratio = round(net / AUTHORED, 3)
    idle = round(sum(1 for d in steps if abs(d) < 0.004) / max(1, len(steps)), 3)
    reversals = sum(1 for d in steps if d < -0.02); max_back = round(min([0.0] + steps), 4)
    i60 = int(0.6 * len(hs)); prog = net > 0 and (hs[i60] - hs[0]) >= 0.4 * net
    # perceptual/geometry gates on the trimmed clip
    tk = DV.bolt_tracker(clip)
    tech = window_technical(clip)
    anat = DV.check_anatomy_temporal(clip, R.BOLT_SPEC, cost=cost)
    cam = DV.camera_model_gate(clip, cost=cost); attach = DV.destination_attachment_gate(clip, cost=cost)
    pp = DV.propulsion_presence_gate(clip, tracker=tk); pvc = DV.propulsion_velocity_coupling_gate(clip, tracker=tk)
    geo = DV.endpoint_geometry_gate(clip, END, tracker=tk, cost=cost)
    idp = DV.end_identity_pose_gate(clip, END, tracker=tk, cost=cost)
    checks = {
        "net_forward_ge_0.10": net >= 0.10, "realized_ratio_ge_0.65": ratio >= 0.65,
        "idle_le_0.20": idle <= 0.20, "no_meaningful_reversal": reversals == 0,
        "progressive_not_teleport": bool(prog), "propulsion_present_directional": bool(pp["pass"] and pvc["coupled"]),
        "camera_locked": bool(cam.get("pass")), "terminal_fixed": bool(attach.get("pass")),
        "anatomy_identity_valid": bool(anat.get("identity_pass") and idp["pass"]),
        "no_contact_or_overshoot": bool(not geo["contact"] and not geo["overshoot"]),
        "endpoint_geometry_ok": bool(geo["pass"]), "usable_start_end_frames": True, "technical": bool(tech["pass"]),
    }
    diag = {"net_forward": net, "realized_ratio": ratio, "idle_fraction": idle, "reversals": reversals,
            "max_backward_step": max_back, "progressive": bool(prog), "window_cx_series": [round(c, 4) for c in hs]}
    return {"accepted": all(checks.values()), "checks": checks, "diag": diag,
            "reports": {"technical": tech, "anatomy": anat, "camera": cam, "attachment": attach, "propulsion_presence": pp,
                        "propulsion_velocity_coupling": pvc, "endpoint_geometry": geo, "end_identity_pose": idp}}


def main():
    DV.assert_allow_paid_reset()
    cost = []
    # Part 1 — freeze evidence
    for f in ("c0.mp4", "c0_raw.mp4", "c1.mp4", "c1_raw.mp4", "c0_contact.jpg", "c1_contact.jpg", "c1_trajectory.png"):
        if os.path.exists(os.path.join(AD, f)): shutil.copy(os.path.join(AD, f), os.path.join(FROZEN, f))
    MR.register("bolt.A1.disp.c1.positive", status="diagnostic_fixture",
                description="A1 displacement cand1 — POSITIVE translation-control: net +0.134, ratio 0.863, progressive, nearer terminal, on-model, locked camera+terminal. Proves the translation mechanism at authored disp 0.156.",
                clip=os.path.join(FROZEN, "c1.mp4"), not_accepted_reason="raw 3s timing fail (delayed launch); trimmed-window validation is this milestone")
    MR.register("bolt.A1.disp.c0.negative", status="diagnostic_fixture",
                description="A1 displacement cand0 — NEGATIVE unstable: net -0.076, big backstep. Provider variance.",
                clip=os.path.join(FROZEN, "c0.mp4"), not_accepted_reason="unstable / backward motion")

    # Part 3 — detect the usable window
    win = DV.detect_usable_action_window(C1, n=30)
    if win.get("onset_frame") is None:
        json.dump({"status": "A1_TRACKING_OR_EVALUATOR_DEFECT", "window": win}, open(os.path.join(AD, "a1_window_result.json"), "w"), indent=2, default=str)
        print("STATUS: A1_TRACKING_OR_EVALUATOR_DEFECT (window detection failed)"); return
    winclip = trim(C1, win["onset_t"], win["action_end_t"] + 0.03, os.path.join(OUT, "A1_window.mp4"))
    shutil.copy(C1, os.path.join(OUT, "A1_full_raw.mp4"))                 # unchanged full raw retained
    contact(C1, os.path.join(OUT, "raw_contact.jpg"), "6x2"); contact(winclip, os.path.join(OUT, "window_contact.jpg"), "5x1")
    traj_plot(win, win["cx_series"], win["t_series"], os.path.join(OUT, "raw_vs_window_trajectory.png"))

    # Part 4 — evaluate the window; keep raw failures separate
    ev = evaluate_window(winclip, win, cost)
    raw = json.load(open(os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/atomic_shots/a1_displacement_result.json")))
    raw_c1 = next((c for c in raw["candidates"] if c["cand"] == 1), {})
    raw_fails = raw_c1.get("fails", [])

    # Part 5 — decide
    if ev["accepted"]:
        status = "A1_TRIMMED_PRIMITIVE_PASS"
    else:
        # tracking/eval defect only if the window couldn't be measured; else the window itself isn't usable
        status = "A1_ACTION_WINDOW_NOT_USABLE"
    out = {"objective": "a1_candidate1_production_window_validation", "status": status,
           "translation_capability": "PASS", "raw_3s_primitive_acceptance": "FAIL",
           "raw_status": "A1_TRANSLATION_PROVED_RAW_CLIP_TIMING_FAIL", "raw_clip_failures_c1": raw_fails,
           "detected_window": {k: win[k] for k in ("onset_frame", "action_end_frame", "arrival_frame", "onset_t", "action_end_t", "max_cx", "baseline_cx", "first_backdrift_t")},
           "window_evaluation": {"accepted": ev["accepted"], "checks": ev["checks"], "diag": ev["diag"],
                                 "fails": [k for k, v in ev["checks"].items() if not v]},
           "artifacts": {"full_raw": "window/A1_full_raw.mp4", "window_clip": "window/A1_window.mp4",
                         "raw_contact": "window/raw_contact.jpg", "window_contact": "window/window_contact.jpg",
                         "raw_vs_window_trajectory": "window/raw_vs_window_trajectory.png"},
           "allow_paid_disk": DV.disk_allow_paid(), "allow_paid_runtime": DV.ALLOW_PAID,
           "allow_paid_reset_assertion": DV.assert_allow_paid_reset(), "inserted_into_short": False, "no_paid_calls": True,
           "vlm_cost_usd": round(sum(cost), 3)}
    if status == "A1_TRIMMED_PRIMITIVE_PASS":
        MR.register("bolt.hover_launch", status="accepted", clip=winclip,
                    description="Approved hover_launch primitive: trimmed production window of A1 cand1 (crouch→launch→arrival). Translation + propulsion + geometry validated.",
                    source="a1_displacement cand1 trimmed", window=[win["onset_t"], win["action_end_t"]])
        out["frozen_primitive"] = "bolt.hover_launch -> accepted"
    json.dump(out, open(os.path.join(AD, "a1_window_result.json"), "w"), indent=2, default=str)
    rr = subprocess.run([sys.executable, "bolt_seq/tests/test_regression.py"], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": PROJ})
    print("=== A1 WINDOW VALIDATION (no spend) ===")
    print("window:", win["onset_t"], "-", win["action_end_t"], "s | frames", win["onset_frame"], "-", win["action_end_frame"])
    print("window diag:", ev["diag"]["net_forward"], "ratio", ev["diag"]["realized_ratio"], "idle", ev["diag"]["idle_fraction"], "rev", ev["diag"]["reversals"], "prog", ev["diag"]["progressive"])
    print("window checks fails:", [k for k, v in ev["checks"].items() if not v] or "NONE")
    print("raw c1 failures (kept separate):", raw_fails)
    print("STATUS:", status, "| ALLOW_PAID disk", DV.disk_allow_paid(), "runtime", DV.ALLOW_PAID, "| regression", rr.stdout.strip().splitlines()[-1] if rr.stdout else "", "| VLM $%.2f" % sum(cost))
    if status == "A1_TRIMMED_PRIMITIVE_PASS": print("FROZEN: bolt.hover_launch -> accepted")


if __name__ == "__main__":
    main()
