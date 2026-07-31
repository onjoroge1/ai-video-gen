"""NO-SPEND salvage of Candidate 1: re-evaluate both paid clips with the phase-aware gate, salvage the
exit with a deterministic boundary bridge, and composite a private assembled test (deterministic meter,
captions, vignette, warnings, SFX). NO provider calls, NO new generation, ALLOW_PAID stays False.
Run: python3 -m bolt_seq.salvage_candidate_1"""
import os, sys, json, subprocess, base64
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C, effects as FX
from bolt_seq.providers import directed_video as DV
from PIL import Image

OUT = os.path.join(PROJ, "renders/bolt_seq/_oxygen_pilot")
CAND = os.path.join(OUT, "candidates")
OXY = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/oxygen_subscription_animatic.mp4")
W, H, FPS = 1080, 1920, 30
def sh(*a): subprocess.run(a, check=True)


def extract(clip, d):
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf", f"scale={W}:{H},fps={FPS}",
       os.path.join(d, "f%04d.png"))
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".png"))


def hud(frame_png, fill, vig, cap, out_png):
    """Composite deterministic HUD over ONE generated frame: oxygen meter (fill), vignette, caption."""
    im = Image.open(frame_png).convert("RGBA")
    im.alpha_composite(FX.resource_meter({"fill": fill, "warn": 0.25, "x": 0.08, "y": 0.07,
                                          "w": 0.84, "h": 0.03}, (W, H)))
    if vig > 0.01:
        im.alpha_composite(FX.visibility_loss({"intensity": vig}, (W, H)))
    if cap:
        cp = out_png + ".cap.png"; C.caption_png(cap, cp)
        im.alpha_composite(Image.open(cp).convert("RGBA"))
    im.convert("RGB").save(out_png)


def encode(frames, out):
    d = os.path.dirname(frames[0])
    sh("ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(d, "f%04d.png"),
       "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", out)
    return out


