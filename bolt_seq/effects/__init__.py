"""Effects layer (GENERIC registry + topic-agnostic procedural adapters). An effect is a pure
function fx(params, size) -> RGBA PIL image, driven by state-bound `params` (e.g. fill, intensity).
Full-frame effects return a WxH image (composited at 0,0); sprite effects return a smaller image the
scene graph places via its transform tracks. Registered by name so topic configs stay declarative and
the train test can reference effects it will never render.

Registry (name -> {fn, kind, note}):
  resource_meter     HUD bar; fill/warn params                         (oxygen reserve, fuel, health)
  destination_growth pulsing beacon ring behind a growing target       (goal chase)
  impact             single-frame white flash                          (breakthrough, collision)
  cloud_rupture      flash + expanding shock ring                      (cloud fixture rupture)
  fog_whiteout       white veil, opacity = intensity                    (blindness / inside cloud)
  visibility_loss    darkening tunnel-vision vignette                   (low oxygen, low light)
  collapse           red-edge + darken ramp                            (near-success failure)
  heat_distortion    warm shimmer veil (stub geometry)                  (train brakes; not rendered)"""
from __future__ import annotations
from PIL import Image, ImageDraw, ImageFilter
import math


def _canvas(size):
    return Image.new("RGBA", size, (0, 0, 0, 0))


def resource_meter(params, size):
    """HUD bar. params: fill(0..1), warn(0..1 threshold), x,y,w,h (fracs), label_frac."""
    W, H = size; img = _canvas(size); d = ImageDraw.Draw(img)
    fill = max(0.0, min(1.0, float(params.get("fill", 1.0))))
    warn = float(params.get("warn", 0.25))
    x = int(W * params.get("x", 0.08)); y = int(H * params.get("y", 0.06))
    w = int(W * params.get("w", 0.84)); h = int(H * params.get("h", 0.028))
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=(0, 0, 0, 150),
                        outline=(255, 255, 255, 120), width=3)
    amber = float(params.get("amber", 0.5))       # green > amber band > warn(red)
    col = (90, 210, 120, 235) if fill > amber else ((240, 180, 60, 240) if fill > warn else (235, 80, 70, 245))
    if fill > 0:
        d.rounded_rectangle([x + 3, y + 3, x + 3 + int((w - 6) * fill), y + h - 3], radius=h // 2, fill=col)
    return img


def destination_growth(params, size):
    """Pulsing beacon rings that grow with `progress` (0..1). Placed behind the destination sprite."""
    W, H = size; img = _canvas(size); d = ImageDraw.Draw(img)
    prog = max(0.0, min(1.0, float(params.get("progress", 0.0))))
    cx = int(W * params.get("x", 0.72)); cy = int(H * params.get("y", 0.46))
    base = int(W * (0.05 + 0.28 * prog))
    for k, a in ((1.0, 90), (1.4, 55), (1.85, 28)):
        r = int(base * k * (0.9 + 0.1 * math.sin(prog * 6.28)))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(120, 220, 255, int(a * (0.5 + prog))), width=6)
    return img


def impact(params, size):
    W, H = size
    a = int(255 * max(0.0, min(1.0, float(params.get("intensity", 1.0)))))
    return Image.new("RGBA", size, (255, 255, 255, a))


def cloud_rupture(params, size):
    """Breakthrough: white flash + one expanding shock ring. `intensity` 0..1 drives both."""
    W, H = size; inten = max(0.0, min(1.0, float(params.get("intensity", 1.0))))
    img = Image.new("RGBA", size, (255, 255, 255, int(230 * inten)))
    d = ImageDraw.Draw(img)
    r = int(min(W, H) * (0.15 + 0.6 * inten)); cx, cy = W // 2, int(H * params.get("y", 0.5))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, int(200 * inten)), width=max(4, int(24 * inten)))
    return img


def fog_whiteout(params, size):
    inten = max(0.0, min(1.0, float(params.get("intensity", 0.5))))
    return Image.new("RGBA", size, (236, 240, 245, int(200 * inten)))


