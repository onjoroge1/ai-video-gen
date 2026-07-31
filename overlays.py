"""
Video overlay banners rendered with Pillow, composited via ffmpeg.

Banners:
  - Prediction banner (top)  — Snapbet-style HIT/MISSED result card
  - Score banner    (bottom) — Dark bar showing match score
"""

import os
import json
import subprocess

from PIL import Image, ImageDraw, ImageFont

# ── Font loading ───────────────────────────────────────────────────────────────

_BOLD_PATHS = [
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
_REGULAR_PATHS = [
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _font(size: int, bold: bool = True) -> ImageFont.ImageFont:
    for p in (_BOLD_PATHS if bold else _REGULAR_PATHS):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _wh(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0], bb[3] - bb[1]


# ── Prediction banner ──────────────────────────────────────────────────────────

def make_prediction_banner(
    width: int,
    height: int,
    predicted_team: str,
    result: str,            # "hit" | "missed"
    win_prob: int = 68,
    confidence: str = "HIGH",
    model_accuracy: int = 61,
) -> Image.Image:
    """
    Dark HUD-style banner matching the Snapbet design.
    Left: icon circle  |  Centre: headline + subtitle + result pill  |  Right: stats
    """
    hit = result.strip().lower() == "hit"
    # Green for HIT, red for MISSED
    ACCENT     = (57, 255, 20)  if hit else (220, 40,  40)
    ACCENT_DIM = (20, 90,  8)   if hit else (90,  14,  14)
    BG         = (8,  13,  24, 248)   # very dark navy, nearly opaque

    img  = Image.new("RGBA", (width, height), BG)
    draw = ImageDraw.Draw(img)

    # ── Outer border ──────────────────────────────────────────────────────────
    draw.rectangle([0, 0, width - 1, height - 1], outline=ACCENT, width=3)
    # Subtle inner glow lines along top and bottom edges
    draw.line([(4, 3), (width - 4, 3)],               fill=(*ACCENT, 80), width=1)
    draw.line([(4, height - 4), (width - 4, height - 4)], fill=(*ACCENT, 80), width=1)

    # ─────────────────────────────────────────────────────────────────────────
    # LEFT SECTION: icon circle  (~22 % of width)
    # ─────────────────────────────────────────────────────────────────────────
    left_w = int(width * 0.22)
    cx, cy = left_w // 2, height // 2

    outer_r = int(height * 0.42)
    inner_r = int(height * 0.35)

    # Faint outer glow ring
    draw.ellipse([cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r],
                 outline=(*ACCENT, 50), width=10)
    # Main ring
    draw.ellipse([cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
                 outline=ACCENT, width=4)

    # ✓ or ✗ symbol
    sym = int(inner_r * 0.52)
    lw  = max(5, int(inner_r * 0.18))
    if hit:
        pts = [
            (cx - sym * 0.50, cy + sym * 0.05),
            (cx - sym * 0.10, cy + sym * 0.48),
            (cx + sym * 0.55, cy - sym * 0.40),
        ]
        draw.line([(int(x), int(y)) for x, y in pts], fill=ACCENT, width=lw)
    else:
        off = int(sym * 0.45)
        draw.line([(cx - off, cy - off), (cx + off, cy + off)], fill=ACCENT, width=lw)
        draw.line([(cx + off, cy - off), (cx - off, cy + off)], fill=ACCENT, width=lw)

    # ─────────────────────────────────────────────────────────────────────────
    # RIGHT STATS SECTION  (~26 % of width)
    # ─────────────────────────────────────────────────────────────────────────
    stats_w  = int(width * 0.26)
    stats_x0 = width - stats_w

    # Vertical divider
    draw.line([(stats_x0, int(height * 0.08)), (stats_x0, int(height * 0.92))],
              fill=(*ACCENT, 60), width=1)

    lbl_sz = max(10, int(height * 0.09))
    val_sz = max(16, int(height * 0.17))
    lbl_f  = _font(lbl_sz, bold=False)
    val_f  = _font(val_sz, bold=True)

    # Confidence fill fraction
    conf_fill = {"HIGH": 0.90, "MEDIUM": 0.55, "LOW": 0.25}.get(confidence.upper(), 0.55)

    stats = [
        ("WIN PROBABILITY", f"{win_prob}%",      win_prob / 100),
        ("CONFIDENCE",      confidence.upper(),  conf_fill),
        ("MODEL ACCURACY",  f"{model_accuracy}%", model_accuracy / 100),
    ]
    row_h     = int(height * 0.76) // len(stats)
    bar_w     = stats_w - 24
    stat_y    = int(height * 0.10)

    for label, value, frac in stats:
        lx = stats_x0 + 12
        draw.text((lx, stat_y), label, font=lbl_f, fill=(145, 145, 165))
        vw, _ = _wh(draw, value, val_f)
        draw.text((width - 14 - vw, stat_y - 2), value, font=val_f, fill=ACCENT)
        bar_y = stat_y + lbl_sz + 5
        draw.rectangle([lx, bar_y, lx + bar_w, bar_y + 5], fill=(35, 38, 58))
        draw.rectangle([lx, bar_y, lx + int(bar_w * frac), bar_y + 5], fill=ACCENT)
        stat_y += row_h

    # ─────────────────────────────────────────────────────────────────────────
    # CENTRE SECTION
    # ─────────────────────────────────────────────────────────────────────────
    c_x0  = left_w + 14
    c_x1  = stats_x0 - 14
    c_cx  = (c_x0 + c_x1) // 2
    c_w   = c_x1 - c_x0

    # Headline: "PREDICTION" WHITE + "HIT"/"MISSED" ACCENT
    hl_sz   = max(22, int(height * 0.21))
    hl_f    = _font(hl_sz)
    part1   = "PREDICTION "
    part2   = "HIT" if hit else "MISSED"
    w1, _   = _wh(draw, part1, hl_f)
    w2, _   = _wh(draw, part2, hl_f)
    hl_x    = c_cx - (w1 + w2) // 2
    hl_y    = int(height * 0.06)
    draw.text((hl_x,      hl_y), part1, font=hl_f, fill=(240, 240, 240))
    draw.text((hl_x + w1, hl_y), part2, font=hl_f, fill=ACCENT)

    # Sub: "We predicted [TEAM] to win"
    sub_sz = max(13, int(height * 0.12))
    sub_f  = _font(sub_sz, bold=False)
    tm_f   = _font(sub_sz, bold=True)
    s1, s2, s3 = "We predicted ", f"[{predicted_team}]", " to win"
    sw1, _ = _wh(draw, s1, sub_f)
    sw2, _ = _wh(draw, s2, tm_f)
    sw3, _ = _wh(draw, s3, sub_f)
    sub_x  = c_cx - (sw1 + sw2 + sw3) // 2
    sub_y  = hl_y + hl_sz + int(height * 0.04)
    draw.text((sub_x,              sub_y), s1, font=sub_f, fill=(190, 190, 190))
    draw.text((sub_x + sw1,        sub_y), s2, font=tm_f,  fill=(240, 240, 240))
    draw.text((sub_x + sw1 + sw2,  sub_y), s3, font=sub_f, fill=(190, 190, 190))

    # Result pill: "THEY WON" / "THEY LOST"
    res_text = "THEY WON" if hit else "THEY LOST"
    res_sz   = max(26, int(height * 0.24))
    res_f    = _font(res_sz)
    rw, rh   = _wh(draw, res_text, res_f)
    rx       = c_cx - rw // 2
    ry       = sub_y + sub_sz + int(height * 0.07)
    pad_x    = int(c_w * 0.06)
    pad_y    = int(height * 0.04)

    # Pill background on a separate layer for alpha blending
    pill_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    pd = ImageDraw.Draw(pill_layer)
    pd.rectangle(
        [rx - pad_x, ry - pad_y, rx + rw + pad_x, ry + rh + pad_y],
        fill=(*ACCENT_DIM, 210),
    )
    img = Image.alpha_composite(img, pill_layer)
    draw = ImageDraw.Draw(img)

    draw.rectangle(
        [rx - pad_x, ry - pad_y, rx + rw + pad_x, ry + rh + pad_y],
        outline=ACCENT, width=2,
    )

    # Chevrons  ▶▶  result  ◀◀
    chev_h = int(res_sz * 0.45)
    chev_y = ry + rh // 2
    chev_gap = int(c_w * 0.02)

    # Left  «
    lchev_x = rx - pad_x - chev_gap - chev_h
    draw.polygon(
        [(lchev_x + chev_h, chev_y - chev_h // 2),
         (lchev_x,          chev_y),
         (lchev_x + chev_h, chev_y + chev_h // 2)],
        fill=ACCENT,
    )
    # Right  »
    rchev_x = rx + rw + pad_x + chev_gap
    draw.polygon(
        [(rchev_x,          chev_y - chev_h // 2),
         (rchev_x + chev_h, chev_y),
         (rchev_x,          chev_y + chev_h // 2)],
        fill=ACCENT,
    )

    draw.text((rx, ry), res_text, font=res_f, fill=ACCENT)

    return img


# ── Score banner ───────────────────────────────────────────────────────────────

def make_score_banner(width: int, height: int, score_text: str) -> Image.Image:
    """Dark bar showing the match score, with a gold accent line along the top."""
    img  = Image.new("RGBA", (width, height), (8, 13, 24, 230))
    draw = ImageDraw.Draw(img)

    # Gold top accent
    draw.rectangle([0, 0, width - 1, 4], fill=(220, 185, 40))

    font_sz = max(28, int(height * 0.52))
    font    = _font(font_sz)
    text    = score_text.upper()
    tw, th  = _wh(draw, text, font)
    tx = (width - tw) // 2
    ty = (height - th) // 2 + 3
    draw.text((tx, ty), text, font=font, fill=(255, 255, 255))

    return img


# ── Video dimension probe ──────────────────────────────────────────────────────

def video_wh(path: str) -> tuple[int, int]:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
         "-print_format", "json", "-show_streams", path],
        capture_output=True, text=True, check=True,
    )
    s = json.loads(r.stdout)["streams"][0]
    return int(s["width"]), int(s["height"])


# ── Composite banners onto a clip ──────────────────────────────────────────────

def apply_overlays(
    input_path: str,
    output_path: str,
    top_img: "Image.Image | None",
    bottom_img: "Image.Image | None",
    tmp_dir: str,
) -> None:
    """
    Overlay RGBA PNG banners on top/bottom of a video clip using ffmpeg.
    If both are None, simply copies the file.
    """
    import shutil

    if top_img is None and bottom_img is None:
        shutil.copy(input_path, output_path)
        return

    extra_inputs: list[str] = []
    filters:      list[str] = []
    label = "0:v"
    idx   = 1

    if top_img is not None:
        p = os.path.join(tmp_dir, "_banner_top.png")
        top_img.save(p, "PNG")
        extra_inputs += ["-i", p]
        filters.append(f"[{label}][{idx}:v]overlay=0:0[ov{idx}]")
        label = f"ov{idx}"
        idx += 1

    if bottom_img is not None:
        p = os.path.join(tmp_dir, "_banner_bot.png")
        bottom_img.save(p, "PNG")
        extra_inputs += ["-i", p]
        filters.append(f"[{label}][{idx}:v]overlay=0:H-h[ov{idx}]")
        label = f"ov{idx}"
        idx += 1

    subprocess.run(
        [
            "ffmpeg", "-i", input_path,
            *extra_inputs,
            "-filter_complex", ";".join(filters),
            "-map", f"[{label}]",
            "-map", "0:a?",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            output_path, "-y",
        ],
        check=True,
        capture_output=True,
    )