def main():
    cost = []
    spec = json.load(open(os.path.join(OUT, "pilot_spec.json")))
    spec["identity_bible"] = spec.get("identity_bible") or "the mascot robot Bolt"
    boundary_exit = spec["boundary"]["end_frame"]; boundary_entry = spec["boundary"]["start_frame"]
    c1 = os.path.join(CAND, "cand_1.mp4"); c0 = os.path.join(CAND, "cand_0.mp4")

    # 1) PHASE-AWARE re-evaluation of both paid clips (no generation)
    print("== phase-aware re-eval (no spend) ==", flush=True)
    r0 = DV.evaluate_phased(c0, spec, cost=cost, log=print)
    r1 = DV.evaluate_phased(c1, spec, cost=cost, log=print)
    json.dump({"candidate_0": r0, "candidate_1": r1},
              open(os.path.join(OUT, "candidate_1_revised_gate_report.json"), "w"), indent=2, default=str)
    print(f"  cand0 phased: {'PASS' if r0['pass'] else 'FAIL'} {r0['reasons'][:3]}")
    print(f"  cand1 phased: {'PASS' if r1['pass'] else 'FAIL'} {r1['reasons'][:3]}")

    # 2) TRIM ANALYSIS — pick the cand_1 frame that best matches the required final state
    print("== trim analysis (no spend) ==", flush=True)
    dur1 = C.dur(c1); trim_scores = []
    import explainer_pipeline as ep
    for t in (dur1 * 0.75, dur1 * 0.85, dur1 * 0.93, dur1 - 0.05):
        fp = os.path.join(CAND, f"_trim_{t:.2f}.jpg")
        sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", c1, "-frames:v", "1",
           "-vf", f"scale={W}:{H}", fp)
        pf = C.preflight(fp, ["the robot is collapsed/slumped/limp on or near the ground",
                              "a large green oxygen portal is close and prominent",
                              "there is NO air bubble", "exactly one robot, identity intact"], cost_sink=cost)
        trim_scores.append({"t": round(t, 2), "violations": pf["violations"], "score": 4 - len(pf["violations"])})
    best = max(trim_scores, key=lambda s: s["score"])
    json.dump({"scores": trim_scores, "best_trim_t": best["t"],
               "rationale": "highest match to collapsed-near-prominent-portal, no bubble"},
              open(os.path.join(OUT, "candidate_1_trim_analysis.json"), "w"), indent=2, default=str)
    print(f"  best trim @ {best['t']}s ({best['score']}/4)")
    trim_t = best["t"]

    # 3) DETERMINISTIC BOUNDARY BRIDGE: trimmed cand_1 end -> deterministic exit frame (mist+flash conceal)
    print("== deterministic boundary bridge (no spend) ==", flush=True)
    endf = os.path.join(CAND, "_c1_endframe.png")
    sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{trim_t:.2f}", "-i", c1, "-frames:v", "1",
       "-vf", f"scale={W}:{H}", endf)
    bdir = os.path.join(CAND, "_bridge_frames"); os.makedirs(bdir, exist_ok=True)
    for f in os.listdir(bdir):
        os.remove(os.path.join(bdir, f))
    A = Image.open(endf).convert("RGBA"); B = Image.open(boundary_exit).convert("RGBA").resize((W, H))
    NB = 8
    for i in range(NB):
        u = i / (NB - 1)
        fr = Image.blend(A.convert("RGB"), B.convert("RGB"), u).convert("RGBA")   # cross-dissolve
        flash = max(0.0, 1 - abs(u - 0.5) * 2)                                    # peak mist/flash mid-bridge
        fr.alpha_composite(FX.fog_whiteout({"intensity": 0.55 * flash}, (W, H)))
        fr.alpha_composite(FX.visibility_loss({"intensity": 0.85}, (W, H)))       # oxygen-zero tunnel vision
        fr.alpha_composite(Image.open(_capcache("STALLS OUT")).convert("RGBA"))
        fr.convert("RGB").save(os.path.join(bdir, f"f{i:04d}.png"))
    bridge = os.path.join(OUT, "candidate_1_boundary_bridge.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
       "-i", os.path.join(bdir, "f%04d.png"), "-c:v", "libx264", "-preset", "medium", "-crf", "19",
       "-pix_fmt", "yuv420p", "-r", str(FPS), bridge)

    # 4) ASSEMBLE the hero block: trimmed cand_1 + HUD (draining meter + vignette + captions) + bridge + audio
    print("== assemble private block (no spend) ==", flush=True)
    trimmed = os.path.join(CAND, "_c1_trimmed.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", c1, "-t", f"{trim_t:.2f}",
       "-vf", f"scale={W}:{H},fps={FPS}", "-an", trimmed)
    hdir = os.path.join(CAND, "_hud_frames")
    frames = extract(trimmed, hdir); M = len(frames)
    for i, fp in enumerate(frames):
        u = i / max(1, M - 1)
        cap = "SO CLOSE" if u < 0.6 else "STALLS OUT"
        hud(fp, fill=max(0.0, 0.12 * (1 - u)), vig=0.2 + 0.6 * u, cap=cap, out_png=fp)  # meter drains, view tunnels
    hero_hud = os.path.join(CAND, "_hero_hud.mp4"); encode(frames, hero_hud)
    body = os.path.join(CAND, "_assembled_body.mp4")
    _concat([hero_hud, bridge], body)
    # audio: water ambient + alarm at start + collapse thud near the bridge, over a silent VO bed
    dur_body = C.dur(body)
    sil = os.path.join(CAND, "_sil.wav")
    sh("ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo",
       "-t", f"{dur_body:.2f}", sil)
    audio = C.build_audio(sil, dur_body, [(0.2, "alarm"), (max(0.1, trim_t - 0.1), "impact")],
                          os.path.join(CAND, "_assembled_audio.m4a"), CAND, ambient="water")
    assembled = os.path.join(OUT, "oxygen_block_candidate_1_assembled.mp4")
    C.mux(body, audio, assembled)
    print(f"  assembled block: {C.dur(assembled):.1f}s")

    # 5) FULL private test: oxygen Short with its final ~hero seconds replaced by the assembled block
    print("== full private test + comparison (no spend) ==", flush=True)
    oxy_dur = C.dur(OXY); cut = max(0, oxy_dur - dur_body)
    head = os.path.join(CAND, "_oxy_head.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", OXY, "-t", f"{cut:.2f}",
       "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-c:a", "aac", "-ac", "2", head)
    full = os.path.join(OUT, "full_oxygen_private_test.mp4")
    _concat_av([head, assembled], full)

    # 6) deterministic-vs-directed comparison (the deterministic climax vs the directed block, side by side)
    det_hero = os.path.join(CAND, "_det_hero.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{cut:.2f}", "-i", OXY,
       "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-an", det_hero)
    comp = os.path.join(OUT, "deterministic_vs_directed_comparison.mp4")
    lblL = _label_png("DETERMINISTIC", 540); lblR = _label_png("DIRECTED (cand_1)", 540)  # drawtext-free labels
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", det_hero, "-i", assembled, "-i", lblL, "-i", lblR,
       "-filter_complex",
       "[0:v]scale=540:960[l0];[2:v]scale=540:-1[ll];[l0][ll]overlay=0:0[l];"
       "[1:v]scale=540:960[r0];[3:v]scale=540:-1[rr];[r0][rr]overlay=0:0[r];"
       "[l][r]hstack=inputs=2[v]", "-map", "[v]", "-t", "5", comp)

    # entry/exit comparison contact sheet
    sheet = Image.new("RGB", (300 * 4, 533), (16, 16, 20))
    tiles = [(boundary_entry, "REQ ENTRY"), (_frame(c1, 0.05), "CAND1 START"),
             (endf, "CAND1 END(trim)"), (boundary_exit, "REQ EXIT")]
    for i, (p, _) in enumerate(tiles):
        im = Image.open(p).convert("RGB"); im.thumbnail((300, 533)); sheet.paste(im, (i * 300, 0))
    csheet = os.path.join(OUT, "entry_exit_comparison_contact_sheet.jpg"); sheet.save(csheet, quality=90)

    # no-spend modification report
    report = {
        "no_spend": True, "provider_called": False, "allow_paid": DV.ALLOW_PAID,
        "candidate_0_phased": {"pass": r0["pass"], "reasons": r0["reasons"]},
        "candidate_1_phased": {"pass": r1["pass"], "reasons": r1["reasons"], "phases": r1.get("phases")},
        "trim": {"best_t": trim_t, "scores": trim_scores},
        "bridge": {"frames": NB, "method": "cross-dissolve trimmed-end→deterministic-exit + mist/flash + tunnel-vision veil"},
        "assembled_block_s": round(C.dur(assembled), 2),
        "deterministic_layers_added": ["oxygen meter (drain 0.12→0)", "captions SO CLOSE→STALLS OUT",
                                       "visibility-loss vignette ramp", "water ambient + alarm + collapse thud"],
        "outputs": ["candidate_1_revised_gate_report.json", "candidate_1_trim_analysis.json",
                    "candidate_1_boundary_bridge.mp4", "oxygen_block_candidate_1_assembled.mp4",
                    "full_oxygen_private_test.mp4", "deterministic_vs_directed_comparison.mp4",
                    "entry_exit_comparison_contact_sheet.jpg"],
        "reeval_vlm_cost_usd": round(sum(cost), 3),
    }
    json.dump(report, open(os.path.join(OUT, "no_spend_modification_report.json"), "w"), indent=2, default=str)
    print(f"\nDONE (no spend). cand1 phased={'PASS' if r1['pass'] else 'FAIL'} | assembled {C.dur(assembled):.1f}s "
          f"| reeval VLM ${sum(cost):.2f} | {OUT}")


