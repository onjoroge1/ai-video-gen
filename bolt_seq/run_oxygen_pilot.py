"""AUTHORIZED PAID PILOT — oxygen final-sprint-and-collapse hero block ONLY. Kling v3-pro, <=3 candidates,
$2.00 hard cap (generation + evaluation), stop after first passing candidate, no retries, no alternate
models, no other blocks, NO silent deterministic fallback. Enables paid mode at RUNTIME ONLY (the on-disk
ALLOW_PAID stays False → no lingering enablement, no automatic Phase-3 continuation). After it runs it
STOPS: the accepted clip (if any) is NOT inserted into any Short — it is presented for manual review.
Run: python3 -m bolt_seq.run_oxygen_pilot"""
import os, sys, json, subprocess, traceback
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq.providers import directed_video as DV
from bolt_seq import compiler as C
from PIL import Image

OUT = os.path.join(PROJ, "renders/bolt_seq/_oxygen_pilot")
CAND = os.path.join(OUT, "candidates"); os.makedirs(CAND, exist_ok=True)

HERO_PROMPT = (
    "A single continuous 5-second shot inside an underwater tunnel. The small white-and-mint robot Bolt, "
    "already impaired and buckling, makes one last desperate forward lunge to the RIGHT toward a glowing "
    "green oxygen portal ring. His final air bubble shrinks and pops, vanishing. Out of oxygen, he "
    "collapses — body slumping and sinking — coming to rest close to the portal. Keep Bolt IDENTICAL "
    "throughout (matte-white body, mint accents, glossy black visor with two glowing cyan eyes, single "
    "hover-base, thin antenna). Do NOT reverse direction, do NOT let a second robot or character appear, "
    "do NOT teleport, do NOT reset the scene. Premium 3D cartoon render, no text.")


def contact_sheet(clip, out_jpg, n=8):
    d = C.dur(clip) or 5.0
    tiles = []
    for i in range(n):
        fp = out_jpg + f".{i}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{d*(i+0.5)/n:.2f}", "-i", clip,
                        "-frames:v", "1", "-vf", "scale=216:384", fp], check=True)
        tiles.append(fp)
    sheet = Image.new("RGB", (216 * 4, 384 * 2), (16, 16, 20))
    for i, fp in enumerate(tiles):
        sheet.paste(Image.open(fp), ((i % 4) * 216, (i // 4) * 384))
    sheet.save(out_jpg, quality=88)
    return out_jpg


def main():
    cost = []
    spec = json.load(open(os.path.join(OUT, "pilot_spec.json")))
    spec["prompt"] = HERO_PROMPT
    spec["model"] = "kling-v3-pro"
    spec.setdefault("budget", {}).update({"candidate_cost_usd": 0.56, "max_video_cost_usd": 2.0,
                                          "max_block_cost_usd": 2.0, "max_candidates": 3,
                                          "stop_after_first_pass": True, "reuse_cached": False,
                                          "retry_ceiling": 0, "eval_cost_usd_est": 0.06})
    print("=== AUTHORIZED PAID PILOT: oxygen final-sprint-and-collapse ===", flush=True)
    print(f"model=kling-v3-pro | cap=${spec['budget']['max_video_cost_usd']} | candidates<=3 | stop-after-first-pass", flush=True)

    DV.ALLOW_PAID = True          # RUNTIME ONLY — on-disk default stays False
    accepted, err = None, None
    try:
        accepted = DV.generate(spec, DV.FalKlingAdapter(), CAND, cost=cost, log=print)
    except DV.DirectedVideoFailure as e:
        err = str(e)
    except Exception as e:
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:800]}"
    finally:
        DV.ALLOW_PAID = False     # revert immediately; one pilot only, no automatic continuation

    # build contact sheets + collect per-candidate evidence for MANUAL REVIEW (no insertion)
    cands = []
    for i in range(3):
        clip = os.path.join(CAND, f"cand_{i}.mp4"); ev = os.path.join(CAND, f"cand_{i}_eval.json")
        if not os.path.exists(clip):
            continue
        cs = contact_sheet(clip, os.path.join(CAND, f"cand_{i}_contact.jpg"))
        evj = json.load(open(ev)) if os.path.exists(ev) else {}
        cands.append({"i": i, "clip": clip, "raw": os.path.join(CAND, f"cand_{i}_raw.mp4"), "contact_sheet": cs,
                      "pass": evj.get("pass"), "reasons": evj.get("reasons"), "scores": evj.get("scores"),
                      "trajectory": evj.get("trajectory"), "flow": evj.get("flow"),
                      "start_frame_match": (evj.get("scores") or {}).get("start_frame_match"),
                      "end_frame_match": (evj.get("scores") or {}).get("end_frame_match")})

    rep_path = os.path.join(CAND, "accepted_report.json") if accepted else os.path.join(CAND, "rejection_report.json")
    spent = json.load(open(rep_path)).get("spent_usd") if os.path.exists(rep_path) else round(sum(cost), 2)
    result = {"model": "kling-v3-pro", "accepted": accepted, "error": err,
              "candidates_generated": len(cands), "total_spend_usd": spent,
              "candidates": cands, "inserted_into_short": False,
              "note": "STOPPED for manual review — accepted clip NOT inserted. On-disk ALLOW_PAID=False."}
    json.dump(result, open(os.path.join(OUT, "pilot_result.json"), "w"), indent=2, default=str)
    print(f"\n=== PILOT DONE === accepted={bool(accepted)} | candidates={len(cands)} | spend=${spent}")
    if err:
        print("outcome:", err[:300])
    for c in cands:
        print(f"  cand {c['i']}: pass={c['pass']} sfm={c['start_frame_match']} efm={c['end_frame_match']} "
              f"dir={(c.get('trajectory') or {}).get('direction')} | {(c.get('reasons') or ['accepted'])[:2]}")
    print("STOPPED for manual review — not inserted into any Short.")


if __name__ == "__main__":
    main()
