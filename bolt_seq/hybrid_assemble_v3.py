"""NO-SPEND hybrid hero block V3. Abandons same-shot difference-matting. Uses a MOTIVATED EDITORIAL CUT:
keep Candidate 1's approach (~1.6s, red O2->0, thruster flicker/cut) → a 2-4 frame red power-down pulse +
camera shake → HARD CUT to a NEW deterministic floor-level angle where the anatomy-clean collapse plays
as a real physical fall (drop + forward rotation + impact squash + floor slide + prone), portal small in
the background, Bolt clearly short of it. No rectangular patch, no crop matte. A perceptual composite gate
checks for pasted-cutout/seam artifacts. No paid generation.
Run: python3 -m bolt_seq.hybrid_assemble_v3"""
import os, sys, json, subprocess, math
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C, effects as FX
from bolt_seq.providers import directed_video as DV
from PIL import Image, ImageDraw, ImageFont, ImageFilter

P = os.path.join(PROJ, "renders/bolt_seq/_oxygen_pilot"); V2 = os.path.join(P, "hybrid_v2"); OUT = os.path.join(P, "hybrid_v3")
os.makedirs(OUT, exist_ok=True)
APPROACH = os.path.join(V2, "approach_overlaid_v2.mp4"); REDTRANS = os.path.join(V2, "_redtrans.mp4")
IMPAIRED = os.path.join(P, "bolt_impaired.png"); COL = os.path.join(P, "bolt_collapsed.png")
PORTAL = os.path.join(P, "hub_clean.png"); PLATE = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/tunnel.png")
ANIMATIC = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/oxygen_subscription_animatic.mp4")
V2_HERO = os.path.join(V2, "hybrid_hero_block_v2.mp4")
W, H, FPS = 1080, 1920, 30
def sh(*a): subprocess.run(a, check=True)
def font(s):
    try: return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", s)
    except Exception: return ImageFont.load_default()


from PIL import ImageEnhance


def grade(img, mult=0.62, tint=(30, 95, 105), tint_amt=0.26):
    """Match the deterministic cutout to the dark teal floor-level scene lighting (darken + teal tint) so
    it doesn't read as a bright pasted cutout."""
    a = img.split()[3]
    rgb = ImageEnhance.Brightness(img.convert("RGB")).enhance(mult)
    rgb = Image.blend(rgb, Image.new("RGB", img.size, tint), tint_amt)
    out = rgb.convert("RGBA"); out.putalpha(a); return out


def contact_shadow(base, cx, cy, w, op=0.5):
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0)); d = ImageDraw.Draw(sh)
    d.ellipse([cx - w * 0.55, cy - w * 0.12, cx + w * 0.55, cy + w * 0.12], fill=(0, 0, 0, int(150 * op)))
    base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))


def _paste(base, img, cx, cy, base_h, rot=0, sx=1.0, sy=1.0, blur_dy=0.0, op=1.0, do_grade=True):
    img = grade(img) if do_grade else img
    h = max(1, int(base_h * sy)); w = max(1, int(img.width * (base_h / img.height) * sx))
    im = img.resize((w, h), Image.LANCZOS)
    if rot: im = im.rotate(rot, expand=True, resample=Image.BICUBIC)
    if op < 1.0:
        al = im.split()[3].point(lambda p: int(p * op)); im.putalpha(al)
    px, py = int(cx - im.width / 2), int(cy - im.height / 2)
    if blur_dy:      # SMOOTH accumulation blur (many faint closely-spaced copies) → a motion smear, not 2 ghosts
        K = 8
        for k in range(K):
            gh = im.copy(); gh.putalpha(gh.split()[3].point(lambda p: int(p / K)))
            base.alpha_composite(gh, (px, int(py - blur_dy * (k / K))))
    else:
        base.alpha_composite(im, (px, py))


def new_angle_bg(zoom):
    """A NEW low/close framing of the tunnel (distinct from the approach's medium straight-on shot)."""
    plate = Image.open(PLATE).convert("RGB")
    tw, th = int(W * zoom), int(H * zoom)
    cov = plate.resize((max(tw, int(plate.width * th / plate.height)), th), Image.LANCZOS)
    x = int((cov.width - W) * 0.35); y = int((cov.height - H) * 0.78)   # pan low → floor-level feel
    x = max(0, min(cov.width - W, x)); y = max(0, min(cov.height - H, y))
    return cov.crop((x, y, x + W, y + H)).convert("RGBA")


def portal(scale):
    im = Image.open(PORTAL).convert("RGBA"); h = int(240 * scale)
    return im.resize((int(im.width * h / im.height), h), Image.LANCZOS)


