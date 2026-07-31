"""AUTHORIZED paid Kling v3-pro start+end pilot (oxygen Shot-A). Rules (user-set):
  1) <=2 candidates  2) hard all-in cap $1.50  3) stop after the FIRST candidate passing ALL 7 authoritative
  clip gates  4) candidate 1 elements OFF  5) elements only if a candidate has meaningful motion BUT identity
  drift (never merely because motion fails)  6) no prompt rewrite / salvage / trim / 3rd candidate without
  review  7) no auto-insertion into the Short or the motion registry.
Approved boundary pair is used AS-IS (seed + sink end frame; not altered). ALLOW_PAID try/finally; reset to
False in finally (covers timeout/exception/interrupt). Persists request IDs, raw responses, raw + normalized
clips, tracker samples, per-gate reports, endpoint-realization, spend ledger, ALLOW_PAID=False proof.
Run: python3 -m bolt_seq.run_shot_A_start_end_pilot"""
import os, sys, json, subprocess, traceback
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq.providers import directed_video as DV
from bolt_seq.character import BOLT

OX = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription"); AT = os.path.join(OX, "atomic_shots")
CAND = os.path.join(AT, "start_end_candidates"); os.makedirs(CAND, exist_ok=True)
SEED = os.path.join(AT, "shot_A_seed.png"); END = os.path.join(AT, "shot_A_end_frame.png")
IDENT = os.path.join(OX, "bolt_hover_run_dry.png")     # clean frontal Bolt, only used if elements enabled
PROMPT = open(os.path.join(AT, "shot_A_prompt_v2.txt")).read().strip()
NEG = open(os.path.join(AT, "shot_A_negative_prompt.txt")).read().strip()
SPEC_MOTION = json.load(open(os.path.join(AT, "shot_A_motion_spec.json")))
CONTRACT = SPEC_MOTION["trajectory_contract"]; CURVE = SPEC_MOTION["performance_curve"]
BOLT_SPEC = {"identity_reference": IDENT, "anatomy": BOLT["anatomy"]}
CAP, VCOST, EVAL_EST, MAX_CAND, TIMEOUT = 1.50, 0.56, 0.20, 2, 600


def evaluate(norm, cost, log):
    """Run the 7 authoritative gates + extra clip constraints + endpoint realization on the FULL clip."""
    tk = DV.bolt_tracker(norm)
    core = DV.evaluate_directed_shot(norm, END, contract=CONTRACT, curve=CURVE, cost=cost)   # 7 gates
    camera = DV.camera_model_gate(norm, cost=cost)
    attach = DV.destination_attachment_gate(norm, cost=cost)
    anat = DV.check_anatomy_temporal(norm, BOLT_SPEC, cost=cost)
    epr = DV.endpoint_realization(norm, END, tracker=tk, cost=cost)
    tc = core["gates"]["trajectory_contract"]; vc = core["gates"]["velocity_coupling"]; es = core["gates"]["end_state"]
    alt_loss = (tk["samples"] and tk["samples"][-1].get("cy") and tk["samples"][0].get("cy")
                and tk["samples"][-1]["cy"] - tk["samples"][0]["cy"] >= 0.02)
    extra = {
        "forward_displacement_no_reversal": tc["checks"]["x_displacement_positive"] and tc["checks"]["no_backward_segment_over_bob"],
        "no_terminal_overlap_or_contact": tc["checks"]["no_terminal_overlap"],
        "no_overshoot": (not epr.get("overshoot_past_authored_x")) and tc["checks"]["final_gap_in_short_band"],
        "no_camera_movement": bool(camera.get("pass")),
        "fixed_terminal_world_attachment": bool(attach.get("pass")),
        "weakening_velocity_and_altitude": bool(vc["checks"].get("velocity_declines_over_clip")) and bool(alt_loss),
        "instability_or_effort_rises": bool(vc["checks"].get("instability_rises_as_propulsion_weakens")) or bool(vc["checks"].get("thrust_tracks_velocity")),
        "final_airborne_lower_reaching_short": bool(es.get("pass")) and epr.get("altitude_dropped_vs_start", 0) >= 0.02 and epr.get("converges_to_endpoint"),
        "anatomy_clean_no_mutation": bool(anat.get("identity_pass")),
        "converges_not_passthrough": bool(epr.get("converges_to_endpoint")),
    }
    gates_pass = core["passed"]              # the 7 authoritative gates
    accepted = all(gates_pass.values()) and camera.get("pass") and attach.get("pass") and anat.get("identity_pass")
    return {"accepted": bool(accepted), "authoritative_gates": gates_pass, "extra_constraints": extra,
            "endpoint_realization": epr, "camera": camera, "attachment": attach, "anatomy": anat,
            "core": core, "tracker_samples": tk["samples"],
            "meaningful_motion": bool(core["gates"]["macro_trajectory"].get("makes_progress") or gates_pass.get("articulation_quality")),
            "identity_drift": not bool(anat.get("identity_pass"))}


def contact_sheet(clip, out):
    d = os.path.dirname(out)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf", "fps=2,scale=240:-1,tile=4x3", out], check=False)


