"""NO-SPEND hybrid hero block: keep ONLY Candidate 1's generated APPROACH motion, then produce the
oxygen-zero event + collapse deterministically. Atomic-action split in practice:
  generated action  = struggling approach (paid clip, trimmed before portal touch)
  deterministic event = oxygen reaches zero (draining meter + shrinking tracked bubble + vignette + flicker)
  controlled payoff  = propulsion failure + hard-cut to an approved anatomy-clean collapsed pose short of the portal
No cross-dissolve of two Bolt compositions; a motivated flash/shake hard transition instead. No video spend.
Run: python3 -m bolt_seq.hybrid_assemble"""
import os, sys, json, subprocess, math
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C, effects as FX, scene_graph as SG
from bolt_seq.character import BOLT
from bolt_seq.providers import directed_video as DV
from PIL import Image, ImageDraw, ImageFont, ImageFilter

P = os.path.join(PROJ, "renders/bolt_seq/_oxygen_pilot"); OUT = os.path.join(P, "hybrid"); os.makedirs(OUT, exist_ok=True)
CAND1 = os.path.join(P, "candidates_v2/cand_1.mp4")
COL = os.path.join(P, "bolt_collapsed.png"); PORTAL = os.path.join(P, "hub_clean.png")
PLATE = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/tunnel.png")
ANIMATIC = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/oxygen_subscription_animatic.mp4")
W, H, FPS = 1080, 1920, 30
def sh(*a): subprocess.run(a, check=True)


def font(sz):
    try: return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", sz)
    except Exception: return ImageFont.load_default()


def get_track(cost):
    frames = DV._frames(CAND1, 12, OUT)
    tr = DV.trace_vlm(CAND1, {"hero": BOLT["identity"], "destination": "the glowing green oxygen portal ring"},
                      frames, cost=cost)
    pf = sorted(tr.get("per_frame", []), key=lambda x: x.get("i", 0))
    dur = C.dur(CAND1); n = len(pf)
    track = []
    for f in pf:
        bb = f.get("hero_bbox") or [0.25, 0.4, 0.24, 0.3]
        i = f.get("i", 0); t = dur * (i + 0.5) / n
        track.append((t, bb[0] + bb[2] / 2, bb[1] + bb[3] / 2))
    cy = [c for _, _, c in track]
    collapse_idx = next((i for i, c in enumerate(cy) if c > 0.6), n - 1)   # floor = collapse onset
    trim_idx = max(2, collapse_idx - 3)                                    # keep approach, drop arrive+fall
    t_trim = round(dur * (trim_idx + 0.5) / n, 2)
    return track, dur, t_trim