def new_collapse_angle():
    """Fresh deterministic shot: a real physical collapse in a new floor-level angle; portal small in the
    background, Bolt clearly short of it. Meter empty, O2: 0%, subtle push + portal pulse on the hold."""
    imp = Image.open(IMPAIRED).convert("RGBA"); col = Image.open(COL).convert("RGBA")
    fdir = os.path.join(OUT, "_co"); os.makedirs(fdir, exist_ok=True)
    for f in os.listdir(fdir): os.remove(os.path.join(fdir, f))
    anim, hold = 15, 19; N = anim + hold; cap = font(88)
    px_portal, py_portal = 0.75, 0.30
    for i in range(N):
        collapsing = i < anim
        z = 1.0 + (0.04 * ((i - anim) / max(1, hold)) if not collapsing else 0.0)   # subtle camera push on hold
        fr = new_angle_bg(1.45 + 0.02 * (z - 1) * 10)
        pp = 1.0 + 0.05 * math.sin(i * 0.5)                                          # portal pulse
        pg = portal(pp); fr.alpha_composite(pg, (int(px_portal * W - pg.width / 2), int(py_portal * H - pg.height / 2)))
        cp = (i / (anim - 1)) if collapsing else 1.0; ease = cp * cp
        if cp < 0.62:            # FALL: impaired pose drops + rotates forward + ~1-frame motion smear
            cy = (0.40 + (0.70 - 0.40) * ease) * H; cx = 0.40 * W
            contact_shadow(fr, cx, 0.82 * H, 640, op=0.35 + 0.25 * cp)
            _paste(fr, imp, cx, cy, 640, rot=60 * ease, blur_dy=58 * min(1.0, cp * 2))
        elif cp < 0.8:           # IMPACT: squash + swap to collapsed (contact shadow grounds it)
            contact_shadow(fr, 0.41 * W, 0.80 * H, 640 * 1.2, op=0.6)
            _paste(fr, col, 0.41 * W, 0.71 * H, 640, rot=20, sx=1.2, sy=0.72)
        else:                    # SLIDE + settle prone, short of portal
            u = (cp - 0.8) / 0.2 if collapsing else 1.0
            contact_shadow(fr, (0.41 + 0.03 * u) * W, 0.82 * H, 630, op=0.6)
            _paste(fr, col, (0.41 + 0.03 * u) * W, 0.72 * H, 630, rot=10)
        fr.alpha_composite(FX.visibility_loss({"intensity": 0.6}, (W, H)), (0, 0))
        # red empty meter + O2 0% (fade in after the cut)
        mimg = Image.new("RGBA", (W, H), (0, 0, 0, 0)); dm = ImageDraw.Draw(mimg)
        mx, my, mw, mh = int(W * 0.08), int(H * 0.05), int(W * 0.60), int(H * 0.028)
        dm.rounded_rectangle([mx, my, mx + mw, my + mh], radius=mh // 2, fill=(0, 0, 0, 150), outline=(235, 80, 70, 200), width=3)
        dm.text((mx + mw + int(W * 0.03), my - 6), "O₂ 0%", font=font(46), fill=(255, 90, 80), stroke_width=3, stroke_fill=(0, 0, 0))
        fr.alpha_composite(mimg)
        if i >= 3:
            a = min(255, (i - 3) * 55); txt = "O₂: 0%"; d = ImageDraw.Draw(fr); tw = d.textbbox((0, 0), txt, font=cap)[2]
            x = (W - tw) // 2; y = int(H * 0.83)
            ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); do = ImageDraw.Draw(ov)
            do.rounded_rectangle([x - 36, y - 20, x + tw + 36, y + 108], radius=22, fill=(0, 0, 0, min(150, a)))
            do.text((x, y), txt, font=cap, fill=(255, 85, 75, a), stroke_width=5, stroke_fill=(0, 0, 0, a))
            fr.alpha_composite(ov)
        fr.convert("RGB").save(os.path.join(fdir, f"c{i:03d}.png"))
    out = os.path.join(OUT, "new_collapse_angle.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(fdir, "c%03d.png"),
       "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", out)
    return out


