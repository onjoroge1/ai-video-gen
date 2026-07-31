"""Resume the authorized Shot-A pilot after an evaluator bug (camera_model_gate missing an import). The
already-PAID candidate 0 is re-evaluated with NO new spend; if it fails, the run continues within the same
authorization (<=3 candidates total, $2.00 all-in cap, stop-after-first-pass). ALLOW_PAID try/finally.
Run: python3 -m bolt_seq.resume_shot_A"""
import os, sys, json, subprocess, traceback
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq.providers import directed_video as DV
import bolt_seq.run_shot_A_pilot as R

AT = R.AT; CAND = R.CAND; CAP, VCOST, EVAL_EST = R.CAP, R.VCOST, R.EVAL_EST


def main():
    cost = []; results = []; accepted = None; err = None
    confirmed = 0.56; potential = 0.0   # candidate 0 already generated + retrieved before the crash
    spec = {"model": "kling-v3-pro", "seed_image": R.SEED, "prompt": R.PROMPT, "budget": {"provider_timeout_s": 600}}

    # 1) re-evaluate the already-paid candidate 0 (NO new spend)
    raw0 = os.path.join(CAND, "shotA_cand_0_raw.mp4"); norm0 = os.path.join(CAND, "shotA_cand_0.mp4")
    if os.path.exists(norm0):
        print("re-evaluating already-paid candidate 0 (no new spend)...", flush=True)
        try:
            ok, G, reports = R.evaluate(raw0, norm0, cost, print)
            R.contact_sheet(norm0, os.path.join(CAND, "shotA_cand_0_raw_contact.jpg"))
            R.contact_sheet(reports["wclip"], os.path.join(CAND, "shotA_cand_0_win_contact.jpg"))
            fails = [k for k, v in G.items() if not v]
            results.append({"i": 0, "raw": raw0, "norm": norm0, "window": reports["window"], "wclip": reports["wclip"],
                            "gate_matrix": G, "fails": fails, "automated_pass": ok, "reports": reports})
            print(f"  cand 0: automated_pass={ok} fails={fails}", flush=True)
            if ok:
                accepted = 0
        except Exception as e:
            err = f"re-eval cand0: {type(e).__name__}: {e}\n{traceback.format_exc()[:400]}"

    # 2) if cand 0 didn't pass, continue the authorized run for candidates 1..2 within the cap
    if accepted is None and err is None:
        DV.ALLOW_PAID = True
        try:
            adapter = DV.FalKlingAdapter()
            for i in (1, 2):
                spent = confirmed + sum(cost)
                if spent + VCOST + EVAL_EST > CAP:
                    print(f"  BUDGET STOP before cand {i}: ${spent:.2f}+${VCOST}+${EVAL_EST} would exceed cap ${CAP}"); break
                raw = os.path.join(CAND, f"shotA_cand_{i}_raw.mp4"); norm = os.path.join(CAND, f"shotA_cand_{i}.mp4")
                print(f"  submitting candidate {i}...", flush=True)
                potential += VCOST
                job = adapter.submit(spec, 600); adapter.poll_and_download(job, raw, 600)
                confirmed += VCOST; potential -= VCOST
                DV._normalize_media(raw, norm)
                ok, G, reports = R.evaluate(raw, norm, cost, print)
                R.contact_sheet(norm, os.path.join(CAND, f"shotA_cand_{i}_raw_contact.jpg"))
                R.contact_sheet(reports["wclip"], os.path.join(CAND, f"shotA_cand_{i}_win_contact.jpg"))
                fails = [k for k, v in G.items() if not v]
                results.append({"i": i, "raw": raw, "norm": norm, "window": reports["window"], "wclip": reports["wclip"],
                                "gate_matrix": G, "fails": fails, "automated_pass": ok, "reports": reports})
                print(f"  cand {i}: automated_pass={ok} fails={fails}", flush=True)
                if ok:
                    accepted = i; break
        except DV.DirectedVideoFailure as e:
            err = str(e)
        except Exception as e:
            err = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:400]}"
        finally:
            DV.ALLOW_PAID = False

    eval_spend = round(sum(cost), 2)
    ledger = {"confirmed_video_usd": round(confirmed, 2), "potential_unretrieved_video_usd": round(potential, 2),
              "evaluation_usd": eval_spend, "max_possible_total_usd": round(confirmed + potential + eval_spend, 2),
              "hard_cap_usd": CAP, "within_cap": (confirmed + potential + eval_spend) <= CAP,
              "note": "candidate 0 ($0.56) was generated+retrieved before the evaluator bug; re-evaluated with no new spend"}
    rr = subprocess.run([sys.executable, "bolt_seq/tests/test_regression.py"], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": PROJ})
    out = {"shot": "oxygen_dry_approach_A", "model": "kling-v3-pro", "accepted_candidate": accepted, "error": err,
           "candidates_evaluated": len(results), "spend_ledger": ledger,
           "allow_paid_on_disk_after": R._disk_allow_paid(), "allow_paid_runtime_after": DV.ALLOW_PAID,
           "inserted_or_published": False, "regression": rr.stdout.strip().splitlines()[-1] if rr.stdout else "",
           "candidates": [{k: v for k, v in r.items() if k != "reports"} for r in results],
           "detail": [r["reports"] for r in results],
           "outcome": ("ACCEPTED pending manual review" if accepted is not None else
                       ("ERROR" if err else "NO candidate passed — no salvage, no respend, no substitution"))}
    json.dump(out, open(os.path.join(AT, "shot_A_pilot_result.json"), "w"), indent=2, default=str)
    print(f"\n=== DONE === accepted={accepted} | evaluated={len(results)} | confirmed ${confirmed:.2f} + "
          f"potential ${potential:.2f} + eval ${eval_spend:.2f} = max ${ledger['max_possible_total_usd']:.2f} (cap ${CAP})")
    for r in results:
        print(f"  cand {r['i']}: pass={r['automated_pass']} fails={r['fails']}")
    if err: print("error:", err[:200])
    print("regression:", out["regression"], "| ALLOW_PAID disk:", out["allow_paid_on_disk_after"], "runtime:", DV.ALLOW_PAID, "| inserted:", out["inserted_or_published"])


if __name__ == "__main__":
    main()
