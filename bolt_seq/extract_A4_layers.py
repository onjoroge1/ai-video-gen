"""A4 layer extraction (NO SPEND). Bolt-only RGBA matte from the EXACT A4 start frame + clean corridor plate +
alpha-contamination diagnostic. Does NOT transform/rotate/crop/warp A4_start_frame — used only as (a) frame-0
handoff ref, (b) Bolt-extraction source, (c) plate-alignment ref. Run: python3 -m bolt_seq.extract_A4_layers"""
import os, sys, json
sys.path.insert(0, "/Users/obadiah/Documents/video"); os.chdir("/Users/obadiah/Documents/video")
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from bolt_seq.providers import directed_video as DV

W, H = 1080, 1920
AT = "renders/bolt_seq/oxygen_subscription/atomic_shots"; OUT = f"{AT}/a4_collapse"; os.makedirs(OUT, exist_ok=True)
START = f"{OUT}/A4_start_frame.png"
PLATE = "renders/bolt_seq/oxygen_subscription/corridor_with_terminal.png"
a0 = np.asarray(Image.open(START).convert("RGB").resize((W, H)), float)
plate = np.asarray(Image.open(PLATE).convert("RGB").resize((W, H)), float)
gray = a0.mean(axis=2)


def _box(x0, y0, x1, y1):
    m = np.zeros((H, W), bool); m[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)] = True; return m


BOLT_BOX = _box(0.06, 0.26, 0.74, 0.82); TERM_BODY = _box(0.63, 0.26, 0.85, 0.53)
tone = float(np.median(a0[~BOLT_BOX].mean(1)) / max(1e-3, np.median(plate[~BOLT_BOX].mean(1))))
plate_toned = np.clip(plate * tone, 0, 255)
# clean plate (tone-matched to A4 start exposure) -> the static background for the whole A4 primitive
Image.fromarray(plate_toned.astype("uint8")).save(f"{OUT}/A4_clean_plate.png")

# Bolt matte by COLOR+geometry (diff-from-plate fails: the A3 Kling corridor drifts hugely from the plate, so diff
# lights up the whole corridor). Bolt = bright white shell OR light mint trim OR cyan glow, in a tight region; the
# dark visor is an interior hole recovered by fill; corridor (dark), red signage (low G/B), terminal (excluded) drop out.
R0, G0, B0 = a0[:, :, 0], a0[:, :, 1], a0[:, :, 2]
mn = np.minimum(np.minimum(R0, G0), B0); mx = np.maximum(np.maximum(R0, G0), B0)
white = mn > 95                                                    # Bolt's white shell
mint = (G0 > R0 + 5) & (G0 > 90) & (mn > 55) & ((mx - mn) < 95)    # light mint trim
cyan = (B0 > R0 + 15) & (B0 > 90)                                  # eyes / chest glow
TIGHT = _box(0.16, 0.40, 0.66, 0.78)
seed = (white | mint | cyan) & TIGHT & ~TERM_BODY
seed = ndimage.binary_closing(seed, iterations=3)
lbl, n = ndimage.label(seed); sizes = ndimage.sum(np.ones_like(lbl), lbl, range(1, n + 1))
big = lbl == (int(np.argmax(sizes)) + 1)
matte = ndimage.binary_fill_holes(ndimage.binary_closing(big, iterations=6))   # close ring + recover dark visor hole
matte = ndimage.binary_fill_holes(ndimage.binary_opening(matte, iterations=2)) # drop thin corridor spurs
core = ndimage.binary_erosion(matte, iterations=2)                 # pull the edge inside Bolt -> no corridor rim
alpha = np.clip(ndimage.gaussian_filter(core.astype(float), 1.0), 0, 1)

rgba = np.dstack([a0, (alpha * 255)]).astype("uint8")
Image.fromarray(rgba, "RGBA").save(f"{OUT}/A4_hover_rgba.png")

# --- alpha contamination diagnostic: inside the character layer, is there any background? ---
inside = alpha > 0.5; ninside = int(inside.sum())
R, G, B = a0[:, :, 0], a0[:, :, 1], a0[:, :, 2]
plate_like = (np.abs(a0 - plate_toned).mean(axis=2) < 15) & inside          # matches the plate -> bg leak
red_sign = (R > G + 40) & (R > B + 40) & inside                             # red corridor signage
term_green = (G > R + 25) & (G > B + 15) & (G > 90) & inside                # terminal green screen
darkbg = (gray < 35) & inside                                              # deep-corridor dark
contam = {
  "matte_area_px": ninside,
  "plate_like_frac": round(float(plate_like.sum()) / max(1, ninside), 4),
  "red_signage_frac": round(float(red_sign.sum()) / max(1, ninside), 4),
  "terminal_green_frac": round(float(term_green.sum()) / max(1, ninside), 4),
  "deep_dark_frac": round(float(darkbg.sum()) / max(1, ninside), 4),
  "clean": None,
}
contam["clean"] = bool(contam["plate_like_frac"] < 0.01 and contam["red_signage_frac"] < 0.002 and contam["terminal_green_frac"] < 0.002)

# diagnostic image: RGBA over magenta (stray bg shows) + edge outline + contamination pixels highlighted
mag = np.full((H, W, 3), [255, 0, 255], float)
comp = mag * (1 - alpha[..., None]) + a0 * alpha[..., None]
comp = comp.astype("uint8").copy()
edge = matte & ~ndimage.binary_erosion(matte, iterations=2)
comp[edge] = [255, 255, 0]
for m, col in [(plate_like, [255, 0, 0]), (red_sign, [255, 128, 0]), (term_green, [0, 255, 0])]:
    comp[m] = col
diag = Image.fromarray(comp); dd = ImageDraw.Draw(diag)
dd.text((20, 20), "A4 HOVER character layer on magenta | yellow=matte edge", fill=(255, 255, 255))
dd.text((20, 44), f"plate-like {contam['plate_like_frac']} red {contam['red_signage_frac']} term-green {contam['terminal_green_frac']} dark {contam['deep_dark_frac']}", fill=(255, 255, 255))
dd.text((20, 68), f"CLEAN={contam['clean']}", fill=(120, 255, 120) if contam["clean"] else (255, 120, 120))
diag.save(f"{OUT}/A4_hover_alpha_diag.png")

json.dump({"objective": "a4_layer_extraction", "no_spend": True, "provider_called": False, "ALLOW_PAID": False,
           "tone_factor_plate_to_A4start": round(tone, 4),
           "A4_start_not_transformed": True, "used_as": ["frame0_handoff_ref", "bolt_extraction_source", "plate_alignment_ref"],
           "exports": {"hover_rgba": "a4_collapse/A4_hover_rgba.png", "clean_plate": "a4_collapse/A4_clean_plate.png",
                       "hover_alpha_diag": "a4_collapse/A4_hover_alpha_diag.png",
                       "collapse_rgba": "PENDING — collapse pose to be confirmed (see report)"},
           "hover_alpha_contamination": contam,
           "collapse_pose_finding": "bolt_collapse.png is an UPRIGHT REST pose (filename misleading); bolt_fail.png is a side-slumped FAILING pose (listing, eyes lit) — neither is a lying-flat floor-collapse. Confirm which is the authoritative collapse contact pose before extracting A4_collapse_rgba.png."},
          open(f"{AT}/a4_layers_result.json", "w"), indent=2, default=str)
print("tone", round(tone, 3)); print(json.dumps(contam, indent=2)); print("hover rgba + clean plate + diag written")