def concat_hard(clips, out):
    lst = os.path.join(OUT, "_cc.txt"); open(lst, "w").write("".join(f"file '{c}'\n" for c in clips))
    sh("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
       "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS), out)
    return out


def add_audio(block, out):
    d = C.dur(block); cut = max(0.1, d - 1.15)
    fc = (f"anoisesrc=color=brown:amplitude=0.7:duration={d},lowpass=f=360,volume=0.14[w];"
          f"sine=frequency=740:duration={d},volume=0.09,afade=t=out:st={cut:.2f}:d=0.2[al];"
          f"sine=frequency=170:duration=0.7,volume=0.35,afade=t=out:st=0.1:d=0.6,adelay={int(cut*1000)}|{int(cut*1000)}[pd];"
          f"anoisesrc=color=brown:amplitude=0.8:duration=0.4,lowpass=f=200,volume=0.5,afade=t=out:st=0.05:d=0.35,"
          f"adelay={int((d-0.95)*1000)}|{int((d-0.95)*1000)}[thud];"
          f"[w][al][pd][thud]amix=inputs=4:normalize=0[a]")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", block, "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
       "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out)
    return out


def contact_v3(approach, trans, coll):
    def grab(clip, frac, out, byf=None):
        if byf is not None:
            sh("ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf", f"select='eq(n\\,{byf})',scale=260:462", "-frames:v", "1", "-fps_mode", "passthrough", out)
        else:
            sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{C.dur(clip)*frac:.2f}", "-i", clip, "-frames:v", "1", "-vf", "scale=260:462", out)
        return out
    specs = [("approach-end", approach, 0.97, None), ("power-down", trans, None, 2), ("cut→new-angle", coll, 0.02, None),
             ("fall", coll, 0.3, None), ("impact", coll, 0.5, None), ("prone-hold", coll, 0.9, None)]
    sheet = Image.new("RGB", (260 * 3, 462 * 2 + 30), (16, 16, 20)); d = ImageDraw.Draw(sheet); ft = font(20)
    for i, (lbl, clip, frac, byf) in enumerate(specs):
        f = grab(clip, frac, os.path.join(OUT, f"_tc_{i}.jpg"), byf)
        sheet.paste(Image.open(f), ((i % 3) * 260, (i // 3) * 492 + 24)); d.text(((i % 3) * 260 + 6, (i // 3) * 492 + 2), lbl, font=ft, fill=(240, 240, 240))
    out = os.path.join(OUT, "transition_contact_sheet_v3.jpg"); sheet.save(out, quality=90); return out


def comparison(v3):
    def lbl(t, w):
        p = os.path.join(OUT, f"_lb_{t}.png"); im = Image.new("RGBA", (w, 54), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        f = font(28); tw = d.textbbox((0, 0), t, font=f)[2]; d.rectangle([0, 0, w, 50], fill=(0, 0, 0, 165))
        d.text(((w - tw) // 2, 8), t, font=f, fill=(240, 240, 240)); im.save(p); return p
    out = os.path.join(OUT, "V2_vs_V3_comparison.mp4"); dur = min(C.dur(V2_HERO), C.dur(v3))
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", V2_HERO, "-i", v3, "-i", lbl("V2", 540), "-i", lbl("V3", 540),
       "-filter_complex", "[0:v]scale=540:960[l0];[2:v]scale=540:-1[ll];[l0][ll]overlay=0:0[l];"
       "[1:v]scale=540:960[r0];[3:v]scale=540:-1[rr];[r0][rr]overlay=0:0[r];[l][r]hstack=inputs=2[v]",
       "-map", "[v]", "-t", f"{dur:.2f}", out)
    return out


def full_hybrid(hero):
    d = C.dur(ANIMATIC); head = os.path.join(OUT, "_head.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", ANIMATIC, "-t", f"{max(0,d-5.0):.2f}",
       "-vf", f"scale={W}:{H},fps={FPS}", "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", "-an", head)
    hv = os.path.join(OUT, "_herov.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", hero, "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", "-an", hv)
    return concat_hard([head, hv], os.path.join(OUT, "full_oxygen_private_hybrid_v3.mp4"))


def main():
    cost = []
    mode = DV.select_continuation_mode({"pose_changes_substantially": True, "matting_unreliable": True,
                                        "same_shot_artifacts": True, "new_angle_improves_payoff": True,
                                        "clean_alpha_matte": False, "background_seam_pass": False,
                                        "scale_lighting_perspective_preserved": False})
    print(f"continuation mode selected: {mode}", flush=True)
    coll = new_collapse_angle()
    hero_v = concat_hard([APPROACH, REDTRANS, coll], os.path.join(OUT, "_hero_v3_v.mp4"))
    hero = add_audio(hero_v, os.path.join(OUT, "hybrid_hero_block_v3.mp4"))
    tcs = contact_v3(APPROACH, REDTRANS, coll)
    cmp = comparison(hero); full = full_hybrid(hero)
    gate = DV.perceptual_composite_gate(hero, cost=cost, mode=mode)
    rep = {"no_spend": True, "video_generated": False, "allow_paid_on_disk": DV.ALLOW_PAID,
           "continuation_mode": mode, "method": "motivated editorial cut to a new deterministic angle (no matting/patch)",
           "hero_block_s": round(C.dur(hero), 2), "full_s": round(C.dur(full), 2),
           "perceptual_composite_gate": {"pass": gate["pass"], "issues": gate["issues"],
                                         "pasted_cutout": gate.get("pasted_cutout"), "scale_jump": gate.get("scale_jump")},
           "outputs": ["hybrid_hero_block_v3.mp4", "new_collapse_angle.mp4", "transition_contact_sheet_v3.jpg",
                       "V2_vs_V3_comparison.mp4", "full_oxygen_private_hybrid_v3.mp4"],
           "eval_cost_usd": round(sum(cost), 3)}
    json.dump(rep, open(os.path.join(OUT, "perceptual_composite_report.json"), "w"), indent=2, default=str)
    print(f"hero {rep['hero_block_s']}s | full {rep['full_s']}s | composite_gate pass={gate['pass']} "
          f"issues={gate['issues']} pasted={gate.get('pasted_cutout')} scalejump={gate.get('scale_jump')} | cost ${sum(cost):.2f}")
    print("outputs in", OUT)


if __name__ == "__main__":
    main()
