"""Freeze V1.2 as the validated world fixture, record the deterministic/generated provider boundary, and
PREPARE (not execute) the paid Shot-A package: oxygen_dry_approach_A (struggling hover approach). Seeds
are COMPOSITED from already-validated assets (no new image generation); all boundaries pass the gate
battery. No paid video. ALLOW_PAID stays False. Run: python3 -m bolt_seq.prepare_shot_A"""
import os, sys, json, shutil
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq.character import BOLT
from bolt_seq.providers import directed_video as DV
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

OX = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription")
V12 = os.path.join(OX, "v1_2"); AT = os.path.join(OX, "atomic_shots"); os.makedirs(AT, exist_ok=True)
PLATE = os.path.join(OX, "corridor_with_terminal.png")
RUN = os.path.join(OX, "bolt_hover_run_dry.png"); STRAIN = os.path.join(OX, "bolt_strain.png")
SEED = os.path.join(AT, "shot_A_seed.png"); ENDT = os.path.join(AT, "shot_A_end_target.png")
W, H = 1080, 1920; TERM_X = 0.66


def _bg():
    im = Image.open(PLATE).convert("RGB"); tw = max(W, int(im.width * H / im.height))
    im = im.resize((tw, H), Image.LANCZOS); return im.crop(((im.width - W) // 2, 0, (im.width - W) // 2 + W, H)).convert("RGBA")


def _grade(im):
    a = im.split()[3]; rgb = ImageEnhance.Brightness(im.convert("RGB")).enhance(0.72)
    rgb = Image.blend(rgb, Image.new("RGB", im.size, (34, 100, 108)), 0.18); o = rgb.convert("RGBA"); o.putalpha(a); return o


def _compose(pose_path, cx, cy, base_h, tilt=0):
    fr = _bg()
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([int(cx * W - 150), int(0.80 * H), int(cx * W + 150), int(0.80 * H + 44)], fill=(0, 0, 0, 120))
    fr.alpha_composite(sh.filter(ImageFilter.GaussianBlur(16)))
    im = _grade(Image.open(pose_path).convert("RGBA"))
    h = base_h; w = int(im.width * h / im.height); im = im.resize((w, h), Image.LANCZOS)
    if tilt: im = im.rotate(tilt, expand=True, resample=Image.BICUBIC)
    fr.alpha_composite(im, (int(cx * W - im.width / 2), int(cy * H - im.height / 2)))
    return fr.convert("RGB")


def verify(img, tag, cost):
    an = DV.anatomy_vlm(img, BOLT["reference"], BOLT["anatomy"], [(0, img)], cost=cost)
    proh = sorted({x for f in an.get("per_frame", []) for x in (f.get("prohibited_seen", []) + f.get("required_altered", []))})
    cp = DV.clean_plate_vlm(img, [(0, img)], cost=cost, expected_objects=["a robot", "a wall-mounted refill terminal"])
    ui = sorted({x for f in cp.get("per_frame", []) for x in f.get("ui_seen", [])})
    env = DV.environment_semantic_gate(img, "a dry oxygen-subscription corridor with ONE wall refill terminal",
                                       ["underwater", "aquatic", "portal", "two terminals", "floating terminal"],
                                       ["dry corridor", "one mechanical refill terminal"], cost=cost)
    da = DV.destination_attachment_gate(img, frames=[(0, img)], cost=cost)  # single-frame proxy (count + not floating)
    import base64, explainer_pipeline as ep
    b = base64.b64encode(open(img, "rb").read()).decode()
    q = ("For a SHOT-A " + tag + " boundary: return ONLY JSON {\"bolt_present\":bool,\"bolt_airborne\":bool,"
         "\"bolt_short_of_terminal\":bool,\"bolt_touching_terminal\":bool," +
         ("\"bolt_beginning_approach\":bool" if tag == "seed" else "\"bolt_strained_unstable\":bool,\"bolt_collapsed\":bool") + "}")
    r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=200, system="Strict boundary auditor.",
        messages=[{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b}},
                   {"type": "text", "text": q}]}]); cost.append(ep._msg_cost(r.usage))
    bp, _ = ep._parse_script_json(r.content[0].text); bp = bp if isinstance(bp, dict) else {}
    plaus = (bp.get("bolt_present") and bp.get("bolt_airborne") and bp.get("bolt_short_of_terminal")
             and not bp.get("bolt_touching_terminal")
             and (bp.get("bolt_beginning_approach") if tag == "seed"
                  else (bp.get("bolt_strained_unstable") and not bp.get("bolt_collapsed"))))
    checks = {"anatomy": not proh, "clean_plate": not ui, "environment_semantic": env.get("pass"),
              "exactly_one_destination": da.get("readings", {}).get("refill_terminal_count") == 1,
              "world_attachment": da.get("pass"), "boundary_plausibility": bool(plaus)}
    return {"all_pass": all(checks.values()), "checks": checks, "anatomy_flags": proh, "ui": ui,
            "env_reading": env.get("reading"), "boundary": bp}


