"""Reusable motion-primitive system for directed hero animation. A PRIMITIVE is an atomic, single-action
motion building block (launch, cruise, strain, reach, power_loss, stumble, fall, impact, recover, react).
The sequence compiler chains primitives with FRAME-EXACT continuity (each step's end frame IS the next step's
start frame) into a shot, producing per-step generation specs + motion contracts + a continuity contract +
a spend estimate — WITHOUT calling any provider. The oxygen Shot-A (launch → effortful cruise/reach →
weakening reach) is the first validation case; nothing here is oxygen-specific.

Design rules:
- ONE atomic generated action per primitive (never launch+cruise+deteriorate+near-fail in one clip).
- Each primitive declares which of the authoritative directed_video gates it must pass.
- Boundary frames are shared: N primitives need N+1 frames; frame i is step[i-1].end AND step[i].start.
"""

# authoritative gate names (directed_video)
G = {"art": "articulation_quality", "self": "self_propulsion_readability", "endpoint": "endpoint_realization",
     "path": "path_monotonicity", "prop_present": "propulsion_presence", "prop_couple": "propulsion_velocity_coupling",
     "perf": "performance_progression", "anat": "anatomy_temporal", "camera": "camera_model",
     "attach": "destination_attachment", "boundary": "boundary_pair_consistency"}

# gates every directed clip must pass regardless of primitive (world/identity integrity)
BASE_GATES = [G["anat"], G["camera"], G["attach"], G["prop_present"], G["boundary"]]

PRIMITIVES = {
    "launch": {
        "duration_s": [0.8, 1.4], "atomic_action": "thrust-launch from near-rest",
        "velocity_profile": "rest → high (accelerating)", "thrust_profile": "rising to peak",
        "altitude_profile": "stable or slight rise", "posture": "hard forward lean, arms drive back",
        "start_role": "at/near rest, low thrust, upright", "end_role": "accelerating, strong thruster, forward lean",
        "required_gates": BASE_GATES + [G["prop_couple"], G["path"], G["endpoint"]],
        "prompt": "launches forward with a strong thruster burst, body pitching forward, rapid acceleration in the travel direction"},
    "cruise": {
        "duration_s": [1.0, 2.2], "atomic_action": "steady forward travel",
        "velocity_profile": "steady, high", "thrust_profile": "steady", "altitude_profile": "stable",
        "posture": "forward lean held", "start_role": "moving forward", "end_role": "moving forward, nearer the target",
        "required_gates": BASE_GATES + [G["path"], G["endpoint"]],
        "prompt": "travels steadily forward with continuous thrust, holding a forward lean, cruising toward the target"},
    "strain": {
        "duration_s": [1.0, 1.8], "atomic_action": "effortful continued travel",
        "velocity_profile": "high but costly", "thrust_profile": "steady, laboured", "altitude_profile": "stable",
        "posture": "tensing, reaching begins, visible exertion rising",
        "start_role": "moving with effort", "end_role": "still advancing but visibly labouring",
        "required_gates": BASE_GATES + [G["path"], G["perf"], G["endpoint"]],
        "prompt": "pushes forward with visibly rising effort, body tensing and the reaching arm extending, propulsion laboured"},
    "reach": {
        "duration_s": [0.8, 1.4], "atomic_action": "extend arm toward target + decelerate short",
        "velocity_profile": "declining to near-zero", "thrust_profile": "reducing", "altitude_profile": "stable/slight drop",
        "posture": "one arm fully extending toward target, decelerating",
        "start_role": "approaching target", "end_role": "arm fully extended, stopped SHORT of the target",
        "required_gates": BASE_GATES + [G["path"], G["endpoint"]],
        "prompt": "extends one arm toward the target while decelerating, stopping just short without touching it"},
    "power_loss": {
        "duration_s": [0.8, 1.4], "atomic_action": "propulsion failure",
        "velocity_profile": "declining → near-zero", "thrust_profile": "weakening/flickering → minimal",
        "altitude_profile": "dropping (losing lift)", "posture": "sagging, forward/down pitch, wobble/roll",
        "start_role": "moving, thrust ok", "end_role": "barely functioning: sunk, strained, thrust failing, short of target",
        "required_gates": BASE_GATES + [G["prop_couple"], G["perf"], G["endpoint"]],
        "prompt": "propulsion visibly fails — the thruster flickers and shrinks, velocity drops, the body loses "
                  "altitude and pitches forward-down with an unsteady roll, barely holding position"},
    "stumble": {
        "duration_s": [0.5, 1.0], "atomic_action": "brief loss of control",
        "velocity_profile": "jolt then recover", "thrust_profile": "sputter", "altitude_profile": "dip",
        "posture": "off-balance lurch", "start_role": "moving", "end_role": "recovering balance",
        "required_gates": BASE_GATES + [G["perf"]],
        "prompt": "briefly lurches off-balance with a thruster sputter and a dip, then begins to steady"},
    "fall": {
        "duration_s": [0.8, 1.6], "atomic_action": "loss of lift, downward motion",
        "velocity_profile": "downward accelerating", "thrust_profile": "off/failing", "altitude_profile": "dropping fast",
        "posture": "limbs trailing up as body drops", "start_role": "airborne, thrust failing", "end_role": "near a surface, falling",
        "required_gates": BASE_GATES + [G["path"], G["perf"], G["endpoint"]],
        "prompt": "loses all lift and falls, body dropping with limbs trailing upward, no thrust"},
    "impact": {
        "duration_s": [0.4, 0.9], "atomic_action": "hit surface + settle",
        "velocity_profile": "abrupt stop", "thrust_profile": "off", "altitude_profile": "at floor",
        "posture": "compress on contact then settle", "start_role": "falling toward a surface", "end_role": "settled/slumped on the surface",
        "required_gates": BASE_GATES + [G["endpoint"]],
        "prompt": "meets the surface, compressing on contact and settling into a slump"},
    "recover": {
        "duration_s": [0.8, 1.6], "atomic_action": "regain lift/control",
        "velocity_profile": "rising from zero", "thrust_profile": "reigniting → steady", "altitude_profile": "rising",
        "posture": "straightening, thruster reigniting", "start_role": "slumped/failing", "end_role": "stabilised, hovering",
        "required_gates": BASE_GATES + [G["prop_couple"], G["perf"]],
        "prompt": "the thruster reignites and strengthens, the body straightens and regains altitude, stabilising"},
    "react": {
        "duration_s": [0.4, 1.0], "atomic_action": "emote/respond in place",
        "velocity_profile": "~0", "thrust_profile": "idle", "altitude_profile": "hover",
        "posture": "expressive body/arm gesture, minimal translation", "start_role": "in place", "end_role": "in place, reacted",
        "required_gates": BASE_GATES + [G["art"]],
        "prompt": "reacts in place with an expressive body and arm gesture, hovering without travelling"},
}


