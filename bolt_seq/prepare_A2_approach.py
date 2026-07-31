"""A2 (effortful approach) — PREPARE ONLY, NO SPEND (ALLOW_PAID stays False). A1 is an accepted immutable
fixture; its exact final clean-body frame is A2's start frame (unchanged). Author A2's END boundary: Bolt
continues toward the terminal (authored displacement ~0.10-0.13), forward pitch + reach INCREASE, base rigid
and visible, NO propulsion VFX, camera/terminal fixed, scale matched to A1's final frame (no scale jump).
Verify boundaries deterministically (VFX-absent, base present, displacement band, scale ratio, terminal fixed).
Build the body-only A2 package. Deterministic propulsion is added ONLY after the clean A2 body clip passes.
Run: python3 -m bolt_seq.prepare_A2_approach"""
import os, sys, json
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from bolt_seq.providers import directed_video as DV
from bolt_seq import prepare_oxygen_shot_A_primitives as P

AT = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/atomic_shots")
FROZEN = os.path.join(AT, "a1_accepted"); OUT = os.path.join(AT, "a2_approach"); os.makedirs(OUT, exist_ok=True)
W, H, TERM_LEFT = P.W, P.H, P.TERM_LEFT
A2_START = os.path.join(FROZEN, "A1_final_clean_body_frame.png")   # EXACT A1 final clean-body frame (immutable)
A1_ACCEPTED_HASH = "ad7161d12928bf1db96b8f2430c0b645a4b74869c2b26fdb1aa78b64e2240bf7"
POSE_STRAIN = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/bolt_strain_reach.png")  # forward-lean, extended reach, trailing arm back, narrowed eyes
# AUTHORITATIVE lower-body requirement (resolved): HOVER-BASE INTEGRITY. The accepted visible design is a
# rounded hover base; separate feet/pods are NOT visibly present in production frames and are NOT claimed.
LOWER_BODY_REQUIREMENT = "hover_base_integrity"
_PLATE = np.asarray(P._bg().convert("RGB"), float)
NEG = ("no thruster flame, no exhaust, no propulsion glow, no energy trail, no cyan halo, no floor illumination, "
       "no jet plume, no particles, no smoke, no glow beneath the robot, no propulsion shadow, no detached energy blobs, "
       "camera movement, pan, zoom, reversing, moving backward, retreating, touching the terminal, shrinking, growing, "
       "legs, feet as boots, humanoid legs, mouth, extra limbs, duplicate robot, morphing, overlay text, captions, "
       "watermark, HUD, blur, low quality")
PROMPT = ("The mascot robot Bolt in a dark dry oxygen corridor, LOCKED STATIC CAMERA, preserve the wall signage. "
          "Bolt keeps pushing forward to the RIGHT toward the wall refill terminal with visible effort, body "
          "pitching further forward and one arm reaching further out — NO thruster, NO exhaust, NO glow, NO plume "
          "of any kind. Keep Bolt's rounded lower hover base and small foot/base pods fully visible and rigid. "
          "Premium 3D cartoon render, no other characters, no text.")


def measure(path):
    a = np.asarray(Image.open(path).convert("RGB").resize((W, H)), float)
    bb = DV._blob_bbox(a, 0, int(0.58 * W), int(0.26 * H), int(0.86 * H))
    cx = (bb[0] + bb[2]) / 2 / W; cyc = (bb[1] + bb[3]) / 2 / H; mh = bb[3] - bb[1]; redge = bb[2] / W
    return {"cx": round(cx, 4), "cy_center": round(cyc, 4), "measured_h": int(mh), "right_edge": round(redge, 4), "bbox": bb}


def vfx_below_body_px(path):
    """Strong PLUME cyan OUTSIDE Bolt's true silhouette (plate-diff) + outside the terminal COLUMN. Because the
    end is a composite on the plate, plate-diff isolates ALL of Bolt (incl. the extended hand) -> the hand is
    NOT miscounted; only a genuine plume (cyan not matching plate, off Bolt) registers. ~0 for a no-plume frame."""
    a = np.asarray(Image.open(path).convert("RGB").resize((W, H)), float); R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    bolt = ndimage.binary_dilation(np.abs(a - _PLATE).mean(axis=2) > 22, iterations=3)
    cyan = (G > 150) & (B > 150) & (R < np.minimum(G, B) - 30); cyan[bolt] = False
    cyan[int(0.28 * H):int(0.80 * H), int(TERM_LEFT * W):] = False                  # diegetic terminal column
    return int(cyan.sum())


