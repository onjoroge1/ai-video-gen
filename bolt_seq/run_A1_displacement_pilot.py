"""A1 DISPLACEMENT VALIDATION — one isolated corrective pilot. Tests whether Kling v3-pro realizes a
MATERIALLY LARGER authored screen-space displacement (~0.14-0.16) for the A1 launch while preserving the
validated world/identity/anatomy/camera/terminal. Preserves everything else; does NOT touch A2/A3 or compile
the sequence. Authors a revised A1 END boundary (larger forward displacement, same pose as start so the
measured translation is clean), verifies the boundary BEFORE spending, dry-runs the evaluator, then runs
<=2 Kling candidates (cap $1.00, stop-after-first-pass). Adds realized_displacement_ratio + progressive-motion
diagnostics to the trajectory report. ALLOW_PAID try/finally + assert. Nothing inserted/promoted.
Run: python3 -m bolt_seq.run_A1_displacement_pilot        (paid)
     DRY=1 python3 -m bolt_seq.run_A1_displacement_pilot  (no spend)"""
import os, sys, json, subprocess, traceback
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
import numpy as np
from PIL import Image, ImageDraw
from bolt_seq.providers import directed_video as DV
from bolt_seq import prepare_oxygen_shot_A_primitives as P
from bolt_seq import run_primitive_chain_pilot as R

AT = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/atomic_shots")
OUT = os.path.join(AT, "a1_displacement"); os.makedirs(OUT, exist_ok=True)
W, H, TERM_LEFT = P.W, P.H, P.TERM_LEFT
CAP, VCOST, EVAL_EST, MAXC, TIMEOUT = 1.00, 0.336, 0.15, 2, 600
DRY = os.environ.get("DRY") == "1"
PROMPT = ("The mascot robot Bolt in a dark dry oxygen corridor, LOCKED STATIC CAMERA, preserve the wall "
          "signage. Bolt " + P.MP.primitive("launch")["prompt"])
NEG = open(os.path.join(AT, "shot_A_negative_prompt_v2.txt")).read().strip()


def author_boundary():
    """Revised A1 pair: SAME pose (hover_run) for start+end so measured centroid displacement is pure
    translation (no pose-morph confound). Start = upright, no plume, left. End = forward lean + strong plume,
    shifted right by ~0.145. Returns paths + authored displacement + boundary self-checks."""
    b0 = P.author_frame("A1disp_B0.png", P.POSE_REACH, gap=0.250, center=0.50, tilt=2, thruster="none")
    b1 = P.author_frame("A1disp_B1v2.png", P.POSE_REACH, gap=0.090, center=0.50, tilt=12, thruster="strong")  # authored disp ~0.155 (65% => 0.10 net)
    def cx(bb): return (bb[0] + bb[2]) / 2 / W
    def edge(bb): return bb[2] / W
    def hgt(bb): return bb[3] - bb[1]
    auth_centroid = round(cx(b1["bbox"]) - cx(b0["bbox"]), 4)
    auth_edge = round(edge(b1["bbox"]) - edge(b0["bbox"]), 4)
    scale_ratio = round(hgt(b1["bbox"]) / hgt(b0["bbox"]), 3)
    checks = {"authored_displacement_ge_0.14": auth_centroid >= 0.14,
              "scale_within_5pct": 0.95 <= scale_ratio <= 1.05,
              "no_terminal_overlap": edge(b1["bbox"]) < TERM_LEFT,
              "distinct_centroid_and_edge": auth_centroid >= 0.10 and auth_edge >= 0.10,
              "no_altitude_substitute": abs(((b1["bbox"][1] + b1["bbox"][3]) / 2 / H) - ((b0["bbox"][1] + b0["bbox"][3]) / 2 / H)) <= 0.03}
    return {"b0": b0, "b1": b1, "authored_centroid_disp": auth_centroid, "authored_edge_disp": auth_edge,
            "scale_ratio": scale_ratio, "checks": checks, "boundary_ok": all(checks.values())}


def displacement_diag(clip, authored_disp, tracker=None):
    tk = tracker or DV.bolt_tracker(clip)
    det = [s for s in tk["samples"] if s.get("cx") is not None]
    cx = [s["cx"] for s in det]; gaps = [s.get("edge_gap") for s in det if s.get("edge_gap") is not None]
    steps = [cx[i + 1] - cx[i] for i in range(len(cx) - 1)]
    net = round(cx[-1] - cx[0], 4) if len(cx) >= 2 else 0.0
    ratio = round(net / authored_disp, 3) if authored_disp else 0.0
    idle = round(sum(1 for d in steps if abs(d) < 0.004) / max(1, len(steps)), 3)
    reversals = sum(1 for d in steps if d < -0.02); max_back = round(min([0.0] + steps), 4)
    nearer = (gaps[-1] <= gaps[0] - 0.08) if len(gaps) >= 2 else False
    i60 = int(0.6 * len(cx)); prog_by60 = round(cx[i60] - cx[0], 4) if len(cx) > i60 else 0.0
    progressive = net > 0 and prog_by60 >= 0.4 * net                    # not a final-frame pose morph
    return {"authored_forward_displacement": authored_disp, "measured_net_forward": net,
            "realized_displacement_ratio": ratio, "idle_fraction": idle, "reversals": reversals,
            "max_backward_step": max_back, "finishes_nearer_terminal": bool(nearer),
            "displacement_by_60pct": prog_by60, "progressive_motion": bool(progressive), "cx_series": [round(x, 4) for x in cx],
            "edge_series": [round(s["bolt_bbox"][2] / W, 4) for s in det if s.get("bolt_bbox")]}


