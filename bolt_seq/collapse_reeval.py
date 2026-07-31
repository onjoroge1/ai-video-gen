"""CORRECTED no-spend re-evaluation of the Shot-B pilot. Fixes the temporal bug: evaluate the FULL raw
provider clips, detect the atomic-collapse window, and gate the ACTION WINDOW (not the truncated head).
Anatomy is temporal + attachment-aware. Then assemble Shot A → Candidate-1 collapse window (real
generated collapse via motivated cut) → full private oxygen Short. No provider calls, no generation.
Run: python3 -m bolt_seq.collapse_reeval"""
import os, sys, json, subprocess
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C, topics as T
from bolt_seq.character import BOLT
from bolt_seq.providers import directed_video as DV
from PIL import Image, ImageDraw, ImageFont

CP = os.path.join(PROJ, "renders/bolt_seq/_oxygen_pilot/collapse_pilot"); CAND = os.path.join(CP, "candidates")
OUT = os.path.join(CP, "corrected"); os.makedirs(OUT, exist_ok=True)
RAW1 = os.path.join(CAND, "cand_1_raw.mp4"); RAW0 = os.path.join(CAND, "cand_0_raw.mp4")
APPROACH = os.path.join(PROJ, "renders/bolt_seq/_oxygen_pilot/hybrid_v2/approach_overlaid_v2.mp4")
REDTRANS = os.path.join(PROJ, "renders/bolt_seq/_oxygen_pilot/hybrid_v2/_redtrans.mp4")
SEED = os.path.join(CP, "collapse_seed.png"); ENDT = os.path.join(CP, "collapse_end_target.png")
ANIMATIC = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/oxygen_subscription_animatic.mp4")
WINDOW = os.path.join(OUT, "candidate_1_atomic_window.mp4")
W, H, FPS = 1080, 1920, 30
WIN_TECH = {"dur_min": 1.1, "dur_max": 1.8}
def sh(*a): subprocess.run(a, check=True)
def font(s):
    try: return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", s)
    except Exception: return ImageFont.load_default()


def extract_window(raw, win, out):
    sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{win['start']}", "-i", raw, "-t", f"{win['dur']}",
       "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}", "-an", out)
    return out


def gate_window(clip, cost):
    dh = T.load("oxygen_subscription")["directed_hero"]["shot_b_atomic_collapse"]
    frames = DV._frames(clip, 9, OUT)
    tg = DV.technical_gate(clip, WIN_TECH, {"motion_direction": "stationary"})
    an = DV.check_anatomy_temporal(clip, {"identity_reference": BOLT["reference"], "anatomy": BOLT["anatomy"]}, frames=frames, cost=cost)
    spec = {"identity_bible": BOLT["identity"], "anatomy": BOLT["anatomy"],
            "phase_contract": {"entities": dh["entities"], "phases": dh["phases"], "prohibited_transitions": []}}
    tv = DV.trace_vlm(clip, dh["entities"], frames, cost=cost); traces = DV._traces(tv) if "error" not in tv else []
    bad = set(an.get("persistent_lower_limb_frames", []))
    mot = DV.evaluate_phased(clip, spec, traces=traces or None, anatomy_bad=bad, tech=WIN_TECH, cost=cost, log=lambda *_: None)
    rev = DV.collapse_review_vlm(clip, SEED, ENDT, frames, cost=cost)
    flags = {"technical": tg["pass"], "anatomy_temporal": an["identity_pass"],
             "atomic_collapse_motion": mot.get("phase_motion_pass") and bool(rev.get("drops_and_collapses")),
             "portal_proximity": (not rev.get("reaches_or_touches_portal")) and bool(rev.get("bolt_short_of_portal")) and (not rev.get("pushed_or_pulled_by_portal")),
             "no_recovery": (not rev.get("recovers_or_gets_up")) and (not rev.get("heroic_relaunch")),
             "clean_plate": not rev.get("ui_seen"),
             "exit_boundary": bool(rev.get("end_clearly_collapsed")) and (rev.get("end_matches_target", 0) >= 6)}
    return {"all_pass": all(flags.values()), "flags": flags, "anatomy": an, "motion": mot.get("reasons"), "review": rev}