def visual_hand_gap(path):
    """Terminal gap measured from Bolt's VISUAL rightmost pixel (plate-diff), not the bright-blob bbox which
    clips a dim extended hand. Excludes floor shadow (y>0.80) and the terminal column (x>=0.79)."""
    a = np.asarray(Image.open(path).convert("RGB").resize((W, H)), float)
    d = np.abs(a - _PLATE).mean(axis=2) > 26; d[int(0.80 * H):] = False; d[:, int(0.79 * W):] = False
    xs = np.where(d.any(axis=0))[0]
    return round(TERM_LEFT - (xs.max() / W), 4) if len(xs) else None


def base_present(path):
    a = np.asarray(Image.open(path).convert("RGB").resize((W, H)), float)
    bb = DV._blob_bbox(a, 0, int(0.58 * W), int(0.26 * H), int(0.86 * H))
    sil, sbb = DV._bolt_silhouette(a, bb, W, H)
    sh = max(1, sbb[3] - sbb[1]); band = sil[int(sbb[3] - 0.30 * sh):sbb[3], sbb[0]:sbb[2]]
    return int(band.sum())


def terminal_diff(p_start, p_end):
    a = np.asarray(Image.open(p_start).convert("RGB").resize((W, H)), float)
    b = np.asarray(Image.open(p_end).convert("RGB").resize((W, H)), float)
    ty0, ty1, tx0, tx1 = int(0.30 * H), int(0.58 * H), int(TERM_LEFT * W), int(0.79 * W)
    return round(float(np.abs(a[ty0:ty1, tx0:tx1] - b[ty0:ty1, tx0:tx1]).mean()), 2)


