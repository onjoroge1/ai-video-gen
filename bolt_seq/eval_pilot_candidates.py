"""Re-evaluate the ALREADY-GENERATED (already-paid) pilot candidates through the FIXED gate. This does
NOT call the video provider and generates NO new candidates — it only runs the VLM/ffmpeg gate + trace
analysis on cand_0.mp4 / cand_1.mp4 that fal already produced. ALLOW_PAID stays False. Produces the full
manual-review package: PASS/FAIL, gate scores, Bolt trajectory, bubble-visibility trace, portal-scale
trace, entry/exit boundary comparison, identity + physical-state continuity. Run:
  python3 -m bolt_seq.eval_pilot_candidates"""
import os, sys, json, base64, subprocess
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq.providers import directed_video as DV
from bolt_seq import compiler as C

OUT = os.path.join(PROJ, "renders/bolt_seq/_oxygen_pilot")
CAND = os.path.join(OUT, "candidates")


def per_frame_traces(clip, cost, n=8):
    """One VLM call → per-frame {bolt_bbox, bubble_present, portal_bbox} for the bubble & portal traces."""
    import explainer_pipeline as ep
    d = C.dur(clip) or 5.0
    content = []
    for i in range(n):
        fp = os.path.join(CAND, f"_tr_{i}.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{d*(i+0.5)/n:.2f}", "-i", clip,
                        "-frames:v", "1", "-vf", "scale=300:533", fp], check=True)
        content += [{"type": "text", "text": f"frame {i}"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                     "data": base64.b64encode(open(fp, "rb").read()).decode()}}]
    content.append({"type": "text", "text": (
        "These 8 frames are in time order from a clip of the robot Bolt in an underwater tunnel with a "
        "glowing GREEN oxygen portal ring and (early on) a translucent air bubble. For EACH frame return "
        "the robot's bbox [x,y,w,h] in 0..1 (null if absent), whether a translucent air bubble is visible "
        "(bubble_present true/false), and the green portal ring's bbox [x,y,w,h] (null if not visible). "
        "Return ONLY JSON: {\"frames\":[{\"i\":int,\"bolt_bbox\":[..]|null,\"bubble_present\":bool,"
        "\"portal_bbox\":[..]|null}]}")})
    try:
        r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=900,
            system="You are a precise visual annotator. Report only what is visible.",
            messages=[{"role": "user", "content": content}])
        cost.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text)
        return (o or {}).get("frames", [])
    except Exception as e:
        return [{"error": str(e)}]


def traces_from(frames):
    bub = [bool(f.get("bubble_present")) for f in frames if "i" in f]
    def area(bb):
        return (bb[2] * bb[3]) ** 0.5 if bb and len(bb) == 4 else None
    portal = [round(area(f.get("portal_bbox")), 3) if area(f.get("portal_bbox")) else None for f in frames if "i" in f]
    bolt = [(round(f["bolt_bbox"][0] + f["bolt_bbox"][2] / 2, 3), round(f["bolt_bbox"][1] + f["bolt_bbox"][3] / 2, 3))
            if f.get("bolt_bbox") else None for f in frames if "i" in f]
    first_absent = next((i for i, b in enumerate(bub) if not b), None)
    reappears = any(bub[i] and (first_absent is not None and i > first_absent) for i in range(len(bub)))
    pv = [p for p in portal if p is not None]
    portal_trend = ("grows_then_recedes" if len(pv) >= 3 and pv[-1] < max(pv) * 0.8 else
                    ("grows" if len(pv) >= 2 and pv[-1] >= pv[0] else "flat/unclear"))
    return {"bubble_visibility_trace": bub, "bubble_first_absent_frame": first_absent,
            "bubble_reappears_after_gone": reappears, "portal_scale_trace": portal,
            "portal_trend": portal_trend, "bolt_centroid_trace": bolt}


def review_one(i, spec, cost):
    clip = os.path.join(CAND, f"cand_{i}.mp4")
    ev = DV.evaluate_candidate(clip, spec, boundary=spec.get("boundary"), gates=spec.get("gates"),
                               cost=cost, log=lambda *_: None)
    frames = per_frame_traces(clip, cost)
    tr = traces_from(frames)
    sc = ev.get("scores", {})
    return {
        "candidate": i, "raw": os.path.join(CAND, f"cand_{i}_raw.mp4"),
        "normalized": clip, "contact_sheet": os.path.join(CAND, f"cand_{i}_contact.jpg"),
        "automated_verdict": "PASS" if ev["pass"] else "FAIL",
        "gate_scores": sc, "rejection_reasons": ev["reasons"],
        "bolt_trajectory": ev.get("trajectory"), "optical_flow": ev.get("flow"),
        "bubble_visibility_trace": tr["bubble_visibility_trace"],
        "bubble_first_absent_frame": tr["bubble_first_absent_frame"],
        "bubble_reappears": tr["bubble_reappears_after_gone"],
        "portal_scale_trace": tr["portal_scale_trace"], "portal_trend": tr["portal_trend"],
        "entry_boundary_match": sc.get("start_frame_match"),
        "exit_boundary_match": sc.get("end_frame_match"),
        "identity_continuity": {"global_identity": sc.get("identity"),
                                "hero_replaced": ev.get("scores", {}).get("hero_replaced"),
                                "n_present_frames": ev.get("trajectory", {}).get("n_present")},
        "physical_state_continuity": {
            "bubble_present_then_absent_no_reappear": (tr["bubble_first_absent_frame"] is not None
                                                       and not tr["bubble_reappears_after_gone"]),
            "portal_trend": tr["portal_trend"],
            "hero_disappearances": ev.get("trajectory", {}).get("disappearances"),
            "hero_reversals": ev.get("trajectory", {}).get("reversals")},
    }


def main():
    cost = []
    spec = json.load(open(os.path.join(OUT, "pilot_spec.json")))
    print("Re-evaluating already-paid candidates through the FIXED gate (no new generation)...", flush=True)
    reviews = []
    for i in (0, 1):
        if os.path.exists(os.path.join(CAND, f"cand_{i}.mp4")):
            reviews.append(review_one(i, spec, cost))
    out = {"note": "Re-evaluation of already-generated paid candidates. No video provider called. ALLOW_PAID="
           + str(DV.ALLOW_PAID), "reviews": reviews, "reeval_vlm_cost_usd": round(sum(cost), 3)}
    json.dump(out, open(os.path.join(OUT, "pilot_manual_review.json"), "w"), indent=2, default=str)
    for r in reviews:
        print(f"\n=== candidate {r['candidate']}: {r['automated_verdict']} ===")
        print("  gate scores:", {k: r["gate_scores"].get(k) for k in ("identity", "start_frame_match",
              "end_frame_match", "start_end_match", "slop", "semantic")})
        print("  reasons:", r["rejection_reasons"])
        print("  bolt trajectory:", r["bolt_trajectory"])
        print("  bubble trace:", r["bubble_visibility_trace"], "first_absent:", r["bubble_first_absent_frame"])
        print("  portal trend:", r["portal_trend"], r["portal_scale_trace"])
        print("  physical continuity:", r["physical_state_continuity"])
    print(f"\nre-eval VLM cost ${sum(cost):.2f} (NO video generation). report: {OUT}/pilot_manual_review.json")


if __name__ == "__main__":
    main()
