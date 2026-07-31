"""Prepare (NO SPEND, ALLOW_PAID stays False) the next Shot-A provider-conditioning package based on the
authoritative fal capability audit. Primary strategy = kling-v3-pro start+end-frame conditioning with the
end frame as a GENERATION INPUT, negative prompt, cfg_scale, audio off. Writes the sanitized request (no
keys), the prompt/negative prompt encoding the 4-phase performance curve + camera lock, the spend estimate,
and seeds the motion registry. Run: python3 -m bolt_seq.prepare_shot_A_conditioning"""
import os, sys, json
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from bolt_seq.providers import directed_video as DV
from bolt_seq import motion_registry as MR

OX = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription")
AT = os.path.join(OX, "atomic_shots")
SEED = os.path.join(AT, "shot_A_seed.png")
END = os.path.join(AT, "shot_A_end_frame.png")                 # SINK end frame: scale-matched (ratio 0.995), short-of-terminal (gap 0.10), Bolt sunk ~75px (weakening encoded geometrically). Passes boundary_pair_consistency_gate 16/16.
IDENT = os.path.join(OX, "bolt_hover_run_dry.png")            # clean Bolt, only used if use_elements enabled (fallback)

PROMPT = (
    "The mascot robot Bolt — rounded matte-white body, mint-green accents, glossy black visor with exactly "
    "two glowing cyan eyes and NO mouth, a cyan chest panel, two arms, hovering on a single rounded base "
    "and NO legs. One continuous 5-second shot inside a dark, dry futuristic oxygen corridor. LOCKED STATIC "
    "CAMERA that never moves, pans, or zooms. Bolt hover-runs to the RIGHT toward the wall-mounted oxygen "
    "refill terminal, at a constant distance from camera (he does not shrink or grow). "
    "Phase 1 (0-1s) urgent launch: hard forward lean, strong propulsion, a decisive push. "
    "Phase 2 (1-3s) effortful advance: the lean is held while one arm reaches forward toward the terminal. "
    "Phase 3 (3-4s) weakening: propulsion visibly fades, thrust drops, the reaching arm extends further, a "
    "slight wobble appears. Phase 4 (4-5s) strained: airborne and unsteady, the arm fully outstretched but "
    "STOPPING SHORT of the terminal without touching it. The reaching arm extends progressively; hover height "
    "and control deteriorate toward the end. Bolt never touches or overlaps the terminal, never reverses, "
    "never leaves frame. Premium 3D cartoon render. No text, no other characters."
)
NEG = (
    "camera movement, camera pan, camera zoom, dolly, tracking shot, shaking camera, reversing direction, "
    "moving backward, retreating, touching the terminal, overlapping the terminal, reaching the terminal, "
    "shrinking, growing larger, changing distance from camera, legs, feet, boots, shoes, lower limbs, mouth, "
    "extra arms, extra limbs, duplicate character, second robot, morphing, identity change, text, captions, "
    "watermark, UI, HUD, meters, on-screen icons, blur, distortion, low quality"
)

VCOST = {"kling-v3-pro": 0.56, "kling-v2.1-pro": 0.49, "kling-v1.6-pro": 0.48}   # per 5s clip (audio off)
EVAL_PER_CAND = 0.15   # 5 VLM gates (2 gates are deterministic/free)


def spec_for(model, duration="5", use_elements=False):
    return {"model": model, "seed_image": SEED, "end_image": END, "identity_reference": IDENT,
            "prompt": PROMPT, "negative_prompt": NEG, "cfg_scale": 0.6, "generate_audio": False,
            "duration": duration, "use_elements": use_elements}