def timeline(raw, win):
    dur = C.dur(raw); n = 10; strip_h = 300; tw = 150
    img = Image.new("RGB", (tw * n, strip_h + 70), (14, 14, 18)); d = ImageDraw.Draw(img)
    for i in range(n):
        t = dur * (i + 0.5) / n; fp = os.path.join(OUT, f"_tl_{i}.jpg")
        sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", raw, "-frames:v", "1", "-vf", f"scale={tw}:{strip_h}", fp)
        img.paste(Image.open(fp), (i * tw, 40))
    def x_of(t): return int((t / dur) * tw * n)
    d.rectangle([x_of(win["start"]), 36, x_of(win["end"]), strip_h + 44], outline=(90, 220, 120), width=5)
    d.text((x_of(win["start"]) + 4, 4), f"collapse window {win['start']}-{win['end']}s", font=font(22), fill=(90, 230, 130))
    d.line([x_of(2.0), 36, x_of(2.0), strip_h + 44], fill=(235, 70, 60), width=4)
    d.text((x_of(2.0) - 150, strip_h + 46), "OLD 2.0s cutoff (bug)", font=font(22), fill=(235, 90, 80))
    d.text((6, strip_h + 46), f"raw {dur:.2f}s", font=font(22), fill=(220, 220, 220))
    out = os.path.join(OUT, "raw_vs_normalized_timeline.jpg"); img.save(out, quality=90); return out


def caption_png(txt):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img); f = font(88)
    tw = d.textbbox((0, 0), txt, font=f)[2]; x = (W - tw) // 2; y = int(H * 0.83)
    d.rounded_rectangle([x - 36, y - 20, x + tw + 36, y + 108], radius=22, fill=(0, 0, 0, 150))
    d.text((x, y), txt, font=f, fill=(255, 85, 75), stroke_width=5, stroke_fill=(0, 0, 0))
    p = os.path.join(OUT, "_cap_oxzero.png"); img.save(p); return p


def concat_hard(clips, out):
    lst = os.path.join(OUT, "_cc.txt"); open(lst, "w").write("".join(f"file '{c}'\n" for c in clips))
    sh("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
       "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS), out)
    return out


def assemble(window):
    # burn O2:0% over the collapse window (deterministic finish); keep the generated collapse motion intact
    wc = os.path.join(OUT, "_window_cap.mp4"); cap = caption_png("O₂: 0%"); wd = C.dur(window)
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", window, "-loop", "1", "-i", cap, "-filter_complex",
       f"[0:v][1:v]overlay=0:0:enable='between(t,0.35,{wd})'[v]", "-map", "[v]", "-t", f"{wd}",
       "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", wc)
    body = concat_hard([APPROACH, REDTRANS, wc], os.path.join(OUT, "_hero_v4_v.mp4")); d = C.dur(body)
    cut = max(0.1, d - wd)
    fc = (f"anoisesrc=color=brown:amplitude=0.7:duration={d},lowpass=f=360,volume=0.14[w];"
          f"sine=frequency=740:duration={d},volume=0.09,afade=t=out:st={cut:.2f}:d=0.2[al];"
          f"sine=frequency=170:duration=0.7,volume=0.32,afade=t=out:st=0.1:d=0.6,adelay={int(cut*1000)}|{int(cut*1000)}[pd];"
          f"anoisesrc=color=brown:amplitude=0.8:duration=0.4,lowpass=f=200,volume=0.5,afade=t=out:st=0.05:d=0.35,"
          f"adelay={int((d-wd+0.9)*1000)}|{int((d-wd+0.9)*1000)}[thud];[w][al][pd][thud]amix=inputs=4:normalize=0[a]")
    hero = os.path.join(OUT, "shotA_to_candidate1_assembly.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", body, "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
       "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", hero)
    dd = C.dur(ANIMATIC); head = os.path.join(OUT, "_head.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", ANIMATIC, "-t", f"{max(0,dd-5.0):.2f}",
       "-vf", f"scale={W}:{H},fps={FPS}", "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", "-an", head)
    hv = os.path.join(OUT, "_herov.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", hero, "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", "-an", hv)
    full = concat_hard([head, hv], os.path.join(OUT, "full_oxygen_private_hybrid_v4.mp4"))
    return hero, full


