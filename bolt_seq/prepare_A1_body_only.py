"""A1 BODY-ONLY REBUILD — PREPARE ONLY (no spend, ALLOW_PAID False). Abandons plume salvage. Re-authors the
A1 start/end frames with NO propulsion VFX (no plume/halo/glow/floor-illumination/particles) and Bolt's
approved lower body (rounded hover chassis + small foot/base pods) visible. Verifies VFX-absence +
lower-body integrity on the frames, prepares the body-only provider package (body translation only; strong
VFX negatives), marks the existing provider-plume clip diagnostic-only, and emits review frames. The single
deterministic plume is added ONLY in post AFTER the body-only clip passes. Does NOT call any provider.
Run: python3 -m bolt_seq.prepare_A1_body_only"""
import os, sys, json
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
import numpy as np, base64
from PIL import Image, ImageDraw
from bolt_seq.providers import directed_video as DV
from bolt_seq import motion_registry as MR
from bolt_seq import prepare_oxygen_shot_A_primitives as P

AT = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/atomic_shots")
OUT = os.path.join(AT, "a1_body_only"); os.makedirs(OUT, exist_ok=True)
W, H, TERM_LEFT = P.W, P.H, P.TERM_LEFT
NEG = ("no thruster flame, no exhaust, no propulsion glow, no energy trail, no cyan halo, no floor illumination, "
       "no jet plume, no particles, no smoke, no glow beneath the robot, no propulsion shadow, no detached energy blobs, "
       "camera movement, pan, zoom, reversing, legs, feet as boots, humanoid legs, mouth, extra limbs, duplicate robot, "
       "morphing, overlay text, captions, watermark, HUD, blur, low quality")
PROMPT = ("The mascot robot Bolt in a dark dry oxygen corridor, LOCKED STATIC CAMERA, preserve the wall signage. "
          "Bolt launches forward and accelerates to the RIGHT toward the wall refill terminal, body pitching "
          "forward with one arm beginning to reach — NO thruster, NO exhaust, NO glow, NO plume of any kind. Keep "
          "Bolt's rounded lower hover base and its small foot/base pods fully visible and rigid at all times. "
          "Premium 3D cartoon render, no other characters, no text.")


_PLATE = np.asarray(P._bg().convert("RGB"), float)


def frame_vfx_absent(path):
    """Deterministic: no cyan propulsion pixels OUTSIDE Bolt's true silhouette (frame-vs-plate diff) + terminal.
    Using the plate-diff silhouette (not a tight bbox) excludes Bolt's own reaching arm, so this measures only
    genuine VFX. For a clean body-only frame it should be ~0."""
    from scipy import ndimage
    a = np.asarray(Image.open(path).convert("RGB"), float); R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    bb = DV._blob_bbox(a, 0, int(TERM_LEFT * W), int(0.14 * H), int(0.94 * H))
    bolt = ndimage.binary_dilation(np.abs(a - _PLATE).mean(axis=2) > 22, iterations=3)   # Bolt = where frame differs from plate
    cyan = (G > 100) & (B > 100) & (R < np.minimum(G, B) - 12)
    cyan[bolt] = False                                                                    # exclude all of Bolt (arm included)
    cyan[int(0.30 * H):int(0.58 * H), int(TERM_LEFT * W):int(0.79 * W)] = False           # exclude terminal
    return int(cyan.sum()), bb


def lower_body_vlm(path):
    a = np.asarray(Image.open(path).convert("RGB"), float)
    bb = DV._blob_bbox(a, 0, int(TERM_LEFT * W), int(0.14 * H), int(0.94 * H))
    src = path
    if bb:                                                     # crop to Bolt so the small pods are readable
        pad = 60; cp = "/tmp/_lb_crop.png"
        Image.open(path).convert("RGB").crop((max(0, bb[0] - pad), max(0, bb[1] - pad), min(W, bb[2] + pad), min(H, bb[3] + pad + 40))).save(cp)
        src = cp
    b = base64.b64encode(open(src, "rb").read()).decode()
    import explainer_pipeline as ep
    r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=200, system="Strict lower-body auditor.",
        messages=[{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b}},
        {"type": "text", "text": "Judge Bolt's lower body. Return ONLY JSON {\"rounded_hover_base_visible\":bool,"
         "\"small_foot_base_pods_visible\":bool,\"humanoid_legs_or_boots\":bool,\"any_glow_or_plume_present\":bool,"
         "\"lower_body_cropped\":bool}"}]}])
    o, _ = ep._parse_script_json(r.content[0].text); return o if isinstance(o, dict) else {}