def main():
    model_id = DV._FAL_ENDPOINTS["kling-v3-pro"]
    sanitized = DV.build_fal_payload(spec_for("kling-v3-pro"), model_id, uri=lambda p: os.path.basename(p))
    sanitized_with_elements = DV.build_fal_payload(spec_for("kling-v3-pro", use_elements=True), model_id, uri=lambda p: os.path.basename(p))

    package = {
        "no_spend": True, "allow_paid": False, "prepared_date": "2026-07-28",
        "primary_strategy": "A — start+end-frame conditioning on kling-v3-pro (end frame IS a generation input)",
        "endpoint_id": model_id,
        "authoritative_fields_used": {
            "start_image_url": "shot_A_seed.png (urgent-launch start)",
            "end_image_url": "shot_A_end_frame.png (strained, short-of-terminal — NOW a generation input, not eval-only)",
            "negative_prompt": "camera-move / reverse / overshoot / anatomy / text prohibitions",
            "cfg_scale": 0.6, "generate_audio": False, "duration": "5",
            "elements": "OPTIONAL fallback (frontal_image_url) — off by default; the start frame already carries identity and schema does not confirm elements composes with start+end",
        },
        "sanitized_request_primary_no_keys": sanitized,
        "sanitized_request_with_elements_fallback_no_keys": sanitized_with_elements,
        "boundary_frames": {"start": SEED, "end": END,
                            "end_frame_authored": "hover_run reach, scale-matched to the seed by MEASURED rendered height (ratio 0.995, fixes the 15% recede/grow bug); gap-to-terminal 0.10 (band [0.06,0.16]); Bolt SUNK ~75px vs the seed to encode propulsion weakening geometrically; corridor+terminal pixels identical to the seed plate (bg change 0.005, terminal IoU 1.0).",
                            "boundary_pair_gate": "passes boundary_pair_consistency_gate 16/16 (stable across 3 runs)"},
        "strain_finding": "gpt-image-2 cannot render this mascot as visibly EXHAUSTED (5 attempts, all read energetic/determined). visible_strain is therefore NOT a keyframe criterion — it is deferred to CLIP-level gates (end_state_gate + progressive_effort_gate + velocity_coupling_gate on the generated result). Weakening is instead signalled to the model by the end frame's altitude drop.",
        "known_limitations": [
            "No motion-path / trajectory / motion-brush / camera-lock FIELD exists on any audited fal endpoint; the in-between effort arc is steered only by prompt + cfg_scale + the start/end/altitude cues, then enforced post-hoc by trajectory_contract_gate + velocity_coupling_gate.",
            "start+end conditioning constrains only the endpoints; the model may interpolate more linearly than the authored 4-phase curve — this is the residual risk the gates catch. The altitude drop gives it a weakening cue.",
            "elements (reference) conditioning is not confirmed to compose with start+end; enable only if identity drifts (use_elements stays False for the first test).",
            "the static end keyframe cannot show facial strain; strain is a clip-level property (see strain_finding).",
        ],
        "preflight_gate": {"gate": "boundary_pair_consistency_gate", "status": "PASS 16/16",
                           "requirement": "must pass before any paid generation (start+end keyframe consistency)"},
        "acceptance": {"authoritative_gates": MR.REQUIRED_GATES,
                       "rule": "all seven must pass independently; macro_trajectory + trajectory_contract are deterministic and cannot be overridden by a VLM; visible_strain is verified here (clip-level), NOT on the keyframe",
                       "motion_registry_target": "bolt.hover_approach_strained (promoted ONLY when all seven pass)"},
        "execution": "PREPARED ONLY. Do not run until explicitly authorized. ALLOW_PAID stays False.",
    }
    json.dump(package, open(os.path.join(AT, "shot_A_conditioning_package.json"), "w"), indent=2, default=str)
    open(os.path.join(AT, "shot_A_prompt_v2.txt"), "w").write(PROMPT)
    open(os.path.join(AT, "shot_A_negative_prompt.txt"), "w").write(NEG)

    def est(vc, ncand): return {"per_candidate_video_usd": vc, "eval_per_candidate_usd": EVAL_PER_CAND,
                                "max_candidates": ncand, "worst_case_all_in_usd": round((vc + EVAL_PER_CAND) * ncand, 2)}
    cost = {
        "no_spend_now": True,
        "option_A_v3pro_start_end": {**est(VCOST["kling-v3-pro"], 3), "status": "RECOMMENDED",
            "controllability": "high (both endpoints pinned + negative + cfg)", "identity_risk": "low (start frame carries identity)",
            "boundary_risk": "low (end frame is an input)", "provider_support": "SCHEMA-CONFIRMED (start_image_url+end_image_url+negative_prompt+cfg_scale)"},
        "option_B_path_control": {"status": "NOT SUPPORTED", "reason": "no motion-path/brush/camera field on any audited fal endpoint"},
        "option_C_two_atomic_clips": {"per_candidate_video_usd": VCOST["kling-v3-pro"], "eval_per_candidate_usd": EVAL_PER_CAND,
            "shots": 2, "max_candidates_per_shot": 3, "worst_case_all_in_usd": round((VCOST["kling-v3-pro"] + EVAL_PER_CAND) * 6, 2),
            "status": "FALLBACK if the single start+end clip cannot achieve the effort arc", "boundary_risk": "medium (A1->A2 matched seam)"},
        "option_D_first_frame_only": {"status": "REJECTED", "reason": "insufficient endpoint/macro control (this pilot)"},
        "recommended": "option_A_v3pro_start_end — <=3 candidates, stop after first all-gates pass, proposed hard cap $2.25",
        "proposed_hard_cap_usd": 2.25,
    }
    json.dump(cost, open(os.path.join(AT, "shot_A_next_strategy_cost_estimate.json"), "w"), indent=2, default=str)

    MR._seed()
    print("=== conditioning package prepared (NO SPEND) ===")
    print("primary sanitized request (no keys):")
    print(json.dumps({k: (v[:40] + "..." if isinstance(v, str) and len(v) > 40 else v) for k, v in sanitized.items()}, indent=2))
    print("worst-case option A all-in: $", cost["option_A_v3pro_start_end"]["worst_case_all_in_usd"], "cap $", cost["proposed_hard_cap_usd"])
    print("registry:", {k: v["status"] for k, v in MR._load()["entries"].items()})
    print("ALLOW_PAID:", DV.ALLOW_PAID)


if __name__ == "__main__":
    main()
