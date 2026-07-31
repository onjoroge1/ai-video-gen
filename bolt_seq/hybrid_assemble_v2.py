"""NO-SPEND hybrid hero block V2. Corrects V1: trim BEFORE any portal overlap (~1.65s); oxygen meter is
RED from frame one (O2 12%->0%); no big deterministic bubble (Kling's small bubbles = ambient); red
power-failure flicker transition (not a white flash / not a collision); and the collapse is DERIVED from
the EXACT last generated frame — its background, portal, camera, lighting and Bolt scale are inherited
(no separately composed scene). Continuation invariant checked. No paid generation.
Run: python3 -m bolt_seq.hybrid_assemble_v2"""
import os, sys, json, subprocess, math
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
from bolt_seq import compiler as C, effects as FX
from bolt_seq.character import BOLT
from bolt_seq.providers import directed_video as DV
from PIL import Image, ImageDraw, ImageFont, ImageFilter

P = os.path.join(PROJ, "renders/bolt_seq/_oxygen_pilot"); OUT = os.path.join(P, "hybrid_v2"); os.makedirs(OUT, exist_ok=True)
CAND1 = os.path.join(P, "candidates_v2/cand_1.mp4")
IMPAIRED = os.path.join(P, "bolt_impaired.png"); COL = os.path.join(P, "bolt_collapsed.png")
ANIMATIC = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription/oxygen_subscription_animatic.mp4")
V1_HERO = os.path.join(P, "hybrid/hybrid_hero_block.mp4")
W, H, FPS = 1080, 1920, 30
T_TRIM = 1.65
def sh(*a): subprocess.run(a, check=True)
def font(s):
    try: return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", s)
    except Exception: return ImageFont.load_default()


def track_bbox(cost):
    frames = DV._frames(CAND1, 12, OUT)
    tr = DV.trace_vlm(CAND1, {"hero": BOLT["identity"], "destination": "the glowing green oxygen portal ring"},
                      frames, cost=cost)
    pf = sorted(tr.get("per_frame", []), key=lambda x: x.get("i", 0)); dur = C.dur(CAND1); n = len(pf)
    tk = []
    for f in pf:
        bb = f.get("hero_bbox") or [0.26, 0.36, 0.24, 0.3]; i = f.get("i", 0)
        tk.append((dur * (i + 0.5) / n, bb[0] + bb[2] / 2, bb[1] + bb[3] / 2, bb[2], bb[3]))
    return tk, dur


def interp_bbox(tk, t):
    if t <= tk[0][0]: return tk[0][1:]
    if t >= tk[-1][0]: return tk[-1][1:]
    for a, b in zip(tk, tk[1:]):
        if a[0] <= t <= b[0]:
            u = (t - a[0]) / ((b[0] - a[0]) or 1e-9)
            return tuple(a[k] + (b[k] - a[k]) * u for k in range(1, 5))
    return tk[-1][1:]


