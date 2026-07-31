"""A1 BODY-ONLY CORE-PRODUCT PROOF — AUTHORIZED paid, ONE candidate, $0.75 all-in cap. Provider generates BODY
motion only (no VFX); NO post-hoc removal/masking/inpainting. Phases: 1 generate → 2 raw-clip gates →
3 action-window detect+trim+re-gate → 4 add ONE deterministic compact plume ONTO the already-clean window →
5 final production gates. ALLOW_PAID try/finally + assert False after. Nothing inserted/promoted.
Run: python3 -m bolt_seq.run_A1_body_only_pilot        (paid, one candidate)
     DRY=1 python3 -m bolt_seq.run_A1_body_only_pilot  (no spend: eval path on an existing clip)"""
import os, sys, json, subprocess, traceback
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from bolt_seq.providers import directed_video as DV
from bolt_seq import motion_registry as MR
from bolt_seq import run_primitive_chain_pilot as R

AT = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/atomic_shots")
OUT = os.path.join(AT, "a1_body_only", "pilot"); os.makedirs(OUT, exist_ok=True)
OX = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription")
PKG = json.load(open(os.path.join(AT, "a1_body_only_package.json")))
B0 = os.path.join(AT, "primitives", "A1body_B0.png"); B1 = os.path.join(AT, "primitives", "A1body_B1.png")
PLATE = os.path.join(OX, "corridor_with_terminal.png")
PROMPT = PKG["sanitized_request_no_keys"]["prompt"]; NEG = PKG["sanitized_request_no_keys"]["negative_prompt"]
AUTHORED = PKG["authored_forward_displacement"]
BOLT_SPEC = R.BOLT_SPEC
CAP, VCOST, EVAL_EST, TIMEOUT = 0.75, 0.336, 0.15, 600
DRY = os.environ.get("DRY") == "1"
EVAL_ONLY = os.environ.get("EVAL_ONLY") == "1"
W, H, TERM_LEFT = 1080, 1920, 0.605


def displacement(clip, tracker):
    det = [s for s in tracker["samples"] if s.get("cx") is not None]
    cx = [s["cx"] for s in det]; steps = [cx[i + 1] - cx[i] for i in range(len(cx) - 1)]
    net = round(cx[-1] - cx[0], 4) if len(cx) >= 2 else 0.0
    idle = round(sum(1 for d in steps if abs(d) < 0.004) / max(1, len(steps)), 3)
    rev = sum(1 for d in steps if d < -0.02); i60 = int(0.6 * len(cx))
    prog = net > 0 and len(cx) > i60 and (cx[i60] - cx[0]) >= 0.4 * net
    return {"net_forward": net, "ratio": round(net / AUTHORED, 3) if AUTHORED else 0, "idle": idle, "reversals": rev, "progressive": bool(prog)}


def eval_bodyonly(clip, is_window, cost):
    tk = DV.bolt_tracker(clip)
    vfx = DV.generated_vfx_absence_gate(clip, plate_path=PLATE, tracker=tk)
    lb = DV.lower_body_integrity_gate(clip, tracker=tk, cost=cost)
    ep = DV.endpoint_geometry_gate(clip, B1, tracker=tk, cost=cost)
    anat = DV.check_anatomy_temporal(clip, BOLT_SPEC, cost=cost)
    cam = DV.camera_model_gate(clip, cost=cost); attach = DV.destination_attachment_gate(clip, cost=cost)
    disp = displacement(clip, tk)
    pr = DV._probe(clip); dur = pr.get("dur", 0) or 0
    tech = (0.5 <= dur) if is_window else (2.5 <= dur <= 3.6)
    anatomy_identity_ok = (len(anat.get("other_prohibited", [])) == 0)     # pods approved; mouth/extra/dup must be absent
    checks = {
        "vfx_absent": bool(vfx["pass"]), "lower_body_integrity": bool(lb["pass"]),
        "forward_translation": bool(disp["net_forward"] >= 0.10 and disp["progressive"] and disp["reversals"] == 0),
        "endpoint_geometry": bool(ep["pass"]), "anatomy_identity": bool(anatomy_identity_ok),
        "camera_locked": bool(cam.get("pass")), "terminal_fixed": bool(attach.get("pass")), "technical": bool(tech),
    }
    return {"accepted": all(checks.values()), "checks": checks, "displacement": disp,
            "reports": {"vfx_absence": vfx, "lower_body": lb, "endpoint": ep, "anatomy": anat, "camera": cam, "attachment": attach},
            "fails": [k for k, v in checks.items() if not v]}