def primitive(name):
    if name not in PRIMITIVES:
        raise KeyError(f"unknown motion primitive '{name}'; known: {sorted(PRIMITIVES)}")
    return PRIMITIVES[name]


def validate_continuity(steps):
    """Each step's end frame MUST be the next step's start frame (frame-exact handoff). Returns issues[]."""
    issues = []
    for i in range(len(steps) - 1):
        if steps[i].get("end") != steps[i + 1].get("start"):
            issues.append(f"discontinuity: {steps[i]['id']}.end ({steps[i].get('end')}) != {steps[i+1]['id']}.start ({steps[i+1].get('start')})")
    for s in steps:
        p = primitive(s["primitive"]); lo, hi = p["duration_s"]
        if not (lo <= s.get("duration", (lo + hi) / 2) <= hi):
            issues.append(f"{s['id']} duration {s.get('duration')} outside {p['duration_s']} for '{s['primitive']}'")
    return issues


def compile_sequence(steps, model="kling-v3-pro", usd_per_s=0.112, candidates_per_step=2, eval_per_cand=0.15,
                     negative_prompt="", cfg_scale=0.6, gen_duration_s=3):
    """PREPARE-ONLY: turn a primitive sequence into per-step generation specs + motion contracts + a
    continuity contract + a spend estimate. gen_duration_s is the PROVIDER-VALID integer clip length (Kling
    v3-pro accepts integer 3–15s; sub-second durations are NOT executable). Each step declares an action
    window inside the 3s clip; deterministic trimming to that window is permitted ONLY AFTER the full raw clip
    passes anatomy + camera + world gates. Does NOT call any provider."""
    if int(gen_duration_s) != gen_duration_s or not (3 <= gen_duration_s <= 15):
        raise ValueError(f"gen_duration_s must be an integer 3..15 for Kling; got {gen_duration_s}")
    issues = validate_continuity(steps)
    plan = []
    for s in steps:
        p = primitive(s["primitive"])
        win = s.get("action_window", [0.3, min(gen_duration_s - 0.5, sum(p["duration_s"]))])
        prompt = (s.get("prompt_prefix", "") + p["prompt"] + s.get("prompt_suffix", "")).strip()
        spec = {"model": model, "seed_image": s["start"], "end_image": s["end"], "prompt": prompt,
                "negative_prompt": negative_prompt, "cfg_scale": cfg_scale, "generate_audio": False,
                "duration": str(int(gen_duration_s)), "use_elements": False}      # INTEGER seconds — provider-valid
        contract = {"id": s["id"], "primitive": s["primitive"], "atomic_action": p["atomic_action"],
                    "gen_duration_s": gen_duration_s, "action_window_s": win,
                    "post_hold": f"{win[1]:.2f}-{gen_duration_s:.1f}s (controlled/suspended hold)",
                    "trim_rule": "evaluate the FULL raw clip against anatomy + camera + world gates FIRST; "
                                 "only then deterministically trim to the action window",
                    "velocity_profile": p["velocity_profile"], "thrust_profile": p["thrust_profile"],
                    "altitude_profile": p["altitude_profile"], "posture": p["posture"],
                    "start_role": p["start_role"], "end_role": p["end_role"],
                    "required_gates": p["required_gates"], "start_frame": s["start"], "end_frame": s["end"]}
        plan.append({"id": s["id"], "spec_sanitized": {**spec, "seed_image": s["start"], "end_image": s["end"]},
                     "motion_contract": contract})
    n_cand = candidates_per_step * len(steps)
    video = round(gen_duration_s * usd_per_s * n_cand, 2)                        # every clip billed at the 3s minimum
    spend = {"model": model, "usd_per_s": usd_per_s, "gen_duration_s": gen_duration_s,
             "candidates_per_step": candidates_per_step, "n_steps": len(steps), "n_candidates_worstcase": n_cand,
             "video_usd_worstcase": video, "eval_usd_est": round(eval_per_cand * n_cand, 2),
             "all_in_worstcase_usd": round(video + eval_per_cand * n_cand, 2),
             "per_candidate_video_usd": round(gen_duration_s * usd_per_s, 3)}
    boundary_frames = [steps[0]["start"]] + [s["end"] for s in steps]
    continuity = {"authored_frame_exact_handoff": True, "boundary_frames": boundary_frames,
                  "rule": "frame i is step[i-1].end AND step[i].start (AUTHORED continuity only); the GENERATED "
                          "seam must additionally pass generated_seam_gate after each pair is produced",
                  "issues": issues, "continuous": not issues}
    return {"steps": plan, "continuity_contract": continuity, "spend_estimate": spend,
            "prepared_only": True, "provider_called": False}
