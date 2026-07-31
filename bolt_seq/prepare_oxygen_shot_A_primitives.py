"""PREPARE-ONLY (no spend, ALLOW_PAID stays False): corrected 3-second primitive package for oxygen Shot-A.
Kling v3-pro takes INTEGER 3-15s durations, so every primitive is a 3s generation with an authored action
window (trim only AFTER the full raw clip passes anatomy/camera/world gates). Authors 4 continuity boundary
frames B0-B3 with deterministic cues: B0 near-rest (arms-down, upright, no plume); a PHYSICALLY-ATTACHED
thruster plume (ROI stored separately from the body); B2 effortful (narrowed eyes + laboured pitch); B3
strengthened weakness (>=20% eye-luminance drop + narrowed eye shape + more pitch/roll + altitude loss,
body scale fixed). Emits 3s provider specs, B0-B3 comparisons, plume-ROI proofs, a 2D target-anchor report,
a generated-seam gate contract, and a revised all-in spend. Does NOT call any provider.
Run: python3 -m bolt_seq.prepare_oxygen_shot_A_primitives"""
import os, sys, json
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
from bolt_seq.providers import directed_video as DV
from bolt_seq import motion_primitives as MP

OX = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription"); AT = os.path.join(OX, "atomic_shots")
PRIM = os.path.join(AT, "primitives"); os.makedirs(PRIM, exist_ok=True)
PLATE = os.path.join(OX, "corridor_with_terminal.png")
POSE_REST = os.path.join(OX, "bolt_collapse.png")       # upright, arms-down = near-rest, less reach (B0)
POSE_REACH = os.path.join(OX, "bolt_hover_run_dry.png")  # one-arm reach, forward (B1/B2/B3)
W, H = 1080, 1920; TERM_LEFT = 0.605; TARGET_H = 760; TARGET_MEASURED_H = 560   # match MEASURED bright-blob height across poses
TERMINAL_POINT = (0.62, 0.55)                           # fixed terminal interaction point (nozzle at the unit's lower-left)
# attached plume: (top_half_width, depth, alpha) — drawn CONNECTED to the base underside centre
PLUME = {"none": None, "faint": (26, 60, 90), "small": (30, 70, 120), "moderate": (46, 110, 165), "strong": (64, 150, 220)}


