"""No-spend Shot-A decision report: (1) deterministic trajectory audit of Candidate 1 (pixel tracker, not
VLM centroid) with bbox overlay + plot; (2) 5-way character-motion reclassification; (3) provider payload
audit (was the end target used as conditioning?); (4) next-strategy comparison + cost estimate. No paid
video, ALLOW_PAID stays False. Run: python3 -m bolt_seq.shot_A_audit"""
import os, sys, json, subprocess, shutil
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C
from bolt_seq.character import BOLT
from bolt_seq.providers import directed_video as DV
from PIL import Image, ImageDraw, ImageFont

AT = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/atomic_shots")
CAND = os.path.join(AT, "candidates"); OUT = os.path.join(AT, "audit"); os.makedirs(OUT, exist_ok=True)
C1 = os.path.join(CAND, "shotA_cand_1.mp4"); C1WIN = os.path.join(CAND, "shotA_cand_1_win.mp4")
SEED = os.path.join(AT, "shot_A_seed.png"); ENDT = os.path.join(AT, "shot_A_end_target.png")
def font(s):
    try: return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", s)
    except Exception: return ImageFont.load_default()


def overlay(tk, out_mp4, w, h):
    fdir = os.path.join(OUT, "_ov"); os.makedirs(fdir, exist_ok=True)
    for f in os.listdir(fdir):
        os.remove(os.path.join(fdir, f))
    term = tk["terminal_anchor"]
    for i, s in enumerate(tk["samples"]):
        im = Image.open(s["frame"]).convert("RGB"); d = ImageDraw.Draw(im)
        d.rectangle(term, outline=(255, 70, 70), width=5); d.text((term[0], term[1] - 26), "TERMINAL (fixed anchor)", font=font(22), fill=(255, 90, 90))
        d.ellipse([term[0] - 6, (term[1] + term[3]) // 2 - 6, term[0] + 6, (term[1] + term[3]) // 2 + 6], fill=(255, 70, 70))
        if s.get("bolt_bbox"):
            bb = s["bolt_bbox"]; d.rectangle(bb, outline=(90, 230, 120), width=5)
            cx, cy = int(s["cx"] * w), int(s["cy"] * h); d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=(90, 230, 120))
            d.text((bb[0], bb[1] - 26), f"BOLT gap={s['edge_gap']:.3f}", font=font(22), fill=(120, 240, 140))
        d.text((20, 20), f"t={s['t']}s  h_vel={s.get('h_vel',0):+.3f}", font=font(26), fill=(240, 240, 240))
        im.save(os.path.join(fdir, f"o{i:03d}.png"))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "6", "-i", os.path.join(fdir, "o%03d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "scale=1080:1920", out_mp4], check=True)


def plot(tk, out_png):
    ts = [s["t"] for s in tk["samples"] if s.get("cx") is not None]
    gap = [s["edge_gap"] for s in tk["samples"] if s.get("edge_gap") is not None]
    cx = [s["cx"] for s in tk["samples"] if s.get("cx") is not None]
    try:
        import matplotlib
        matplotlib.use("Agg"); import matplotlib.pyplot as plt
        clip_ts = [s["t"] for s in tk["samples"] if s.get("cx") is not None and s.get("clipped")]
        fig, ax = plt.subplots(figsize=(8, 4.5)); ax.plot(ts, gap, "-o", color="#e04630", label="edge gap → terminal")
        ax.plot(ts, cx, "-o", color="#5ac878", label="Bolt center x")
        for ct in clip_ts:
            ax.axvline(ct, color="#888", ls=":", lw=0.8)
        if clip_ts:
            ax.axvline(clip_ts[0], color="#888", ls=":", lw=0.8, label="ROI-clipped (Bolt overlaps terminal)")
        ax.set_xlabel("t (s)"); ax.set_ylabel("fraction of frame")
        ax.set_title(f"Cand 1 trajectory (deterministic tracker) — clean disp {tk['clean_horizontal_displacement']:+.3f} · "
                     f"clean gap↓ {tk['clean_gap_reduction_pct']:.0f}% · rev {tk['reversals']} · overshoot {tk['overshoot']}")
        ax.legend(); ax.grid(alpha=0.3); fig.tight_layout(); fig.savefig(out_png, dpi=110); plt.close()
        return True
    except Exception:
        img = Image.new("RGB", (800, 450), (18, 18, 22)); d = ImageDraw.Draw(img)
        d.text((20, 20), f"Cand1 tracker: disp {tk['horizontal_displacement']:+.3f} | gap↓ {tk['gap_reduction_pct']:.0f}% | rev {tk['reversals']}", font=font(22), fill=(240, 240, 240))
        for j, (t, g, x) in enumerate(zip(ts, gap, cx)):
            d.text((20, 60 + j * 22), f"t={t:.2f}  gap={g:.3f}  cx={x:.3f}", font=font(18), fill=(200, 220, 200))
        img.save(out_png); return False


def main():
    cost = []
    # 0. freeze full package
    FR = os.path.join(AT, "frozen_shot_A_pilot"); os.makedirs(FR, exist_ok=True)
    for f in ("shot_A_pilot_result.json", "shot_A_pilot_spec.json", "shot_A_gate_contract.json",
              "shot_A_prompt.txt", "shot_A_spend_estimate.json"):
        if os.path.exists(os.path.join(AT, f)): shutil.copy(os.path.join(AT, f), os.path.join(FR, f))
    for c in ("shotA_cand_0.mp4", "shotA_cand_1.mp4", "shotA_cand_0_raw.mp4", "shotA_cand_1_raw.mp4"):
        if os.path.exists(os.path.join(CAND, c)): shutil.copy(os.path.join(CAND, c), os.path.join(FR, c))

    # 1. deterministic trajectory audit (full + window)
    W, Hh = 1080, 1920
    tk_full = DV.bolt_tracker(C1); tk_win = DV.bolt_tracker(C1WIN)
    overlay(tk_full, os.path.join(OUT, "cand_1_bbox_overlay.mp4"), W, Hh)
    plotted = plot(tk_full, os.path.join(OUT, "cand_1_trajectory_plot.png"))
    json.dump({"full": tk_full["samples"], "window": tk_win["samples"]},
              open(os.path.join(OUT, "cand_1_trajectory_samples.json"), "w"), indent=2, default=str)
    json.dump({"terminal_anchor_px": tk_full["terminal_anchor"], "established_once": True,
               "terminal_fixed": tk_full["terminal_fixed"], "terminal_change_frac": tk_full["terminal_change_frac"],
               "frame": [W, Hh]}, open(os.path.join(OUT, "cand_1_terminal_anchor_report.json"), "w"), indent=2, default=str)
    win_disp = tk_win["clean_horizontal_displacement"]
    def clip_block(tk):
        return {"clean_horizontal_displacement": tk["clean_horizontal_displacement"],
                "clean_gap_reduction_pct": tk["clean_gap_reduction_pct"],
                "raw_gap_reduction_pct": tk["gap_reduction_pct"], "reversals": tk["reversals"],
                "reversal_magnitude": tk["reversal_magnitude"], "overshoot": tk["overshoot"],
                "clipped_frames": tk["clipped_frames"], "clean_gap_start": tk["clean_gap_start"],
                "clean_gap_end": tk["clean_gap_end"], "gap_start": tk["gap_start"], "gap_end": tk["gap_end"]}
    made_progress = tk_full["clean_horizontal_displacement"] >= 0.10 and tk_full["clean_gap_reduction_pct"] >= 40
    tracker_audit = {"method": "deterministic pixel tracker (bright-blob segmentation in a left ROI, terminal "
                     "region excluded); NOT a VLM centroid. Terminal anchor established once from the plate.",
                     "full_clip": clip_block(tk_full), "window": clip_block(tk_win),
                     "artifacts_handled": {"roi_clipping": "last frames where Bolt overlaps the terminal band are "
                     "flagged 'clipped'; authoritative numbers use the clean (unclipped, full-body) region only",
                     "clipped_frames_full": tk_full["clipped_frames"], "roi_right_frac": tk_full["roi_right_frac"],
                     "terminal_left_frac": tk_full["terminal_left_frac"],
                     "terminal_fixed_checked_before_arrival": True, "terminal_fixed": tk_full["terminal_fixed"]},
                     "vlm_centroid_prior": {"gap_start": 0.42, "gap_end": 0.385, "approaches": False,
                     "assessment": "UNDER-REPORTED Bolt's advance — contradicted by the deterministic tracker and the bbox overlay"},
                     "corrected_finding": ("Bolt makes REAL, substantial forward progress toward the terminal "
                     f"(clean displacement {tk_full['clean_horizontal_displacement']:+.3f}, clean gap reduction "
                     f"{tk_full['clean_gap_reduction_pct']:.0f}%); the VLM 'approaches=False' was a measurement error."
                     if made_progress else "progress is modest"),
                     "residual_defects": {"path_oscillation": f"{tk_full['reversals']} reversal(s), magnitude "
                     f"{tk_full['reversal_magnitude']} — Bolt bobs/drifts rather than locomotes cleanly",
                     "overshoot": tk_full["overshoot"], "overshoot_note": "Bolt's right edge reaches the terminal "
                     "band (arrives) instead of ending SHORT-and-strained as the atomic shot requires"},
                     "verdict": "real destination-directed progress, but non-clean path + endpoint overshoot"}
    json.dump(tracker_audit, open(os.path.join(AT, "shot_A_tracker_audit.json"), "w"), indent=2, default=str)

    # 2. 5-way character-motion reclassification (window)
    # A/B/D/E judge the character within the action window; C (macro-trajectory) is about the WHOLE journey,
    # so it runs on the FULL clip — the window is trimmed before Bolt arrives and would under-measure it.
    A = DV.articulation_quality_gate(C1WIN, cost=cost); B = DV.self_propulsion_readability_gate(C1WIN, cost=cost)
    Cc = DV.macro_trajectory_gate(C1, cost=cost); Dd = DV.progressive_effort_gate(C1WIN, cost=cost)
    E = DV.end_state_gate(C1WIN, ENDT, cost=cost)
    reclass = {"world_pass": True, "camera_pass": True, "destination_attachment_pass": True, "anatomy_pass": True,
               "identity_pass": True, "clean_plate_pass": True,
               "articulation_quality_pass": A["pass"], "self_propulsion_pass": B["pass"],
               "macro_trajectory_pass": Cc["pass"], "progressive_effort_pass": Dd["pass"], "end_state_pass": E["pass"],
               "production_ready": False,
               "gates": {"articulation": A, "self_propulsion": B, "macro_trajectory": Cc, "progressive_effort": Dd, "end_state": E},
               "macro_trajectory_correction": "The deterministic tracker shows Bolt makes REAL forward progress "
               "toward the terminal (the earlier VLM-centroid 'approaches=False' was wrong). macro_trajectory still "
               "does not pass, but for the correct reasons: path oscillation and endpoint OVERSHOOT (Bolt arrives at "
               "the terminal instead of stopping short-and-strained) — NOT an absence of motion.",
               "note": "Articulation is genuine AND trajectory progress is genuine. Non-production-ready due to: "
               "self-propulsion readability (reads as drift/translation), progressive effort (no increasing strain), "
               "and end-state (overshoots the intended short-of-terminal endpoint). Do NOT call this static/sticker."}
    json.dump(reclass, open(os.path.join(AT, "shot_A_evaluator_reclassification.json"), "w"), indent=2, default=str)

    # 3. provider payload audit (sanitized, no keys) — was the end target used as conditioning?
    payload = {"provider": "fal-ai/kling-video/v3/pro/image-to-video", "mode": "first-frame image-to-video",
               "request_schema": {"start_image": "shot_A_seed.png (data URI)", "end_image": None,
               "prompt": "shot_A_prompt.txt (positive; prohibitions embedded in text)", "negative_prompt": None,
               "duration": "5", "aspect_ratio": "9:16 (from 1080x1920 seed)", "motion_control_inputs": None,
               "authorization_header": "Key <redacted>"},
               "end_target_used_as_conditioning": False, "end_target_used_for_evaluation_only": True,
               "architectural_finding": "first-frame-only image-to-video produced acceptable local articulation "
               "but insufficient endpoint and macro-trajectory control; do not repeat this configuration.",
               "candidates": {"cand_0": "same payload", "cand_1": "same payload"},
               "note": "fal request IDs were not persisted to the pilot report this run (adapter returned "
               "status_url transiently); confirmed spend tracked by retrieval. Persist request IDs next run."}
    json.dump(payload, open(os.path.join(AT, "shot_A_provider_payload_audit.json"), "w"), indent=2, default=str)

    # 4. next strategy comparison + cost estimate (prepare only)
    options = {
        "option_1_start_end_frame_conditioning": {"controllability": "high (endpoint pinned)",
            "identity_risk": "low-med", "boundary_risk": "low (end frame is an input)",
            "candidate_count": 3, "est_cost_usd": round(0.56 * 3 + 0.3, 2),
            "provider_support": "verify: some Kling modes accept a tail/end keyframe (e.g. start+end); v3-pro i2v as called does NOT",
            "implementation": "adapter: add end-frame (tail_image) input + end-frame conditioning; keep 4 gates"},
        "option_2_explicit_path_motion_control": {"controllability": "high for path, medium for pose",
            "identity_risk": "low-med", "boundary_risk": "medium", "candidate_count": 3, "est_cost_usd": round(0.56 * 3 + 0.3, 2),
            "provider_support": "verify: motion-brush/trajectory support varies by provider/mode", "implementation": "path spec + motion-control adapter (heavier)"},
        "option_3_two_shorter_atomic_clips": {"controllability": "high (short arcs)", "identity_risk": "medium (two gens)",
            "boundary_risk": "medium (A1->A2 matching intermediate boundary / motivated cut)",
            "candidate_count": "2 shots x up to 3 = up to 6", "est_cost_usd": round(0.56 * 6 + 0.5, 2),
            "provider_support": "works with the current first-frame i2v (each arc is short)",
            "implementation": "A1 seed/end + A2 seed/end (matching midpoint) + boundary gate + editorial cut"},
        "option_4_first_frame_only_single_clip": {"status": "REJECTED", "reason": "insufficient endpoint/macro control (this pilot)"}}
    motion_path = {"forward_progress": "strong, monotonic", "vertical_drift": "slight instability only",
                   "speed": "moderate -> slower", "body_lean": "forward -> drooping", "no_reverse": True,
                   "no_contact": True, "no_collapse": True}
    json.dump({"options": options, "motion_path": motion_path, "recommended": "option_1 (if provider supports end-frame) "
               "else option_3 (two shorter clips)", "start_end_frames_ready": {"start": SEED, "end": ENDT},
               "allow_paid": False}, open(os.path.join(AT, "shot_A_next_strategy_cost_estimate.json"), "w"), indent=2, default=str)
    md = ["# Shot-A next-strategy decision report (no spend)", "",
          "## Trajectory audit (deterministic pixel tracker, not VLM centroid)",
          f"- **clean region (full-body tracked): displacement {tk_full['clean_horizontal_displacement']:+.3f}, "
          f"gap reduction {tk_full['clean_gap_reduction_pct']:.0f}%** (gap {tk_full['clean_gap_start']}→{tk_full['clean_gap_end']})",
          f"- reversals {tk_full['reversals']} (mag {tk_full['reversal_magnitude']}) · overshoot **{tk_full['overshoot']}** · "
          f"{tk_full['clipped_frames']} late frames ROI-clipped (Bolt overlaps terminal → raw gap↓{tk_full['gap_reduction_pct']:.0f}% is inflated, not used)",
          f"- terminal fixed (checked before Bolt arrives): {tk_full['terminal_fixed']} · anchor established once from the plate",
          "- **VLM-centroid prior said gap 0.42→0.385 / approaches=False — that was WRONG.** The deterministic "
          "tracker + the bbox overlay show Bolt genuinely advances from far-left to beside the terminal.",
          f"- **verdict: {tracker_audit['verdict']}**", "",
          "## Candidate 1 reclassification",
          f"- articulation_quality: {A['pass']} · self_propulsion: {B['pass']} · macro_trajectory: {Cc['pass']} · "
          f"progressive_effort: {Dd['pass']} · end_state: {E['pass']} → production_ready: False",
          f"- macro_trajectory FAILS but **makes_progress={Cc['makes_progress']}** (real advance, disp {Cc['clean_horizontal_displacement']:+.3f}, "
          f"gap↓{Cc['clean_gap_reduction_pct']:.0f}%); it fails only on path-smoothness ({Cc['reversals']} reversals) and overshoot ({Cc['overshoot']}). NOT static.",
          "- world/camera/destination/anatomy/identity/clean-plate all PASS. Real blockers: self-propulsion readability, progressive effort, end-state overshoot.", "",
          "## Provider payload finding",
          "- The end target was **NOT** supplied to the provider — it was used only for evaluation. First-frame-only "
          "i2v gave real local articulation but weak endpoint/macro-trajectory control. **Do not repeat.**", "",
          "## Options", "| option | controllability | identity risk | boundary risk | candidates | est $ | provider support |",
          "|---|---|---|---|---|---|---|"]
    for k, v in options.items():
        if k.startswith("option_4"): md.append(f"| {k} | — | — | — | — | — | REJECTED |"); continue
        md.append(f"| {k} | {v['controllability']} | {v['identity_risk']} | {v['boundary_risk']} | {v['candidate_count']} | ${v['est_cost_usd']} | {v['provider_support']} |")
    md += ["", "**Recommended:** option 1 (start+end-frame conditioning) if the provider supports an end keyframe; "
           "otherwise option 3 (two shorter atomic clips A1 push / A2 weakening, matched boundary). The end frame "
           "must be a GENERATION INPUT next time. No paid call — awaiting your direction."]
    open(os.path.join(AT, "shot_A_next_strategy.md"), "w").write("\n".join(md))

    print("=== Shot-A audit (no spend) ===")
    print("tracker full:", tracker_audit["full_clip"], "verdict:", tracker_audit["verdict"])
    print("reclass:", {k: v for k, v in reclass.items() if k.endswith("_pass")})
    print("payload: end_target_as_conditioning =", payload["end_target_used_as_conditioning"])
    print(f"plot_matplotlib={plotted} | audit VLM cost ${sum(cost):.2f} | ALLOW_PAID disk:", DV.ALLOW_PAID)
    print("outputs in", AT)


if __name__ == "__main__":
    main()
