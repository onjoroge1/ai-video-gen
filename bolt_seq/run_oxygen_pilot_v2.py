"""AUTHORIZED corrected oxygen pilot (v2). Clean-seed → Kling v3-pro i2v → full production-readiness
gate. Limits: hero block only · ≤2 candidates · $1.40 hard cap incl. evaluation · stop after first
candidate that passes ALL automated production-readiness gates · no retries · no alternate models · no
other blocks · no silent fallback · no automatic insertion · ALLOW_PAID enabled at RUNTIME ONLY.
Run: python3 -m bolt_seq.run_oxygen_pilot_v2"""
import os, sys, json, subprocess, base64, traceback
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C, topics as T
from bolt_seq.character import BOLT
from bolt_seq.providers import directed_video as DV
from PIL import Image

OUT = os.path.join(PROJ, "renders/bolt_seq/_oxygen_pilot"); CAND = os.path.join(OUT, "candidates_v2")
os.makedirs(CAND, exist_ok=True)
SEED = os.path.join(OUT, "clean_seed.png"); EXIT_REF = os.path.join(OUT, "boundary_exit.png")
CAP = 1.40; VCOST = 0.56

PROMPT = (T.load("oxygen_subscription")["directed_hero"]["prompt"] +
    " ABSOLUTELY NO legs, feet, boots, shoes, knees, pelvis, separate lower limbs, or walking anatomy — "
    "Bolt has ONLY one smooth rounded hover-base. NO generated text, numbers, meters, bars, HUD, captions, "
    "gauges or UI of any kind. NO battery icon or screen on its body. NO acrobatic somersaults or flips. "
    "Bolt must NOT pass through or enter the portal — he collapses just short of it.")


def contact_sheet(clip, out_jpg, n=8):
    d = C.dur(clip) or 5.0; tiles = []
    for i in range(n):
        fp = out_jpg + f".{i}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{d*(i+0.5)/n:.2f}", "-i", clip,
                        "-frames:v", "1", "-vf", "scale=216:384", fp], check=True); tiles.append(fp)
    sh = Image.new("RGB", (216 * 4, 384 * 2), (16, 16, 20))
    for i, fp in enumerate(tiles): sh.paste(Image.open(fp), ((i % 4) * 216, (i // 4) * 384))
    sh.save(out_jpg, quality=88); return out_jpg


def entry_boundary(clip, cost):
    """Does the candidate START at the seeded entry state (impaired Bolt near green portal, bubble, no UI)?"""
    import explainer_pipeline as ep
    f0 = os.path.join(CAND, "_efirst.jpg")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-frames:v", "1", "-vf", "scale=360:640", f0], check=True)
    b_cand = base64.b64encode(open(f0, "rb").read()).decode()
    b_seed = base64.b64encode(open(SEED, "rb").read()).decode()
    try:
        r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=200,
            system="Strict boundary auditor.", messages=[{"role": "user", "content": [
                {"type": "text", "text": "REQUIRED ENTRY (reference):"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b_seed}},
                {"type": "text", "text": "CANDIDATE first frame:"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b_cand}},
                {"type": "text", "text": "Does the candidate's first frame START in the same state/composition "
                 "as the reference (same Bolt near the green portal, air bubble present, underwater tunnel)? "
                 "Return ONLY JSON: {\"match\":0-10}"}]}])
        cost.append(ep._msg_cost(r.usage)); o, _ = ep._parse_script_json(r.content[0].text)
        return int((o or {}).get("match", 0))
    except Exception as e:
        return 0


