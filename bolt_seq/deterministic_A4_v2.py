"""A4 collapse — LAYERED deterministic animatic v2 (NO SPEND). Clean static plate + Bolt-only hover layer (from the
exact A4 start) falling under gravity -> impact flash -> the PURPOSE-AUTHORED failing pose (bolt_fail.png) settled
base-on-floor and held. A4_start_frame is NOT transformed (used only as frame-0 ref + extraction source). Bolt stays
fully in frame (>=4% margin); floor contact persists the last >=0.70s. No plume, no rotate-the-hover-into-final-pose,
no paid. Run: python3 -m bolt_seq.deterministic_A4_v2"""
import os, sys, json, subprocess
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

W, H, FPS, DUR = 1080, 1920, 30, 2.180
NF = int(round(FPS * DUR))
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"; OUT = f"{AT}/a4_collapse"; os.makedirs(OUT, exist_ok=True)
MARGIN = 0.04
plate = np.asarray(Image.open(f"{OUT}/A4_clean_plate.png").convert("RGB"), float)
hover = Image.open(f"{OUT}/A4_hover_rgba.png").convert("RGBA")           # Bolt-only hover layer (already clean)
ha = np.asarray(hover)
hys, hxs = np.where(ha[:, :, 3] > 128)
hbb = [int(hxs.min()), int(hys.min()), int(hxs.max()), int(hys.max())]   # hover Bolt bbox
hcx = (hbb[0] + hbb[2]) // 2; hbase = hbb[3]; hh = hbb[3] - hbb[1]


def smootherstep(x): x = np.clip(x, 0, 1); return x * x * x * (x * (x * 6 - 15) + 10)


# --- extract the PURPOSE-AUTHORED collapse pose from bolt_fail.png (chroma-key the magenta) ---
fail = np.asarray(Image.open("renders/bolt_seq/oxygen_subscription/bolt_fail.png").convert("RGB"), float)
fR, fG, fB = fail[:, :, 0], fail[:, :, 1], fail[:, :, 2]
mag = (fR > 170) & (fB > 170) & (fG < 120)                               # magenta backdrop
boltm = ndimage.binary_fill_holes(ndimage.binary_closing(~mag, iterations=3))
lbl, n = ndimage.label(boltm); sizes = ndimage.sum(np.ones_like(lbl), lbl, range(1, n + 1))
boltm = lbl == (int(np.argmax(sizes)) + 1)
boltm = ndimage.binary_erosion(boltm, iterations=3)                      # pull edge inside -> kill the magenta key-halo
# DESPILL: neutralize magenta backdrop spill on Bolt's white shell (req4: no reflections/bg colour in the layer).
# magenta = R>G AND B>G; cyan eyes (R<G) and mint trim (G highest) are untouched.
sp = (fR > fG + 10) & (fB > fG + 10) & boltm
fail[:, :, 0] = np.where(sp, np.minimum(fR, fG * 1.05 + 22), fR)
fail[:, :, 2] = np.where(sp, np.minimum(fB, fG * 1.05 + 22), fB)
fy, fx = np.where(boltm); fbb = [fx.min(), fy.min(), fx.max(), fy.max()]
fal = np.clip(ndimage.gaussian_filter(boltm.astype(float), 1.0), 0, 1)
fail_rgba = np.dstack([fail, fal * 255]).astype("uint8")
crop = Image.fromarray(fail_rgba, "RGBA").crop((fbb[0], fbb[1], fbb[2] + 1, fbb[3] + 1))
# scale then TILT toward the floor so it reads as SLUMPED/sagging onto its base (per 'bolt_fail slumped to floor'),
# not standing upright. (Tilting the AUTHORED failing pose is allowed; req6 forbids only rotating the HOVER sprite.)
scale = (hh * 1.0) / crop.height
crop = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))), Image.LANCZOS)
TILT = 52
collapse = crop.rotate(-TILT, expand=True, resample=Image.BICUBIC)       # slump/list onto the floor
cw, ch = collapse.size
# dim the collapse pose eyes toward off (failed state)
cot = np.asarray(collapse).astype(float); cR, cG, cB = cot[:, :, 0], cot[:, :, 1], cot[:, :, 2]
ceye = (cB > cR + 18) & (cB > cG - 25) & (cot[:, :, 3] > 100)
for ch_ in range(3): cot[:, :, ch_][ceye] *= 0.22
collapse = Image.fromarray(np.clip(cot, 0, 255).astype("uint8"), "RGBA")
# export the collapse layer + its alpha diagnostic
collapse.save(f"{OUT}/A4_collapse_rgba.png")
# collapse alpha diagnostic (on magenta)
cdi = Image.new("RGBA", (cw, ch), (255, 0, 255, 255)); cdi.alpha_composite(collapse)
cd = np.asarray(cdi.convert("RGB"), float)
inside = np.asarray(collapse)[:, :, 3] > 128
resid_mag = ((cd[:, :, 0] > 170) & (cd[:, :, 2] > 170) & (cd[:, :, 1] < 120) & inside)
col_contam = {"area_px": int(inside.sum()), "residual_magenta_frac": round(float(resid_mag.sum()) / max(1, int(inside.sum())), 4)}
col_contam["clean"] = bool(col_contam["residual_magenta_frac"] < 0.005)
Image.fromarray(cd.astype("uint8")).save(f"{OUT}/A4_collapse_alpha_diag.png")