def _bg():
    im = Image.open(PLATE).convert("RGB"); tw = max(W, int(im.width * H / im.height))
    im = im.resize((tw, H), Image.LANCZOS)
    return im.crop(((im.width - W) // 2, 0, (im.width - W) // 2 + W, H)).convert("RGBA")


def _eye_effect(o, dim_frac, narrow):
    """Deterministically fatigue the eyes: reduce cyan-glow luminance by dim_frac and NARROW the glow shape
    (compress its outer rows toward the dark visor). Operates on the head region of an RGBA cutout."""
    if dim_frac <= 0 and narrow <= 0:
        return o
    arr = np.asarray(o.convert("RGBA"), float); hh = arr.shape[0]
    head = arr[: int(0.45 * hh)]; R, Gc, B = head[:, :, 0], head[:, :, 1], head[:, :, 2]
    glow = (B > R + 18) & (B > Gc - 30)                    # cyan eyes (B>R, B≈G); survives dimming; excludes mint (G>>B)
    ys, xs = np.where(glow)
    if len(ys):
        if dim_frac > 0:
            for ch in range(3):
                head[:, :, ch][glow] = head[:, :, ch][glow] * (1 - dim_frac)
        if narrow > 0:                                   # dim the top/bottom `narrow` fraction of the glow -> thinner band
            y0, y1 = ys.min(), ys.max(); span = max(1, y1 - y0)
            cut = int(span * narrow)
            band = np.zeros_like(glow); band[y0:y0 + cut] = True; band[y1 - cut:y1 + 1] = True
            m = glow & band
            for ch in range(3):
                head[:, :, ch][m] = head[:, :, ch][m] * 0.30
        arr[: int(0.45 * hh)] = head
    return Image.fromarray(arr.astype("uint8"), "RGBA")


def _grade(im, dim_frac=0.0, narrow=0.0):
    a = im.split()[3]; rgb = ImageEnhance.Brightness(im.convert("RGB")).enhance(0.72)
    rgb = Image.blend(rgb, Image.new("RGB", im.size, (34, 100, 108)), 0.18)
    o = rgb.convert("RGBA"); o.putalpha(a)
    return _eye_effect(o, dim_frac, narrow)


def _pose_img(pose, dim_frac, narrow, target_h):
    im = Image.open(pose).convert("RGBA"); im = im.crop(im.getbbox())
    im = _grade(im, dim_frac, narrow)
    scale = target_h / im.height
    return im.resize((max(1, int(im.width * scale)), target_h), Image.LANCZOS)


def _attach_plume(fr, base_cx_px, base_bottom_px, strength):
    """Draw a thruster plume PHYSICALLY CONNECTED to the underside centre of Bolt's base (overlaps the base
    slightly, tapers downward). Returns the plume ROI bbox (stored separately from the body)."""
    spec = PLUME[strength]
    if not spec:
        return None
    hw, depth, alpha = spec
    top = base_bottom_px - 10                              # overlap up into the base so it reads as attached
    jet = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(jet)
    d.polygon([(base_cx_px - hw, top), (base_cx_px + hw, top), (base_cx_px + hw // 3, top + depth),
               (base_cx_px, top + int(depth * 1.15)), (base_cx_px - hw // 3, top + depth)], fill=(95, 235, 248, alpha))
    d.ellipse([base_cx_px - hw, top - 6, base_cx_px + hw, top + 14], fill=(150, 245, 250, min(255, alpha + 40)))
    fr.alpha_composite(jet.filter(ImageFilter.GaussianBlur(6)))
    return [base_cx_px - hw - 6, top - 6, base_cx_px + hw + 6, top + int(depth * 1.15) + 6]


def _body_bb(rgb):
    """WHITE-BODY bbox (achromatic bright pixels) — deliberately excludes cyan (eyes/chest/plume) and mint, so
    dimming the eyes or changing the plume does NOT move the measured scale/position. This is why the earlier
    bright|cyan blob halved when the head was dimmed."""
    a = np.asarray(rgb.convert("RGB"), float); x1 = int(TERM_LEFT * W); y0 = int(0.14 * H); y1e = int(0.94 * H)
    sub = a[y0:y1e, :x1]; R, G, Bc = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
    mn = np.minimum(np.minimum(R, G), Bc); mx = np.maximum(np.maximum(R, G), Bc)
    white = (mn > 150) & ((mx - mn) < 55)                  # graded white body ~(157,169,170); excludes cyan/mint
    ys, xs = np.where(white)
    if len(xs) < 40:
        return None
    return [int(np.percentile(xs, 2)), y0 + int(np.percentile(ys, 2)), int(np.percentile(xs, 98)), y0 + int(np.percentile(ys, 98))]


def compose(pose, cx, cy, tilt, thruster="none", dim_frac=0.0, narrow=0.0, target_h=TARGET_H, with_plume=True):
    fr = _bg()
    im = _pose_img(pose, dim_frac, narrow, target_h)
    if tilt:
        im = im.rotate(-tilt, expand=True, resample=Image.BICUBIC)      # clockwise = forward pitch / roll
    px, py = int(cx * W - im.width / 2), int(cy * H - im.height / 2)
    # contact shadow
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([int(cx * W - 120), int(0.85 * H), int(cx * W + 120), int(0.85 * H + 30)], fill=(0, 0, 0, 80))
    fr.alpha_composite(sh.filter(ImageFilter.GaussianBlur(16)))
    abox = im.split()[3].getbbox()                         # Bolt's EXACT on-frame bbox from the pasted sprite alpha
    bolt_bb = [px + abox[0], py + abox[1], px + abox[2], py + abox[3]] if abox else None
    base_cx_px = int((bolt_bb[0] + bolt_bb[2]) / 2) if bolt_bb else int(cx * W)
    base_bottom_px = (bolt_bb[3] - int(0.03 * (bolt_bb[3] - bolt_bb[1]))) if bolt_bb else py + im.height
    plume_roi = _attach_plume(fr, base_cx_px, base_bottom_px, thruster) if with_plume else None
    fr.alpha_composite(im, (px, py))
    return fr.convert("RGB"), plume_roi, bolt_bb


def author_frame(name, pose, cx=None, gap=None, center=0.50, tilt=3, thruster="none", dim_frac=0.0, narrow=0.0):
    """Body scale/position measured on a PLUME-FREE composite; final display frame rendered WITH the attached
    plume. Converges on MEASURED bright-blob height (== TARGET_MEASURED_H, ≤1.5%), MEASURED right edge
    (== TERM_LEFT-gap) and MEASURED vertical centre (== `center`) — so tilt/pose don't distort the geometry.
    Saves display + body frames."""
    if cx is None:
        cx = 0.42
    cy = center
    content_h = int(TARGET_H)

    def geom(ch, cyv, cxv):
        _, _, bb = compose(pose, cxv, cyv, tilt, "none", dim_frac, narrow, target_h=ch, with_plume=False)
        return bb
    for _ in range(14):                                    # scale to a common Bolt bbox HEIGHT (exact alpha geometry)
        bb = geom(content_h, cy, cx); mh = (bb[3] - bb[1]) if bb else 0
        if not mh:
            content_h = int(content_h * 1.2); continue
        if abs(mh - TARGET_MEASURED_H) <= TARGET_MEASURED_H * 0.012:
            break
        content_h = int(content_h * TARGET_MEASURED_H / mh)
    for _ in range(10):                                    # converge bbox vertical centre to `center`
        bb = geom(content_h, cy, cx)
        if bb:
            mc = (bb[1] + bb[3]) / 2 / H
            if abs(mc - center) < 0.005:
                break
            cy += (center - mc)
    if gap is not None:                                    # converge reaching (right) edge to (TERM_LEFT-gap)
        target_edge = TERM_LEFT - gap
        for _ in range(12):
            bb = geom(content_h, cy, cx)
            if not bb:
                break
            e = bb[2] / W
            if abs(target_edge - e) < 0.004:
                break
            cx += (target_edge - e)
    disp, plume_roi, bb = compose(pose, cx, cy, tilt, thruster, dim_frac, narrow, target_h=content_h, with_plume=True)
    body, _, bb_body = compose(pose, cx, cy, tilt, "none", dim_frac, narrow, target_h=content_h, with_plume=False)
    dp = os.path.join(PRIM, name); disp.save(dp)
    bp = dp.replace(".png", ".body.png"); body.save(bp)
    return {"display": dp, "body": bp, "cx": round(cx, 4), "plume_roi": plume_roi, "bbox": bb_body}


def eye_luminance(disp, bb):
    """Mean (G+B)/2 over a FIXED eye sub-rectangle of the bbox (the two eyes), averaging ALL pixels — no
    brightness/cyan threshold that heavy dimming would defeat. Same bbox-relative rect across frames of the
    SAME pose, so dimming the eyes reduces the value proportionally. Compare same-pose frames (B1 vs B3)."""
    a = np.asarray(Image.open(disp).convert("RGB"), float); x0, y0, x1, y1 = bb; bh = y1 - y0; bw = x1 - x0
    rect = a[int(y0 + 0.28 * bh):int(y0 + 0.44 * bh), int(x0 + 0.24 * bw):int(x1 - 0.24 * bw)]   # visor band (antenna shifts it lower in the full bbox)
    if rect.size == 0:
        return 0.0
    return float(((rect[:, :, 1] + rect[:, :, 2]) / 2).mean())


def plume_roi_proof(disp, bb, plume_roi, out):
    im = Image.open(disp).convert("RGB"); d = ImageDraw.Draw(im)
    j = DV._detect_jet(np.asarray(im, float), bb, W, H)
    d.rectangle(j["roi"], outline=(255, 210, 0), width=4); d.text((j["roi"][0], j["roi"][1] - 22), f"plume ROI frac={j['frac']}", fill=(255, 210, 0))
    if plume_roi:
        d.rectangle(plume_roi, outline=(0, 255, 180), width=2)
    d.rectangle(bb, outline=(150, 150, 255), width=2); d.text((bb[0], bb[1] - 20), "body mask", fill=(150, 150, 255))
    im.resize((W // 2, H // 2)).save(out, quality=90)
    return j["frac"]


def main():
    DV.assert_allow_paid_reset()
    # corrected negative prompt (item 10): overlay-text terms, preserve diegetic corridor signage
    NEG = ("camera movement, camera pan, camera zoom, dolly, shaking camera, reversing direction, moving "
           "backward, retreating, touching the terminal, overlapping the terminal, shrinking, growing, changing "
           "distance from camera, legs, feet, boots, lower limbs, mouth, extra arms, extra limbs, duplicate "
           "character, second robot, morphing, identity change, overlay text, captions, subtitles, watermark, "
           "HUD, on-screen UI, meters, on-body icons, blur, distortion, low quality")
    open(os.path.join(AT, "shot_A_negative_prompt_v2.txt"), "w").write(NEG)

    # 4 boundary frames. B0 near-rest (arms-down pose, upright, no plume, further left/full silhouette);
    # B1 strong difference (attached strong plume, forward pitch, rightward); B2 effortful (narrowed eyes,
    # laboured pitch); B3 strengthened weakness (eye dim>=20% + narrow + more pitch/roll + altitude loss).
    B0 = author_frame("B0_launch_start.png", POSE_REST, gap=0.250, center=0.50, tilt=2, thruster="none")
    B1 = author_frame("B1_launch_end.png", POSE_REACH, gap=0.175, center=0.50, tilt=12, thruster="strong")
    B2 = author_frame("B2_approach_end.png", POSE_REACH, gap=0.135, center=0.52, tilt=13, thruster="moderate", dim_frac=0.15, narrow=0.12)
    B3 = author_frame("B3_weakening_end.png", POSE_REACH, gap=0.100, center=0.60, tilt=15, thruster="small", dim_frac=0.75, narrow=0.42)  # sunk (hand lands at the low nozzle)
    B = {"B0": B0, "B1": B1, "B2": B2, "B3": B3}
    frames = {k: v["display"] for k, v in B.items()}; bodies = {k: v["body"] for k, v in B.items()}
    bbs = {k: B[k]["bbox"] for k in B}                      # EXACT alpha-geometry bbox (dim/plume/background invariant)

    steps = [
        {"id": "A1_hover_launch", "primitive": "launch", "action_window": [0.3, 1.4], "start": B0["display"], "end": B1["display"],
         "prompt_prefix": "The mascot robot Bolt in a dark dry oxygen corridor, LOCKED STATIC CAMERA, preserve the wall signage. Bolt "},
        {"id": "A2_effortful_approach", "primitive": "strain", "action_window": [0.4, 1.9], "start": B1["display"], "end": B2["display"],
         "prompt_prefix": "The mascot robot Bolt in a dark dry oxygen corridor, LOCKED STATIC CAMERA, preserve the wall signage. Bolt "},
        {"id": "A3_weakening_reach", "primitive": "power_loss", "action_window": [0.3, 1.5], "start": B2["display"], "end": B3["display"],
         "prompt_prefix": "The mascot robot Bolt in a dark dry oxygen corridor, LOCKED STATIC CAMERA, preserve the wall signage. Bolt ",
         "prompt_suffix": ", reaching one arm toward the wall refill terminal but stopping short without touching it"},
    ]
    plan = MP.compile_sequence(steps, negative_prompt=NEG, candidates_per_step=2, gen_duration_s=3)

    # ---- reports (deterministic-heavy) ----
    heights = {k: (bbs[k][3] - bbs[k][1]) for k in B}
    hmin, hmax = min(heights.values()), max(heights.values())
    edges = {k: bbs[k][2] / W for k in B}
    centers = {k: (bbs[k][1] + bbs[k][3]) / 2 / H for k in B}      # vertical centre = tilt-robust altitude signal
    # 2D target-anchor distance (item 7): reaching-hand centroid -> fixed terminal point
    anchor = {k: DV.target_anchor_distance(bbs[k], TERMINAL_POINT, W, H) for k in B}
    euclid = {k: anchor[k]["euclidean"] for k in B}
    # plume ROI proofs (item 4) — measured strictly below the base
    plume_frac = {}
    for k in B:
        plume_frac[k] = plume_roi_proof(frames[k], bbs[k], B[k]["plume_roi"], os.path.join(PRIM, f"{k}_plume_roi.jpg"))
    # eye luminance (item 6): require >=20% drop B0->B3
    eyeL = {k: round(eye_luminance(frames[k], bbs[k]), 1) for k in B}
    eye_drop_pct = round((1 - eyeL["B3"] / max(1e-6, eyeL["B1"])) * 100, 1)   # same pose (B1) reference isolates the dim

    report = {
        "duration_strategy": {"provider": "kling-v3-pro", "gen_duration_s": 3, "reason": "integer 3-15s only; sub-second not executable",
                              "action_windows": {s["id"]: s["action_window"] for s in steps},
                              "trim_rule": "trim to the action window ONLY after the full raw 3s clip passes anatomy+camera+world gates"},
        "scale_consistency_le_2pct": {"heights_px": heights, "ratio_spread": round(hmax / hmin, 3), "pass": (hmax / hmin) <= 1.02},
        "monotonic_approach_2d": {"euclidean_to_terminal": euclid,
                                  "pass": euclid["B0"] > euclid["B1"] > euclid["B2"] > euclid["B3"],
                                  "per_frame": anchor},
        "plume": {"attached_to_base": True, "roi_measured_below_base_only": True, "frac_by_frame": plume_frac,
                  "launch_peak": plume_frac["B1"] >= max(plume_frac["B0"], plume_frac["B2"], plume_frac["B3"]),
                  "B0_near_zero": plume_frac["B0"] <= 0.01, "decays_to_end": plume_frac["B3"] <= plume_frac["B1"] * 0.6,
                  "proofs": {k: f"primitives/{k}_plume_roi.jpg" for k in B}},
        "weakness_B3": {"eye_luminance": eyeL, "eye_drop_pct_vs_B1": eye_drop_pct, "eye_drop_ge_20pct": eye_drop_pct >= 20,
                        "altitude_drop_frac": round(centers["B3"] - centers["B0"], 4), "pitch_deg": 15,
                        "sunk_below_start": centers["B3"] > centers["B0"] + 0.03, "body_scale_fixed": (hmax / hmin) <= 1.02},
        "seam_gate_contract": {"gate": "generated_seam_gate", "when": "AFTER each adjacent pair is generated",
                               "pairs": ["A1->A2", "A2->A3"], "checks": ["background_registration", "scale_continuity",
                               "position_continuity", "identity_continuity", "lighting_continuity", "pose_velocity_continuity"],
                               "note": "authored frame-exact handoff is NOT proof of a generated seam"},
        "a3_propulsion_gate": "propulsion_decay_or_extinguish (plume present early, materially declining, may extinguish)",
        "negative_prompt_v2": "shot_A_negative_prompt_v2.txt (overlay-text terms; diegetic corridor signage preserved)",
    }
    out = {"no_spend": True, "prepared_only": True, "provider_called": False, "allow_paid_reset": DV.assert_allow_paid_reset(),
           "boundary_frames": frames, "boundary_frames_body": bodies, "steps": plan["steps"],
           "continuity_contract": plan["continuity_contract"], "spend_estimate": plan["spend_estimate"], "reports": report}
    json.dump(out, open(os.path.join(AT, "shot_A_primitive_sequence_plan.json"), "w"), indent=2, default=str)

    # comparisons
    for s in steps:
        a = Image.open(s["start"]).convert("RGB").resize((330, 586)); b = Image.open(s["end"]).convert("RGB").resize((330, 586))
        sh = Image.new("RGB", (680, 616), (12, 12, 14)); d = ImageDraw.Draw(sh)
        sh.paste(a, (0, 26)); sh.paste(b, (350, 26)); d.text((6, 6), f"{s['id']}: START", fill=(200, 220, 255)); d.text((356, 6), "END", fill=(160, 230, 160))
        sh.save(os.path.join(PRIM, f"{s['id']}_seed_end.jpg"), quality=90)
    strip = Image.new("RGB", (4 * 250 + 30, 470), (12, 12, 14)); d = ImageDraw.Draw(strip)
    for i, k in enumerate(["B0", "B1", "B2", "B3"]):
        strip.paste(Image.open(frames[k]).convert("RGB").resize((250, 444)), (i * 250 + 6, 24)); d.text((i * 250 + 8, 6), k, fill=(230, 230, 230))
    strip.save(os.path.join(PRIM, "boundary_frames_strip.jpg"), quality=90)

    r = report
    print("=== corrected 3s primitive package (PREPARED, no spend) ===")
    print("duration:", plan["spend_estimate"]["gen_duration_s"], "s x", plan["spend_estimate"]["n_candidates_worstcase"], "cand | all-in $", plan["spend_estimate"]["all_in_worstcase_usd"])
    print("scale<=2%:", r["scale_consistency_le_2pct"]["pass"], "spread", r["scale_consistency_le_2pct"]["ratio_spread"], r["scale_consistency_le_2pct"]["heights_px"])
    print("2D approach euclid:", euclid, "monotonic", r["monotonic_approach_2d"]["pass"])
    print("plume frac:", plume_frac, "| B0~0", r["plume"]["B0_near_zero"], "launch_peak", r["plume"]["launch_peak"], "decays", r["plume"]["decays_to_end"])
    print("eye luminance:", eyeL, "drop%", eye_drop_pct, ">=20%", r["weakness_B3"]["eye_drop_ge_20pct"])
    print("B3 altitude drop:", r["weakness_B3"]["altitude_drop_frac"], "sunk", r["weakness_B3"]["sunk_below_start"])
    print("ALLOW_PAID:", DV.ALLOW_PAID)


if __name__ == "__main__":
    main()