def add_compact_plume(inclip, outclip):
    """Phase 4: ADD exactly one COMPACT SHARP deterministic plume beneath Bolt's lower-body anchor, per frame.
    No removal of any pixels — composited on top of the already-clean body-only clip. Anchored to the SAME bbox
    the gates use (tracker ROI) so the plume is centred on body_cx and its top sits within the attachment window
    (top<=body_bottom+0.04H, |cx-body_cx|<=0.10W). Starts BELOW the visible base so it never covers the base/pods;
    origin fixed to Bolt (zero lag); intensity/length respond to velocity around a visible minimum; slight
    velocity shear as it trails but the mouth never detaches."""
    fdir = os.path.join(OUT, "_pf_in"); rdir = os.path.join(OUT, "_pf_out")
    for d in (fdir, rdir):
        os.makedirs(d, exist_ok=True); [os.remove(os.path.join(d, x)) for x in os.listdir(d)]
    fps = DV._probe(inclip).get("fps", 30) or 30
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", inclip, "-vf", f"fps={fps},scale={W}:{H}", os.path.join(fdir, "f%04d.png")], check=True)
    files = sorted(f for f in os.listdir(fdir) if f.endswith(".png"))
    from scipy import ndimage

    def _base(a, bb):
        """TRUE rounded-base bottom + centre: Bolt is brighter than the dark corridor and cyan-white tinted; the
        bright-mask bbox undershoots the dim lower base by ~0.05H, so measure the real silhouette bottom here."""
        R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
        m = (a.mean(axis=2) > 85) & (B >= R - 8)
        reg = np.zeros_like(m); reg[max(0, bb[1] - 20):min(H, bb[3] + int(0.10 * H)), max(0, bb[0] - 30):min(W, bb[2] + 30)] = True
        m = ndimage.binary_closing(m & reg, iterations=3); lbl, n = ndimage.label(m)
        if not n:
            return (bb[0] + bb[2]) / 2, bb[3], bb[2] - bb[0]
        sizes = ndimage.sum(np.ones_like(lbl), lbl, range(1, n + 1)); big = lbl == (int(np.argmax(sizes)) + 1)
        ys, xs = np.where(big); bot = int(ys.max())
        low = xs[ys > bot - int(0.06 * H)]                    # centre of the LOWEST slice (the base mouth)
        cx = (low.min() + low.max()) / 2 if len(low) else (bb[0] + bb[2]) / 2
        return cx, bot, bb[2] - bb[0]

    anchors = []
    for f in files:
        a = np.asarray(Image.open(os.path.join(fdir, f)).convert("RGB"), float)
        bb = DV._blob_bbox(a, 0, int(0.58 * W), int(0.26 * H), int(0.86 * H))
        anchors.append(_base(a, bb) if bb else None)
    for i, f in enumerate(files):
        out = Image.open(os.path.join(fdir, f)).convert("RGBA")
        if anchors[i]:
            ax, ay, bw = anchors[i]; v = (ax - anchors[i - 1][0]) / W if (i > 0 and anchors[i - 1]) else 0.0
            speed = min(0.08, abs(v))
            L = int(0.115 * H + 220 * speed)                 # compact but visibly present; grows with speed
            hw = max(14, int(0.075 * bw + 40 * speed))       # mouth half-width (kept within _detect_jet's cx +/-0.24bw)
            top = int(ay - 0.010 * H); shear = int(-np.sign(v) * 90 * speed)   # nozzle at the base rim (small overlap, base stays visible)
            jet = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(jet)
            d.polygon([(int(ax - hw * 1.35), top + int(0.02 * H)), (int(ax + hw * 1.35), top + int(0.02 * H)),
                       (int(ax + shear), top + int(L * 1.05))], fill=(120, 235, 250, 90))                       # soft outer glow (compact)
            d.polygon([(int(ax - hw), top), (int(ax + hw), top), (int(ax + shear), top + L)], fill=(110, 238, 252, 235))       # sharp cone
            d.polygon([(int(ax - hw // 2), top), (int(ax + hw // 2), top), (int(ax + shear), top + int(L * 0.72))], fill=(210, 252, 255, 255))  # bright core
            d.ellipse([int(ax - hw * 1.15), int(top - 0.014 * H), int(ax + hw * 1.15), int(top + 0.02 * H)], fill=(215, 252, 255, 235))          # nozzle glow at the base
            out = Image.alpha_composite(out, jet.filter(ImageFilter.GaussianBlur(3)))
        out.convert("RGB").save(os.path.join(rdir, f))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", f"{fps}", "-i", os.path.join(rdir, "f%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", outclip], check=True)
    return outclip


def contact(clip, out, cols=8):
    """Even N-frame contact sheet. Sample a fixed number of frames (<= tile capacity) so ffmpeg emits ONE image."""
    dur = DV._probe(clip).get("dur", 3.0) or 3.0
    fps = max(0.5, round((cols - 0.5) / max(0.3, dur), 3))     # ~cols frames across the clip, never exceeding the grid
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf", f"fps={fps},scale=220:-1,tile={cols}x1", "-frames:v", "1", out], check=False)


def final_gates(finalclip, bodyclip, cost):
    """Propulsion + base-not-covered gates run on the FINAL (plumed) clip. Bolt-motion INVARIANTS
    (endpoint/trajectory/anatomy) run on the CLEAN body clip: the plume is additive BELOW Bolt and cannot alter
    his motion, but being cyan it would contaminate the bbox tracker on the final clip — so measure those on the
    already-validated body clip. lower_body runs on the FINAL clip to prove the plume did NOT cover the base."""
    tkf = DV.bolt_tracker(finalclip); tkb = DV.bolt_tracker(bodyclip)
    g = {"propulsion_presence": DV.propulsion_presence_gate(finalclip, tracker=tkf),
         "propulsion_attachment": DV.propulsion_attachment_gate(finalclip, tracker=tkf),
         "propulsion_cleanup": DV.propulsion_cleanup_gate(finalclip, plate_path=PLATE, tracker=tkf),
         "visual_artifact": DV.visual_artifact_gate(finalclip, PLATE, tracker=tkf),
         "lower_body": DV.lower_body_integrity_gate(finalclip, tracker=tkf, cost=cost),   # base still visible WITH the plume
         "camera": DV.camera_model_gate(finalclip, cost=cost),
         "endpoint": DV.endpoint_geometry_gate(bodyclip, B1, tracker=tkb, cost=cost),     # Bolt-motion invariant (clean clip)
         "path": DV.path_monotonicity_gate(bodyclip, tracker=tkb),
         "anatomy": DV.check_anatomy_temporal(bodyclip, BOLT_SPEC, cost=cost)}
    gp = {"exactly_one_effect_attached": g["propulsion_cleanup"]["pass"] and g["propulsion_attachment"]["pass"],
          "propulsion_present": g["propulsion_presence"]["pass"], "no_residual_or_secondary": g["propulsion_cleanup"]["pass"],
          "no_visual_artifact": g["visual_artifact"]["pass"], "base_pods_visible": g["lower_body"]["pass"],
          "camera_fixed": g["camera"]["pass"], "endpoint_ok": g["endpoint"]["pass"], "trajectory_ok": g["path"]["pass"],
          "anatomy_ok": len(g["anatomy"].get("other_prohibited", [])) == 0}
    return {"pass": all(gp.values()), "gate_pass": gp,
            "gate_clip_map": {"final_clip": ["propulsion_presence", "propulsion_attachment", "propulsion_cleanup",
                                             "visual_artifact", "lower_body", "camera"],
                              "clean_body_clip": ["endpoint", "path", "anatomy"]},
            "reports": g}


def main():
    if DRY:
        clip = os.path.join(AT, "a1_displacement", "c1.mp4"); cost = []
        ev = eval_bodyonly(clip, False, cost)
        print("DRY eval OK — no crash | accepted", ev["accepted"], "| fails", ev["fails"], "| disp", ev["displacement"], "| VLM $%.2f" % sum(cost), "| ALLOW_PAID", DV.ALLOW_PAID)
        return

    cost = []; confirmed = 0.0; potential = 0.0; err = None
    raw_eval = win_eval = final = None; window = None; status = None; raw = norm = winclip = finalclip = None
    request_id = payload = raw_response = None
    if EVAL_ONLY:
        # Re-run phases 2-5 on the EXISTING clip with the corrected gates. No provider call; ALLOW_PAID stays False.
        norm = os.path.join(OUT, "bodyonly.mp4")
        prior = os.path.join(AT, "a1_body_only_pilot_result.json")
        if os.path.exists(prior):
            pj = json.load(open(prior)); pv = pj.get("provider", {}); confirmed = pj.get("spend_ledger", {}).get("confirmed_video_usd", VCOST)
            request_id = pv.get("request_id"); payload = pv.get("sanitized_request"); raw_response = pv.get("raw_response")
        else:
            confirmed = VCOST
        print("EVAL_ONLY: re-evaluating existing clip with corrected gates (no spend)...", flush=True)
    else:
        DV.ALLOW_PAID = True
        try:
            adapter = DV.FalKlingAdapter()
            spec = {"model": "kling-v3-pro", "seed_image": B0, "end_image": B1, "prompt": PROMPT, "negative_prompt": NEG,
                    "cfg_scale": 0.6, "generate_audio": False, "duration": "3", "use_elements": False}
            spent = confirmed + potential + sum(cost)
            if spent + VCOST + EVAL_EST > CAP:
                raise DV.DirectedVideoFailure(f"budget: ${spent}+${VCOST}+${EVAL_EST} > ${CAP}")
            raw = os.path.join(OUT, "raw.mp4"); norm = os.path.join(OUT, "bodyonly.mp4")
            print("submitting ONE body-only candidate (3s)...", flush=True)
            potential += VCOST
            job = adapter.submit(spec, TIMEOUT); adapter.poll_and_download(job, raw, TIMEOUT)
            confirmed += VCOST; potential -= VCOST
            DV._normalize_media(raw, norm)
            request_id = job.get("request_id"); raw_response = job.get("raw_response"); payload = job.get("submitted_payload_sanitized")
        except DV.DirectedVideoFailure as e:
            err = str(e); status = "A1_BODY_ONLY_GENERATION_FAIL"
        except Exception as e:
            err = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:500]}"; status = "A1_BODY_ONLY_GENERATION_FAIL"
        finally:
            DV.ALLOW_PAID = False

    # PHASE 2/3/4/5 (no further provider calls)
    body_reason = None
    try:
        if norm and os.path.exists(norm):
            raw_eval = eval_bodyonly(norm, False, cost); contact(norm, os.path.join(OUT, "raw_contact.jpg"))
            window = DV.detect_usable_action_window(norm, n=30)
            winclip = os.path.join(OUT, "bodyonly_window.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{window['onset_t']:.3f}", "-to", f"{window['action_end_t']+0.05:.3f}",
                            "-i", norm, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", winclip], check=True)
            win_eval = eval_bodyonly(winclip, True, cost); contact(winclip, os.path.join(OUT, "window_contact.jpg"))
            # classify body-only window
            wc = win_eval["checks"]
            if not wc["vfx_absent"]:
                body_reason = "A1_PROVIDER_VFX_LEAK_FAIL"
            elif not wc["lower_body_integrity"]:
                body_reason = "A1_LOWER_BODY_INTEGRITY_FAIL"
            elif not wc["forward_translation"]:
                body_reason = "A1_TRANSLATION_FAIL"
            elif not wc["anatomy_identity"]:
                body_reason = "A1_IDENTITY_ANATOMY_FAIL"
            elif win_eval["accepted"]:
                body_reason = "A1_BODY_ONLY_MOTION_PASS" if raw_eval["accepted"] else "A1_BODY_ONLY_TIMING_FAIL_WINDOW_PASS"
            else:
                body_reason = "A1_BODY_ONLY_GENERATION_FAIL"
            # PHASE 4/5 only if the body-only window passes (VFX-clean; NO removal ever)
            if body_reason in ("A1_BODY_ONLY_MOTION_PASS", "A1_BODY_ONLY_TIMING_FAIL_WINDOW_PASS"):
                finalclip = add_compact_plume(winclip, os.path.join(OUT, "A1_final_primitive.mp4"))
                contact(finalclip, os.path.join(OUT, "final_contact.jpg"))
                final = final_gates(finalclip, winclip, cost)
                status = "A1_FULL_PRIMITIVE_PASS" if final["pass"] else "A1_BODY_ONLY_PASS_VFX_FAIL"
            else:
                status = "A1_BODY_ONLY_GENERATION_FAIL"
    except Exception as e:
        err = (err or "") + f" | eval: {type(e).__name__}: {e}\n{traceback.format_exc()[:400]}"; status = status or "A1_BODY_ONLY_GENERATION_FAIL"

    auth = DV.assert_allow_paid_reset()
    eval_spend = round(sum(cost), 2)
    ledger = {"confirmed_video_usd": round(confirmed, 2), "potential_unretrieved_usd": round(potential, 2),
              "evaluation_usd": eval_spend, "max_total_usd": round(confirmed + potential + eval_spend, 2),
              "cap_usd": CAP, "within_cap": (confirmed + potential + eval_spend) <= CAP}
    # keep clip diagnostic/pending; do NOT auto-promote
    MR.register("bolt.hover_launch", status="body_only_pilot_pending_review" if status == "A1_FULL_PRIMITIVE_PASS" else "pending_gates",
                clip=(finalclip if status == "A1_FULL_PRIMITIVE_PASS" else None),
                description=f"A1 body-only pilot result: {status}. Not promoted; awaiting manual review.", not_accepted_reason=status)
    rr = subprocess.run([sys.executable, "bolt_seq/tests/test_regression.py"], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": PROJ})
    out = {"objective": "a1_body_only_core_product_proof", "status": status, "body_only_window_verdict": body_reason, "error": err,
           "lower_body_authority": {"human_review_lower_body_approved": True, "reference_asset": "hover_run_dry",
                                    "required_anatomy": "rounded hover chassis + approved small foot/base pods",
                                    "no_humanoid_legs": True, "no_boots": True, "no_replacement_thruster_cone": True,
                                    "note": "generated clip (Bolt-cropped + temporal) determines lower-body integrity, NOT the full-frame VLM precheck; the original precheck false-negative is preserved in a1_body_only_package.json"},
           "provider": {"request_id": locals().get("request_id"), "sanitized_request": locals().get("payload"), "raw_response": locals().get("raw_response")},
           "raw_clip_eval": raw_eval, "detected_window": {k: window.get(k) for k in ("onset_t", "action_end_t", "onset_frame", "action_end_frame", "max_cx")} if window else None,
           "window_eval": win_eval, "final_production_gates": final,
           "spend_ledger": ledger, "allow_paid_disk_after": DV.disk_allow_paid(), "allow_paid_runtime_after": DV.ALLOW_PAID,
           "allow_paid_reset_assertion": auth, "inserted_into_short": False, "auto_promoted": False,
           "no_posthoc_provider_vfx_removal": True, "regression": rr.stdout.strip().splitlines()[-1] if rr.stdout else "",
           "artifacts": {"raw": "pilot/raw.mp4", "bodyonly": "pilot/bodyonly.mp4", "window": "pilot/bodyonly_window.mp4",
                         "final": "pilot/A1_final_primitive.mp4" if finalclip else None, "raw_contact": "pilot/raw_contact.jpg",
                         "window_contact": "pilot/window_contact.jpg", "final_contact": "pilot/final_contact.jpg" if finalclip else None}}
    json.dump(out, open(os.path.join(AT, "a1_body_only_pilot_result.json"), "w"), indent=2, default=str)
    print("\n=== A1 BODY-ONLY PILOT ===")
    print("request:", locals().get("request_id"), "| spend: confirmed $%.2f + potential $%.2f + eval $%.2f = $%.2f (cap $%.2f) within=%s" % (confirmed, potential, eval_spend, ledger["max_total_usd"], CAP, ledger["within_cap"]))
    if raw_eval: print("raw-clip eval:", raw_eval["checks"], "| disp", raw_eval["displacement"])
    if win_eval: print("window:", window["onset_t"] if window else None, "-", window["action_end_t"] if window else None, "| eval:", win_eval["checks"], "| disp", win_eval["displacement"])
    print("body_only_window_verdict:", body_reason)
    if final: print("final production gates:", final["gate_pass"])
    print("STATUS:", status, "| ALLOW_PAID disk", DV.disk_allow_paid(), "runtime", DV.ALLOW_PAID, "| regression", out["regression"], "| inserted", out["inserted_into_short"])
    if err: print("note:", err[:200])


if __name__ == "__main__":
    main()
