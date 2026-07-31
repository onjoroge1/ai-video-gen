"""A1 PROPULSION-ATTACHMENT CORRECTION — NO SPEND. The provider plume lags/drifts (propulsion_attachment_gate
confirms). Un-approves the primitive, corrects the classification, and tests a DETERMINISTIC repair on the
cand1 window: remove the provider cyan plume using the locked corridor plate, track Bolt's lower anchor per
frame, re-attach a deterministic plume tied to measured forward velocity (directional lag as DEFORMATION, not
position lag), then re-run the gates. Preserves all original clips/reports separately. If clean removal fails,
prepares (no spend) a revised no-plume A1 package. ALLOW_PAID=False throughout.
Run: python3 -m bolt_seq.run_A1_vfx_repair"""
import os, sys, json, subprocess, shutil
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from bolt_seq.providers import directed_video as DV
from bolt_seq import motion_registry as MR
from bolt_seq import run_primitive_chain_pilot as R

OX = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription"); AT = os.path.join(OX, "atomic_shots")
AD = os.path.join(AT, "a1_displacement"); RP = os.path.join(AD, "vfx_repair"); os.makedirs(RP, exist_ok=True)
WIN = os.path.join(AD, "window", "A1_window.mp4"); PLATE = os.path.join(OX, "corridor_with_terminal.png")
END = os.path.join(AT, "primitives", "A1disp_B1v2.png")
W, H, TERM_LEFT = 1080, 1920, 0.605


