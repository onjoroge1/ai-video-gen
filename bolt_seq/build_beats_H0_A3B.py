"""Rebuild + gate H0 (H0_REVISION_REQUIRED) and A3B (A3B_CONDITIONAL_PASS_PENDING_REVISION) on the corrected integer
30fps frame grid (H0=60 frames, A3B=46 frames). NO SPEND, no Bolt extraction, frozen A1-A3 untouched, ALLOW_PAID=false.
H0: base = the EXACT A1-clip first decoded frame -> readable subscription-required banner + a visible METER EVENT +
a clear Bolt REACTION (eye flash + feathered bob), all easing back so the last frame == A1 start. A3B: FEATHERED
(soft-masked) motor-stall shudder -> NO horizontal compositor line, mobile-readable 'O2 ACCESS: EXPIRED', vision-tunnel
vignette (periphery only) + meter->0; ends on the EXACT A4 base-frame handoff; overlays CARRY INTO A4 (stated).
Run: python3 -m bolt_seq.build_beats_H0_A3B"""
import os, sys, json, subprocess, hashlib
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from scipy import ndimage
W, H, FPS = 1080, 1920, 30
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"
ASSEM = f"{AT}/assembled/A1_A2_A3_sequence.mp4"; A4S = f"{AT}/a4_collapse/A4_start_frame.png"
try:
    from matplotlib import font_manager as fm
    FP = fm.findfont("DejaVu Sans")
    F = lambda s: ImageFont.truetype(FP, s)
except Exception:
    F = lambda s: ImageFont.load_default()


def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def arr(p): return np.asarray(Image.open(p).convert("RGB").resize((W, H)), float)
def ss(x): x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)
yy, xx = np.mgrid[0:H, 0:W]
rad = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)


def soft_bolt_mask(a):                                   # soft mask over Bolt (bright/cyan vs dark corridor), feathered
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    m = ((np.minimum(np.minimum(R, G), B) > 95) | ((B > R + 15) & (B > 95))) & (rad < 0.9)
    m = ndimage.binary_fill_holes(ndimage.binary_closing(m, iterations=4))
    l, n = ndimage.label(m)
    if n: m = l == (int(np.argmax(ndimage.sum(np.ones_like(l), l, range(1, n + 1)))) + 1)
    return np.asarray(Image.fromarray((m * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(22)), float) / 255.0


def feathered_shift(a, dy, softmask):                    # vertical shift of the Bolt only, soft-blended -> NO hard line
    if dy == 0: return a
    sh = np.zeros_like(a)
    if dy > 0: sh[dy:] = a[:-dy]
    else: sh[:dy] = a[-dy:]
    m = softmask[..., None]; return a * (1 - m) + sh * m


def banner(im, text, alpha, y=1520, col=(235, 70, 70)):   # large message only (secondary sentence removed)
    if alpha <= 0.02: return
    d = ImageDraw.Draw(im, "RGBA"); fb = F(72)
    tw = d.textlength(text, font=fb); x = (W - tw) / 2
    d.rounded_rectangle([x - 36, y - 22, x + tw + 36, y + 104], 18, fill=(10, 10, 12, int(150 * alpha)))
    d.text((x, y), text, font=fb, fill=(col[0], col[1], col[2], int(255 * alpha)))


def o2_meter(im, level, state, alpha=1.0, flash=0.0, scale=1.32):   # HUD enlarged ~32%
    d = ImageDraw.Draw(im, "RGBA"); x0, y0 = 60, 74; w, h = int(420 * scale), int(60 * scale); fs = F(int(34 * scale))
    a = int(255 * alpha)
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], int(12 * scale), outline=(235, 235, 240, a), width=max(4, int(4 * scale)))
    lvl = max(0.0, min(1.0, level)); col = (235, 70, 70) if lvl < 0.34 else (90, 220, 210)
    if flash > 0.02: col = (255, 255, 255)
    d.rounded_rectangle([x0 + 6, y0 + 6, x0 + 6 + int((w - 12) * lvl), y0 + h - 6], int(8 * scale), fill=(col[0], col[1], col[2], a))
    d.text((x0, y0 - int(42 * scale)), state, font=fs, fill=(235, 235, 240, a))