def main():
    cost = []
    # 1. freeze validated world fixture
    FW = os.path.join(OX, "validated_world_fixture_v1_2"); os.makedirs(FW, exist_ok=True)
    for f in ("dry_motion_test_v1_2.mp4", "dry_motion_test_v1_2_contact_sheet.jpg", "camera_model_report.json",
              "world_attachment_report.json", "natural_motion_report.json", "motion_test_acceptance.json"):
        if os.path.exists(os.path.join(V12, f)):
            shutil.copy(os.path.join(V12, f), os.path.join(FW, f))
    shutil.copy(PLATE, os.path.join(FW, "corridor_with_terminal.png"))
    json.dump({"validated_world_fixture": True, "locked_camera": True, "exactly_one_destination": True,
               "terminal_world_attachment": True, "deterministic_locomotion_premium": False,
               "note": "world/camera/attachment proven; natural whole-body locomotion is generated-motion-only"},
              open(os.path.join(FW, "validated_world_fixture.json"), "w"), indent=2)
    # 2. provider boundary rule
    json.dump({"deterministic_provider": ["environment plates", "attached world objects", "meters/persistent state",
               "captions", "warning effects", "camera framing", "transitions", "editorial cuts", "non-hero cutaways"],
               "generated_motion_provider": ["natural character locomotion", "physical struggle", "falls and impacts",
               "complex body dynamics", "emotional hero action"],
               "finding": "whole-body PNG translation cannot satisfy the premium locomotion gate (not: all deterministic animation is impossible)"},
              open(os.path.join(OX, "provider_boundary.json"), "w"), indent=2)
    # 3. build + verify Shot-A boundaries (composited from validated assets, no new gen)
    _compose(RUN, 0.26, 0.52, 560, tilt=6).save(SEED)                 # beginning approach, forward lean
    _compose(STRAIN, 0.50, 0.55, 540, tilt=12).save(ENDT)            # closer, strained/unstable, still airborne, short
    vs = verify(SEED, "seed", cost); ve = verify(ENDT, "end", cost)
    # comparison sheet
    a = Image.open(SEED).convert("RGB"); a.thumbnail((360, 640)); b = Image.open(ENDT).convert("RGB"); b.thumbnail((360, 640))
    sheet = Image.new("RGB", (740, 664), (16, 16, 20)); d = ImageDraw.Draw(sheet)
    sheet.paste(a, (0, 24)); sheet.paste(b, (380, 24)); d.text((8, 4), "SHOT-A SEED (begin approach)", fill=(240, 240, 240))
    d.text((388, 4), "SHOT-A END TARGET (strained, short)", fill=(240, 240, 240))
    sheet.save(os.path.join(AT, "shot_A_seed_end_comparison.jpg"), quality=90)

    # 4. package files
    PRICES = {"kling-v3-pro": 0.56}
    prompt = (
        "A single continuous ~3-second shot in a DRY dystopian sealed corridor (oxygen pipes, vents, red "
        "subscription-expiration warnings — NOT underwater, NO water/bubbles). LOCKED camera; the corridor "
        "and the ONE wall-mounted mechanical oxygen refill terminal stay completely FIXED. The small "
        "white-and-mint robot Bolt HOVER-PROPELS from the left toward the terminal, PROGRESSIVELY WEAKENING: "
        "Phase 1 forward lean, controlled propulsion, purposeful reach; Phase 2 propulsion becomes less "
        "stable, slight vertical wobble, arms showing effort, slowing; Phase 3 strained final approach, "
        "visible fatigue, still airborne, ending CLOSE TO but clearly SHORT OF the terminal. Keep Bolt "
        "IDENTICAL — one rounded hover-base (NO legs/feet/boots), two arms, one antenna, black visor, two "
        "cyan eyes, cyan chest, no mouth, no on-body text. Do NOT reach zero oxygen, do NOT fail/collapse/"
        "impact, do NOT recover, do NOT touch or pass the terminal, NO somersault/crawl/walk/tumble, NO "
        "heroic acceleration, NO camera move, NO terminal movement or growth, NO UI/captions.")
    open(os.path.join(AT, "shot_A_prompt.txt"), "w").write(prompt)
    gate_contract = {
        "authoritative_gates": {
            "technical": "technical_gate", "environment_semantic": "environment_semantic_gate",
            "exactly_one_destination": "destination_attachment_gate", "camera_coherence": "camera_model_gate",
            "terminal_world_attachment": "destination_attachment_gate", "trajectory_toward_terminal": "trajectory_gate",
            "no_terminal_contact": "trajectory_gate", "no_overshoot": "trajectory_gate",
            "temporal_anatomy": "check_anatomy_temporal", "identity_continuity": "check_anatomy_temporal",
            "clean_plate": "check_clean_plate", "natural_character_motion": "natural_character_motion_gate",
            "progressive_effort": "natural_character_motion_gate", "propulsion_weakens": "natural_character_motion_gate",
            "no_recovery": "trajectory_gate+natural_character_motion_gate", "start_boundary": "boundary match shot_A_seed",
            "end_boundary": "boundary match shot_A_end_target", "manual_visual_review": "human"},
        "rule": "natural_character_motion_gate MUST NOT judge camera or terminal movement; production_ready "
                "requires EVERY independent gate to pass",
        "eval_protocol": "evaluate FULL raw clip → detect action window → trim → temporal/attachment-aware anatomy"}
    json.dump(gate_contract, open(os.path.join(AT, "shot_A_gate_contract.json"), "w"), indent=2)
    spend = {"provider": "fal-ai/kling-video/v3/pro/image-to-video", "model": "kling-v3-pro",
             "max_candidates": 3, "per_candidate_usd": 0.56, "first_pass_usd": 0.56,
             "worst_case_video_usd": round(0.56 * 3, 2), "vlm_eval_usd_est": 0.30,
             "worst_case_all_in_usd": round(0.56 * 3 + 0.30, 2), "proposed_hard_cap_usd": 2.00,
             "stop_after_first_complete_pass": True, "no_fallback": True, "no_automatic_insertion": True,
             "allow_paid_runtime_only": True, "note": "Kling min 5s → generate 5s, trim to 2.5-3.5s window."}
    json.dump(spend, open(os.path.join(AT, "shot_A_spend_estimate.json"), "w"), indent=2)
    spec = {"shot_id": "oxygen_dry_approach_A", "action": "struggling_hover_approach",
            "duration_target_s": [2.5, 3.5], "primary_action_count": 1, "transition_count": 0,
            "camera": "locked", "environment": "sealed dry dystopian corridor (validated plate)",
            "destination": "one wall-embedded mechanical oxygen refill terminal (fixed)",
            "seed": SEED, "end_target": ENDT, "character": BOLT, "prompt_file": "shot_A_prompt.txt",
            "includes_only": ["Bolt hover-propels toward terminal while progressively weakening"],
            "excludes": ["oxygen zero", "propulsion failure", "collapse", "impact", "recovery",
                         "terminal contact", "passing terminal", "UI/captions"],
            "gate_contract": "shot_A_gate_contract.json", "spend_estimate": "shot_A_spend_estimate.json",
            "allow_paid": False}
    json.dump(spec, open(os.path.join(AT, "shot_A_pilot_spec.json"), "w"), indent=2, default=str)
    json.dump({"seed": vs, "end_target": ve, "ready_for_authorization": vs["all_pass"] and ve["all_pass"],
               "cost_usd": round(sum(cost), 3), "no_new_generation": True, "no_paid_video": True},
              open(os.path.join(AT, "shot_A_preflight_report.json"), "w"), indent=2, default=str)

    print("=== SHOT-A PACKAGE (prepared, not executed) ===")
    print("SEED preflight:", "ALL PASS" if vs["all_pass"] else "FAIL", vs["checks"])
    print("END preflight :", "ALL PASS" if ve["all_pass"] else "FAIL", ve["checks"])
    print("spend: v3-pro first-pass ~$0.56 · worst-case all-in ~$1.98 · proposed cap $2.00 · <=3 cand · stop-after-first-pass")
    print("READY FOR AUTHORIZATION:", vs["all_pass"] and ve["all_pass"], "| preflight cost $%.2f (no gen, no paid video)" % sum(cost))
    print("package:", AT)


if __name__ == "__main__":
    main()
