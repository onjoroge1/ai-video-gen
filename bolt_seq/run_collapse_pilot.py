"""AUTHORIZED Shot-B atomic-collapse pilot. Kling v3-pro, seed=collapse_seed.png, <=2 candidates, $1.40
all-in cap, stop after first FULL pass. Every candidate must pass ALL automated gates (technical, anatomy,
clean-plate, atomic-collapse motion, portal proximity, no-recovery, start boundary, exit boundary) with no
reject-immediately flag; manual review is the final human gate. No auto-insert, no fallback model, no
respend. If NEITHER candidate passes → STOP (do NOT salvage with a deterministic cutout, do NOT spend
again without a new review). ALLOW_PAID enabled at RUNTIME ONLY.
Run: python3 -m bolt_seq.run_collapse_pilot"""
import os, sys, json, subprocess, traceback
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C, topics as T
from bolt_seq.character import BOLT
from bolt_seq.providers import directed_video as DV
from PIL import Image

P = os.path.join(PROJ, "renders/bolt_seq/_oxygen_pilot"); CP = os.path.join(P, "collapse_pilot")
CAND = os.path.join(CP, "candidates"); os.makedirs(CAND, exist_ok=True)
SEED = os.path.join(CP, "collapse_seed.png"); ENDT = os.path.join(CP, "collapse_end_target.png")
CAP, VCOST, TRIM = 1.40, 0.56, 2.0
TECH = {"dur_min": 1.4, "dur_max": 2.4}   # atomic collapse is a short clip (Kling 5s → trimmed to ~2s)

PROMPT = (
    "A single continuous shot, floor-level angle in a dim underwater tunnel. This is the INSTANT AFTER "
    "POWER FAILURE — the small white-and-mint robot Bolt is ALREADY WEAK in the very first frame, hovering "
    "feebly just above the floor on its SINGLE rounded hover-base, thruster sputtering and dying. The "
    "hover-thrust cuts out; Bolt drops straight DOWN, his body tips FORWARD, he hits the floor with a small "
    "impact and a slight slide, and stays COLLAPSED and motionless, prone. A small green portal glows far "
    "in the BACKGROUND, out of reach — Bolt never approaches or touches it and collapses well short of it. "
    "Keep Bolt IDENTICAL throughout: one rounded hover-base (NO legs, NO feet, NO boots, NO separate lower "
    "limbs), mint accents, glossy visor with two cyan eyes, one antenna, two rounded arms, plain cyan chest "
    "with NO text or labels. Do NOT fly toward or touch the portal; the portal must NOT push or pull him; NO "
    "recovery, NO getting back up, NO heroic relaunch, NO somersaults, NO walking or crawling, NO camera "
    "reset, NO on-screen text/meter/HUD/UI. He must NOT start energetic or healthy — he is already failing. "
    "Premium 3D cartoon render.")