def red_meter(u):
    """Red O2 meter from frame 1: fill = 12%*(1-u) draining to 0, live 'O2 nn%' label. Never green."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    x, y, w, h = int(W * 0.08), int(H * 0.05), int(W * 0.60), int(H * 0.028)
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=(0, 0, 0, 150), outline=(235, 80, 70, 200), width=3)
    fill = max(0.0, 0.12 * (1 - u))
    if fill > 0:
        d.rounded_rectangle([x + 3, y + 3, x + 3 + int((w - 6) * (fill / 0.12)), y + h - 3], radius=h // 2, fill=(235, 70, 60, 245))
    pct = max(0, int(round(12 * (1 - u))))
    d.text((x + w + int(W * 0.03), y - 6), f"O₂ {pct}%", font=font(46), fill=(255, 90, 80), stroke_width=3, stroke_fill=(0, 0, 0))
    return img


def approach_v2(cost):
    trim = os.path.join(OUT, "candidate_1_safe_trim_v2.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", CAND1, "-t", f"{T_TRIM}",
       "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}", "-an", trim)
    d = C.dur(trim); fdir = os.path.join(OUT, "_ap"); os.makedirs(fdir, exist_ok=True)
    for f in os.listdir(fdir): os.remove(os.path.join(fdir, f))
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", trim, "-vf", f"fps={FPS}", os.path.join(fdir, "s%04d.png"))
    src = sorted(os.path.join(fdir, x) for x in os.listdir(fdir) if x.startswith("s"))
    tk, _ = track_bbox.cache if hasattr(track_bbox, "cache") else (None, None)
    for i, sp in enumerate(src):
        u = min(1.0, (i / FPS) / (d or 1e-9)); fr = Image.open(sp).convert("RGBA")
        fr.alpha_composite(FX.visibility_loss({"intensity": 0.15 + 0.5 * u}, (W, H)), (0, 0))  # vignette tightens
        fr.alpha_composite(red_meter(u), (0, 0))
        # thruster flicker at Bolt base (intensifying stutter toward the cut)
        cx, cy, bw, bh = interp_bbox(_TK, i / FPS)
        flick = (0.6 + 0.4 * math.sin((i / FPS) * 46)) * (1.0 if u < 0.7 else (0.15 if i % 2 else 0.9))
        tg = Image.new("RGBA", (W, H), (0, 0, 0, 0)); dt = ImageDraw.Draw(tg)
        bx, by = int(cx * W), int((cy + bh * 0.45) * H)
        for rr, aa in ((60, 55), (34, 110), (16, 190)):
            dt.ellipse([bx - rr, by - rr, bx + rr, by + rr], fill=(120, 220, 255, int(aa * flick)))
        fr.alpha_composite(tg.filter(ImageFilter.GaussianBlur(6)), (0, 0))
        fr.convert("RGB").save(sp)
    out = os.path.join(OUT, "approach_overlaid_v2.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(fdir, "s%04d.png"),
       "-t", f"{d}", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", out)
    return out, trim


def inherited_bg(trim):
    """Derive the continuation background from the EXACT last generated frame: patch Bolt out (copy the
    empty tunnel strip to his left), preserving portal/background/camera/lighting. Returns the bg, Bolt
    bbox, and the untouched last frame (for isolating the real Bolt)."""
    last = os.path.join(OUT, "_lastgen.png")
    sh("ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.04", "-i", trim, "-frames:v", "1", last)
    im = Image.open(last).convert("RGB")
    cx, cy, bw, bh = interp_bbox(_TK, C.dur(trim))
    x0 = int((cx - bw * 0.62) * W); x1 = min(int((cx + bw * 0.62) * W), int(0.52 * W))  # cap before portal (~0.55)
    y0 = int((cy - bh * 0.62) * H); y1 = min(int((cy + bh * 0.7) * H), H)
    wpx = x1 - x0; srcx = max(0, x0 - wpx)
    im.paste(im.crop((srcx, y0, srcx + wpx, y1)), (x0, y0))
    im = im.filter(ImageFilter.GaussianBlur(0.6))
    out = os.path.join(OUT, "inherited_background_frame.png"); im.save(out)
    return out, (cx, cy, bw, bh), last


def isolate_bolt(last, bg, start):
    """Isolate the ACTUAL generated Bolt from the last frame via difference against the patched bg — so
    the collapse inherits the real protagonist (same orientation/scale/appearance/thruster), not a swap."""
    from PIL import ImageChops
    a = Image.open(last).convert("RGB"); b = Image.open(bg).convert("RGB")
    mask = ImageChops.difference(a, b).convert("L").point(lambda p: 255 if p > 26 else 0).filter(ImageFilter.GaussianBlur(2))
    cx, cy, bw, bh = start
    x0, x1 = int((cx - bw * 0.8) * W), int((cx + bw * 0.8) * W)
    y0, y1 = int((cy - bh * 0.85) * H), min(int((cy + bh * 0.95) * H), H)
    region = Image.new("L", a.size, 0); ImageDraw.Draw(region).rectangle([x0, y0, x1, y1], fill=255)
    mask = ImageChops.multiply(mask, region)
    iso = a.convert("RGBA"); iso.putalpha(mask); iso = iso.crop((x0, y0, x1, y1))
    return iso, ((x0 + x1) / 2, (y0 + y1) / 2)   # sprite + its center in px


def _paste_bolt(base, img, cx, cy, base_h, rot, sx, sy, blur_dy):
    h = max(1, int(base_h * sy)); w = max(1, int(img.width * (base_h / img.height) * sx))
    im = img.resize((w, h), Image.LANCZOS)
    if rot: im = im.rotate(rot, expand=True, resample=Image.BICUBIC)
    px, py = int(cx - im.width / 2), int(cy - im.height / 2)
    if blur_dy:                                    # vertical motion-blur ghosts
        for g, a in ((-0.6, 90), (-0.3, 150)):
            gh = im.copy(); al = gh.split()[3].point(lambda p: int(p * a / 255)); gh.putalpha(al)
            base.alpha_composite(gh, (px, int(py + blur_dy * g)))
    base.alpha_composite(im, (px, py))


def collapse_anim(bg_path, start, iso, iso_center, anim=14, hold=20):
    """Collapse DERIVED from the inherited frame: it BEGINS with the real generated Bolt (iso sprite at
    its exact position/scale/orientation) tipping forward and sinking with motion blur; only once it is
    low and blurred does it settle into the anatomy-clean prone pose SHORT of the portal. Meter empty;
    'O2: 0%' fades in a few frames after the threshold; subtle camera push on the held beat."""
    cx0, cy0, bw, bh = start; icx, icy = iso_center
    col = Image.open(COL).convert("RGBA"); bgim = Image.open(bg_path).convert("RGB")
    fdir = os.path.join(OUT, "_co"); os.makedirs(fdir, exist_ok=True)
    for f in os.listdir(fdir): os.remove(os.path.join(fdir, f))
    cap = font(84); N = anim + hold; floor_y = 0.75 * H; short_x = min(cx0, 0.34) * W
    for i in range(N):
        collapsing = i < anim; cp = (i / (anim - 1)) if collapsing else 1.0
        z = 1.0 + (0.035 * ((i - anim) / max(1, hold)) if not collapsing else 0.0)   # subtle push on the hold
        bw2, bh2 = int(W * z), int(H * z)
        fr = bgim.resize((bw2, bh2), Image.LANCZOS).crop(((bw2 - W) // 2, (bh2 - H) // 2, (bw2 - W) // 2 + W, (bh2 - H) // 2 + H)).convert("RGBA")
        ease = cp * cp
        if cp < 0.5:      # EARLY: the REAL generated Bolt (iso), tipping + sinking + motion blur
            cx = icx + (short_x - icx) * ease; cy = icy + (floor_y - icy) * ease
            rot = 46 * ease; blur = 0.16 * H * (cp * 2)
            _paste_bolt(fr, iso, cx, cy, iso.height, rot, 1.0, 1.0, blur)
        else:             # LATE: anatomy-clean prone pose settling on the floor (masked by the prior blur)
            u2 = (cp - 0.5) / 0.5
            cy = floor_y + (0.02 * H) * u2; sx, sy = (1.18, 0.72) if 0.55 <= cp <= 0.7 else (1.0, 1.0)
            blur = 0.10 * H * (1 - u2) if collapsing else 0
            _paste_bolt(fr, col, short_x, cy, iso.height * 0.98, 8, sx, sy, blur)
        fr.alpha_composite(FX.visibility_loss({"intensity": 0.62}, (W, H)), (0, 0))
        fr.alpha_composite(red_meter(1.0), (0, 0))    # empty meter, O2 0%
        if i >= 4:                                    # caption fades in AFTER the power-fail (not on frame 0)
            ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
            a = min(255, (i - 4) * 60); txt = "O₂: 0%"; tw = d.textbbox((0, 0), txt, font=cap)[2]
            x = (W - tw) // 2; y = int(H * 0.82)
            d.rounded_rectangle([x - 36, y - 20, x + tw + 36, y + 104], radius=22, fill=(0, 0, 0, min(150, a)))
            d.text((x, y), txt, font=cap, fill=(255, 85, 75, a), stroke_width=5, stroke_fill=(0, 0, 0, a))
            fr.alpha_composite(ov)
        fr.convert("RGB").save(os.path.join(fdir, f"c{i:03d}.png"))
    out = os.path.join(OUT, "deterministic_collapse_animation.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(fdir, "c%03d.png"),
       "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", out)
    return out


def red_transition(approach):
    """3-4 frame RED power-failure flicker + directional blur + camera drop (NOT white, NOT a collision)."""
    d = C.dur(approach); last = os.path.join(OUT, "_apl.png")
    sh("ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.04", "-i", approach, "-frames:v", "1", last)
    base = Image.open(last).convert("RGB"); fdir = os.path.join(OUT, "_tr"); os.makedirs(fdir, exist_ok=True)
    for f in os.listdir(fdir): os.remove(os.path.join(fdir, f))
    for i in range(4):
        fr = base.copy().transform((W, H), Image.AFFINE, (1, 0, 0, 0, 1, int(10 + 16 * i)))  # camera drop
        fr = fr.filter(ImageFilter.GaussianBlur(0)).filter(ImageFilter.BoxBlur((6, 0)))       # horizontal blur
        red = Image.new("RGBA", (W, H), (200, 20, 15, [150, 60, 170, 40][i]))                 # red flicker (not white)
        comp = fr.convert("RGBA"); comp.alpha_composite(red); comp.convert("RGB").save(os.path.join(fdir, f"t{i:03d}.png"))
    out = os.path.join(OUT, "_redtrans.mp4")
    sh("ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(fdir, "t%03d.png"),
       "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", out)
    return out


def concat_hard(clips, out):
    lst = os.path.join(OUT, "_cc.txt")
    open(lst, "w").write("".join(f"file '{c}'\n" for c in clips))
    sh("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
       "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS), out)
    return out


def add_audio(block, out):
    d = C.dur(block); cut = max(0.1, d - 1.1)
    fc = (f"anoisesrc=color=brown:amplitude=0.7:duration={d},lowpass=f=360,volume=0.14[w];"
          f"sine=frequency=740:duration={d},volume=0.09,afade=t=out:st={cut:.2f}:d=0.25[al];"  # alarm cuts at power-fail
          f"sine=frequency=180:duration=0.7,volume=0.35,afade=t=out:st=0.1:d=0.6,adelay={int(cut*1000)}|{int(cut*1000)}[pd];"  # power-down whine
          f"anoisesrc=color=brown:amplitude=0.8:duration=0.4,lowpass=f=200,volume=0.5,afade=t=out:st=0.05:d=0.35,"
          f"adelay={int((d-0.7)*1000)}|{int((d-0.7)*1000)}[thud];"  # collapse thud
          f"[w][al][pd][thud]amix=inputs=4:normalize=0[a]")
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", block, "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
       "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out)
    return out


def _grab(clip, frac, out, byframe=None):
    if byframe is not None:   # frame-accurate for very short clips (avoids -ss past a 4-frame clip)
        sh("ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf", f"select='eq(n\\,{byframe})',scale=260:462",
           "-frames:v", "1", "-fps_mode", "passthrough", out)
    else:
        sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{C.dur(clip)*frac:.2f}", "-i", clip, "-frames:v", "1", "-vf", "scale=260:462", out)
    return out


def transition_contact(approach, trans, collapse):
    fp = []
    specs = [("approach-end", approach, 0.97, None), ("redfail-1", trans, None, 1), ("redfail-2", trans, None, 3),
             ("collapse-0", collapse, 0.05, None), ("collapse-mid", collapse, 0.35, None), ("collapse-settle", collapse, 0.9, None)]
    for lbl, clip, frac, byf in specs:
        f = os.path.join(OUT, f"_tc_{lbl}.jpg"); _grab(clip, frac, f, byframe=byf); fp.append((f, lbl))
    sheet = Image.new("RGB", (260 * 3, 462 * 2 + 30), (16, 16, 20)); d = ImageDraw.Draw(sheet); ft = font(20)
    for i, (f, lbl) in enumerate(fp):
        sheet.paste(Image.open(f), ((i % 3) * 260, (i // 3) * 492 + 24)); d.text(((i % 3) * 260 + 6, (i // 3) * 492 + 2), lbl, font=ft, fill=(240, 240, 240))
    out = os.path.join(OUT, "transition_contact_sheet.jpg"); sheet.save(out, quality=90); return out


def comparison(v2):
    def lbl(t, w):
        p = os.path.join(OUT, f"_lb_{t.replace(' ','_')}.png"); im = Image.new("RGBA", (w, 54), (0, 0, 0, 0))
        d = ImageDraw.Draw(im); f = font(28); tw = d.textbbox((0, 0), t, font=f)[2]
        d.rectangle([0, 0, w, 50], fill=(0, 0, 0, 165)); d.text(((w - tw) // 2, 8), t, font=f, fill=(240, 240, 240)); im.save(p); return p
    out = os.path.join(OUT, "v1_vs_v2_comparison.mp4"); dur = min(C.dur(V1_HERO), C.dur(v2))
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", V1_HERO, "-i", v2, "-i", lbl("V1", 540), "-i", lbl("V2", 540),
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
    return concat_hard([head, hv], os.path.join(OUT, "full_oxygen_private_hybrid_v2.mp4"))


def main():
    cost = []
    global _TK
    _TK, dur = track_bbox(cost)
    cx, cy, bw, bh = interp_bbox(_TK, T_TRIM)
    print(f"trim @ {T_TRIM}s | Bolt bbox center ({cx:.2f},{cy:.2f}) size ({bw:.2f},{bh:.2f}) — before portal overlap", flush=True)
    approach, trim = approach_v2(cost)
    bg, start, last = inherited_bg(trim)
    iso, iso_center = isolate_bolt(last, bg, start)
    coll = collapse_anim(bg, start, iso, iso_center)
    trans = red_transition(approach)
    hero_v = concat_hard([approach, trans, coll], os.path.join(OUT, "_hero_v2_v.mp4"))
    hero = add_audio(hero_v, os.path.join(OUT, "hybrid_hero_block_v2.mp4"))
    # continuation invariant: last approach frame vs first collapse frame
    la = os.path.join(OUT, "_la.png"); fc = os.path.join(OUT, "_fc.png")
    sh("ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.04", "-i", approach, "-frames:v", "1", la)
    sh("ffmpeg", "-y", "-loglevel", "error", "-i", coll, "-frames:v", "1", fc)
    cont = DV.check_continuation(la, fc, cost=cost)
    tcs = transition_contact(approach, trans, coll)
    cmp = comparison(hero); full = full_hybrid(hero)
    rep = {"no_spend": True, "video_generated": False, "allow_paid_on_disk": DV.ALLOW_PAID,
           "safe_trim_s": T_TRIM, "hero_block_s": round(C.dur(hero), 2), "full_s": round(C.dur(full), 2),
           "meter": "RED from frame 1, O2 12%->0% live label", "big_bubble_removed": True,
           "transition": "3-4 frame red power-failure flicker + horizontal blur + camera drop (no white flash, no collision)",
           "collapse": "derived from last generated frame (inherited bg/portal/camera/lighting/scale); "
                       "down+forward-rotate+thrust-out+motion-blur+impact-squash+prone; short of portal",
           "continuation_invariant_ok": cont["ok"], "continuation_reset_reasons": cont.get("reset_reasons"),
           "final_hold_s": round(20 / FPS, 2), "payoff_caption": "O2: 0%",
           "outputs": ["candidate_1_safe_trim_v2.mp4", "inherited_background_frame.png",
                       "deterministic_collapse_animation.mp4", "hybrid_hero_block_v2.mp4",
                       "transition_contact_sheet.jpg", "v1_vs_v2_comparison.mp4", "full_oxygen_private_hybrid_v2.mp4"],
           "eval_cost_usd": round(sum(cost), 3)}
    json.dump(rep, open(os.path.join(OUT, "no_spend_hybrid_v2_report.json"), "w"), indent=2, default=str)
    print(f"hero {rep['hero_block_s']}s | full {rep['full_s']}s | continuation_ok {cont['ok']} {cont.get('reset_reasons')} | cost ${sum(cost):.2f}")
    print("outputs in", OUT)


if __name__ == "__main__":
    main()