def accept_A1_disp(clip, end_frame, authored_disp, cost):
    common = R.common_gates(clip, cost)
    tk = DV.bolt_tracker(clip)
    pp = DV.propulsion_presence_gate(clip, tracker=tk)
    pvc = DV.propulsion_velocity_coupling_gate(clip, tracker=tk)
    er = DV.endpoint_realization_gate(clip, end_frame, tracker=tk)
    dd = displacement_diag(clip, authored_disp, tracker=tk)
    disp_checks = {"authored_ge_0.14": authored_disp >= 0.14, "measured_net_ge_0.10": dd["measured_net_forward"] >= 0.10,
                   "realized_ratio_ge_0.65": dd["realized_displacement_ratio"] >= 0.65, "idle_le_0.35": dd["idle_fraction"] <= 0.35,
                   "no_meaningful_reversal": dd["reversals"] == 0, "finishes_nearer_terminal": dd["finishes_nearer_terminal"],
                   "progressive_motion": dd["progressive_motion"]}
    prim = {"visible_propulsion": bool(pp["pass"]), "propulsion_coupled": bool(pvc["coupled"]), "endpoint_realization": bool(er["pass"])}
    accepted = common["all_pass"] and all(prim.values()) and all(disp_checks.values())
    fails = ([k for k, v in common["checks"].items() if not v] + [k for k, v in prim.items() if not v]
             + [k for k, v in disp_checks.items() if not v])
    return {"accepted": bool(accepted), "common": common["checks"], "primitive": prim, "displacement": disp_checks,
            "displacement_diag": dd, "fails": fails, "reports": {**common["reports"], "propulsion_presence": pp,
            "propulsion_velocity_coupling": pvc, "endpoint_realization": er}}


def traj_plot(dd, out):
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        cx = dd["cx_series"]; ed = dd["edge_series"]; t = list(range(len(cx)))
        fig, ax = plt.subplots(figsize=(8, 4.2))
        ax.plot(t, cx, "-o", label="Bolt centroid x"); ax.plot(range(len(ed)), ed, "-o", label="reaching edge x")
        ax.set_title(f"A1 displacement — authored {dd['authored_forward_displacement']} measured {dd['measured_net_forward']} "
                     f"ratio {dd['realized_displacement_ratio']} idle {dd['idle_fraction']} prog {dd['progressive_motion']}")
        ax.set_xlabel("frame"); ax.set_ylabel("fraction of frame"); ax.legend(); ax.grid(alpha=0.3); fig.tight_layout(); fig.savefig(out, dpi=110); plt.close()
    except Exception as e:
        open(out.replace(".png", ".txt"), "w").write(str(dd))


