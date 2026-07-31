"""Candidate-source dossier for bolt_hover_run_dry.png (READ-ONLY, NO SPEND). Delivers hash/dims/alpha-stats,
checkerboard + saturated diagnostics, side-by-side vs the accepted A3 Bolt, and a structural-identity checklist.
Does NOT begin any rig — the source stays a CANDIDATE pending human approval. Run: python3 -m bolt_seq.provenance_dossier"""
import os, sys, json, hashlib
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"; OUT = f"{AT}/a4_collapse/provenance"; os.makedirs(OUT, exist_ok=True)
SRC = "renders/bolt_seq/oxygen_subscription/bolt_hover_run_dry.png"

im = Image.open(SRC); mode, (Wc, Hc) = im.mode, im.size
sha = hashlib.sha256(open(SRC, "rb").read()).hexdigest()
rgba = np.asarray(im.convert("RGBA"))
al = rgba[:, :, 3]
alpha_stats = {"fully_opaque_frac": round(float((al == 255).mean()), 4), "fully_transparent_frac": round(float((al == 0).mean()), 4),
               "semi_transparent_frac": round(float(((al > 0) & (al < 255)).mean()), 4), "has_real_alpha": bool((al < 250).mean() > 0.02)}
mask = al > 128; ys, xs = np.where(mask); bb = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def feats(rgb, m):
    R, G, B = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]; ys, xs = np.where(m)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max(); bh, bw = y1 - y0, x1 - x0
    cyan = (B > R + 18) & (B > G - 12) & (B > 90) & m
    head = np.zeros_like(m); head[y0:int(y0 + 0.42 * bh), :] = True
    chestband = np.zeros_like(m); chestband[int(y0 + 0.42 * bh):int(y0 + 0.72 * bh), int(x0 + 0.28 * bw):int(x0 + 0.72 * bw)] = True
    top = np.zeros_like(m); top[y0:int(y0 + 0.14 * bh), :] = True
    visor = (rgb.mean(2) < 95) & m & head
    eyes = cyan & head; el, en = ndimage.label(eyes); n_eyes = int(sum(1 for i in range(1, en + 1) if (el == i).sum() > max(10, 0.0002 * m.sum())))
    def npal(px):
        if px.sum() == 0: return [0, 0, 0]
        v = rgb[px].mean(0); s = max(1.0, v.mean()); return [round(float(c / s), 3) for c in v]
    return {"head_body_ratio": round(0.42 * bh / max(1, 0.58 * bh), 3), "aspect_h_w": round(bh / max(1, bw), 3),
            "visor_frac": round(float(visor.sum()) / max(1, int(m.sum())), 4), "n_eyes": n_eyes,
            "cyan_chest_frac": round(float((cyan & chestband).sum()) / max(1, int(m.sum())), 4),
            "antenna_bulb": bool((cyan & top).sum() > 8),
            "cyan_pal": npal(cyan), "shell_pal": npal((np.minimum(np.minimum(R, G), B) > 110) & m),
            "_crop": (x0, y0, x1, y1)}


src_f = feats(rgba[:, :, :3].astype(float), mask)
# accepted A3 reference
a3 = np.asarray(Image.open(f"{AT}/a4_collapse/A4_start_frame.png").convert("RGB"), float)
a3m = np.zeros(a3.shape[:2], bool); a3m[827:1420, 153:776] = True
corner = a3[830:850, 900:1000].mean((0, 1)); a3m &= (np.abs(a3 - corner).mean(2) > 22)
a3m = ndimage.binary_fill_holes(ndimage.binary_closing(a3m, iterations=3))
lb, nn = ndimage.label(a3m); a3m = lb == (int(np.argmax(ndimage.sum(np.ones_like(lb), lb, range(1, nn + 1)))) + 1)
a3_f = feats(a3, a3m)


def near(a, b, tol): return bool(abs(a - b) <= tol)
def paln(a, b, tol): return bool(np.abs(np.array(a) - np.array(b)).mean() <= tol)
checklist = {
  "head_body_ratio": {"src": src_f["head_body_ratio"], "a3": a3_f["head_body_ratio"], "match": near(src_f["head_body_ratio"], a3_f["head_body_ratio"], 0.15)},
  "visor_present":   {"src": src_f["visor_frac"] > 0.03, "a3": a3_f["visor_frac"] > 0.03, "match": (src_f["visor_frac"] > 0.03) == (a3_f["visor_frac"] > 0.03)},
  "two_eyes":        {"src": src_f["n_eyes"], "a3": a3_f["n_eyes"], "match": bool(src_f["n_eyes"] == 2)},
  "antenna_bulb":    {"src": src_f["antenna_bulb"], "a3": a3_f["antenna_bulb"], "match": bool(src_f["antenna_bulb"])},
  "cyan_chest_panel":{"src": src_f["cyan_chest_frac"], "a3": a3_f["cyan_chest_frac"], "match": bool(src_f["cyan_chest_frac"] > 0.01 and a3_f["cyan_chest_frac"] > 0.01)},
  "cyan_palette":    {"src": src_f["cyan_pal"], "a3": a3_f["cyan_pal"], "match": paln(src_f["cyan_pal"], a3_f["cyan_pal"], 0.18)},
  "shell_palette":   {"src": src_f["shell_pal"], "a3": a3_f["shell_pal"], "match": paln(src_f["shell_pal"], a3_f["shell_pal"], 0.18)},
  "side_ears": {"src": "present (visual)", "a3": "present (visual)", "match": "VISUAL — confirm on board"},
  "hands": {"src": "present (visual)", "a3": "present (visual)", "match": "VISUAL — confirm on board"},
  "hover_base": {"src": "present (visual)", "a3": "present (visual)", "match": "VISUAL — confirm on board"},
}
auto_matches = [k for k, v in checklist.items() if v.get("match") is True]