def interp(track, t):
    pts = [(tt, cx, cy) for tt, cx, cy in track]
    if t <= pts[0][0]: return pts[0][1], pts[0][2]
    if t >= pts[-1][0]: return pts[-1][1], pts[-1][2]
    for (t0, x0, y0), (t1, x1, y1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            u = (t - t0) / ((t1 - t0) or 1e-9); return x0 + (x1 - x0) * u, y0 + (y1 - y0) * u
    return pts[-1][1], pts[-1][2]


def safe_trim(t_trim):
    out = os.path.join(OUT, "candidate_1_safe_trim.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", CAND1, "-t", f"{t_trim}",
       "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}", "-an", out)
    return out


def bubble(r):
    s = max(8, int(r * 2) + 8); im = Image.new("RGBA", (s, s), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for rr in range(int(r), 0, -1):
        a = int(60 * (rr / r) ** 0.6); d.ellipse([s // 2 - rr, s // 2 - rr, s // 2 + rr, s // 2 + rr],
                                                 fill=(175, 218, 255, max(8, 50 - a // 2)))
    d.ellipse([s // 2 - int(r), s // 2 - int(r), s // 2 + int(r), s // 2 + int(r)], outline=(220, 242, 255, 200), width=3)
    d.ellipse([int(s * 0.36), int(s * 0.30), int(s * 0.5), int(s * 0.44)], fill=(255, 255, 255, 190))
    return im.filter(ImageFilter.GaussianBlur(0.8))


def overlay_approach(trim, track, hud=True):
    """Composite deterministic oxygen-reserve bubble (tracked child) + draining meter + rising vignette +
    flickering thruster over the generated approach. hud=False → bubble-only tracking test."""
    d = C.dur(trim); fdir = os.path.join(OUT, "_ap_bubble" if not hud else "_ap_hud"); os.makedirs(fdir, exist_ok=True)
    for f in os.listdir(fdir): os.remove(os.path.join(fdir, f))
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", trim, "-vf", f"fps={FPS}", os.path.join(fdir, "s%04d.png"))
    src = sorted(os.path.join(fdir, x) for x in os.listdir(fdir) if x.startswith("s"))
    for i, sp in enumerate(src):
        t = i / FPS; u = min(1.0, t / (d or 1e-9))
        fr = Image.open(sp).convert("RGBA")
        cx, cy = interp(track, t)
        if hud:
            fr.alpha_composite(FX.visibility_loss({"intensity": 0.12 + 0.45 * u}, (W, H)), (0, 0))
            fr.alpha_composite(FX.resource_meter({"fill": max(0.0, 0.35 * (1 - u)), "warn": 0.3}, (W, H)), (0, 0))
            # thruster flicker at Bolt's base (cuts out toward zero)
            flick = (0.6 + 0.4 * math.sin(t * 44)) * (1.0 if u < 0.8 else (0.2 if int(t * 20) % 2 else 0.8))
            tg = Image.new("RGBA", (W, H), (0, 0, 0, 0)); dt = ImageDraw.Draw(tg)
            bx, by = int(cx * W), int(cy * H + 0.12 * H)
            for rr, aa in ((70, 60), (40, 110), (18, 200)):
                dt.ellipse([bx - rr, by - rr, bx + rr, by + rr], fill=(120, 220, 255, int(aa * flick)))
            fr.alpha_composite(tg.filter(ImageFilter.GaussianBlur(6)), (0, 0))
        # tracked shrinking oxygen bubble (deterministic child — NOT the Kling bubble)
        br = 82 * (1 - 0.85 * u)
        bub = bubble(br); fr.alpha_composite(bub, (int(cx * W + 0.10 * W - bub.width / 2), int(cy * H - 0.10 * H - bub.height / 2)))
        fr.convert("RGB").save(sp)
    out = os.path.join(OUT, "approach_overlaid.mp4" if hud else "deterministic_bubble_tracking_test.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(fdir, "s%04d.png"),
       "-t", f"{d}", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", out)
    return out


def transition(approach):
    """Oxygen-zero event: ~5 frames of white flash + shake + blur off the LAST approach frame (masks the cut)."""
    d = C.dur(approach); last = os.path.join(OUT, "_last.png")
    sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0,d-0.05):.2f}", "-i", approach, "-frames:v", "1", last)
    base = Image.open(last).convert("RGB"); fdir = os.path.join(OUT, "_tr"); os.makedirs(fdir, exist_ok=True)
    for f in os.listdir(fdir): os.remove(os.path.join(fdir, f))
    N = 6
    for i in range(N):
        u = i / (N - 1); fr = base.copy()
        dx, dy = int(28 * math.sin(i * 2.3) * (1 - u)), int(20 * math.cos(i * 3.1) * (1 - u))
        fr = fr.transform((W, H), Image.AFFINE, (1, 0, dx, 0, 1, dy))
        fr = fr.filter(ImageFilter.GaussianBlur(6 * (1 - u) + 1))
        fl = Image.new("RGBA", (W, H), (255, 255, 255, int(235 * (1 - abs(u - 0.3) * 2 if u < 0.8 else 40))))
        comp = fr.convert("RGBA"); comp.alpha_composite(fl); comp.convert("RGB").save(os.path.join(fdir, f"t{i:03d}.png"))
    out = os.path.join(OUT, "oxygen_zero_transition.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(fdir, "t%03d.png"),
       "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", out)
    return out


def collapse_scene(dur=1.4):
    """Approved anatomy-clean collapsed Bolt, clearly SHORT of the portal; empty meter; heavy vignette;
    causal payoff caption OXYGEN: 0."""
    ents = [
        {"id": "env", "kind": "environment", "provider": "deterministic_2d", "z": 0, "base_h": H, "image": PLATE,
         "tracks": {"scale": SG.track([(0, 1.06), (1, 1.10)])}},
        {"id": "portal", "kind": "destination", "provider": "deterministic_2d", "z": 20, "base_h": 520, "image": PORTAL,
         "tracks": {"x": SG.const_track(0.74), "y": SG.const_track(0.44)}},
        {"id": "bolt", "kind": "character", "provider": "deterministic_2d", "z": 50, "base_h": 560, "image": COL,
         "tracks": {"x": SG.const_track(0.33), "y": SG.const_track(0.74)}},   # collapsed, short of the portal
        {"id": "vig", "kind": "effect", "provider": "deterministic_2d", "draw": "visibility_loss", "z": 60,
         "base_h": H, "tracks": {"opacity": SG.const_track(1.0), "intensity": SG.const_track(0.6)}},
        {"id": "meter", "kind": "meter", "provider": "deterministic_2d", "draw": "resource_meter", "z": 80,
         "base_h": H, "tracks": {"opacity": SG.const_track(1.0), "fill": SG.const_track(0.0), "warn": SG.const_track(0.3)}},
    ]
    base = os.path.join(OUT, "_collapse_base.mp4")
    C.render_scene_block(base, ents, dur, W=W, H=H, fps=FPS, tmp_dir=OUT, draw_fn=FX.draw, tmix=1)
    # burn the causal payoff caption (PIL overlay; drawtext unavailable)
    cap = os.path.join(OUT, "_cap_oxzero.png"); img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    f = font(96); txt = "OXYGEN: 0"; tw = d.textbbox((0, 0), txt, font=f)[2]; x = (W - tw) // 2; y = int(H * 0.80)
    d.rounded_rectangle([x - 40, y - 24, x + tw + 40, y + 120], radius=24, fill=(0, 0, 0, 150))
    d.text((x, y), txt, font=f, fill=(255, 90, 80), stroke_width=5, stroke_fill=(0, 0, 0)); img.save(cap)
    out = os.path.join(OUT, "_collapse_scene.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", base, "-loop", "1", "-i", cap, "-filter_complex",
       f"[0:v][1:v]overlay=0:0:enable='between(t,0.15,{dur})'[v]", "-map", "[v]", "-t", f"{dur}",
       "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", out)
    return out


def concat_hard(clips, out):
    lst = os.path.join(OUT, "_cc.txt")
    with open(lst, "w") as fh:
        for c in clips: fh.write(f"file '{c}'\n")
    # re-encode (uniform params) so the hard cut is clean; NO cross-dissolve
    sh("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
       "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS), out)
    return out


def add_audio(block, out):
    d = C.dur(block)
    fc = (f"anoisesrc=color=brown:amplitude=0.7:duration={d},lowpass=f=360,volume=0.14[w];"
          f"sine=frequency=760:duration={d},volume=0.10,afade=t=in:st={max(0,d-1.6):.2f}:d=1.2[al];"  # rising alarm
          f"anoisesrc=color=white:amplitude=0.9:duration=0.5,volume=0.5,afade=t=out:st=0.08:d=0.4,"
          f"adelay={int((d-1.55)*1000)}|{int((d-1.55)*1000)}[imp];"  # impact at the oxygen-zero cut
          f"[w][al][imp]amix=inputs=3:normalize=0[a]")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", block, "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
       "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out)
    return out


def full_hybrid(hero):
    d = C.dur(ANIMATIC); head = os.path.join(OUT, "_head.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", ANIMATIC, "-t", f"{max(0,d-5.0):.2f}",
       "-vf", f"scale={W}:{H},fps={FPS}", "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", "-an", head)
    hv = os.path.join(OUT, "_herov.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", hero, "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", "-an", hv)
    out = os.path.join(OUT, "full_oxygen_private_hybrid.mp4")
    return concat_hard([head, hv], out)


def contact_sheet(clip, out_jpg, n=8):
    d = C.dur(clip); sheet = Image.new("RGB", (216 * 4, 384 * 2), (16, 16, 20))
    for i in range(n):
        fp = out_jpg + f".{i}.jpg"
        sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{d*(i+0.5)/n:.2f}", "-i", clip, "-frames:v", "1", "-vf", "scale=216:384", fp)
        sheet.paste(Image.open(fp), ((i % 4) * 216, (i // 4) * 384))
    sheet.save(out_jpg, quality=88); return out_jpg


def comparison(hybrid):
    det = os.path.join(OUT, "_det_hero.mp4"); dd = C.dur(ANIMATIC)
    sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0,dd-5):.2f}", "-i", ANIMATIC, "-t", "5",
       "-vf", f"scale={W}:{H},fps={FPS}", "-an", det)
    def lbl(text, w):
        p = os.path.join(OUT, f"_lb_{text.replace(' ','_')}.png"); im = Image.new("RGBA", (w, 56), (0, 0, 0, 0))
        d = ImageDraw.Draw(im); f = font(30); tw = d.textbbox((0, 0), text, font=f)[2]
        d.rectangle([0, 0, w, 52], fill=(0, 0, 0, 160)); d.text(((w - tw) // 2, 8), text, font=f, fill=(240, 240, 240)); im.save(p); return p
    out = os.path.join(OUT, "deterministic_vs_hybrid_comparison.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", det, "-i", hybrid, "-i", lbl("DETERMINISTIC", 540), "-i", lbl("HYBRID (cand_1 approach)", 540),
       "-filter_complex", "[0:v]scale=540:960[l0];[2:v]scale=540:-1[ll];[l0][ll]overlay=0:0[l];"
       "[1:v]scale=540:960[r0];[3:v]scale=540:-1[rr];[r0][rr]overlay=0:0[r];[l][r]hstack=inputs=2[v]",
       "-map", "[v]", "-t", "5", out)
    return out


def main():
    cost = []
    track, dur, t_trim = get_track(cost)
    print(f"cand_1 dur {dur:.2f}s → safe trim at {t_trim}s (approach only, before touch/fall)", flush=True)
    trim = safe_trim(t_trim)
    btest = overlay_approach(trim, track, hud=False)
    approach = overlay_approach(trim, track, hud=True)
    trans = transition(approach)
    coll = collapse_scene()
    hero_v = concat_hard([approach, trans, coll], os.path.join(OUT, "_hero_v.mp4"))
    hero = add_audio(hero_v, os.path.join(OUT, "hybrid_hero_block.mp4"))
    full = full_hybrid(hero)
    cs = contact_sheet(hero, os.path.join(OUT, "hybrid_hero_contact_sheet.jpg"))
    cmp = comparison(hero)
    # anatomy re-check of the DETERMINISTIC collapse pose (the paid clip's collapse is discarded)
    an = DV.anatomy_vlm(COL, BOLT["reference"], BOLT["anatomy"], [(0, COL)], cost=cost)
    col_clean = not any(f.get("prohibited_seen") or f.get("required_altered") for f in an.get("per_frame", []))
    rep = {"no_spend": True, "video_generated": False, "allow_paid_on_disk": DV.ALLOW_PAID,
           "safe_trim_s": t_trim, "cand1_full_s": round(dur, 2),
           "atomic_split": {"generated": "struggling_approach (trimmed cand_1)",
                            "deterministic_event": "oxygen_zero (draining meter + shrinking tracked bubble + vignette + flicker)",
                            "controlled_payoff": "propulsion failure + hard-cut to anatomy-clean collapsed pose short of portal"},
           "collapse_pose_anatomy_clean": col_clean,
           "transition": "flash + shake + blur hard cut (NO cross-dissolve)",
           "payoff_caption": "OXYGEN: 0",
           "hybrid_hero_block_s": round(C.dur(hero), 2), "full_hybrid_s": round(C.dur(full), 2),
           "outputs": ["candidate_1_safe_trim.mp4", "deterministic_bubble_tracking_test.mp4",
                       "oxygen_zero_transition.mp4", "hybrid_hero_block.mp4", "full_oxygen_private_hybrid.mp4",
                       "hybrid_hero_contact_sheet.jpg", "deterministic_vs_hybrid_comparison.mp4"],
           "eval_cost_usd": round(sum(cost), 3)}
    json.dump(rep, open(os.path.join(OUT, "no_spend_hybrid_report.json"), "w"), indent=2, default=str)
    print(f"hero block {rep['hybrid_hero_block_s']}s | full {rep['full_hybrid_s']}s | collapse anatomy-clean {col_clean} | cost ${sum(cost):.2f}")
    print("outputs in", OUT)


if __name__ == "__main__":
    main()
