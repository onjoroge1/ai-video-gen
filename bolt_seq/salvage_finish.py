"""Finish the no-spend salvage: comparison video + entry/exit contact sheet + report, reusing artifacts
already built by salvage_candidate_1 (phased report, trim, assembled block, det_hero). NO VLM, NO spend.
Run: python3 -m bolt_seq.salvage_finish"""
import os, sys, json, subprocess
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from bolt_seq import compiler as C
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(PROJ, "renders/bolt_seq/_oxygen_pilot"); CAND = os.path.join(OUT, "candidates")
def sh(*a): subprocess.run(a, check=True)


def label_png(text, w):
    p = os.path.join(CAND, f"_lbl_{text.replace(' ','_').replace('(','').replace(')','')}.png")
    img = Image.new("RGBA", (w, 60), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    try: f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 34)
    except Exception: f = ImageFont.load_default()
    tw = d.textbbox((0, 0), text, font=f)[2]; d.rectangle([0, 0, w, 56], fill=(0, 0, 0, 160))
    d.text(((w - tw) // 2, 8), text, font=f, fill=(245, 245, 245)); img.save(p); return p


def frame(clip, frac, name):
    p = os.path.join(CAND, name)
    sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{C.dur(clip)*frac:.2f}", "-i", clip, "-frames:v", "1", p)
    return p


def main():
    spec = json.load(open(os.path.join(OUT, "pilot_spec.json")))
    be, bx = spec["boundary"]["start_frame"], spec["boundary"]["end_frame"]
    det_hero = os.path.join(CAND, "_det_hero.mp4")
    assembled = os.path.join(OUT, "oxygen_block_candidate_1_assembled.mp4")
    endf = os.path.join(CAND, "_c1_endframe.png"); c1 = os.path.join(CAND, "cand_1.mp4")
    r = json.load(open(os.path.join(OUT, "candidate_1_revised_gate_report.json")))
    trim = json.load(open(os.path.join(OUT, "candidate_1_trim_analysis.json")))
    r0, r1 = r["candidate_0"], r["candidate_1"]

    # comparison (drawtext-free: PIL label PNGs overlaid)
    comp = os.path.join(OUT, "deterministic_vs_directed_comparison.mp4")
    lblL, lblR = label_png("DETERMINISTIC", 540), label_png("DIRECTED cand_1", 540)
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", det_hero, "-i", assembled, "-i", lblL, "-i", lblR,
       "-filter_complex",
       "[0:v]scale=540:960[l0];[2:v]scale=540:-1[ll];[l0][ll]overlay=0:0[l];"
       "[1:v]scale=540:960[r0];[3:v]scale=540:-1[rr];[r0][rr]overlay=0:0[r];[l][r]hstack=inputs=2[v]",
       "-map", "[v]", "-t", "5", comp)

    # entry/exit comparison contact sheet
    sheet = Image.new("RGB", (300 * 4, 560), (16, 16, 20)); d = ImageDraw.Draw(sheet)
    try: f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 20)
    except Exception: f = ImageFont.load_default()
    tiles = [(be, "REQ ENTRY"), (frame(c1, 0.04, "_c1start.jpg"), "CAND1 START"),
             (endf, "CAND1 END(trim)"), (bx, "REQ EXIT")]
    for i, (p, lab) in enumerate(tiles):
        im = Image.open(p).convert("RGB"); im.thumbnail((300, 533)); sheet.paste(im, (i * 300, 27))
        d.text((i * 300 + 8, 4), lab, font=f, fill=(240, 240, 240))
    csheet = os.path.join(OUT, "entry_exit_comparison_contact_sheet.jpg"); sheet.save(csheet, quality=90)

    report = {
        "no_spend": True, "provider_called": False, "allow_paid_on_disk": False,
        "candidate_0_phased": {"pass": r0["pass"], "reasons": r0["reasons"]},
        "candidate_1_phased": {"pass": r1["pass"], "reasons": r1["reasons"], "phases": r1.get("phases"),
                               "reversal": r1.get("reversal"), "identity": r1.get("identity")},
        "trim": {"best_t": trim["best_trim_t"], "scores": trim["scores"]},
        "bridge": "cross-dissolve trimmed-end→deterministic-exit + mist/flash + tunnel-vision veil (8 frames)",
        "assembled_block_s": round(C.dur(assembled), 2),
        "full_private_test_s": round(C.dur(os.path.join(OUT, "full_oxygen_private_test.mp4")), 2),
        "deterministic_layers_added": ["oxygen meter (drain 0.12→0)", "captions SO CLOSE→STALLS OUT",
                                       "visibility-loss vignette ramp", "water ambient + alarm + collapse thud",
                                       "deterministic exit bridge"],
        "outputs": ["candidate_1_revised_gate_report.json", "candidate_1_trim_analysis.json",
                    "candidate_1_boundary_bridge.mp4", "oxygen_block_candidate_1_assembled.mp4",
                    "full_oxygen_private_test.mp4", "deterministic_vs_directed_comparison.mp4",
                    "entry_exit_comparison_contact_sheet.jpg"],
    }
    json.dump(report, open(os.path.join(OUT, "no_spend_modification_report.json"), "w"), indent=2, default=str)
    print("cand0 phased:", "PASS" if r0["pass"] else "FAIL", r0["reasons"][:3])
    print("cand1 phased:", "PASS" if r1["pass"] else "FAIL", r1["reasons"][:3])
    print("cand1 phases:", {k: v["ok"] for k, v in (r1.get("phases") or {}).items()})
    print("assembled:", round(C.dur(assembled), 1), "s | full test:", report["full_private_test_s"], "s")
    print("outputs in", OUT)


if __name__ == "__main__":
    main()
