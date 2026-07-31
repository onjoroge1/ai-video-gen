"""PILOT PREFLIGHT (no video spend). Enforces the conditional-authorization gates before any paid call:
  1. regenerate the oxygen hub as an UNOCCUPIED green oxygen refill portal (no Bolt/robot/face/eyes/
     occupied platform) + asset-role preflight must pass;
  2. render the exact deterministic ENTRY and EXIT boundary frames with the clean hub;
  3. inspect them: exactly one Bolt, identity consistent, bubble present@entry / absent@exit, hub
     visually distinct from Bolt, no duplication/contamination.
Writes the updated pilot spec (Kling v3-pro, $2.00 hard cap incl. eval, 3 candidates, no retries) but
CALLS NO VIDEO PROVIDER. Run: python3 -m bolt_seq.pilot_preflight"""
import os, sys, json, subprocess
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import topics as T, compiler as C, effects as FX, orchestrator as O, scene_graph as SG
from bolt_seq.providers import directed_video as DV
from PIL import Image

OXY = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription")
OUT = os.path.join(PROJ, "renders/bolt_seq/_oxygen_pilot"); os.makedirs(OUT, exist_ok=True)
HUB = os.path.join(OUT, "hub_clean.png")

HUB_PROMPT = ("A glowing GREEN circular oxygen refill portal: a luminous upright ring gateway of breathable "
              "green-and-cyan light, like a sci-fi checkpoint doorway or teleporter ring, radiant in the "
              "centre. It is EMPTY and UNOCCUPIED. There is NO robot, NO mascot, NO humanoid, NO creature, "
              "NO face, NO eyes, and NO figure standing on or inside it. Just the glowing green portal ring "
              "itself. Premium 3D render, dramatic rim light. The ENTIRE background must be SOLID FLAT "
              "MAGENTA (#FF00FF) filling the whole frame — no scenery, no ground, no platform occupant.")
HUB_CHECK = [
    "shows a glowing GREEN circular oxygen refill portal / ring / gateway",
    "the portal is EMPTY and unoccupied — nothing is standing on or inside it",
    "there is NO robot, mascot, humanoid, or creature of any kind",
    "there is NO face and NO glowing character eyes",
    "it reads clearly as a green oxygen refill point, visually distinct from a white robot mascot",
]


def regen_hub(cost, log):
    r = C.gen_with_preflight(HUB_PROMPT, HUB, HUB_CHECK, size="1024x1024", cutout=True,
                             tries=4, reuse=False, cost_sink=cost, log=log)
    return r


# purpose-built boundary poses (the oxygen fail/collapse poses read too energetic for the strict check)
_ID = ("A small toy-robot mascot Bolt, full body, centered. It has " + C.POSE_IDENTITY + ". Premium 3D "
       "cartoon render, dramatic lighting, no scenery. ")
_MAG = (" The ENTIRE background must be SOLID FLAT MAGENTA (#FF00FF) filling the frame — no ground, no shadow.")
IMPAIRED = os.path.join(OUT, "bolt_impaired.png"); COLLAPSED = os.path.join(OUT, "bolt_collapsed.png")
IMPAIRED_PROMPT = (_ID + "POSE: the robot is BUCKLING and sagging under crushing force and oxygen "
                   "starvation — body hunched low, arms trembling and drooping, straining desperately, "
                   "barely holding itself up, clearly failing and about to give out. Heavy and labored. "
                   "NOT upright, NOT fresh, NOT energetic, NOT waving." + _MAG)
IMPAIRED_CHECK = ["the robot is clearly straining, buckling, sagging or drooping — impaired and about to give out",
                  "the robot does NOT look fresh, energetic, upright-and-strong, or waving",
                  "it is a single white-and-mint robot with cyan eyes (identity intact)"]
COLLAPSED_PROMPT = (_ID + "POSE: the robot has COLLAPSED — body crumpled and slumped downward, sinking and "
                    "falling, head bowed low, arms hanging completely limp, powered-out and motionless, a "
                    "fallen limp heap. NOT upright, NOT standing, NOT actively floating. (Its visor eyes may "
                    "still faintly glow — that is fine.)" + _MAG)
COLLAPSED_CHECK = ["the robot's POSTURE is clearly collapsed, slumped, crumpled, limp or sinking (fallen)",
                   "the robot does NOT look upright, standing, or actively energetic",
                   "the body is low/drooping with head bowed and arms limp",
                   "it is a single white-and-mint robot (identity intact); glowing eyes are acceptable"]


