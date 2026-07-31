"""A4 provenance inventory (READ-ONLY, NO SPEND). Scores every candidate clean/pre-composite Bolt source against the
ACCEPTED A3 Bolt (reference = A4_start_frame Bolt region) on design-identity features: palette (cyan/mint/shell,
brightness-normalized), cyan CHEST PANEL, two cyan eyes on a dark visor, antenna bulb, side ears, hover base, head
aspect. Excludes bolt_fail/bolt_collapse from ACCEPTANCE (still scored, to confirm they differ). Builds a labeled
side-by-side board (reference + candidates) for the authoritative visual call. Run: python3 -m bolt_seq.provenance_inventory"""
import os, sys, json
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"; OUT = f"{AT}/a4_collapse/provenance"; os.makedirs(OUT, exist_ok=True)


def load_rgb(p, size=None):
    im = Image.open(p).convert("RGB")
    if size: im = im.resize(size)
    return np.asarray(im, float), im


def character_mask(rgb, alpha=None):
    """mask of the character: use alpha if meaningful, else remove a smooth/neutral or magenta backdrop."""
    H, W = rgb.shape[:2]; R, G, B = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    if alpha is not None and (alpha < 250).mean() > 0.02:
        m = alpha > 128
    else:
        # remove the corner backdrop colour (neutral studio or magenta) by colour distance + include dark visor
        corner = np.concatenate([rgb[:6, :6].reshape(-1, 3), rgb[:6, -6:].reshape(-1, 3), rgb[-6:, :6].reshape(-1, 3)]).mean(0)
        dist = np.abs(rgb - corner).mean(2)
        m = dist > 22
    m = ndimage.binary_fill_holes(ndimage.binary_closing(m, iterations=3))
    l, n = ndimage.label(m)
    if n: sz = ndimage.sum(np.ones_like(l), l, range(1, n + 1)); m = l == (int(np.argmax(sz)) + 1)
    return ndimage.binary_fill_holes(m)


def features(rgb, mask):
    R, G, B = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    ys, xs = np.where(mask)
    if len(ys) < 50: return None
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max(); bh, bw = y1 - y0, x1 - x0
    cyan = (B > R + 18) & (B > G - 12) & (B > 90) & mask
    mint = (G > R + 12) & (G > B - 8) & (G > 100) & mask
    shell = (np.minimum(np.minimum(R, G), B) > 110) & mask
    def norm(px):
        if px.sum() == 0: return [0, 0, 0]
        v = rgb[px].mean(0); s = max(1.0, v.mean()); return [round(float(c / s), 3) for c in v]   # brightness-normalized hue signature
    # chest band = lower-centre of the character; eyes/visor band = upper-centre
    chest_band = np.zeros_like(mask); chest_band[int(y0 + 0.42 * bh):int(y0 + 0.72 * bh), int(x0 + 0.28 * bw):int(x0 + 0.72 * bw)] = True
    head_band = np.zeros_like(mask); head_band[y0:int(y0 + 0.42 * bh), :] = True
    visor = (rgb.mean(2) < 95) & mask & head_band
    eyes = cyan & head_band; el, en = ndimage.label(eyes); esz = [int((el == i).sum()) for i in range(1, en + 1)]
    n_eyes = int(sum(1 for s in esz if s > max(10, 0.0002 * mask.sum())))
    antenna = bool((cyan & (np.arange(rgb.shape[0])[:, None] < y0 + 0.12 * bh)).sum() > 8)
    return {
        "aspect_h_w": round(bh / max(1, bw), 3),
        "cyan_frac": round(float(cyan.sum()) / max(1, int(mask.sum())), 4),
        "mint_frac": round(float(mint.sum()) / max(1, int(mask.sum())), 4),
        "shell_frac": round(float(shell.sum()) / max(1, int(mask.sum())), 4),
        "cyan_chest_frac": round(float((cyan & chest_band).sum()) / max(1, int(mask.sum())), 4),
        "visor_frac": round(float(visor.sum()) / max(1, int(mask.sum())), 4),
        "n_eyes": n_eyes, "antenna": antenna,
        "cyan_hue": norm(cyan), "mint_hue": norm(mint), "shell_hue": norm(shell),
        "_crop": (x0, y0, x1, y1),
    }


# reference = accepted A3 Bolt (A4_start_frame Bolt region)
ref_rgb, _ = load_rgb(f"{AT}/a4_collapse/A4_start_frame.png")
ref_mask = np.zeros(ref_rgb.shape[:2], bool); ref_mask[827:1420, 153:776] = True
refm = character_mask(ref_rgb, None) & ref_mask
ref = features(ref_rgb, refm)

cands = {
  "canonical_assets_mascot": "assets/mascot/bolt.png",
  "cloud_phase2_bolt": "renders/bolt_cloud_experiment_package/phase2/assets/bolt.png",
  "oxygen_hover_run_dry(A-seed)": "renders/bolt_seq/oxygen_subscription/bolt_hover_run_dry.png",
  "oxygen_strain": "renders/bolt_seq/oxygen_subscription/bolt_strain.png",
  "oxygen_strain_reach": "renders/bolt_seq/oxygen_subscription/bolt_strain_reach.png",
  "oxygen_swim": "renders/bolt_seq/oxygen_subscription/bolt_swim.png",
  "pilot_collapsed": "renders/bolt_seq/_oxygen_pilot/bolt_collapsed.png",
  "pilot_impaired": "renders/bolt_seq/_oxygen_pilot/bolt_impaired.png",
  "REJECTED_bolt_fail": "renders/bolt_seq/oxygen_subscription/bolt_fail.png",
  "REJECTED_bolt_collapse": "renders/bolt_seq/oxygen_subscription/bolt_collapse.png",
}


