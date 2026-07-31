"""CORE PRODUCT PROOF V1 — execute the A1->A2->A3 primitive chain (AUTHORIZED paid, cap $3.00, <=2 cand/prim,
sequential stop-after-first-pass, stop-if-both-fail). Uses the EXISTING prepared plan (boundary frames +
contracts) unchanged. Each primitive is a 3s generation; the FULL raw clip is evaluated first; trim to the
authored window ONLY after it passes. Per-primitive acceptance uses each primitive's required gates wired to
the user's explicit proof lists (deterministic signals override contradictory VLM). Assemble, then run the
existing generated_seam_gate on A1->A2 and A2->A3. ALLOW_PAID try/finally + post-run assert (disk+runtime
False). Returns exactly one status. Nothing inserted into the Short.
Run: python3 -m bolt_seq.run_primitive_chain_pilot          (paid)
     DRY=1 python3 -m bolt_seq.run_primitive_chain_pilot    (no spend: evaluate an existing clip to de-risk)"""
import os, sys, json, subprocess, traceback
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq.providers import directed_video as DV
from bolt_seq.character import BOLT

AT = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/atomic_shots")
OUT = os.path.join(AT, "primitive_chain"); os.makedirs(OUT, exist_ok=True)
PLAN = json.load(open(os.path.join(AT, "shot_A_primitive_sequence_plan.json")))
IDENT = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/bolt_hover_run_dry.png")
BOLT_SPEC = {"identity_reference": IDENT, "anatomy": BOLT["anatomy"]}
CAP, VCOST, EVAL_EST, MAXC, TIMEOUT = 3.00, 0.336, 0.15, 2, 600
DRY = os.environ.get("DRY") == "1"


def technical_gate(clip):
    import numpy as np
    from PIL import Image
    pr = DV._probe(clip); dur = pr.get("dur", 0) or 0
    ok_dur = 2.5 <= dur <= 3.6; ok_dim = pr.get("w", 0) >= 720 and pr.get("h", 0) >= 1280
    out = DV.tempfile.mkdtemp()
    def fr(t):
        fp = os.path.join(out, f"t{t}.png"); subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", clip, "-frames:v", "1", fp], check=True); return np.asarray(Image.open(fp).convert("RGB"), float)
    a, b = fr(0.2), fr(min(dur - 0.1, 2.5))
    not_black = a.mean() > 12; not_frozen = float(np.abs(a - b).mean()) > 1.5
    return {"gate": "technical", "pass": bool(ok_dur and ok_dim and not_black and not_frozen),
            "dur": dur, "wh": [pr.get("w"), pr.get("h")], "not_black": not_black, "not_frozen": not_frozen}


def common_gates(clip, cost):
    tech = technical_gate(clip)
    anat = DV.check_anatomy_temporal(clip, BOLT_SPEC, cost=cost)
    cam = DV.camera_model_gate(clip, cost=cost)
    attach = DV.destination_attachment_gate(clip, cost=cost)
    checks = {"technical": bool(tech["pass"]), "anatomy_identity": bool(anat.get("identity_pass")),
              "locked_camera": bool(cam.get("pass")), "fixed_terminal": bool(attach.get("pass"))}
    return {"checks": checks, "all_pass": all(checks.values()), "reports": {"technical": tech, "anatomy": anat, "camera": cam, "attachment": attach}}


def _vel_series(tk):
    det = [s for s in tk["samples"] if s.get("cx") is not None]
    return det