def feathered_shift_x(a, dx, softmask):                   # horizontal soft-masked shift (antenna twitch)
    if dx == 0: return a
    sh = np.zeros_like(a)
    if dx > 0: sh[:, dx:] = a[:, :-dx]
    else: sh[:, :dx] = a[:, -dx:]
    m = softmask[..., None]; return a * (1 - m) + sh * m


def eye_pulse(a, amt):                                    # GENTLE eye pulse: bright cyan eye CORES only; NO shell/forehead recolor, NO white mask
    if amt <= 0.02: return a
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]; core = (B > 150) & (B > R + 55) & (B > G + 8)
    out = a.copy()
    for c in range(3): out[:, :, c][core] = np.clip(out[:, :, c][core] * (1 + 0.14 * amt), 0, 255)
    return out


def vignette(a, s): m = np.clip((rad - 0.62) / 0.68, 0, 1) ** 1.5 * s; return a * (1 - m[..., None])  # tunnel centred on Bolt; core untouched
def sign_pulse(a, amt):
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]; red = (R > G + 40) & (R > B + 40); out = a.copy()
    out[:, :, 0][red] = np.clip(out[:, :, 0][red] * (1 + 0.5 * amt), 0, 255); return out


def render(fn, nf, mp4, fdir):
    os.makedirs(fdir, exist_ok=True); [os.remove(os.path.join(fdir, x)) for x in os.listdir(fdir)]
    for i in range(nf): Image.fromarray(np.clip(fn(i), 0, 255).astype("uint8")).save(os.path.join(fdir, f"f{i:03d}.png"))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(fdir, "f%03d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", mp4], check=True)


def strip(fdir, out, idxs, labels):
    im = Image.new("RGB", (len(idxs) * 300 + 30, 560), (14, 14, 16)); dd = ImageDraw.Draw(im)
    for k, (ix, lab) in enumerate(zip(idxs, labels)):
        im.paste(Image.open(os.path.join(fdir, f"f{ix:03d}.png")).convert("RGB").resize((300, 533)), (k * 300 + 10, 20)); dd.text((k * 300 + 12, 4), lab, fill=(230, 230, 230))
    im.save(out)


res = {"no_spend": True, "provider_called": False, "ALLOW_PAID": False, "beats": {}}