def contact_sheet(clip, out, n=8):
    d = C.dur(clip) or TRIM; sh = Image.new("RGB", (216 * 4, 384 * 2), (16, 16, 20))
    for i in range(n):
        fp = out + f".{i}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{d*(i+0.5)/n:.2f}", "-i", clip, "-frames:v", "1", "-vf", "scale=216:384", fp], check=True)
        sh.paste(Image.open(fp), ((i % 4) * 216, (i // 4) * 384))
    sh.save(out, quality=88); return out


def gate(clip, cost, log):
    """Full automated gate battery for a candidate. Returns (all_pass, flags, detail)."""
    frames = DV._frames(clip, 9, CAND)
    tg = DV.technical_gate(clip, TECH, {"motion_direction": "stationary"})
    an = DV.check_anatomy(clip, {"identity_reference": BOLT["reference"], "anatomy": BOLT["anatomy"]}, frames=frames, cost=cost)
    dh = T.load("oxygen_subscription")["directed_hero"]["shot_b_atomic_collapse"]
    spec = {"identity_bible": BOLT["identity"], "anatomy": BOLT["anatomy"],
            "phase_contract": {"entities": dh["entities"], "phases": dh["phases"], "prohibited_transitions": []}}
    tv = DV.trace_vlm(clip, dh["entities"], frames, cost=cost)
    traces = DV._traces(tv) if "error" not in tv else []
    anatomy_bad = set(an.get("prohibited_frames", []) + an.get("altered_frames", []))
    mot = DV.evaluate_phased(clip, spec, traces=traces or None, anatomy_bad=anatomy_bad, tech=TECH, cost=cost, log=log)
    rev = DV.collapse_review_vlm(clip, SEED, ENDT, frames, cost=cost)
    flags = {
        "technical": tg["pass"],
        "anatomy": an["identity_pass"] and not rev.get("morph_or_redesign"),
        "clean_plate": not rev.get("ui_seen"),
        "atomic_collapse_motion": mot.get("phase_motion_pass") and bool(rev.get("drops_and_collapses")),
        "portal_proximity": (not rev.get("reaches_or_touches_portal")) and bool(rev.get("bolt_short_of_portal"))
                            and (not rev.get("pushed_or_pulled_by_portal")),
        "no_recovery": (not rev.get("recovers_or_gets_up")) and (not rev.get("heroic_relaunch")),
        "start_boundary": bool(rev.get("starts_weak")) and (rev.get("start_matches_seed", 0) >= 7),
        "exit_boundary": bool(rev.get("end_clearly_collapsed")) and (rev.get("end_matches_target", 0) >= 7),
        "no_walking": not rev.get("walking_or_crawling"),
        "no_camera_reset": not rev.get("camera_reset"),
    }
    all_pass = all(flags.values())
    detail = {"technical": tg["reasons"], "anatomy": {"pass": an["identity_pass"], "features": an.get("features"),
              "frames": sorted(anatomy_bad)}, "motion": mot.get("reasons"), "review": rev,
              "flags": flags}
    return all_pass, flags, detail


def main():
    cost = []
    spec = {"model": "kling-v3-pro", "seed_image": SEED, "prompt": PROMPT,
            "budget": {"provider_timeout_s": 600}}
    print("=== SHOT-B ATOMIC-COLLAPSE PILOT (v3-pro, <=2 cand, $1.40 cap, stop-after-first-pass) ===", flush=True)
    DV.ALLOW_PAID = True                          # RUNTIME ONLY
    adapter = DV.FalKlingAdapter(); video_spent = 0.0; results = []; accepted = None; err = None
    try:
        for i in range(2):
            total = video_spent + sum(cost)
            if total + VCOST + 0.14 > CAP:
                print(f"  budget stop before cand {i}: total ${total:.2f} + ${VCOST} risks cap ${CAP}"); break
            raw = os.path.join(CAND, f"cand_{i}_raw.mp4"); norm = os.path.join(CAND, f"cand_{i}.mp4")
            print(f"  submitting candidate {i} (v3-pro, collapse seed)...", flush=True)
            job = adapter.submit(spec, 600); adapter.poll_and_download(job, raw, 600); video_spent += VCOST
            # Kling min 5s → trim to the atomic collapse window (~2s) + normalize
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-t", f"{TRIM}",
                            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30", "-an", norm], check=True)
            all_pass, flags, detail = gate(norm, cost, print)
            cs = contact_sheet(norm, os.path.join(CAND, f"cand_{i}_contact.jpg"))
            results.append({"i": i, "raw": raw, "clip": norm, "contact_sheet": cs, "all_pass": all_pass,
                            "flags": flags, "detail": detail})
            print(f"  cand {i}: all_pass={all_pass} flags={flags}", flush=True)
            if all_pass:
                accepted = i; break                # stop immediately after first full pass
    except DV.DirectedVideoFailure as e:
        err = str(e)
    except Exception as e:
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:600]}"
    finally:
        DV.ALLOW_PAID = False

    total_spend = round(video_spent + sum(cost), 2)
    out = {"shot": "B atomic collapse", "model": "kling-v3-pro", "accepted_candidate": accepted, "error": err,
           "candidates_generated": len(results), "video_spend_usd": round(video_spent, 2),
           "eval_spend_usd": round(sum(cost), 2), "total_spend_usd": total_spend, "cap_usd": CAP,
           "inserted": False, "allow_paid_on_disk": DV.ALLOW_PAID,
           "go_no_go": ("ACCEPTED pending manual review" if accepted is not None else
                        "NO candidate passed — STOP: no deterministic salvage, no respend without new review"),
           "candidates": results}
    json.dump(out, open(os.path.join(CP, "collapse_pilot_result.json"), "w"), indent=2, default=str)
    print(f"\n=== DONE === accepted={accepted} | generated={len(results)} | "
          f"video ${video_spent:.2f} + eval ${sum(cost):.2f} = ${total_spend} (cap ${CAP})")
    if err: print("outcome:", err[:300])
    for r in results:
        fails = [k for k, v in r["flags"].items() if not v]
        print(f"  cand {r['i']}: all_pass={r['all_pass']} | fails={fails}")
    print("go/no-go:", out["go_no_go"], "| ALLOW_PAID on disk:", DV.ALLOW_PAID)


if __name__ == "__main__":
    main()