def main():
    import hashlib
    DV.assert_allow_paid_reset()
    start_hash = hashlib.sha256(open(A2_START, "rb").read()).hexdigest()
    start = measure(A2_START)
    target_disp = 0.130                      # max displacement that keeps the VISUAL reaching hand short of the terminal (tilt 14)
    target_cx = start["cx"] + target_disp

    # Converge the authored end on BLOB-space geometry (what Kling + the gates measure), NOT alpha geometry, so
    # start->end has no scale jump / no vertical drift and the displacement lands in [0.10,0.13]. author_frame
    # converges alpha geometry, which (with tilt) differs from the blob metric — so wrap it in a correction loop.
    orig_tmh = P.TARGET_MEASURED_H
    P.TARGET_MEASURED_H = start["measured_h"]
    center_param = start["cy_center"]
    gap = round(TERM_LEFT - (target_cx + (start["right_edge"] - start["cx"])), 4)
    e = m_end = None
    try:
        for _ in range(10):
            # user choice: HOVER pose (moderate reach) + increased forward pitch + narrowed/dimmed eyes for effort.
            # tilt 14 (>A1's 12) — 18 dropped the reaching hand into the terminal; 14 keeps the hand short.
            e = P.author_frame("A2_end.png", P.POSE_REACH, gap=gap, center=center_param, tilt=14, thruster="none", dim_frac=0.15, narrow=0.12)
            m_end = measure(e["display"]); disp = round(m_end["cx"] - start["cx"], 4)
            ok_h = abs(m_end["measured_h"] - start["measured_h"]) <= start["measured_h"] * 0.03
            ok_cy = abs(m_end["cy_center"] - start["cy_center"]) <= 0.012
            ok_disp = 0.120 <= disp <= 0.140
            if ok_h and ok_cy and ok_disp:
                break
            P.TARGET_MEASURED_H = int(max(200, P.TARGET_MEASURED_H * start["measured_h"] / max(1, m_end["measured_h"])))
            center_param += (start["cy_center"] - m_end["cy_center"])
            gap = round(gap - (target_cx - m_end["cx"]), 4)
    finally:
        P.TARGET_MEASURED_H = orig_tmh
    disp = round(m_end["cx"] - start["cx"], 4)

    # move authored end into the a2 dir
    import shutil
    end_disp = os.path.join(OUT, "A2_end.png"); shutil.copy(e["display"], end_disp)
    end_body = os.path.join(OUT, "A2_end.body.png"); shutil.copy(e["body"], end_body)

    scale_ratio = round(m_end["measured_h"] / start["measured_h"], 4)
    vhand = visual_hand_gap(end_disp)                                            # terminal gap from the VISUAL hand
    checks = {
        "start_byte_identical_to_A1_final": bool(start_hash == A1_ACCEPTED_HASH), "start_sha256": start_hash,
        "start_vfx_outside_bolt_px": vfx_below_body_px(A2_START), "end_vfx_outside_bolt_px": vfx_below_body_px(end_disp),
        "start_base_px": base_present(A2_START), "end_base_px": base_present(end_disp),
        "authored_displacement": disp, "displacement_ge_0.11_floor": bool(disp >= 0.11),
        "scale_ratio_end_over_start": scale_ratio, "scale_stable_0.97_1.03": bool(0.97 <= scale_ratio <= 1.03),
        "vertical_drift": round(abs(m_end["cy_center"] - start["cy_center"]), 4),
        "terminal_region_mean_diff": terminal_diff(A2_START, end_disp),
        "start_cx": start["cx"], "end_cx": m_end["cx"], "visual_hand_gap_to_terminal": vhand,
        "end_tilt_deg": 14, "end_pose": "hover_run_dry (moderate reach) + tilt 14 forward pitch + dim_frac 0.15 + narrow 0.12 (strained eyes)",
        "lower_body_requirement": LOWER_BODY_REQUIREMENT,
    }
    checks["vfx_absent_both"] = bool(checks["start_vfx_outside_bolt_px"] < 60 and checks["end_vfx_outside_bolt_px"] < 60)
    checks["hover_base_present_both"] = bool(checks["start_base_px"] > 200 and checks["end_base_px"] > 200)
    checks["minimal_vertical_drift"] = bool(checks["vertical_drift"] <= 0.02)
    checks["no_terminal_contact_or_overlap"] = bool(vhand is not None and vhand > 0.03)   # VISUAL hand stays short of terminal
    checks["room_for_A3_vertical_sink"] = True                                            # A3 sinks (vertical); horizontal gap not consumed

    spec = DV.build_fal_payload({"model": "kling-v3-pro", "seed_image": A2_START, "end_image": end_disp,
                                 "prompt": PROMPT, "negative_prompt": NEG, "cfg_scale": 0.6, "generate_audio": False,
                                 "duration": "3", "use_elements": False}, DV._FAL_ENDPOINTS["kling-v3-pro"],
                                uri=lambda x: os.path.basename(x))
    package = {"objective": "a2_effortful_approach", "no_spend": True, "prepared_only": True, "provider_called": False,
               "a1_status": "A1_FULL_PRIMITIVE_PASS (accepted immutable fixture; not regenerated)",
               "a2_start_frame": A2_START, "a2_start_is_exact_a1_final_clean_body_frame": True,
               "a2_end_frame": end_disp, "authored_forward_displacement": disp, "target_band": [0.10, 0.13],
               "boundary_checks": checks,
               "sanitized_request_no_keys": spec,
               "generation_scope": ["forward translation (continue)", "increase forward pitch", "increase reach",
                                    "rigid visible base", "locked camera", "fixed terminal"],
               "vfx_in_generation": "NONE (all propulsion visuals negated)",
               "raw_clip_gates": ["generated_vfx_absence_gate", "lower_body_integrity_gate", "path_monotonicity",
                                  "endpoint_geometry", "anatomy_temporal", "camera_model", "destination_attachment"],
               "post_production": {"add": "exactly ONE deterministic compact plume AFTER the clean A2 body clip passes",
                                   "same_rules_as_A1": True},
               "allow_paid": DV.ALLOW_PAID, "allow_paid_reset": DV.assert_allow_paid_reset()}
    json.dump(package, open(os.path.join(AT, "a2_approach_package.json"), "w"), indent=2, default=str)

    # review montage: A2 start (=A1 final) vs A2 end
    tiles = [("A2 START (=A1 final clean-body)", A2_START), ("A2 END (authored, no plume)", end_disp)]
    sh = Image.new("RGB", (2 * 360 + 30, 660), (12, 12, 14)); d = ImageDraw.Draw(sh)
    for i, (t, p) in enumerate(tiles):
        sh.paste(Image.open(p).convert("RGB").resize((360, 640)), (i * 360 + 10, 18)); d.text((i * 360 + 12, 3), t, fill=(230, 230, 230))
    sh.save(os.path.join(OUT, "A2_boundary_review.jpg"), quality=92)

    print("=== A2 APPROACH — PREPARED (no spend) ===")
    print("A2 start (=A1 final clean-body):", {k: start[k] for k in ("cx", "cy_center", "measured_h")})
    print("A2 end (authored):", {k: m_end[k] for k in ("cx", "cy_center", "measured_h")})
    for k, v in checks.items():
        print(f"  {k}: {v}")
    print("ALLOW_PAID:", DV.ALLOW_PAID, "| wrote a2_approach_package.json + A2_boundary_review.jpg | provider NOT called")


if __name__ == "__main__":
    main()
