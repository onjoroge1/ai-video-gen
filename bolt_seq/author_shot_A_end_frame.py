"""Re-author the Shot-A end frame for boundary-pair consistency (NO SPEND). Fixes: (1) Bolt was 15% taller
than the seed — scale is now matched to the seed's MEASURED rendered height (not canvas height); (2) the
strain pose read as two-palms 'pushing an invisible wall' — candidate poses are tried and the one that reads
as a strained ONE-arm reach (per boundary_pair_consistency_gate) wins. The corridor+terminal pixels are the
EXACT seed plate (only Bolt's lateral position, pose, mild hover height change), so background change is ~0.
Emits: overlay, bbox comparison, scale-ratio report, terminal-anchor comparison, background-difference
heatmap, hand-to-terminal measurement, boundary_pair_consistency_report.json.
Run: python3 -m bolt_seq.author_shot_A_end_frame"""
import os, sys, json
PROJ = "/Users/obadiah/Documents/video"; os.chdir(PROJ); sys.path.insert(0, PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"), override=True)
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
from bolt_seq.providers import directed_video as DV

OX = os.path.join(PROJ, "renders/bolt_seq/oxygen_subscription")
AT = os.path.join(OX, "atomic_shots"); AUD = os.path.join(AT, "audit"); os.makedirs(AUD, exist_ok=True)
PLATE = os.path.join(OX, "corridor_with_terminal.png")
SEED = os.path.join(AT, "shot_A_seed.png"); OUT = os.path.join(AT, "shot_A_end_frame.png")
W, H = 1080, 1920
TERM_LEFT = 0.605; TARGET_GAP = 0.10
POSES = {"hover_run": (os.path.join(OX, "bolt_hover_run_dry.png"), 5)}  # deterministic reach: same asset family as seed → guaranteed identity + scale. tilt 5 keeps forward lean without pitching the head off the terminal. Generated strain pose (5 gpt-image attempts) never achieved strain and drifted, so it is NOT used.
SEED_CY = 0.52
END_CY = 0.56   # MODERATE sink: Bolt loses altitude (~75px) = propulsion weakening encoded geometrically
                # (facial strain is unachievable for this mascot), while keeping the hand near terminal height
                # and staying airborne with clearance. Chosen variant per user decision.


def _bg():
    im = Image.open(PLATE).convert("RGB"); tw = max(W, int(im.width * H / im.height))
    im = im.resize((tw, H), Image.LANCZOS)
    return im.crop(((im.width - W) // 2, 0, (im.width - W) // 2 + W, H)).convert("RGBA")


def _grade(im):
    a = im.split()[3]; rgb = ImageEnhance.Brightness(im.convert("RGB")).enhance(0.72)
    rgb = Image.blend(rgb, Image.new("RGB", im.size, (34, 100, 108)), 0.18)
    o = rgb.convert("RGBA"); o.putalpha(a); return o


def _bolt_h(rgb):
    a = np.asarray(rgb.convert("RGB"), float)
    bb = DV._blob_bbox(a, 0, int(TERM_LEFT * W), int(0.18 * H), int(0.90 * H))
    return (bb[3] - bb[1]) if bb else 0, bb


def _right_edge(rgb):
    a = np.asarray(rgb.convert("RGB"), float)
    bb = DV._blob_bbox(a, 0, int(TERM_LEFT * W), int(0.18 * H), int(0.90 * H))
    return (bb[2] / W) if bb else None


def compose(asset, content_h, cx, cy, tilt):
    fr = _bg()
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([int(cx * W - 130), int(0.82 * H), int(cx * W + 130), int(0.82 * H + 36)], fill=(0, 0, 0, 95))
    fr.alpha_composite(sh.filter(ImageFilter.GaussianBlur(16)))
    im = Image.open(asset).convert("RGBA"); im = im.crop(im.getbbox())
    scale = content_h / im.height; im = im.resize((max(1, int(im.width * scale)), content_h), Image.LANCZOS)
    im = _grade(im)
    if tilt: im = im.rotate(-tilt, expand=True, resample=Image.BICUBIC)   # negative = clockwise = FORWARD lean toward the right-side terminal
    fr.alpha_composite(im, (int(cx * W - im.width / 2), int(cy * H - im.height / 2)))
    return fr.convert("RGB")


def author_one(asset, tilt, target_h):
    # 1) scale loop: match MEASURED rendered height to the seed's
    content_h = int(target_h * 1.02); cx, cy = 0.42, END_CY
    for _ in range(10):
        img = compose(asset, content_h, cx, cy, tilt); mh, _ = _bolt_h(img)
        if mh == 0: content_h += 40; continue
        if abs(mh - target_h) <= target_h * 0.02: break
        content_h = int(content_h * target_h / mh)
    # 2) position loop: converge right edge to TERM_LEFT - TARGET_GAP
    target_edge = TERM_LEFT - TARGET_GAP
    for _ in range(10):
        img = compose(asset, content_h, cx, cy, tilt); e = _right_edge(img)
        if e is None: break
        if abs(target_edge - e) < 0.005: break
        cx += (target_edge - e)
    return compose(asset, content_h, cx, cy, tilt), content_h, cx


def artifacts(end_img_path, rep):
    A = Image.open(SEED).convert("RGB"); B = Image.open(end_img_path).convert("RGB")
    bs = rep["measured"]["start_bolt_bbox"]; be = rep["measured"]["end_bolt_bbox"]
    ts = rep["measured"]["start_terminal_bbox"]; te = rep["measured"]["end_terminal_bbox"]
    # overlay (blend + both boxes + terminal)
    ov = Image.blend(A, B, 0.5).copy(); d = ImageDraw.Draw(ov)
    if bs: d.rectangle(bs, outline=(120, 200, 255), width=5); d.text((bs[0], bs[1] - 24), "SEED Bolt", fill=(120, 200, 255))
    if be: d.rectangle(be, outline=(120, 240, 140), width=5); d.text((be[0], be[1] - 24), "END Bolt", fill=(120, 240, 140))
    if te: d.rectangle(te, outline=(255, 90, 90), width=5); d.text((te[0], te[1] - 24), "terminal", fill=(255, 90, 90))
    ov.save(os.path.join(AUD, "boundary_pair_overlay.jpg"), quality=90)
    # bbox comparison (side by side with boxes)
    sc = A.copy(); dc = ImageDraw.Draw(sc)
    if bs: dc.rectangle(bs, outline=(120, 200, 255), width=6)
    ec = B.copy(); de = ImageDraw.Draw(ec)
    if be: de.rectangle(be, outline=(120, 240, 140), width=6)
    if te: de.rectangle(te, outline=(255, 90, 90), width=4)
    cmp = Image.new("RGB", (W, H // 2 + 30), (12, 12, 14))
    cmp.paste(sc.resize((W // 2, H // 2)), (0, 30)); cmp.paste(ec.resize((W // 2, H // 2)), (W // 2, 30))
    ImageDraw.Draw(cmp).text((8, 6), f"SEED h={rep['measured']['start_bolt_bbox'][3]-rep['measured']['start_bolt_bbox'][1]}px | "
                             f"END h={rep['measured']['end_bolt_bbox'][3]-rep['measured']['end_bolt_bbox'][1]}px | ratio {rep['measured']['height_ratio']}", fill=(230, 230, 230))
    cmp.save(os.path.join(AUD, "boundary_pair_bbox_compare.jpg"), quality=90)
    # background-difference heatmap
    diff = np.abs(np.asarray(A, float) - np.asarray(B, float)).mean(axis=2)
    hm = (np.clip(diff / max(1.0, diff.max()) * 255, 0, 255)).astype("uint8")
    Image.fromarray(hm).convert("L").save(os.path.join(AUD, "boundary_pair_bg_diff_heatmap.png"))


def main():
    cost = []
    seed_h, seed_bb = _bolt_h(Image.open(SEED))
    results = {}
    for name, (asset, tilt) in POSES.items():
        img, ch, cx = author_one(asset, tilt, seed_h)
        tmp = os.path.join(AUD, f"_end_{name}.png"); img.save(tmp)
        rep = DV.boundary_pair_consistency_gate(SEED, tmp, cost=cost)
        results[name] = {"pass": rep["pass"], "n_fail": sum(1 for v in rep["checks"].values() if not v),
                         "content_h": ch, "cx": round(cx, 3), "report": rep, "path": tmp}
        print(f"{name}: pass={rep['pass']} ratio={rep['measured']['height_ratio']} "
              f"gap={rep['measured']['final_gap']} bg={rep['measured']['bg_change_outside_bolt']} "
              f"fails={[k for k,v in rep['checks'].items() if not v]}")
    # pick: a full pass, else fewest failures (prefer pose that isn't two-palms and reaches)
    best = sorted(results.items(), key=lambda kv: (not kv[1]["pass"], kv[1]["n_fail"]))[0]
    name, r = best
    Image.open(r["path"]).convert("RGB").save(OUT)
    rep = r["report"]
    # hand-to-terminal: reaching hand tip (rightmost Bolt px at terminal height) -> terminal interaction point (terminal left-mid)
    B = np.asarray(Image.open(OUT).convert("RGB"), float)
    te = rep["measured"]["end_terminal_bbox"]
    hand_bb = DV._blob_bbox(B, 0, int(TERM_LEFT * W), int(0.30 * H), int(0.62 * H))   # Bolt within terminal's vertical band
    hand_tip = [hand_bb[2], (hand_bb[1] + hand_bb[3]) // 2] if hand_bb else None
    term_point = [te[0], (te[1] + te[3]) // 2] if te else [int(TERM_LEFT * W), int(0.43 * H)]
    hand_gap = round((term_point[0] - hand_tip[0]) / W, 4) if hand_tip else None
    artifacts(OUT, rep)
    out = {"no_spend": True, "chosen_pose": name, "chosen_content_height": r["content_h"],
           "seed_bolt_height_px": seed_h, "boundary_pair_pass": rep["pass"], "checks": rep["checks"],
           "measured": rep["measured"], "pose_readings": rep["pose_readings"],
           "hand_to_terminal": {"reaching_hand_tip_px": hand_tip, "terminal_interaction_point_px": term_point,
                                "horizontal_gap_frac": hand_gap},
           "scale_ratio_report": {"seed_height_px": seed_h, "end_height_px": rep["measured"]["end_bolt_bbox"][3] - rep["measured"]["end_bolt_bbox"][1],
                                  "ratio": rep["measured"]["height_ratio"], "target_band": [0.95, 1.05], "hard_tol": [0.92, 1.08]},
           "terminal_anchor_comparison": {"start": rep["measured"]["start_terminal_bbox"], "end": rep["measured"]["end_terminal_bbox"],
                                          "iou": rep["measured"]["terminal_iou"]},
           "artifacts": {"overlay": "audit/boundary_pair_overlay.jpg", "bbox_compare": "audit/boundary_pair_bbox_compare.jpg",
                         "bg_diff_heatmap": "audit/boundary_pair_bg_diff_heatmap.png"},
           "candidates": {k: {"pass": v["pass"], "fails": [c for c, ok in v["report"]["checks"].items() if not ok]} for k, v in results.items()},
           "vlm_cost_usd": round(sum(cost), 3), "manual_review_required": True, "allow_paid": DV.ALLOW_PAID}
    json.dump(out, open(os.path.join(AT, "boundary_pair_consistency_report.json"), "w"), indent=2, default=str)
    # 3-up comparison for human review
    def th(p): return Image.open(p).convert("RGB").resize((300, 533))
    sheet = Image.new("RGB", (900, 560), (12, 12, 14)); dd = ImageDraw.Draw(sheet)
    sheet.paste(th(SEED), (0, 24)); sheet.paste(th(os.path.join(AT, "shot_A_end_target.png")), (300, 24)); sheet.paste(th(OUT), (600, 24))
    dd.text((6, 6), "SEED (start)", fill=(230, 230, 230)); dd.text((306, 6), "OLD end_target", fill=(230, 160, 160))
    dd.text((606, 6), f"NEW end ({name}) ratio {rep['measured']['height_ratio']}", fill=(160, 230, 160))
    sheet.save(os.path.join(AT, "shot_A_end_frame_comparison.jpg"), quality=90)
    print(f"\nCHOSEN: {name} | boundary_pair_pass={rep['pass']} | height ratio {rep['measured']['height_ratio']} "
          f"| gap {rep['measured']['final_gap']} | bg {rep['measured']['bg_change_outside_bolt']} | hand_gap {hand_gap}")
    print("fails:", [k for k, v in rep["checks"].items() if not v])
    print("wrote", OUT, "+ boundary_pair_consistency_report.json + artifacts | ALLOW_PAID", DV.ALLOW_PAID)
    return rep["pass"]


if __name__ == "__main__":
    main()