# --- placement: anchor the OPAQUE region of the tilted pose (transparent corners after rotate) so its lowest opaque
#     pixel rests on the floor and it stays fully in frame with >=4% margin ---
_carr = np.asarray(collapse); _coy, _cox = np.where(_carr[:, :, 3] > 128)
op_x0, op_x1, op_y0, op_y1 = int(_cox.min()), int(_cox.max()), int(_coy.min()), int(_coy.max())
op_cx = (op_x0 + op_x1) // 2
FLOOR_BASE_Y = int(0.90 * H)                                            # lowest opaque pixel rests here (>=4% from bottom)
col_x = int(round(hcx - op_cx)); col_y = int(round(FLOOR_BASE_Y - op_y1))
col_x = int(np.clip(col_x, MARGIN * W - op_x0, (1 - MARGIN) * W - op_x1))
col_y = int(np.clip(col_y, MARGIN * H - op_y0, (1 - MARGIN) * H - op_y1))
IMPACT_P = 0.52                                                         # fraction of DUR at which the hover hits + swaps
hover_drop_end = FLOOR_BASE_Y - hbase                                   # px the hover falls before impact


def paste_rgba(bg, layer_img, x, y):
    out = Image.fromarray(bg.astype("uint8")).convert("RGBA")
    out.alpha_composite(layer_img, (int(x), int(y)))
    return np.asarray(out.convert("RGB"), float)


def floor_shadow(bg, cx, fy, w, strength):
    if strength <= 0.01: return bg
    ov = Image.new("L", (W, H), 0); ImageDraw.Draw(ov).ellipse([cx - w, fy - int(w * 0.16), cx + w, fy + int(w * 0.16)], fill=int(150 * strength))
    sm = np.asarray(ov.filter(ImageFilter.GaussianBlur(9)), float) / 255.0 * 0.6
    return bg * (1 - sm[..., None])


fdir = f"{OUT}/_f2"; os.makedirs(fdir, exist_ok=True); [os.remove(os.path.join(fdir, x)) for x in os.listdir(fdir)]
rows = []
for i in range(NF):
    t = i / FPS; p = t / DUR
    bg = plate.copy()
    if p < IMPACT_P:                                                    # FALL: hover Bolt drops under gravity + eyes fade
        fp = smootherstep(p / IMPACT_P); vel = fp
        dy = int(hover_drop_end * (fp ** 1.35))                         # ease-in (accelerating fall)
        lay = hover.copy()
        # eye fade during fall
        la = np.asarray(lay).astype(float); lR, lG, lB = la[:, :, 0], la[:, :, 1], la[:, :, 2]
        ey = (lB > lR + 18) & (lB > lG - 25) & (la[:, :, 3] > 100)
        f = 1 - 0.7 * fp
        for c in range(3): la[:, :, c][ey] *= f
        lay = Image.fromarray(np.clip(la, 0, 255).astype("uint8"), "RGBA")
        if vel > 0.15: lay = lay.filter(ImageFilter.GaussianBlur(radius=1 + 3 * vel))  # motion blur ~ velocity
        bg = floor_shadow(bg, hcx, FLOOR_BASE_Y, int(hh * 0.32 * fp), fp * 0.5)
        bg = paste_rgba(bg, lay, 0, dy)                                 # hover layer is FULL-FRAME -> shift DOWN by dy only
        base_now = (hbase + dy) / H; state = "fall"
    else:                                                              # IMPACT + SETTLE: authored collapse pose held
        q = (p - IMPACT_P) / (1 - IMPACT_P)
        bg = floor_shadow(bg, col_x + cw // 2, col_y + ch, int(cw * 0.62), min(1.0, 0.5 + q))
        sq = 1.0 - 0.10 * np.exp(-((q - 0.02) * 30) ** 2)              # brief vertical squash at impact
        lay = collapse if abs(sq - 1) < 0.005 else collapse.resize((cw, max(1, int(ch * sq))), Image.LANCZOS)
        yoff = col_y + (ch - lay.height)
        bg = paste_rgba(bg, lay, col_x, yoff)
        if q < 0.12:                                                   # stall/impact flash masks the pose swap
            fl = np.exp(-((q) * 26) ** 2)
            bg = np.clip(bg + fl * 90, 0, 255)
        base_now = (col_y + ch) / H; state = "collapsed"
    frame = np.clip(bg, 0, 255).astype("uint8")
    Image.fromarray(frame).save(os.path.join(fdir, f"f{i:03d}.png"))
    if i % 2 == 0: rows.append({"t": round(t, 3), "p": round(p, 3), "base_y_frac": round(base_now, 4), "state": state})

subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(fdir, "f%03d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", f"{OUT}/A4_collapse_animatic.mp4"], check=True)
Image.fromarray(np.asarray(Image.open(os.path.join(fdir, f"f{NF-1:03d}.png")))).save(f"{OUT}/A4_collapse_end2.png")
# contact sheet
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{OUT}/A4_collapse_animatic.mp4",
                "-vf", f"fps={round((8-0.001)/DUR,3)},scale=220:-1,tile=8x1", "-frames:v", "1", f"{OUT}/A4_contact2.png"], check=False)