def main():
    cost = []
    spec = {
        "entity": "bolt", "block": "oxy_final_sprint_collapse", "model": "kling-v3-pro",
        "seed_image": SEED, "identity_reference": BOLT["reference"], "identity_bible": BOLT["identity"],
        "anatomy": BOLT["anatomy"], "prompt": PROMPT,
        "phase_contract": {k: T.load("oxygen_subscription")["directed_hero"][k]
                           for k in ("entities", "phases", "prohibited_transitions")},
        "boundary": {"start_frame": SEED, "end_frame": EXIT_REF if os.path.exists(EXIT_REF) else None},
        "budget": {"provider_timeout_s": 600},
    }
    json.dump({k: v for k, v in spec.items() if k != "anatomy"}, open(os.path.join(OUT, "pilot_v2_spec.json"), "w"),
              indent=2, default=str)
    print("=== CORRECTED PILOT (clean seed, v3-pro, ≤2 cand, $1.40 cap) ===", flush=True)

    DV.ALLOW_PAID = True                        # RUNTIME ONLY
    adapter = DV.FalKlingAdapter(); video_spent = 0.0; results = []; accepted = None; err = None
    try:
        for i in range(2):
            total = video_spent + sum(cost)
            if total + VCOST + 0.15 > CAP:
                print(f"  budget stop before cand {i}: total ${total:.2f} + ${VCOST} would risk cap ${CAP}")
                break
            raw = os.path.join(CAND, f"cand_{i}_raw.mp4"); norm = os.path.join(CAND, f"cand_{i}.mp4")
            print(f"  submitting candidate {i} (v3-pro, clean seed)...", flush=True)
            job = adapter.submit(spec, 600); adapter.poll_and_download(job, raw, 600)
            DV._normalize_media(raw, norm); video_spent += VCOST
            pr = DV.production_readiness(norm, spec, boundary=spec["boundary"], cost=cost, log=print)
            eb = entry_boundary(norm, cost)
            pr["flags"]["entry_boundary_pass"] = eb >= 7
            auto = ["technical_pass", "motion_pass", "identity_pass", "equipment_pass", "clean_plate_pass",
                    "entry_boundary_pass"]
            auto_ok = all(pr["flags"].get(k) is True for k in auto)
            cs = contact_sheet(norm, os.path.join(CAND, f"cand_{i}_contact.jpg"))
            rec = {"i": i, "raw": raw, "clip": norm, "contact_sheet": cs, "entry_boundary": eb,
                   "flags": pr["flags"], "anatomy": pr["anatomy"], "clean_plate": pr["clean_plate"],
                   "motion": pr["motion"], "auto_production_ready": auto_ok, "reasons": pr["reasons"]}
            results.append(rec)
            print(f"  cand {i}: auto_production_ready={auto_ok} flags={pr['flags']} entry={eb}", flush=True)
            if auto_ok:
                accepted = i; break
    except DV.DirectedVideoFailure as e:
        err = str(e)
    except Exception as e:
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:600]}"
    finally:
        DV.ALLOW_PAID = False                    # revert; one pilot, no automatic continuation

    total_spend = round(video_spent + sum(cost), 2)
    out = {"model": "kling-v3-pro", "accepted_candidate": accepted, "error": err,
           "candidates_generated": len(results), "video_spend_usd": round(video_spent, 2),
           "eval_spend_usd": round(sum(cost), 2), "total_spend_usd": total_spend, "cap_usd": CAP,
           "inserted_into_short": False, "allow_paid_on_disk": DV.ALLOW_PAID,
           "note": "STOP for manual review — exit_integration_pass + manual_review_pass are human; nothing inserted.",
           "candidates": results}
    json.dump(out, open(os.path.join(OUT, "pilot_v2_result.json"), "w"), indent=2, default=str)
    print(f"\n=== PILOT v2 DONE === accepted={accepted} | generated={len(results)} | "
          f"video ${video_spent:.2f} + eval ${sum(cost):.2f} = ${total_spend} (cap ${CAP})")
    if err: print("outcome:", err[:300])
    for r in results:
        print(f"  cand {r['i']}: auto_ready={r['auto_production_ready']} | {r['flags']} | reasons={r['reasons'][:2]}")
    print("STOPPED for manual review — not inserted into any Short. ALLOW_PAID on disk:", DV.ALLOW_PAID)


if __name__ == "__main__":
    main()