def regen_poses(cost, log):
    ri = C.gen_with_preflight(IMPAIRED_PROMPT, IMPAIRED, IMPAIRED_CHECK, size="1024x1536", cutout=True,
                              tries=4, reuse=False, cost_sink=cost, log=log)
    rc = C.gen_with_preflight(COLLAPSED_PROMPT, COLLAPSED, COLLAPSED_CHECK, size="1024x1536", cutout=True,
                              tries=4, reuse=False, cost_sink=cost, log=log)
    return ri, rc


def hero_entities():
    """Oxygen hero entities with the CLEAN hub swapped in and Bolt poses resolved from disk."""
    topic = T.load("oxygen_subscription")
    ents = []
    for e in topic["entities"]:
        e = json.loads(json.dumps(e))            # deep copy (plain data)
        if e["id"] == "hub":
            e["provider"] = "deterministic_2d"; e["image"] = HUB; e.pop("asset", None)
        elif e["id"] == "bolt":
            e["provider"] = "deterministic_2d"
            e["images"] = {"swim": os.path.join(OXY, "bolt_swim.png"), "strain": os.path.join(OXY, "bolt_strain.png"),
                           "fail": IMPAIRED, "collapse": COLLAPSED}   # purpose-built boundary poses
            e["pose0"] = "fail"; e.pop("asset", None)
        elif e.get("provider") == "image_generator":
            e["provider"] = "deterministic_2d"; e["image"] = os.path.join(OXY, f"{e['id']}.png")
            e.pop("asset", None)
        ents.append(e)
    return topic, ents


ENTRY = {"oxygen_reserve": 0.12, "distance_to_hub": 0.14, "hub_screen_size": 0.90,
         "bolt_condition": "failing", "bubble_present": True, "bolt_identity": "bolt_v1"}
EXIT = {"oxygen_reserve": 0.0, "distance_to_hub": 0.08, "hub_screen_size": 1.0,
        "bolt_condition": "collapsed", "bubble_present": False, "collapse": True, "bolt_identity": "bolt_v1"}


def render_boundary(topic, ents, state, tag):
    """Render one deterministic boundary frame by pinning start==end==state, then grabbing frame 0."""
    from bolt_seq import bindings as B
    blk = {"id": f"bnd_{tag}", "start_state": state, "end_state": state,
           "entity_overrides": {"bolt": {"base_h": 560, "tracks": {"y": SG.const_track(0.66 if tag == "exit" else 0.5)}}}}
    merged = O._apply_overrides(ents, blk["entity_overrides"])
    resolved = B.resolve_bindings(merged, topic["bindings"], state, state)
    clip = os.path.join(OUT, f"_bnd_{tag}.mp4")
    C.render_scene_block(clip, resolved, 0.3, tmp_dir=OUT, draw_fn=FX.draw)
    png = os.path.join(OUT, f"boundary_{tag}.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-frames:v", "1", png], check=True)
    return png


ENTRY_CHECK = [
    "exactly one white-and-mint robot (Bolt) is present — not zero, not two",
    "the robot's POSTURE looks strained, buckling, or impaired (not fresh/energetic); its eyes may still glow",
    "a translucent round air bubble is visible near the robot",
    "a glowing green oxygen portal is visible and is CLEARLY NOT a robot (no face, distinct from Bolt)",
    "there is NO second robot, duplicate character, or garbled/contaminated figure",
]
EXIT_CHECK = [
    "exactly one white-and-mint robot (Bolt) is present — not zero, not two",
    "the robot's POSTURE is collapsed/slumped/limp/sinking (judge posture only; glowing eyes are fine)",
    "there is NO air bubble present",
    "a glowing green oxygen portal is visible, larger/closer, and CLEARLY NOT a robot",
    "there is NO second robot, duplicate character, or garbled/contaminated figure",
]