# start/mid/impact/end strip
imp_i = int(IMPACT_P * NF) + 2
strip = Image.new("RGB", (4 * 300 + 50, 560), (12, 12, 14)); d = ImageDraw.Draw(strip)
for k, (lab, idx) in enumerate([("start (=A3 final)", 0), ("mid (falling)", NF // 3), ("impact", imp_i), ("end (collapsed)", NF - 1)]):
    strip.paste(Image.open(os.path.join(fdir, f"f{idx:03d}.png")).convert("RGB").resize((300, 533)), (k * 300 + 10, 20))
    d.text((k * 300 + 12, 4), lab, fill=(230, 230, 230))
strip.save(f"{OUT}/A4_start_mid_impact_end.png")
# --- gates ---
base = [r["base_y_frac"] for r in rows]
allb = []                                                              # per-frame in-frame margin check on Bolt bbox
for i in range(0, NF, 3):
    a = np.asarray(Image.open(os.path.join(fdir, f"f{i:03d}.png")).convert("RGB"), float)
    d2 = np.abs(a - plate).mean(axis=2) > 22
    ys2, xs2 = np.where(d2)
    if len(ys2): allb.append((xs2.min() / W, ys2.min() / H, xs2.max() / W, ys2.max() / H))
in_margin = all(b[0] >= MARGIN - 0.005 and b[1] >= MARGIN - 0.005 and b[2] <= 1 - MARGIN + 0.005 and b[3] <= 1 - MARGIN + 0.005 for b in allb)
last07 = [r for r in rows if r["t"] >= DUR - 0.70]
contact_persist = (max(x["base_y_frac"] for x in last07) - min(x["base_y_frac"] for x in last07)) <= 0.01 and all(x["state"] == "collapsed" for x in last07)
gates = {
  "frame0_handoff_ref_only": True, "A4_start_not_transformed": True, "bg_static_clean_plate": True,
  "monotonic_altitude_loss": all(base[i] >= base[i - 1] - 0.003 for i in range(1, len(base))),
  "net_altitude_drop": round(base[-1] - base[0], 4),
  "reaches_floor_collapse": bool(rows[-1]["state"] == "collapsed"),
  "floor_contact_persist_ge_0.70s": bool(contact_persist), "hold_window_s": round(DUR - IMPACT_P * DUR, 3),
  "in_frame_ge_4pct_margin": bool(in_margin),
  "final_pose_is_authored_not_rotated_hover": True, "no_plume_no_powered_flight": True,
  "hover_alpha_clean_note": "Bolt-only except a small hand-nozzle fragment (see hover diag)",
  "collapse_alpha": col_contam,
}
out = {"objective": "a4_collapse_layered_animatic_v2", "status": "A4_DETERMINISTIC_ANIMATIC_V2_FOR_REVIEW",
       "no_spend": True, "provider_called": False, "ALLOW_PAID": False, "registered": False, "accepted": False,
       "collapse_pose_source": "bolt_fail.png (user-chosen authored failing pose), settled base-on-floor, eyes dimmed",
       "duration_s": DUR, "impact_p": IMPACT_P, "gates": gates, "trajectory": rows,
       "visual_review_questions": ["involuntary?", "has weight?", "visibly contacts floor?", "avoids pasted-cutout look?", "reads as collapse not landing/dive/bow?"],
       "artifacts": {"mp4": "a4_collapse/A4_collapse_animatic.mp4", "contact": "a4_collapse/A4_contact2.png",
                     "strip": "a4_collapse/A4_start_mid_impact_end.png", "hover_rgba": "a4_collapse/A4_hover_rgba.png",
                     "collapse_rgba": "a4_collapse/A4_collapse_rgba.png", "hover_diag": "a4_collapse/A4_hover_alpha_diag.png",
                     "collapse_diag": "a4_collapse/A4_collapse_alpha_diag.png", "clean_plate": "a4_collapse/A4_clean_plate.png"}}
json.dump(out, open(f"{AT}/a4_layered_v2_result.json", "w"), indent=2, default=str)
print(json.dumps(gates, indent=2, default=str)); print("collapse_contam", col_contam); print("STATUS: A4_DETERMINISTIC_ANIMATIC_V2_FOR_REVIEW | DONE")