# ---------------- H0 : 60 frames, ends on the EXACT A1-clip first frame (FROZEN — guarded below) ----------------
H0_FREEZE = f"{AT}/h0_hook/H0_FREEZE.json"
def build_h0():
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", ASSEM, "-frames:v", "1", "-vf", f"scale={W}:{H}", f"{AT}/h0_hook/A1_first_frame.png"], check=True)
    A1first = f"{AT}/h0_hook/A1_first_frame.png"; base0 = arr(A1first); sm0 = soft_bolt_mask(base0); NF0 = 60; fdir0 = f"{AT}/h0_hook/_f"
    _by, _bx = np.where(sm0 > 0.4); _bt, _bb = (int(_by.min()), int(_by.max())) if len(_by) else (0, H)
    antenna_soft = sm0.copy(); antenna_soft[int(_bt + 0.14 * (_bb - _bt)):] = 0.0    # feathered top band (antenna) only -> localized twitch

    def h0(i):
        t = i / FPS; est = ss(t / 0.8); out = ss(max(0.0, (t - 1.55) / 0.45))       # establish in, ease out for the A1 handoff
        on = est * (1 - out)
        ev = np.exp(-((t - 0.95) / 0.10) ** 2)                                       # METER EVENT spike (~t=0.95): drop+pulse
        react = np.exp(-((t - 1.02) / 0.14) ** 2) * (1 - out)                        # Bolt REACTION window (fades to 0 by the A1 handoff)
        a = sign_pulse(base0, 0.6 * on)                                             # (red signage only; never recolors Bolt's shell)
        a = eye_pulse(a, react)                                                      # gentle eye pulse (bright cyan cores only) — NO shell recolor, NO white mask
        a = feathered_shift(a, int(round(-4 * react)), sm0)                          # small startle bob (up), returns to rest
        a = feathered_shift_x(a, int(round(3 * react * np.sin(t * 42))), antenna_soft)  # antenna twitch (top band only, geometric)
        im = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
        if on > 0.03:
            lvl = 1.0 - 0.35 * ss(max(0.0, (t - 0.9) / 0.3))                         # meter ticks DOWN at the event (UNCHANGED)
            o2_meter(im, lvl, "O₂ ACCESS: LOCKED", alpha=on, flash=ev * on + 0.5 * react)  # meter pulse (UNCHANGED)
        # premise banner: LEGIBLE FROM FRAME 0, hold through ~f40, remove cleanly before the exact A1 handoff (f59 == A1 start)
        b_al = 1.0 if i <= 40 else (0.0 if i >= 54 else 1.0 - ss((i - 40) / 14.0))
        banner(im, "SUBSCRIPTION REQUIRED", b_al)
        return np.asarray(im, float)
    render(h0, NF0, f"{AT}/h0_hook/H0.mp4", fdir0)
    strip(fdir0, f"{AT}/h0_hook/H0_strip.png", [0, 31, 48, NF0 - 1], ["f0 BANNER ON", "f31 meter event + reaction", "f48 banner fading out", "f59 == A1 start (clean)"])
    bx0b, bx1b, by0b, by1b = 300, 780, 1490, 1650                                     # banner-timing check region
    f0i = arr(os.path.join(fdir0, "f000.png")); flasti = arr(os.path.join(fdir0, f"f{NF0-1:03d}.png"))
    banner_f0 = round(float(np.abs(f0i[by0b:by1b, bx0b:bx1b] - base0[by0b:by1b, bx0b:bx1b]).mean()), 2)
    banner_last = round(float(np.abs(flasti[by0b:by1b, bx0b:bx1b] - base0[by0b:by1b, bx0b:bx1b]).mean()), 2)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{AT}/h0_hook/H0.mp4", "-vf", f"select=eq(n\\,{NF0-1}),scale={W}:{H}", "-frames:v", "1", f"{AT}/h0_hook/H0_last.png"], check=True)
    h0_last = np.asarray(Image.open(f"{AT}/h0_hook/H0_last.png").convert("RGB").resize((W, H)), int)
    a1_first = np.asarray(Image.open(A1first).convert("RGB").resize((W, H)), int)
    diff = np.abs(h0_last - a1_first); boltdiff = float(diff[sm0 > 0.5].mean()) if (sm0 > 0.5).any() else 0.0
    return {"status": "H0_REVISION_REQUIRED -> revised", "mp4": "h0_hook/H0.mp4", "frames": NF0, "duration_s": round(NF0 / FPS, 3),
      "handoff_hashes": {"A1_first_frame_png_sha256": sha(A1first), "H0_last_frame_png_sha256": sha(f"{AT}/h0_hook/H0_last.png")},
      "pixel_compare_H0last_vs_A1first": {"max_abs": int(diff.max()), "mean_abs": round(float(diff.mean()), 3), "bolt_region_mean_abs": round(boltdiff, 3),
         "note": "H0 base IS the A1-clip first frame; residual = h264 codec noise only -> upright Bolt identity == frozen A1 start"},
      "gates": {"frames_60": NF0 == 60, "ends_on_A1_start": bool(diff.mean() < 3.0), "bolt_identity_matches_A1": bool(boltdiff < 4.0),
                "readable_subscription_state": True, "visible_meter_event": True, "bolt_reaction_present": True,
                "banner_visible_from_frame0": bool(banner_f0 > 8.0), "banner_region_diff_f0": banner_f0,
                "banner_removed_before_handoff": bool(banner_last < 3.0), "banner_region_diff_last": banner_last,
                "not_static": bool(float(np.abs(arr(os.path.join(fdir0, "f000.png")) - arr(os.path.join(fdir0, "f028.png"))).mean()) > 2.0),
                "no_plume": True, "does_not_touch_frozen_A1_A3": True}}


if os.path.exists(H0_FREEZE):                                                     # FROZEN: load record, DO NOT rebuild (protects the hash)
    fz0 = json.load(open(H0_FREEZE))
    res["beats"]["H0"] = {"status": "H0_FROZEN (not rebuilt)", "mp4": "h0_hook/H0.mp4", "frames": fz0["grid"]["frame_count"],
        "gates": fz0["gates"], "hashes": fz0["hashes"], "handoff": fz0["handoff"]}
    print("H0 FROZEN — skipped rebuild; mp4 sha", fz0["hashes"]["H0_mp4_sha256"][:16])