# helpers
_CAPS = {}
def _capcache(text):
    if text not in _CAPS:
        p = os.path.join(CAND, f"_cap_{text.replace(' ','_')}.png"); C.caption_png(text, p); _CAPS[text] = p
    return _CAPS[text]

def _label_png(text, w):
    from PIL import ImageDraw, ImageFont
    p = os.path.join(CAND, f"_lbl_{text.replace(' ','_').replace('(','').replace(')','')}.png")
    img = Image.new("RGBA", (w, 60), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    try: f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 34)
    except Exception: f = ImageFont.load_default()
    tw = d.textbbox((0, 0), text, font=f)[2]
    d.rectangle([0, 0, w, 56], fill=(0, 0, 0, 150))
    d.text(((w - tw) // 2, 8), text, font=f, fill=(245, 245, 245))
    img.save(p); return p

def _frame(clip, frac):
    p = os.path.join(CAND, f"_fr_{os.path.basename(clip)}_{frac}.jpg")
    sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{C.dur(clip)*frac:.2f}", "-i", clip, "-frames:v", "1", p)
    return p

def _concat(clips, out):
    lst = os.path.join(CAND, "_cc.txt"); open(lst, "w").write("".join(f"file '{c}'\n" for c in clips))
    sh("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out)
    return out

def _concat_av(clips, out):
    # re-encode concat (A+V may differ) via filter concat
    ins = [];
    for c in clips: ins += ["-i", c]
    n = len(clips)
    fc = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
    sh("ffmpeg", "-y", "-loglevel", "error", *ins, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
       "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-ac", "2", out)
    return out


if __name__ == "__main__":
    main()