# checkerboard + saturated diagnostics + side-by-side vs A3
sqp = 40; yy, xx = np.mgrid[0:Hc, 0:Wc]; chk = ((xx // sqp + yy // sqp) % 2)
cb = np.where(chk[..., None] == 0, np.array([235, 235, 235]), np.array([170, 200, 235])).astype(float)
af = al[..., None] / 255.0; rgb = rgba[:, :, :3].astype(float)
comp_cb = (cb * (1 - af) + rgb * af).astype("uint8")
comp_sat = (np.full((Hc, Wc, 3), [255, 110, 0]) * (1 - af) + rgb * af).astype("uint8")
Image.fromarray(comp_cb).save(f"{OUT}/hover_run_dry_checker.png")
Image.fromarray(comp_sat).save(f"{OUT}/hover_run_dry_saturated.png")
# side-by-side: A3 Bolt crop | candidate on checker | candidate on saturated
ax0, ay0, ax1, ay1 = a3_f["_crop"]; a3crop = Image.fromarray(a3[ay0:ay1, ax0:ax1].astype("uint8"))
cx0, cy0, cx1, cy1 = src_f["_crop"]
cell = 460; sb = Image.new("RGB", (3 * cell + 40, cell + 60), (30, 30, 34)); dd = ImageDraw.Draw(sb)
for i, (lab, img) in enumerate([("ACCEPTED A3 Bolt", a3crop),
                                ("candidate on checker", Image.fromarray(comp_cb[cy0:cy1, cx0:cx1])),
                                ("candidate on saturated", Image.fromarray(comp_sat[cy0:cy1, cx0:cx1]))]):
    t = img.copy(); t.thumbnail((cell - 16, cell - 16)); tile = Image.new("RGB", (cell, cell), (60, 60, 66))
    tile.paste(t, ((cell - t.width) // 2, (cell - t.height) // 2)); sb.paste(tile, (i * cell + 10, 40)); dd.text((i * cell + 12, 12), lab, fill=(235, 235, 235))
sb.save(f"{OUT}/hover_run_dry_vs_A3.png")

dossier = {"objective": "candidate_source_dossier", "read_only": True, "no_spend": True, "ALLOW_PAID": False,
           "status": "CANDIDATE — NOT confirmed canonical; NOT approved; rig NOT started (awaiting human approval)",
           "asset": {"path": SRC, "sha256": sha, "dimensions": [Wc, Hc], "mode": mode, "alpha_stats": alpha_stats,
                     "opaque_bbox": bb},
           "provenance_evidence": {
             "identity_reference_for_A_chain": "run_primitive_chain_pilot.py:20 IDENT = bolt_hover_run_dry.png (BOLT_SPEC identity_reference for A1/A2/A3 gen+eval)",
             "pose_source_for_boundary_frames": "prepare_oxygen_shot_A_primitives.py:23 POSE_REACH = bolt_hover_run_dry.png -> authored B1/B2/B3 (the A1/A2/A3 end targets), lines 203-205",
             "generated_by": "gen_dry_hover_run.py (DRY reaching/hover-run Bolt); preflight accepted (anatomy_clean, checklist_pass)",
             "same_asset_family_note": "author_shot_A_end_frame.py:23 'same asset family as seed -> guaranteed identity + scale'"},
           "structural_identity_checklist": checklist,
           "auto_matched_features": auto_matches,
           "auto_score_caveat": "quantitative checks are ADVISORY; side_ears/hands/hover_base + final canonical decision require the human visual review on hover_run_dry_vs_A3.png. Palette compares brightness-normalized hue (candidate is studio-lit; A3 is dim corridor).",
           "artifacts": {"checker": "a4_collapse/provenance/hover_run_dry_checker.png", "saturated": "a4_collapse/provenance/hover_run_dry_saturated.png", "vs_A3": "a4_collapse/provenance/hover_run_dry_vs_A3.png"}}
json.dump(dossier, open(f"{AT}/a4_source_candidate_dossier.json", "w"), indent=2, default=str)
print("sha", sha[:16], "| dims", (Wc, Hc), "| alpha", alpha_stats)
print("checklist auto-matches:", auto_matches)
for k, v in checklist.items(): print(f"  {k}: {v.get('match')}  src={v.get('src')} a3={v.get('a3')}")
print("DONE")