def main():
    cost = []
    print("=== 1. REGENERATE CLEAN HUB (unoccupied green portal) ===", flush=True)
    hub_r = regen_hub(cost, print)
    hub_pass = hub_r["passed"]
    print(f"  hub asset-role preflight: {'PASS' if hub_pass else 'FAIL'}")
    print(f"  attempts: {[a.get('violations') for a in hub_r['attempts']]}")

    print("=== 1b. REGENERATE BOUNDARY POSES (impaired + collapsed) ===", flush=True)
    ri, rc = regen_poses(cost, print)
    print(f"  impaired pose: {'PASS' if ri['passed'] else 'FAIL'} | collapsed pose: {'PASS' if rc['passed'] else 'FAIL'}")

    print("=== 2. RENDER DETERMINISTIC BOUNDARY FRAMES (clean hub) ===", flush=True)
    topic, ents = hero_entities()
    entry_png = render_boundary(topic, ents, ENTRY, "entry")
    exit_png = render_boundary(topic, ents, EXIT, "exit")

    print("=== 3. INSPECT BOUNDARY FRAMES ===", flush=True)
    entry_pf = C.preflight(entry_png, ENTRY_CHECK, cost_sink=cost)
    exit_pf = C.preflight(exit_png, EXIT_CHECK, cost_sink=cost)
    print(f"  entry frame: {'PASS' if entry_pf['pass'] else 'FAIL'} {entry_pf['violations']}")
    print(f"  exit frame:  {'PASS' if exit_pf['pass'] else 'FAIL'} {exit_pf['violations']}")

    # contact sheet (hub | entry | exit)
    try:
        sheet = Image.new("RGB", (300 * 3, 533), (18, 18, 22))
        for i, p in enumerate([HUB, entry_png, exit_png]):
            im = Image.open(p).convert("RGB"); im.thumbnail((300, 533)); sheet.paste(im, (i * 300, 0))
        sheet.save(os.path.join(OUT, "preflight_contact_sheet.jpg"), quality=90)
    except Exception as e:
        print("contact sheet:", e)

    all_pass = hub_pass and entry_pf["pass"] and exit_pf["pass"]

    # updated pilot spec to the AUTHORIZED terms (Kling v3-pro, $2 cap incl eval, 3 candidates, no retries)
    bolt = next(e for e in ents if e["id"] == "bolt"); bolt = dict(bolt); bolt["image"] = os.path.join(OXY, "bolt_fail.png")
    bolt["asset"] = {"identity": ("the mascot robot Bolt: rounded matte-white body, mint-green accents, glossy "
                                  "black visor with two glowing cyan eyes and NO mouth, single hover-base, thin antenna")}
    bolt["tracks"] = {"x": {"kf": [[0.0, 0.32], [1.0, 0.5]], "curve": "decel"}}
    hero_blk = {"id": "oxy_final_sprint_collapse", "role": "climax", "start_state": ENTRY, "end_state": EXIT,
                "prohibited": ["bolt_reverses", "bubble_reappears", "hub_recedes", "bolt_flies_up",
                               "identity_change", "mutation", "teleportation", "duplication", "scene_reset"],
                "state_window_prohibitions": [{"event": "bubble_reappears",
                                               "when": {"var": "oxygen_reserve", "op": "<=", "value": 0.12}}]}
    budget = {"max_candidates": 3, "max_block_cost_usd": 2.0, "max_video_cost_usd": 2.0,
              "stop_after_first_pass": True, "reuse_cached": True, "provider_timeout_s": 600,
              "retry_ceiling": 0, "candidate_cost_usd": 0.56, "eval_cost_usd_est": 0.05}
    gates = {**DV.DEFAULT_GATES, "identity_min": 8, "start_end_min": 7, "start_frame_min": 7,
             "end_frame_min": 7, "slop_max": 3, "max_reversals": 0, "max_disappearances": 0,
             "min_displacement": 0.10}
    boundary = {"start_frame": entry_png, "end_frame": exit_png}
    spec = DV.build_spec(bolt, hero_blk, topic, boundary=boundary, gates=gates, budget=budget)
    spec["identity_reference"] = os.path.join(OXY, "bolt_fail.png")
    spec["model"] = "kling-v3-pro"
    spec["deterministic_layers_kept"] = ["oxygen meter", "hub tracking", "captions", "warning/visibility "
                                         "effects", "audio bed + SFX", "persistent state"]
    json.dump(spec, open(os.path.join(OUT, "pilot_spec.json"), "w"), indent=2, default=str)

    report = {"hub_preflight": {"pass": hub_pass, "attempts": hub_r["attempts"]},
              "boundary_poses": {"impaired_pass": ri["passed"], "collapsed_pass": rc["passed"]},
              "entry_frame": {"pass": entry_pf["pass"], "violations": entry_pf["violations"], "png": entry_png},
              "exit_frame": {"pass": exit_pf["pass"], "violations": exit_pf["violations"], "png": exit_png},
              "all_preflight_passed": all_pass, "preflight_cost_usd": round(sum(cost), 3),
              "authorized_terms": {"model": "kling-v3-pro", "max_candidates": 3, "hard_cap_usd": 2.0,
                                   "stop_after_first_pass": True, "no_retries": True,
                                   "manual_review_before_insert": True},
              "note": "NO VIDEO PROVIDER CALLED. ALLOW_PAID=%s." % DV.ALLOW_PAID}
    json.dump(report, open(os.path.join(OUT, "preflight_report.json"), "w"), indent=2, default=str)
    print(f"\nPREFLIGHT {'PASSED' if all_pass else 'FAILED'} | cost ${sum(cost):.2f} (image+VLM, NO video) | {OUT}")


if __name__ == "__main__":
    main()