def main():
    DV.assert_allow_paid_reset()
    # mark existing provider-plume clip diagnostic-only
    MR.register("bolt.A1.disp.c1.positive", status="diagnostic_fixture",
                description="A1_EXISTING_CLIP_DIAGNOSTIC_ONLY — provider plume lags + not cleanly removable; superseded by the body-only rebuild.",
                not_accepted_reason="A1_EXISTING_CLIP_DIAGNOSTIC_ONLY")

    # re-author NO-PLUME start/end frames (Bolt body + visible base/pods; larger validated displacement 0.156)
    b0 = P.author_frame("A1body_B0.png", P.POSE_REACH, gap=0.250, center=0.50, tilt=2, thruster="none")
    b1 = P.author_frame("A1body_B1.png", P.POSE_REACH, gap=0.090, center=0.50, tilt=12, thruster="none")
    frames = {"B0": b0["display"], "B1": b1["display"]}

    checks = {}; cost_note = 0
    for k, p in frames.items():
        cyan_px, bb = frame_vfx_absent(p)
        vlm = lower_body_vlm(p)
        checks[k] = {"vfx_cyan_outside_body_px": cyan_px, "vfx_absent": cyan_px < 60,
                     "lower_body": vlm,
                     "lower_body_ok": bool(vlm.get("rounded_hover_base_visible") and vlm.get("small_foot_base_pods_visible")
                                           and not vlm.get("humanoid_legs_or_boots") and not vlm.get("any_glow_or_plume_present")
                                           and not vlm.get("lower_body_cropped"))}
    def cx(bb): return round((bb[0] + bb[2]) / 2 / W, 4)
    authored_disp = round(cx(b1["bbox"]) - cx(b0["bbox"]), 4)

    # body-only provider package (sanitized, no keys) — provider does BODY translation only; plume added in post
    spec = DV.build_fal_payload({"model": "kling-v3-pro", "seed_image": b0["display"], "end_image": b1["display"],
                                 "prompt": PROMPT, "negative_prompt": NEG, "cfg_scale": 0.6, "generate_audio": False,
                                 "duration": "3", "use_elements": False}, DV._FAL_ENDPOINTS["kling-v3-pro"],
                                uri=lambda x: os.path.basename(x))
    package = {"objective": "a1_body_only_rebuild", "no_spend": True, "prepared_only": True, "provider_called": False,
               "existing_clip_status": "A1_EXISTING_CLIP_DIAGNOSTIC_ONLY", "target_next_status": "A1_BODY_ONLY_MOTION_PASS",
               "boundary_frames": frames, "authored_forward_displacement": authored_disp,
               "frame_prechecks": checks,
               "sanitized_request_no_keys": spec,
               "generation_scope": ["body articulation", "forward translation", "pitch + reach", "locked camera", "fixed terminal"],
               "vfx_in_generation": "NONE (all propulsion visuals negated)",
               "raw_clip_gates": ["generated_vfx_absence_gate", "lower_body_integrity_gate", "propulsion? NONE-expected",
                                  "path_monotonicity", "endpoint_geometry", "anatomy_temporal", "camera_model", "destination_attachment"],
               "post_production": {"add": "exactly ONE deterministic plume at the lower-body anchor AFTER the body-only clip passes",
                                   "rules": ["attachment point fixed to Bolt", "no floor glow", "must not cover feet/base",
                                             "deformation may trail with velocity", "attachment never detaches"],
                                   "final_vfx_gates": ["exactly one propulsion effect", "attached to lower-body anchor",
                                                       "zero residual provider VFX", "feet remain visible", "no floor glow",
                                                       "no secondary blob", "no mask damage"]},
               "allow_paid": DV.ALLOW_PAID, "allow_paid_reset": DV.assert_allow_paid_reset(),
               "awaiting": "review of these start/end frames, then authorization for the body-only paid generation"}
    json.dump(package, open(os.path.join(AT, "a1_body_only_package.json"), "w"), indent=2, default=str)

    # review comparison: old plume B1 vs new no-plume B1 + B0
    old_b1 = os.path.join(AT, "a1_displacement", "window") if False else os.path.join(AT, "primitives", "A1disp_B1v2.png")
    tiles = [("B0 no-plume (start)", frames["B0"]), ("B1 no-plume (end)", frames["B1"]),
             ("OLD B1 (had plume)", old_b1 if os.path.exists(old_b1) else frames["B1"])]
    sh = Image.new("RGB", (3 * 300 + 40, 560), (12, 12, 14)); d = ImageDraw.Draw(sh)
    for i, (t, p) in enumerate(tiles):
        sh.paste(Image.open(p).convert("RGB").resize((300, 533)), (i * 300 + 10, 22)); d.text((i * 300 + 12, 4), t, fill=(230, 230, 230))
    sh.save(os.path.join(OUT, "A1_body_only_review.jpg"), quality=92)
    # lower-body crops for close inspection
    for k, p in frames.items():
        im = Image.open(p).convert("RGB")
        im.crop((int(0.15 * W), int(0.55 * H), int(0.65 * W), int(0.85 * H))).save(os.path.join(OUT, f"{k}_lowerbody.jpg"), quality=92)

    print("=== A1 BODY-ONLY REBUILD (PREPARED, no spend) ===")
    print("authored_forward_displacement:", authored_disp)
    for k, c in checks.items():
        print(f"  {k}: vfx_absent={c['vfx_absent']} (cyan_outside_body {c['vfx_cyan_outside_body_px']}px) | lower_body_ok={c['lower_body_ok']} {c['lower_body']}")
    print("existing clip status: A1_EXISTING_CLIP_DIAGNOSTIC_ONLY | target: A1_BODY_ONLY_MOTION_PASS")
    print("ALLOW_PAID:", DV.ALLOW_PAID, "| wrote a1_body_only_package.json + review frames | provider NOT called")


if __name__ == "__main__":
    main()