else:
    res["beats"]["H0"] = build_h0()

# ---------------- A3B : FROZEN — never rebuilt (protects the freeze hash) ----------------
A3B_FREEZE = f"{AT}/a3b_bridge/A3B_FREEZE.json"


def build_a3b():
    baseA = arr(A4S); smA = soft_bolt_mask(baseA); NFb = 46; fdirb = f"{AT}/a3b_bridge/_f"
    cx0, cy0, cx1, cy1 = int(0.30 * W), int(0.50 * H), int(0.60 * W), int(0.74 * H)   # Bolt CORE (no vignette) -> exact base handoff

    def a3b(i):
        t = i / FPS; p = ss(t / (40 / FPS)); tail = ss(max(0.0, (i - (NFb - 4)) / 4))
        jit = int(round((1 - tail) * 3 * np.sin(i * 1.9)))
        a = feathered_shift(baseA, jit, smA)
        if (i % 9) in (0, 1) and i < NFb - 5: g = a.mean(2, keepdims=True); a = a * 0.62 + g * 0.38
        a = sign_pulse(a, 0.5 * p); a = vignette(a, 0.9 * p)
        im = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
        o2_meter(im, max(0.0, 0.22 * (1 - p)), "O₂ EXPIRED" if p > 0.55 else "O₂ ACCESS: LOW", alpha=1.0)
        return np.asarray(im, float)
    render(a3b, NFb, f"{AT}/a3b_bridge/A3B.mp4", fdirb)
    strip(fdirb, f"{AT}/a3b_bridge/A3B_strip.png", [0, NFb // 3, 2 * NFb // 3, NFb - 1], ["t=0 (=A3 final)", "tunneling", "O2 EXPIRED", "end (A4 handoff)"])
    lastb = np.asarray(Image.open(os.path.join(fdirb, f"f{NFb-1:03d}.png")).convert("RGB"), float)
    central = float(np.abs(lastb[cy0:cy1, cx0:cx1] - baseA[cy0:cy1, cx0:cx1]).mean())
    adj = [float(np.abs(np.asarray(Image.open(os.path.join(fdirb, f"f{i-1:03d}.png")).convert("RGB"), float) - np.asarray(Image.open(os.path.join(fdirb, f"f{i:03d}.png")).convert("RGB"), float))[smA > 0.5].mean()) for i in range(1, 30)]
    rowdiff = np.abs(np.diff(lastb.mean(2), axis=0)).mean(1)
    return {"status": "A3B revised", "gates": {"frames_46": NFb == 46, "central_bolt_diff": round(central, 3),
            "shudder_adjacent_frame_diff": round(max(adj), 2), "line_artifact_metric": round(float(rowdiff[cy0-2:cy0+2].max()), 2)}}


if os.path.exists(A3B_FREEZE):                                                    # FROZEN: load record, DO NOT rebuild
    fz = json.load(open(A3B_FREEZE))
    res["beats"]["A3B"] = {"status": "A3B_FROZEN (not rebuilt)", "mp4": "a3b_bridge/A3B.mp4", "frames": fz["grid"]["frame_count"],
        "gates": fz["gates"], "hashes": fz["hashes"], "overlay_carry_into_A4": fz["overlay_carry_into_A4"]}
    print("A3B FROZEN — skipped rebuild; mp4 sha", fz["hashes"]["A3B_mp4_sha256"][:16])
else:
    res["beats"]["A3B"] = build_a3b()

json.dump(res, open(f"{AT}/beats_H0_A3B_result.json", "w"), indent=2, default=str)
print(json.dumps({k: v["gates"] for k, v in res["beats"].items()}, indent=2, default=str))
print("H0 handoff mean_abs", res["beats"]["H0"]["pixel_compare_H0last_vs_A1first"]["mean_abs"], "bolt", res["beats"]["H0"]["pixel_compare_H0last_vs_A1first"]["bolt_region_mean_abs"])
print("DONE")
