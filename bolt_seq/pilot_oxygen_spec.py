"""Assemble (but do NOT execute) the first paid directed_video pilot: the oxygen FINAL-SPRINT-AND-
COLLAPSE hero block only. Meters, hub tracking, captions, warning effects and audio stay deterministic.
Produces the candidate spec, deterministic start/end boundary frames, a scoped prohibition set, the
pilot budget, and a spend estimate. Spends NOTHING (ALLOW_PAID=False). Run:
  python3 -m bolt_seq.pilot_oxygen_spec"""
import os, sys, json, subprocess
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from bolt_seq import topics as T, compiler as C
from bolt_seq.providers import directed_video as DV

OUT = os.path.join(PROJ, "renders", "bolt_seq", "_oxygen_pilot"); os.makedirs(OUT, exist_ok=True)
OXY = os.path.join(PROJ, "renders", "bolt_seq", "oxygen_subscription")
ANIMATIC = os.path.join(OXY, "oxygen_subscription_animatic.mp4")

# provider price sheet (USD per 5s image->video); pilot defaults to the cheaper standard model
PRICES = {"kling-v2.1-standard": 0.28, "kling-v3-pro": 0.56}


def _boundary_frames():
    """Deterministic START/END boundary frames for the hero block, taken from the existing oxygen
    animatic (real deterministic output). START = final sprint (o2 low, hub close, bubble present);
    END = collapse (o2 zero, collapsed near hub, bubble absent)."""
    start = os.path.join(OUT, "boundary_start.png"); end = os.path.join(OUT, "boundary_end.png")
    if os.path.exists(ANIMATIC):
        dur = C.dur(ANIMATIC)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{dur*0.80:.2f}", "-i", ANIMATIC,
                        "-frames:v", "1", start], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{dur-0.2:.2f}", "-i", ANIMATIC,
                        "-frames:v", "1", end], check=True)
        return {"start_frame": start, "end_frame": end}
    return {}


def build():
    topic = T.load("oxygen_subscription")
    bolt = next(e for e in topic["entities"] if e["id"] == "bolt")
    bolt = dict(bolt)
    bolt["image"] = os.path.join(OXY, "bolt_fail.png")           # impaired pose = the i2v identity seed
    bolt["asset"] = {**bolt.get("asset", {}),
                     "identity": ("the mascot robot Bolt: rounded matte-white body, mint-green accents, "
                                  "glossy black visor with two glowing cyan eyes and NO mouth, single "
                                  "hover-base, thin antenna")}
    # merged E+F "final sprint & collapse" hero block
    hero = {
        "id": "oxy_final_sprint_collapse", "role": "climax",
        "start_state": {"oxygen_reserve": 0.12, "distance_to_hub": 0.14, "hub_screen_size": 0.90,
                        "bolt_condition": "failing", "bubble_present": True, "bolt_identity": "bolt_v1"},
        "end_state": {"oxygen_reserve": 0.0, "distance_to_hub": 0.08, "hub_screen_size": 1.0,
                      "bolt_condition": "collapsed", "bubble_present": False, "collapse": True,
                      "bolt_identity": "bolt_v1"},
        # BLOCK-scoped prohibitions (not the whole topic's must_not_occur applied indiscriminately)
        "prohibited": ["bolt_reverses", "bubble_reappears", "hub_recedes", "bolt_flies_up",
                       "identity_change", "mutation"],
        "state_window_prohibitions": [
            {"event": "bubble_reappears", "when": {"var": "oxygen_reserve", "op": "<=", "value": 0.12}}],
    }
    # the hero MUST move toward the hub then collapse; give the spec an explicit forward direction
    bolt_track = dict(bolt)
    bolt_track["tracks"] = {"x": {"kf": [[0.0, 0.32], [1.0, 0.5]], "curve": "decel"}}   # last forward lunge
    boundary = _boundary_frames()
    budget = {"max_candidates": 3, "max_block_cost_usd": 5.0, "max_video_cost_usd": 5.0,
              "stop_after_first_pass": True, "reuse_cached": True, "provider_timeout_s": 600,
              "retry_ceiling": 2, "candidate_cost_usd": PRICES["kling-v2.1-standard"]}
    # tighten gates for a hero: identity/no-reversal/no-disappearance/on-model, boundary matched
    gates = {**DV.DEFAULT_GATES, "identity_min": 8, "start_end_min": 7, "start_frame_min": 7,
             "end_frame_min": 7, "slop_max": 3, "max_reversals": 0, "max_disappearances": 0,
             "min_displacement": 0.10}
    spec = DV.build_spec(bolt_track, hero, topic, boundary=boundary, gates=gates, budget=budget)
    spec["identity_reference"] = bolt["image"]
    spec["deterministic_layers_kept"] = ["oxygen meter", "hub tracking", "captions",
                                         "warning/visibility effects", "audio bed + SFX", "persistent state"]

    # spend estimate (no spend performed)
    est = {}
    for model, price in PRICES.items():
        est[model] = {"per_candidate_usd": price, "max_candidates": budget["max_candidates"],
                      "worst_case_video_usd": round(price * budget["max_candidates"], 2),
                      "expected_usd_first_pass": price,
                      "vlm_gate_eval_usd_est": round(0.03 * budget["max_candidates"], 3),
                      "budget_cap_usd": budget["max_video_cost_usd"]}
    estimate = {"model_default": "kling-v2.1-standard", "prices": PRICES, "by_model": est,
                "pilot_rule": "stop after first passing candidate; hard cap $5; 3 candidates max",
                "note": "No paid API called. ALLOW_PAID=%s." % DV.ALLOW_PAID}

    json.dump(spec, open(os.path.join(OUT, "pilot_spec.json"), "w"), indent=2, default=str)
    json.dump(estimate, open(os.path.join(OUT, "spend_estimate.json"), "w"), indent=2, default=str)
    print("=== OXYGEN PILOT SPEC (no spend) ===")
    print("motion_direction:", spec["motion_direction"], "| axis:", spec["motion_axis"])
    print("scoped prohibited_events:", spec["prohibited_events"])
    print("boundary frames:", {k: os.path.basename(v) for k, v in boundary.items()})
    print("budget:", {k: spec["budget"][k] for k in ("max_candidates", "max_video_cost_usd",
                                                      "stop_after_first_pass", "candidate_cost_usd")})
    print("spend estimate:")
    for m, e in est.items():
        print(f"  {m}: first-pass ~${e['expected_usd_first_pass']} · worst-case ${e['worst_case_video_usd']} "
              f"(+~${e['vlm_gate_eval_usd_est']} VLM) · cap ${e['budget_cap_usd']}")
    print("written:", OUT)
    return spec, estimate


if __name__ == "__main__":
    build()