def main():
    bnd = author_boundary()
    b0d = bnd["b0"]["display"]; b1d = bnd["b1"]["display"]
    a, b = Image.open(b0d).convert("RGB").resize((330, 586)), Image.open(b1d).convert("RGB").resize((330, 586))
    sh = Image.new("RGB", (680, 616), (12, 12, 14)); d = ImageDraw.Draw(sh)
    sh.paste(a, (0, 26)); sh.paste(b, (350, 26)); d.text((6, 6), "A1 START (B0)", fill=(200, 220, 255))
    d.text((356, 6), f"A1 END v2 (+{bnd['authored_centroid_disp']})", fill=(160, 230, 160))
    sh.save(os.path.join(OUT, "A1_revised_start_end.jpg"), quality=90)
    print("boundary:", {k: bnd[k] for k in ("authored_centroid_disp", "authored_edge_disp", "scale_ratio", "boundary_ok")}, bnd["checks"])
    if not bnd["boundary_ok"]:
        json.dump({"status": "A1_BOUNDARY_FAILURE", "boundary": bnd}, open(os.path.join(AT, "a1_displacement_result.json"), "w"), indent=2, default=str)
        print("STATUS: A1_BOUNDARY_FAILURE (revised boundary did not meet its own spec — not spending)"); return

    if DRY:
        cost = []
        ev = accept_A1_disp(os.path.join(AT, "start_end_candidates", "c0.mp4"), b1d, bnd["authored_centroid_disp"], cost)
        print("DRY eval OK — no crash | accepted", ev["accepted"], "fails", ev["fails"], "| VLM $%.2f" % sum(cost), "| ALLOW_PAID", DV.ALLOW_PAID)
        return

    cost = []; confirmed = 0.0; potential = 0.0; results = []; err = None; status = None; accepted_clip = None
    DV.ALLOW_PAID = True
    try:
        adapter = DV.FalKlingAdapter()
        spec = {"model": "kling-v3-pro", "seed_image": b0d, "end_image": b1d, "prompt": PROMPT, "negative_prompt": NEG,
                "cfg_scale": 0.6, "generate_audio": False, "duration": "3", "use_elements": False}
        for cand in range(MAXC):
            spent = confirmed + potential + sum(cost)
            if spent + VCOST + EVAL_EST > CAP:
                err = f"BUDGET STOP before cand{cand}: ${spent:.2f}+${VCOST}+${EVAL_EST} > ${CAP}"; status = "EXECUTION_ERROR"; break
            raw = os.path.join(OUT, f"c{cand}_raw.mp4"); norm = os.path.join(OUT, f"c{cand}.mp4")
            print(f"submitting A1-disp cand{cand} (3s)...", flush=True)
            potential += VCOST
            job = adapter.submit(spec, TIMEOUT); adapter.poll_and_download(job, raw, TIMEOUT)
            confirmed += VCOST; potential -= VCOST
            DV._normalize_media(raw, norm)
            ev = accept_A1_disp(norm, b1d, bnd["authored_centroid_disp"], cost)
            R.contact_sheet(norm, os.path.join(OUT, f"c{cand}_contact.jpg"))
            traj_plot(ev["displacement_diag"], os.path.join(OUT, f"c{cand}_trajectory.png"))
            rec = {"cand": cand, "request_id": job.get("request_id"), "endpoint": job.get("endpoint"),
                   "submit_status": job.get("submit_status"), "submitted_payload_sanitized": job.get("submitted_payload_sanitized"),
                   "raw_response": job.get("raw_response"), "raw": raw, "norm": norm, "accepted": ev["accepted"],
                   "common": ev["common"], "primitive": ev["primitive"], "displacement": ev["displacement"],
                   "displacement_diag": ev["displacement_diag"], "fails": ev["fails"]}
            results.append(rec)
            json.dump(ev["reports"], open(os.path.join(OUT, f"c{cand}_gates.json"), "w"), indent=2, default=str)
            print(f"  cand{cand}: accepted={ev['accepted']} net={ev['displacement_diag']['measured_net_forward']} "
                  f"ratio={ev['displacement_diag']['realized_displacement_ratio']} idle={ev['displacement_diag']['idle_fraction']} "
                  f"prog={ev['displacement_diag']['progressive_motion']} fails={ev['fails']}", flush=True)
            if ev["accepted"]:
                accepted_clip = norm; status = "A1_DISPLACEMENT_PASS"; break
        if status is None:
            # both candidates ran and failed → classify boundary-good so it's a provider translation failure
            movement_ever = any(r["displacement_diag"]["measured_net_forward"] >= 0.10 for r in results)
            status = "A1_PROVIDER_TRANSLATION_FAILURE" if not movement_ever else "A1_PROVIDER_TRANSLATION_FAILURE"
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
    rr = subprocess.run([sys.executable, "bolt_seq/tests/test_regression.py"], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": PROJ})
    out = {"objective": "a1_displacement_validation", "status": status or "EXECUTION_ERROR", "error": err,
           "boundary": {k: bnd[k] for k in ("authored_centroid_disp", "authored_edge_disp", "scale_ratio", "checks", "boundary_ok")},
           "spend_ledger": ledger, "allow_paid_disk_after": DV.disk_allow_paid(), "allow_paid_runtime_after": DV.ALLOW_PAID,
           "allow_paid_reset_assertion": auth, "inserted_into_short": False, "registry_promoted": False,
           "candidates": results, "regression": rr.stdout.strip().splitlines()[-1] if rr.stdout else ""}
    json.dump(out, open(os.path.join(AT, "a1_displacement_result.json"), "w"), indent=2, default=str)
    print("\n=== A1 DISPLACEMENT PILOT ===")
    for r in results:
        dd = r["displacement_diag"]
        print(f"  cand{r['cand']}: accepted={r['accepted']} req={r['request_id']} net={dd['measured_net_forward']} ratio={dd['realized_displacement_ratio']} idle={dd['idle_fraction']} prog={dd['progressive_motion']} fails={r['fails']}")
    print(f"spend: confirmed ${confirmed:.2f} + potential ${potential:.2f} + eval ${eval_spend:.2f} = ${ledger['max_total_usd']:.2f} (cap ${CAP}) within={ledger['within_cap']}")
    print(f"STATUS: {out['status']} | ALLOW_PAID disk={out['allow_paid_disk_after']} runtime={DV.ALLOW_PAID} | regression {out['regression']} | inserted {out['inserted_into_short']}")
    if err: print("note:", err[:200])


if __name__ == "__main__":
    main()