def main():
    cost = []
    win1 = DV.detect_action_window(RAW1, cost=cost); win0 = DV.detect_action_window(RAW0, cost=cost)
    print("cand1 window:", win1["start"], "-", win1["end"], "events:", win1["events"], flush=True)
    print("cand0 window:", win0["start"], "-", win0["end"], "events:", win0["events"], flush=True)
    extract_window(RAW1, win1, WINDOW)
    # global mutation scan on FULL raw + shot acceptance on the WINDOW
    full_an1 = DV.check_anatomy_temporal(RAW1, {"identity_reference": BOLT["reference"], "anatomy": BOLT["anatomy"]}, cost=cost)
    g1 = gate_window(WINDOW, cost)
    # cand 0: reclassify — it DOES collapse, reject for wrong causal (thrust strengthens into the dive)
    rev0 = DV.collapse_review_vlm(RAW0, SEED, ENDT, DV._frames(RAW0, 9, OUT), cost=cost)
    an0 = DV.check_anatomy_temporal(RAW0, {"identity_reference": BOLT["reference"], "anatomy": BOLT["anatomy"]}, cost=cost)
    tl = timeline(RAW1, win1)
    hero, full = assemble(WINDOW)

    json.dump({"provider_generation_duration_s": win1["raw_dur"], "requested_delivery_duration_s": win1["dur"],
               "cand1_window": win1, "cand0_window": win0,
               "bug": "candidates were truncated to 2.0s BEFORE evaluation; collapse occurs ~2.1-2.6s"},
              open(os.path.join(OUT, "event_detection_report.json"), "w"), indent=2, default=str)
    json.dump({"cand1_full_raw": {"identity_pass": full_an1["identity_pass"],
               "persistent_lower_limb_frames": full_an1["persistent_lower_limb_frames"],
               "transient_lower_limb_frames": full_an1["transient_lower_limb_frames"], "features": full_an1["features"]},
               "cand1_window": {"identity_pass": g1["anatomy"]["identity_pass"],
               "persistent": g1["anatomy"]["persistent_lower_limb_frames"], "transient": g1["anatomy"]["transient_lower_limb_frames"]},
               "cand0_full_raw": {"identity_pass": an0["identity_pass"], "persistent": an0["persistent_lower_limb_frames"]},
               "note": "temporal + attachment-aware: single-frame lower-limb flags during a tip are transient (arm/rotation), not mutations"},
              open(os.path.join(OUT, "corrected_anatomy_report.json"), "w"), indent=2, default=str)
    json.dump({"candidate_1": {"window_s": [win1["start"], win1["end"]], "gate": g1["flags"],
               "all_pass_automated": g1["all_pass"], "verdict": "PROVISIONAL PASS pending manual review" if g1["all_pass"] else "still failing: " + str([k for k, v in g1["flags"].items() if not v]),
               "review": g1["review"], "motion_reasons": g1["motion"]},
               "candidate_0": {"reclassified": "collapses but REJECT — incorrect causal motion (thrust "
               "STRENGTHENS and propels Bolt into the dive; not a power-loss collapse)",
               "heroic_relaunch": rev0.get("heroic_relaunch"), "drops_and_collapses": rev0.get("drops_and_collapses")}},
              open(os.path.join(OUT, "corrected_atomic_collapse_report.json"), "w"), indent=2, default=str)
    print("\n=== CORRECTED CANDIDATE 1 (window) GATE ===")
    for k, v in g1["flags"].items(): print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print("cand1 all_pass_automated:", g1["all_pass"], "| verdict:", "PROVISIONAL PASS pending manual review" if g1["all_pass"] else "FAIL")
    print("cand1 full-raw anatomy persistent lower-limb frames:", full_an1["persistent_lower_limb_frames"], "transient:", full_an1["transient_lower_limb_frames"])
    print("cand0:", "collapses but wrong causal (heroic relaunch=%s)" % rev0.get("heroic_relaunch"))
    print(f"hero {C.dur(hero):.2f}s | full {C.dur(full):.2f}s | window {C.dur(WINDOW):.2f}s | cost ${sum(cost):.2f} (VLM only, no spend)")
    print("outputs in", OUT)


if __name__ == "__main__":
    main()