def score(f):
    if not f or not ref: return 0.0, {}
    def hue_d(a, b): return float(np.abs(np.array(a) - np.array(b)).mean())
    sub = {
      "palette_cyan": max(0.0, 1 - hue_d(f["cyan_hue"], ref["cyan_hue"]) / 0.25),
      "palette_mint": max(0.0, 1 - hue_d(f["mint_hue"], ref["mint_hue"]) / 0.25),
      "palette_shell": max(0.0, 1 - hue_d(f["shell_hue"], ref["shell_hue"]) / 0.20),
      "cyan_chest_panel": max(0.0, 1 - abs(f["cyan_chest_frac"] - ref["cyan_chest_frac"]) / max(0.01, ref["cyan_chest_frac"] + 0.01)),
      "two_eyes": 1.0 if (f["n_eyes"] == ref["n_eyes"] == 2 or (f["n_eyes"] == 2)) else 0.3,
      "antenna": 1.0 if f["antenna"] == ref["antenna"] else 0.4,
      "head_aspect": max(0.0, 1 - abs(f["aspect_h_w"] - ref["aspect_h_w"]) / 0.8),
    }
    w = {"palette_cyan": 1.2, "palette_mint": 1.2, "palette_shell": 1.0, "cyan_chest_panel": 1.6, "two_eyes": 1.2, "antenna": 0.6, "head_aspect": 0.8}
    s = round(sum(sub[k] * w[k] for k in sub) / sum(w.values()), 3)
    return s, {k: round(v, 3) for k, v in sub.items()}


rows = []
tiles = [("ACCEPTED_A3 (ref)", ref, ref_rgb, refm, 1.0)]
for name, p in cands.items():
    if not os.path.exists(p): rows.append({"candidate": name, "path": p, "MISSING": True}); continue
    rgb, im = load_rgb(p); alpha = np.asarray(Image.open(p).convert("RGBA"))[:, :, 3] if Image.open(p).mode in ("RGBA", "LA", "P") else None
    m = character_mask(rgb, alpha); f = features(rgb, m); s, sub = score(f)
    rows.append({"candidate": name, "path": p, "transparent_source": bool(alpha is not None and (alpha < 250).mean() > 0.02),
                 "identity_score": s, "subscores": sub, "features": {k: v for k, v in (f or {}).items() if k != "_crop"},
                 "accept_eligible": bool(not name.startswith("REJECTED"))})
    tiles.append((name, f, rgb, m, s))

rows_sorted = sorted([r for r in rows if "identity_score" in r], key=lambda r: -r["identity_score"])
# board
cell = 300; cols = len(tiles); board = Image.new("RGB", (cols * cell + 20, cell + 70), (30, 30, 34)); dd = ImageDraw.Draw(board)
for i, (label, f, rgb, m, s) in enumerate(tiles):
    if f and "_crop" in f:
        x0, y0, x1, y1 = f["_crop"]; crop = Image.fromarray(rgb[y0:y1, x0:x1].astype("uint8"))
    else:
        crop = Image.fromarray(rgb.astype("uint8"))
    crop.thumbnail((cell - 16, cell - 16)); tile = Image.new("RGB", (cell, cell), (60, 60, 66)); tile.paste(crop, ((cell - crop.width) // 2, (cell - crop.height) // 2))
    board.paste(tile, (i * cell + 10, 40)); dd.text((i * cell + 12, 12), label[:26], fill=(235, 235, 235)); dd.text((i * cell + 12, cell + 46), f"score {s}", fill=(150, 255, 150) if s >= 0.8 else (255, 200, 120))
board.save(f"{OUT}/A4_provenance_board.png")

out = {"objective": "a4_provenance_inventory", "read_only": True, "no_spend": True, "ALLOW_PAID": False,
       "reference": "accepted A3 Bolt = A4_start_frame Bolt region", "reference_features": {k: v for k, v in ref.items() if k != "_crop"} if ref else None,
       "source_types_found": {"psd_figma_3d_svg": "NONE in project", "transparent_png_sprites": "yes (magenta-backed, alpha)", "neutral_bg_render": "assets/mascot/bolt.png"},
       "excluded_from_acceptance": ["bolt_fail.png", "bolt_collapse.png"],
       "candidates_ranked": rows_sorted, "all_candidates": rows,
       "artifacts": {"board": "a4_collapse/provenance/A4_provenance_board.png"}}
json.dump(out, open(f"{AT}/a4_provenance_inventory.json", "w"), indent=2, default=str)
print("REF chest_cyan", ref["cyan_chest_frac"], "aspect", ref["aspect_h_w"], "cyan_hue", ref["cyan_hue"], "mint_hue", ref["mint_hue"])
for r in rows_sorted: print(f"{r['identity_score']:.3f}  {r['candidate']:32s} chest {r['features'].get('cyan_chest_frac')} eyes {r['features'].get('n_eyes')} transp {r.get('transparent_source')}")
print("DONE")