def accept_A1(clip, end_frame, cost):
    """launch: real launch from near-rest, visible propulsion, propulsion coupled to acceleration, forward
    monotonic path, endpoint realization (+ common)."""
    tk = DV.bolt_tracker(clip)
    pp = DV.propulsion_presence_gate(clip, tracker=tk)
    pvc = DV.propulsion_velocity_coupling_gate(clip, tracker=tk)     # use .coupled (launch thrust rises, not weakens)
    pm = DV.path_monotonicity_gate(clip, tracker=tk)
    er = DV.endpoint_realization_gate(clip, end_frame, tracker=tk)
    det = _vel_series(tk); k = max(1, len(det) // 2)
    v_early = sum(abs(s.get("h_vel", 0)) for s in det[1:k]) / max(1, k - 1)
    v_late = sum(abs(s.get("h_vel", 0)) for s in det[k:]) / max(1, len(det) - k)
    launch_accel = v_late >= v_early                                 # accelerating from near-rest
    checks = {"visible_propulsion": bool(pp["pass"]), "propulsion_coupled_to_accel": bool(pvc["coupled"]),
              "real_launch_accel": bool(launch_accel), "forward_monotonic_path": bool(pm["pass"]),
              "endpoint_realization": bool(er["pass"])}
    return checks, {"propulsion_presence": pp, "propulsion_velocity_coupling": pvc, "path_monotonicity": pm,
                    "endpoint_realization": er, "launch_v_early": round(v_early, 4), "launch_v_late": round(v_late, 4)}


def accept_A2(clip, end_frame, cost):
    """effortful approach: continued forward travel, effort increases, no backward/idle, endpoint (+ common)."""
    tk = DV.bolt_tracker(clip)
    pm = DV.path_monotonicity_gate(clip, tracker=tk)
    perf = DV.performance_progression_gate(clip, tracker=tk, cost=cost)   # use effort-rise + directional sub-readings
    er = DV.endpoint_realization_gate(clip, end_frame, tracker=tk)
    eff = perf.get("readings", {}).get("effort", [0, 0, 0, 0])
    effort_increases = len(eff) >= 4 and eff[3] >= eff[0] + 1
    checks = {"continued_forward_travel": bool(pm["pass"] and pm.get("net_forward", 0) > 0),
              "no_backward_or_idle": bool(pm.get("reversals", 1) == 0 and pm.get("idle_frac", 1) <= 0.45),
              "effort_increases": bool(effort_increases), "endpoint_realization": bool(er["pass"])}
    return checks, {"path_monotonicity": pm, "performance_progression": perf, "endpoint_realization": er}


def accept_A3(clip, end_frame, cost):
    """weakening reach: propulsion decays/extinguishes, velocity falls, altitude loss, weakening posture,
    short of terminal, no recovery/contact/overshoot, endpoint (+ common)."""
    tk = DV.bolt_tracker(clip)
    decay = DV.propulsion_decay_or_extinguish_gate(clip, tracker=tk)
    perf = DV.performance_progression_gate(clip, tracker=tk, cost=cost)
    tc = DV.trajectory_contract_gate(clip, tracker=tk)
    er = DV.endpoint_realization_gate(clip, end_frame, tracker=tk)
    pc = perf.get("checks", {})
    checks = {"propulsion_decays_or_extinguishes": bool(decay["pass"]),
              "velocity_falls": bool(pc.get("velocity_declines")), "altitude_loss": bool(pc.get("altitude_drops")),
              "weakening_posture": bool(pc.get("effort_or_instability_rises")),
              "short_of_terminal": bool(tc["checks"].get("final_gap_in_short_band")),
              "no_overshoot_or_contact": bool(tc["checks"].get("no_terminal_overlap") and not tc["measured"].get("overshoot")),
              "no_recovery": bool(decay.get("declines")), "endpoint_realization": bool(er["pass"])}
    return checks, {"propulsion_decay": decay, "performance_progression": perf, "trajectory_contract": tc, "endpoint_realization": er}


ACCEPT = {"A1_hover_launch": accept_A1, "A2_effortful_approach": accept_A2, "A3_weakening_reach": accept_A3}


def evaluate(step, clip, cost):
    end_frame = step["spec_sanitized"]["end_image"]
    common = common_gates(clip, cost)
    prim_checks, prim_reports = ACCEPT[step["id"]](clip, end_frame, cost)
    accepted = common["all_pass"] and all(prim_checks.values())
    fails = [k for k, v in common["checks"].items() if not v] + [k for k, v in prim_checks.items() if not v]
    return {"accepted": bool(accepted), "common": common["checks"], "primitive": prim_checks, "fails": fails,
            "reports": {**common["reports"], **prim_reports}}


def trim(clip, window, out):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(window[0]), "-to", str(window[1]),
                    "-i", clip, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", out], check=True); return out


def contact_sheet(clip, out):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf", "fps=3,scale=220:-1,tile=5x2", out], check=False)


def main():
    if DRY:
        clip = os.path.join(AT, "start_end_candidates", "c0.mp4")
        print("DRY RUN — evaluating existing clip through all three acceptance paths (no spend):", clip)
        cost = []
        for step in PLAN["steps"]:
            ev = evaluate(step, clip, cost)
            print(f"  {step['id']}: accepted={ev['accepted']} fails={ev['fails']}")
        print(f"DRY eval OK — no crash | VLM ${sum(cost):.2f} | ALLOW_PAID {DV.ALLOW_PAID}")
        return

    cost = []; confirmed = 0.0; potential = 0.0; accepted = {}; results = []; err = None; status = None
    DV.ALLOW_PAID = True
    try:
        adapter = DV.FalKlingAdapter()
        for step in PLAN["steps"]:
            sid = step["id"]; sp = step["spec_sanitized"]; win = step["motion_contract"]["action_window_s"]
            spec = {"model": "kling-v3-pro", "seed_image": sp["seed_image"], "end_image": sp["end_image"],
                    "prompt": sp["prompt"], "negative_prompt": sp["negative_prompt"], "cfg_scale": sp["cfg_scale"],
                    "generate_audio": False, "duration": "3", "use_elements": False}
            step_ok = False
            for cand in range(MAXC):
                spent = confirmed + potential + sum(cost)
                if spent + VCOST + EVAL_EST > CAP:
                    err = f"BUDGET STOP before {sid} cand{cand}: ${spent:.2f}+${VCOST}+${EVAL_EST} > ${CAP}"; status = "PROVIDER_CEILING"; break
                raw = os.path.join(OUT, f"{sid}_c{cand}_raw.mp4"); norm = os.path.join(OUT, f"{sid}_c{cand}.mp4")
                print(f"submitting {sid} cand{cand} (3s)...", flush=True)
                potential += VCOST
                job = adapter.submit(spec, TIMEOUT); adapter.poll_and_download(job, raw, TIMEOUT)
                confirmed += VCOST; potential -= VCOST
                DV._normalize_media(raw, norm)
                ev = evaluate(step, norm, cost)
                contact_sheet(norm, os.path.join(OUT, f"{sid}_c{cand}_contact.jpg"))
                rec = {"primitive": sid, "cand": cand, "request_id": job.get("request_id"), "endpoint": job.get("endpoint"),
                       "submit_status": job.get("submit_status"), "submitted_payload_sanitized": job.get("submitted_payload_sanitized"),
                       "raw_response": job.get("raw_response"), "raw": raw, "norm": norm, "accepted": ev["accepted"],
                       "common": ev["common"], "primitive_checks": ev["primitive"], "fails": ev["fails"]}
                results.append(rec)
                json.dump({k: v for k, v in ev["reports"].items()}, open(os.path.join(OUT, f"{sid}_c{cand}_gates.json"), "w"), indent=2, default=str)
                print(f"  {sid} cand{cand}: accepted={ev['accepted']} fails={ev['fails']}", flush=True)
                if ev["accepted"]:
                    tr = trim(norm, win, os.path.join(OUT, f"{sid}_trim.mp4"))
                    accepted[sid] = {"raw": raw, "norm": norm, "trim": tr, "cand": cand}; step_ok = True; break
            if status == "PROVIDER_CEILING":
                break
            if not step_ok:
                status = "LOCALIZED_PRIMITIVE_FAILURE"
                err = f"{sid}: both candidates failed — stopping; not spending on later primitives"
                print(err); break

        seams = {}
        if status is None and len(accepted) == 3:                     # all three primitives accepted → assemble + seam gates
            order = ["A1_hover_launch", "A2_effortful_approach", "A3_weakening_reach"]
            trims = [accepted[s]["trim"] for s in order]
            lst = os.path.join(OUT, "concat.txt"); open(lst, "w").write("".join(f"file '{os.path.abspath(t)}'\n" for t in trims))
            seq = os.path.join(OUT, "sequence_A1_A2_A3.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", seq], check=False)
            if not os.path.exists(seq) or os.path.getsize(seq) < 1000:
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c:v", "libx264", "-pix_fmt", "yuv420p", seq], check=True)
            contact_sheet(seq, os.path.join(OUT, "sequence_contact.jpg"))
            s1 = DV.generated_seam_gate(accepted["A1_hover_launch"]["trim"], accepted["A2_effortful_approach"]["trim"], cost=cost)
            s2 = DV.generated_seam_gate(accepted["A2_effortful_approach"]["trim"], accepted["A3_weakening_reach"]["trim"], cost=cost)
            seams = {"A1->A2": s1, "A2->A3": s2}
            status = "CORE_PROOF_PASS" if (s1["pass"] and s2["pass"]) else "GENERATED_SEAM_FAILURE"
    except DV.DirectedVideoFailure as e:
        err = str(e); status = status or "EXECUTION_ERROR"
    except Exception as e:
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:600]}"; status = status or "EXECUTION_ERROR"
    finally:
        DV.ALLOW_PAID = False

    auth = DV.assert_allow_paid_reset()
    eval_spend = round(sum(cost), 2)
    ledger = {"confirmed_video_usd": round(confirmed, 2), "potential_unretrieved_usd": round(potential, 2),
              "evaluation_usd": eval_spend, "max_total_usd": round(confirmed + potential + eval_spend, 2),
              "cap_usd": CAP, "within_cap": (confirmed + potential + eval_spend) <= CAP}
    matrix = {sid: {"accepted": sid in accepted,
                    "cand": accepted.get(sid, {}).get("cand"),
                    "checks": next((r["common"] | r["primitive_checks"] for r in results if r["primitive"] == sid and r["accepted"]),
                                   next((r["common"] | r["primitive_checks"] for r in results if r["primitive"] == sid), {}))}
              for sid in ["A1_hover_launch", "A2_effortful_approach", "A3_weakening_reach"]}
    rr = subprocess.run([sys.executable, "bolt_seq/tests/test_regression.py"], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": PROJ})
    out = {"objective": "core_product_proof_v1", "status": status or "EXECUTION_ERROR", "error": err,
           "spend_ledger": ledger, "allow_paid_disk_after": DV.disk_allow_paid(), "allow_paid_runtime_after": DV.ALLOW_PAID,
           "allow_paid_reset_assertion": auth, "inserted_into_short": False, "registry_promoted": False,
           "acceptance_matrix": matrix, "seam_reports": seams,
           "assembled_sequence": os.path.join(OUT, "sequence_A1_A2_A3.mp4") if status in ("CORE_PROOF_PASS", "GENERATED_SEAM_FAILURE") else None,
           "candidates": results, "regression": rr.stdout.strip().splitlines()[-1] if rr.stdout else ""}
    json.dump(out, open(os.path.join(AT, "primitive_chain_pilot_result.json"), "w"), indent=2, default=str)
    print("\n=== PRIMITIVE CHAIN PILOT ===")
    for r in results:
        print(f"  {r['primitive']} cand{r['cand']}: accepted={r['accepted']} req={r['request_id']} fails={r['fails']}")
    if seams:
        for k, v in seams.items(): print(f"  seam {k}: pass={v['pass']} fails={[c for c,x in v['checks'].items() if not x]}")
    print(f"spend: confirmed ${confirmed:.2f} + potential ${potential:.2f} + eval ${eval_spend:.2f} = ${ledger['max_total_usd']:.2f} (cap ${CAP}) within={ledger['within_cap']}")
    print(f"STATUS: {out['status']} | ALLOW_PAID disk={out['allow_paid_disk_after']} runtime={DV.ALLOW_PAID} | regression {out['regression']} | inserted {out['inserted_into_short']}")
    if err: print("note:", err[:200])


if __name__ == "__main__":
    main()