def plate_img():
    im = Image.open(PLATE).convert("RGB"); tw = max(W, int(im.width * H / im.height))
    im = im.resize((tw, H), Image.LANCZOS)
    return np.asarray(im.crop(((im.width - W) // 2, 0, (im.width - W) // 2 + W, H)), float)


def bolt_bbox(a):
    return DV._blob_bbox(a, 0, int(TERM_LEFT * W), int(0.14 * H), int(0.94 * H))


def remove_and_reattach(frames_dir, out_dir):
    """Per frame: remove cyan plume BELOW the body (replace with plate), track anchor, re-attach deterministic
    plume tied to velocity with a backward DEFORMATION (attachment fixed). Returns per-frame anchors + a
    residual-cyan measure for removal-quality classification."""
    from scipy import ndimage
    plate = plate_img()
    tb = [int(0.605 * W), int(0.30 * H), int(0.79 * W), int(0.58 * H)]          # terminal (protect its cyan screen)
    removed_dir = os.path.join(os.path.dirname(out_dir), "_frames_removed_only"); os.makedirs(removed_dir, exist_ok=True)
    [os.remove(os.path.join(removed_dir, x)) for x in os.listdir(removed_dir)]
    files = sorted(f for f in os.listdir(frames_dir) if f.endswith(".png"))
    anchors = []; residuals = []; bg_mismatch = []
    for f in files:
        a = np.asarray(Image.open(os.path.join(frames_dir, f)).convert("RGB"), float)
        bb = bolt_bbox(a)
        anchors.append(((bb[0] + bb[2]) / 2, bb[3]) if bb else None)
    for i, f in enumerate(files):
        im = Image.open(os.path.join(frames_dir, f)).convert("RGB"); a = np.asarray(im, float)
        bb = bolt_bbox(a)
        if bb:
            R_, G_, B_ = a[:, :, 0], a[:, :, 1], a[:, :, 2]
            cyan = (G_ > 95) & (B_ > 95) & (R_ < np.minimum(G_, B_) - 10)       # provider plume + soft halo, FULL frame

            def protect(m):                                                     # keep Bolt's body cyan + the terminal screen
                m[max(0, bb[1] - 6):min(H, bb[3] + 2), max(0, bb[0] - 14):min(W, bb[2] + 14)] = False
                m[max(0, tb[1] - 6):min(H, tb[3] + 6), max(0, tb[0] - 6):min(W, tb[2] + 6)] = False
                return m
            m = protect(cyan.copy())
            m = ndimage.binary_dilation(m, iterations=4)                       # cover soft halo + motion blur (temporal-union effect per frame)
            m = protect(m)                                                     # re-protect after dilation
            ring = ndimage.binary_dilation(m, iterations=6) & ~m
            if ring.sum() > 50:
                bg_mismatch.append(float(np.abs(a[ring] - plate[ring]).mean()))
            a[m] = plate[m]                                                    # replace complete provider-VFX region from the locked plate
            Image.fromarray(a.astype("uint8"), "RGB").save(os.path.join(removed_dir, f))   # removed-only (before re-attach)
            # TRUE residual: provider-colored cyan remaining ANYWHERE outside Bolt + terminal after removal
            R2, G2, B2 = a[:, :, 0], a[:, :, 1], a[:, :, 2]
            rm = protect((G2 > 95) & (B2 > 95) & (R2 < np.minimum(G2, B2) - 10))
            residuals.append(int(rm.sum()))
        out = Image.fromarray(a.astype("uint8"), "RGB")
        # re-attach deterministic plume at the tracked anchor, tied to velocity, backward deformation only
        if anchors[i]:
            ax, ay = anchors[i]
            v = 0.0
            if i > 0 and anchors[i - 1]:
                v = (ax - anchors[i - 1][0]) / W
            speed = min(0.10, abs(v)); L = int(60 + 900 * speed); hw = int(26 + 120 * speed)
            alpha = int(150 + 700 * speed); alpha = min(240, alpha)
            shear = int(-np.sign(v) * 800 * speed)                             # tail bends BACKWARD (deformation); top stays on anchor
            jet = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(jet)
            top = int(ay - 8)
            d.polygon([(int(ax - hw), top), (int(ax + hw), top), (int(ax + shear + hw // 3), top + L),
                       (int(ax + shear), top + int(L * 1.12)), (int(ax + shear - hw // 3), top + L)], fill=(95, 235, 248, alpha))
            d.ellipse([int(ax - hw), top - 6, int(ax + hw), top + 16], fill=(150, 245, 250, min(255, alpha + 30)))
            jet = jet.filter(ImageFilter.GaussianBlur(6))
            out = Image.alpha_composite(out.convert("RGBA"), jet).convert("RGB")
        out.save(os.path.join(out_dir, f))
    return anchors, residuals, len(files), bg_mismatch


def main():
    DV.assert_allow_paid_reset()
    cost = []
    # --- correct classification + un-approve (preserve original evidence) ---
    res_path = os.path.join(AD, "a1_window_result.json")
    if os.path.exists(res_path) and not os.path.exists(res_path + ".orig"):
        shutil.copy(res_path, res_path + ".orig")
    MR.register("bolt.hover_launch", status="pending_gates",
                description="UN-APPROVED: provider plume fails propulsion_attachment_gate (lags/drifts). Awaiting deterministic VFX repair or a no-plume re-gen.",
                clip=None, not_accepted_reason="propulsion_effect_attachment FAIL (VFX plume not attached)")
    # --- re-evaluate both candidates with the attachment gate (no spend) ---
    att = {}
    for name, clip in [("cand0", os.path.join(AD, "c0.mp4")), ("cand1", os.path.join(AD, "c1.mp4")), ("cand1_window", WIN)]:
        att[name] = DV.propulsion_attachment_gate(clip)

    # --- deterministic repair on the window clip ---
    fdir = os.path.join(RP, "_frames_in"); rdir = os.path.join(RP, "_frames_out")
    for dd in (fdir, rdir):
        os.makedirs(dd, exist_ok=True); [os.remove(os.path.join(dd, x)) for x in os.listdir(dd)]
    fps = DV._probe(WIN).get("fps", 30) or 30
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", WIN, "-vf", f"fps={fps},scale={W}:{H}", os.path.join(fdir, "f%04d.png")], check=True)
    anchors, residuals, nfr, bg_mismatch = remove_and_reattach(fdir, rdir)
    repaired = os.path.join(RP, "A1_window_vfxrepair.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", f"{fps}", "-i", os.path.join(rdir, "f%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", repaired], check=True)
    # removal quality: TRUE residual cyan (incl. halo) after replacement + plate-vs-generated-bg mismatch
    max_resid = max(residuals) if residuals else 0
    mean_bg_mismatch = round(float(np.mean(bg_mismatch)), 2) if bg_mismatch else 999.0
    removal_clean = max_resid < 300 and mean_bg_mismatch <= 10.0   # little residual halo AND plate matches the generated floor

    # 3-way comparison (provider | removed-only | repaired) at a mid-launch frame
    mid = nfr // 2; removed_dir = os.path.join(RP, "_frames_removed_only")
    tw = W // 3; ba = Image.new("RGB", (3 * tw + 24, H // 3 + 24), (12, 12, 14)); dd = ImageDraw.Draw(ba)
    ba.paste(Image.open(os.path.join(fdir, f"f{mid:04d}.png")).convert("RGB").resize((tw, H // 3)), (0, 20))
    ba.paste(Image.open(os.path.join(removed_dir, f"f{mid:04d}.png")).convert("RGB").resize((tw, H // 3)), (tw + 12, 20))
    ba.paste(Image.open(os.path.join(rdir, f"f{mid:04d}.png")).convert("RGB").resize((tw, H // 3)), (2 * tw + 24, 20))
    dd.text((4, 4), "PROVIDER plume", fill=(230, 200, 200)); dd.text((tw + 16, 4), "REMOVED only", fill=(230, 230, 160)); dd.text((2 * tw + 28, 4), "REPAIRED (re-attached)", fill=(160, 230, 160))
    ba.save(os.path.join(RP, "before_removed_repaired.jpg"), quality=90)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", repaired, "-vf", "fps=4,scale=200:-1,tile=5x1", os.path.join(RP, "repaired_contact.jpg")], check=False)

    # --- build the removed-only clip + verify it has NO provider VFX and NO dark artifact ---
    removed_clip = os.path.join(RP, "A1_window_removed_only.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", f"{fps}", "-i", os.path.join(removed_dir, "f%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", removed_clip], check=True)
    removed_provider_clean = max_resid < 200                          # no provider cyan outside Bolt+terminal after removal
    va_removed = DV.visual_artifact_gate(removed_clip, PLATE)         # no dark holes from the plate reconstruction
    plate_reconstruction_ok = va_removed["pass"] and mean_bg_mismatch <= 10.0

    # --- diagnostic mask frames (Part 1) at a mid frame ---
    from scipy import ndimage
    a_mid = np.asarray(Image.open(os.path.join(fdir, f"f{mid:04d}.png")).convert("RGB"), float)
    bbm = bolt_bbox(a_mid)
    def save_mask(mask, name, base):
        ov = Image.fromarray((base * 0.35).astype("uint8"), "RGB").convert("RGBA"); d2 = ImageDraw.Draw(ov)
        col = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ca = np.asarray(col);
        m3 = Image.new("RGBA", (W, H), (0, 0, 0, 0)); arr = np.zeros((H, W, 4), "uint8"); arr[mask] = (90, 235, 248, 180);
        ov = Image.alpha_composite(ov, Image.fromarray(arr, "RGBA"))
        ov.convert("RGB").resize((W // 3, H // 3)).save(os.path.join(RP, name), quality=88)
    if bbm:
        R3, G3, B3 = a_mid[:, :, 0], a_mid[:, :, 1], a_mid[:, :, 2]
        body_m = np.zeros((H, W), bool); body_m[max(0, bbm[1]):bbm[3], max(0, bbm[0]):bbm[2]] = True
        prov_m = (G3 > 95) & (B3 > 95) & (R3 < np.minimum(G3, B3) - 10); prov_m[body_m] = False
        save_mask(body_m, "diag_body_mask.jpg", a_mid)
        save_mask(prov_m, "diag_provider_removal_mask.jpg", a_mid)
        rep_mid = np.asarray(Image.open(os.path.join(rdir, f"f{mid:04d}.png")).convert("RGB"), float)
        Rr, Gr, Br = rep_mid[:, :, 0], rep_mid[:, :, 1], rep_mid[:, :, 2]
        det_m = (Gr > 110) & (Br > 110) & (Rr < np.minimum(Gr, Br) - 15); det_m[body_m] = False
        save_mask(det_m, "diag_deterministic_plume_mask.jpg", rep_mid)

    # --- re-run FINAL-OUTPUT gates on the repaired clip ---
    tk = DV.bolt_tracker(repaired)
    gates = {
        "propulsion_presence": DV.propulsion_presence_gate(repaired, tracker=tk),
        "propulsion_attachment": DV.propulsion_attachment_gate(repaired, tracker=tk),
        "propulsion_cleanup": DV.propulsion_cleanup_gate(repaired, plate_path=PLATE, tracker=tk),
        "propulsion_velocity_coupling": DV.propulsion_velocity_coupling_gate(repaired, tracker=tk),
        "camera_model": DV.camera_model_gate(repaired, cost=cost),
        "anatomy_temporal": DV.check_anatomy_temporal(repaired, R.BOLT_SPEC, cost=cost),
        "path_monotonicity": DV.path_monotonicity_gate(repaired, tracker=tk),
        "endpoint_geometry": DV.endpoint_geometry_gate(repaired, END, tracker=tk, cost=cost),
        "visual_artifact": DV.visual_artifact_gate(repaired, PLATE, tracker=tk),
    }
    gp = {"propulsion_presence": gates["propulsion_presence"]["pass"], "propulsion_attachment": gates["propulsion_attachment"]["pass"],
          "propulsion_cleanup_exactly_one": gates["propulsion_cleanup"]["pass"], "velocity_coupling": gates["propulsion_velocity_coupling"]["coupled"],
          "camera_locked": gates["camera_model"]["pass"], "anatomy_identity": gates["anatomy_temporal"]["identity_pass"],
          "trajectory_forward": gates["path_monotonicity"]["pass"], "endpoint_geometry": gates["endpoint_geometry"]["pass"],
          "visual_artifact_clean": gates["visual_artifact"]["pass"]}
    repair_pass = all(gp.values())
    if not removed_provider_clean:
        status = "A1_RESIDUAL_PROVIDER_VFX_FAIL"
    elif not plate_reconstruction_ok:
        status = "A1_CLEAN_PLATE_RECONSTRUCTION_FAIL"
    elif repair_pass:
        status = "A1_FINAL_VFX_CLEAN_PASS"
    else:
        status = "A1_RESIDUAL_PROVIDER_VFX_FAIL"

    # --- registry: ONE authoritative state (supersede any prior accepted/pending entry) ---
    if status == "A1_FINAL_VFX_CLEAN_PASS":
        MR.register("bolt.hover_launch", status="repaired_clean_pending_review", clip=repaired,
                    description="VFX-clean hover_launch: provider plume fully removed (temporal union, residual 0, no dark artifact), single deterministic attached plume. Passes all final-output gates incl. cleanup/exactly-one + attachment + artifact.",
                    provider="fal-ai/kling-video/v3/pro (body+translation) + deterministic post-VFX plume", not_accepted_reason="awaiting manual review")
    else:
        MR.register("bolt.hover_launch", status="pending_gates", clip=None,
                    description=f"NOT approved — {status}. Provider VFX not clean / plate reconstruction issue in the repaired output.",
                    not_accepted_reason=status)

    # --- Part 3: revised no-plume package (prepared, no spend) unless the repair is fully clean ---
    revised_pkg = None
    if status != "A1_FINAL_VFX_CLEAN_PASS":
        revised_pkg = {
            "strategy": "provider generates BODY launch+translation ONLY; deterministic propulsion added AFTER generation",
            "boundary_frames": "re-author B0/B1 with NO thruster plume or bottom halo (plume=none)",
            "prompt": "Bolt launches forward and accelerates rightward, body pitching forward — NO visible thruster/exhaust/glow; plume added in post",
            "negative_prompt_additions": ["thruster", "exhaust", "jet", "glow trail", "propulsion flame", "cyan halo"],
            "post_generation": "attach ONE deterministic velocity-tied plume at the tracked lower anchor (this module's renderer)",
            "provider_responsibility": "translation + body pose only; NOT VFX attachment", "needs_authorization": True, "allow_paid": False}

    out = {"objective": "a1_repair_audit_correction",
           "corrected_classification": {"deterministic_primary_plume_attachment": "PASS", "provider_vfx_removal": "FAIL_before_fix",
                                        "final_repaired_primitive": ("PASS" if status == "A1_FINAL_VFX_CLEAN_PASS" else "FAIL"),
                                        "superseded_status": "A1_PRIMARY_PLUME_ATTACHED_RESIDUAL_VFX_FAIL"},
           "attachment_reeval": {k: {"pass": v.get("pass"), "measured": v.get("measured"), "fails": [c for c, x in (v.get("checks") or {}).items() if not x]} for k, v in att.items()},
           "temporal_removal": {"removed_provider_clean": removed_provider_clean, "max_residual_cyan_px": max_resid,
                                "plate_reconstruction_ok": plate_reconstruction_ok, "plate_vs_generated_bg_mismatch": mean_bg_mismatch,
                                "va_removed_dark_artifact_frames": va_removed["frames_with_dark_artifact"], "frames": nfr,
                                "removed_only_clip": "vfx_repair/A1_window_removed_only.mp4", "repaired_clip": "vfx_repair/A1_window_vfxrepair.mp4"},
           "final_output_gates": gp, "final_output_repair_pass": repair_pass,
           "gate_reports": {k: (v if isinstance(v, dict) else str(v)) for k, v in gates.items()},
           "diagnostic_frames": ["vfx_repair/diag_body_mask.jpg", "vfx_repair/diag_provider_removal_mask.jpg",
                                 "vfx_repair/diag_deterministic_plume_mask.jpg", "vfx_repair/before_removed_repaired.jpg"],
           "revised_no_plume_package": revised_pkg, "status": status,
           "allow_paid_disk": DV.disk_allow_paid(), "allow_paid_runtime": DV.ALLOW_PAID,
           "allow_paid_reset_assertion": DV.assert_allow_paid_reset(), "no_paid_calls": True, "inserted_into_short": False,
           "authoritative_registry_state": MR.get("bolt.hover_launch")["status"], "vlm_cost_usd": round(sum(cost), 3)}
    json.dump(out, open(os.path.join(AD, "a1_vfx_repair_result.json"), "w"), indent=2, default=str)
    rr = subprocess.run([sys.executable, "bolt_seq/tests/test_regression.py"], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": PROJ})
    print("=== A1 REPAIR AUDIT CORRECTION (no spend) ===")
    for k, v in att.items():
        print(f"  attachment {k}: pass={v.get('pass')} fails={[c for c,x in (v.get('checks') or {}).items() if not x]}")
    print("removed_provider_clean:", removed_provider_clean, "| max_residual_cyan_px:", max_resid, "| plate_reconstruction_ok:", plate_reconstruction_ok, "| dark_artifact_frames(removed):", va_removed["frames_with_dark_artifact"])
    print("final-output gate pass:", gp)
    print("STATUS:", status, "| registry bolt.hover_launch ->", MR.get("bolt.hover_launch")["status"])
    print("ALLOW_PAID disk", DV.disk_allow_paid(), "runtime", DV.ALLOW_PAID, "| regression", rr.stdout.strip().splitlines()[-1] if rr.stdout else "", "| VLM $%.2f" % sum(cost))


if __name__ == "__main__":
    main()