def visibility_loss(params, size):
    """Tunnel-vision vignette; `intensity` 0..1 = how closed-in / dark the edges get."""
    W, H = size; inten = max(0.0, min(1.0, float(params.get("intensity", 0.0))))
    if inten <= 0.01:
        return _canvas(size)
    mask = Image.new("L", (W, H), 0); d = ImageDraw.Draw(mask)
    rx = int(W * (0.62 - 0.30 * inten)); ry = int(H * (0.55 - 0.28 * inten))
    d.ellipse([W // 2 - rx, H // 2 - ry, W // 2 + rx, H // 2 + ry], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(int(80 + 120 * inten)))
    veil = Image.new("RGBA", (W, H), (2, 6, 16, int(235 * inten)))
    out = _canvas(size); out.paste(veil, (0, 0)); out.putalpha(Image.eval(mask, lambda p: 255 - p))
    a = out.split()[3].point(lambda p: int(p * (0.6 + 0.4 * inten))); out.putalpha(a)
    return out


def collapse(params, size):
    """Near-success failure wash: red edge glow + darken. `intensity` 0..1."""
    W, H = size; inten = max(0.0, min(1.0, float(params.get("intensity", 0.0))))
    img = Image.new("RGBA", size, (60, 0, 0, int(120 * inten)))
    d = ImageDraw.Draw(img)
    for k in range(6):
        a = int(140 * inten * (1 - k / 6)); m = k * 26
        d.rectangle([m, m, W - m, H - m], outline=(220, 40, 30, a), width=10)
    return img


def heat_distortion(params, size):
    """Warm shimmer veil (train fixture — registered but geometry is a stub; train never renders)."""
    inten = max(0.0, min(1.0, float(params.get("intensity", 0.3))))
    return Image.new("RGBA", size, (255, 140, 60, int(60 * inten)))


def air_bubble(params, size):
    """A translucent air-bubble SPRITE (returned smaller than the frame → placed by the scene graph's
    transform). Represents a carried reserve of air; parent-attached to the character."""
    S = 400; img = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    d.ellipse([20, 20, S - 20, S - 20], fill=(150, 205, 245, 70), outline=(220, 240, 255, 180), width=8)
    d.ellipse([90, 80, 180, 170], fill=(255, 255, 255, 120))          # highlight
    d.arc([40, 40, S - 40, S - 40], 200, 320, fill=(255, 255, 255, 90), width=6)
    return img


def _rng(seed):
    import random
    return random.Random(seed)


def speed_streaks(params, size):
    """Parallax speed lines that scroll with `phase` (0..1). axis 'v'(down) or 'h'(left). Seeded →
    deterministic. Sells forward/downward velocity without a baked PNG."""
    W, H = size; img = _canvas(size); d = ImageDraw.Draw(img)
    ph = float(params.get("phase", 0.0)); n = int(params.get("density", 80))
    axis = params.get("axis", "v"); span = H if axis == "v" else W
    rng = _rng(int(params.get("seed", 7)))
    for _ in range(n):
        base = rng.randint(0, span); off = int((ph * span * 1.6)) % (span + 200)
        a = rng.randint(40, 150); L = rng.randint(40, 150); wln = rng.randint(2, 5)
        if axis == "v":
            x = rng.randint(0, W); y = (base + off) % (H + 200) - 100
            d.line([(x, y), (x, y + L)], fill=(255, 255, 255, a), width=wln)
        else:
            y = rng.randint(0, H); x = W - ((base + off) % (W + 200)) + 100
            d.line([(x, y), (x - L, y)], fill=(255, 255, 255, a), width=wln)
    return img


def rising_bubbles(params, size):
    """Underwater bubbles drifting up-left as `phase` advances. Seeded, deterministic."""
    W, H = size; img = _canvas(size); d = ImageDraw.Draw(img)
    ph = float(params.get("phase", 0.0)); n = int(params.get("density", 55))
    rng = _rng(int(params.get("seed", 11)))
    for _ in range(n):
        bx = rng.randint(0, W); by = rng.randint(0, H); rr = rng.randint(3, 11)
        y = (by - int(ph * H * 1.5)) % (H + 60) - 30
        x = (bx - int(ph * W * 0.4)) % (W + 60) - 30
        a = rng.randint(30, 120)
        d.ellipse([x - rr, y - rr, x + rr, y + rr], outline=(210, 235, 255, a), width=2)
    return img


def soft_shadow(params, size):
    """A small soft dark ellipse SPRITE (not full-frame) — placed by the scene graph via a parent/transform
    to ground a wall-mounted or floor object (contact/attachment shadow)."""
    w = int(params.get("w", 360)); h = int(params.get("h", 120))
    img = Image.new("RGBA", (max(8, w), max(8, h)), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse([4, 4, w - 4, h - 4], fill=(0, 0, 0, int(150 * params.get("strength", 0.6))))
    return img.filter(ImageFilter.GaussianBlur(max(4, h // 6)))


REGISTRY = {
    "resource_meter":     {"fn": resource_meter,     "kind": "hud",       "note": "reserve/fuel/health bar"},
    "soft_shadow":        {"fn": soft_shadow,        "kind": "sprite",    "note": "contact/attachment shadow"},
    "destination_growth": {"fn": destination_growth, "kind": "behind",    "note": "goal beacon rings"},
    "impact":             {"fn": impact,             "kind": "fullframe", "note": "white flash"},
    "cloud_rupture":      {"fn": cloud_rupture,      "kind": "fullframe", "note": "flash + shock ring"},
    "fog_whiteout":       {"fn": fog_whiteout,       "kind": "fullframe", "note": "white veil"},
    "visibility_loss":    {"fn": visibility_loss,    "kind": "fullframe", "note": "tunnel-vision vignette"},
    "collapse":           {"fn": collapse,           "kind": "fullframe", "note": "red-edge failure wash"},
    "heat_distortion":    {"fn": heat_distortion,    "kind": "fullframe", "note": "brake heat shimmer (stub)"},
    "speed_streaks":      {"fn": speed_streaks,      "kind": "fullframe", "note": "parallax speed lines"},
    "rising_bubbles":     {"fn": rising_bubbles,     "kind": "fullframe", "note": "underwater bubble drift"},
    "air_bubble":         {"fn": air_bubble,         "kind": "sprite",    "note": "carried air reserve"},
}


def draw(name, params, size):
    """Dispatch used as compiler.render_scene_block(draw_fn=effects.draw)."""
    e = REGISTRY.get(name)
    if not e:
        return _canvas(size)
    return e["fn"](params or {}, size)


def list_effects():
    return {k: {"kind": v["kind"], "note": v["note"]} for k, v in REGISTRY.items()}