def main():
    cost = []; results = []; accepted_i = None; err = None
    confirmed = 0.0; potential = 0.0
    prev = None
    DV.ALLOW_PAID = True
    try:
        adapter = DV.FalKlingAdapter()
        for i in range(MAX_CAND):
            spent = confirmed + potential + sum(cost)
            if spent + VCOST + EVAL_EST > CAP:
                print(f"BUDGET STOP before cand {i}: ${spent:.2f}+${VCOST}+${EVAL_EST} > cap ${CAP}"); break
            # elements decision (rule 4/5): cand 0 OFF; cand 1 ON only if cand 0 had meaningful motion + identity drift
            use_elements = (i == 1 and prev is not None and prev["meaningful_motion"] and prev["identity_drift"])
            spec = {"model": "kling-v3-pro", "seed_image": SEED, "end_image": END, "identity_reference": IDENT,
                    "prompt": PROMPT, "negative_prompt": NEG, "cfg_scale": 0.6, "generate_audio": False,
                    "duration": "5", "use_elements": use_elements, "budget": {"provider_timeout_s": TIMEOUT}}
            raw = os.path.join(CAND, f"c{i}_raw.mp4"); norm = os.path.join(CAND, f"c{i}.mp4")
            print(f"submitting candidate {i} (elements={'ON' if use_elements else 'OFF'})...", flush=True)
            potential += VCOST
            job = adapter.submit(spec, TIMEOUT)
            adapter.poll_and_download(job, raw, TIMEOUT)
            confirmed += VCOST; potential -= VCOST
            DV._normalize_media(raw, norm)
            ev = evaluate(norm, cost, print)
            contact_sheet(norm, os.path.join(CAND, f"c{i}_contact.jpg"))
            json.dump(ev["tracker_samples"], open(os.path.join(CAND, f"c{i}_tracker_samples.json"), "w"), indent=1, default=str)
            rec = {"i": i, "elements": use_elements, "request_id": job.get("request_id"),
                   "endpoint": job.get("endpoint"), "submit_status": job.get("submit_status"),
                   "submitted_payload_sanitized": job.get("submitted_payload_sanitized"),
                   "raw_response": job.get("raw_response"), "raw": raw, "norm": norm,
                   "accepted": ev["accepted"], "authoritative_gates": ev["authoritative_gates"],
                   "extra_constraints": ev["extra_constraints"], "endpoint_realization": ev["endpoint_realization"],
                   "meaningful_motion": ev["meaningful_motion"], "identity_drift": ev["identity_drift"],
                   "fails": [k for k, v in ev["authoritative_gates"].items() if not v] +
                            [k for k, v in ev["extra_constraints"].items() if not v]}
            results.append(rec); prev = ev
            json.dump(ev["core"], open(os.path.join(CAND, f"c{i}_gate_report.json"), "w"), indent=2, default=str)
            print(f"  cand {i}: accepted={ev['accepted']} fails={rec['fails']}", flush=True)
            if ev["accepted"]:
                accepted_i = i; break                                   # rule 3: stop on first full pass
    except DV.DirectedVideoFailure as e:
        err = str(e)
    except Exception as e:
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:500]}"
    finally:
        DV.ALLOW_PAID = False                                           # rule: always reset (timeout/exc/interrupt)

    auth_reset = DV.assert_allow_paid_reset()   # raises if disk or runtime is not False
    eval_spend = round(sum(cost), 2)
    ledger = {"confirmed_video_usd": round(confirmed, 2), "potential_unretrieved_video_usd": round(potential, 2),
              "evaluation_usd": eval_spend, "max_possible_total_usd": round(confirmed + potential + eval_spend, 2),
              "hard_cap_usd": CAP, "within_cap": (confirmed + potential + eval_spend) <= CAP}
    rr = subprocess.run([sys.executable, "bolt_seq/tests/test_regression.py"], capture_output=True, text=True,
                        env={**os.environ, "PYTHONPATH": PROJ})
    out = {"shot": "oxygen_start_end_A", "model": "kling-v3-pro", "rules": {"max_candidates": MAX_CAND, "cap_usd": CAP,
           "stop_after_first_pass": True, "cand1_elements": "OFF", "no_salvage_rewrite_trim_3rd": True, "no_auto_insert": True},
           "accepted_candidate": accepted_i, "error": err, "candidates_run": len(results), "spend_ledger": ledger,
           "allow_paid_disk_after": DV.disk_allow_paid(),          # ACTUAL value (False), not an is-False check
           "allow_paid_runtime_after": DV.ALLOW_PAID, "allow_paid_reset_assertion": auth_reset,
           "inserted_or_published": False, "registry_promoted": False,
           "regression": rr.stdout.strip().splitlines()[-1] if rr.stdout else "",
           "candidates": results,
           "outcome": ("ACCEPTED pending manual review" if accepted_i is not None else
                       ("ERROR" if err else "NO candidate passed — no salvage/rewrite/3rd per rules; returning for review"))}
    json.dump(out, open(os.path.join(AT, "shot_A_start_end_pilot_result.json"), "w"), indent=2, default=str)
    print("\n=== DONE ===")
    for r in results:
        print(f"  cand {r['i']} (elements={'ON' if r['elements'] else 'OFF'}): accepted={r['accepted']} req={r['request_id']} fails={r['fails']}")
    print(f"spend: confirmed ${confirmed:.2f} + potential ${potential:.2f} + eval ${eval_spend:.2f} = ${ledger['max_possible_total_usd']:.2f} (cap ${CAP}) within_cap={ledger['within_cap']}")
    print("accepted:", accepted_i, "| error:", (err or "none")[:150])
    print("regression:", out["regression"], "| ALLOW_PAID disk:", out["allow_paid_on_disk_after"], "runtime:", DV.ALLOW_PAID, "| inserted:", out["inserted_or_published"])


if __name__ == "__main__":
    main()
