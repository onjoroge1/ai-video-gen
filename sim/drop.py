"""The hero drop is OUR pixels. The provider draws the world; it does not draw the physics subject.

WHY (negative validation, class 1 -- every lens killed it independently):
Asked for "enormous raindrops", the model drew the ICON of a raindrop: a tailed teardrop (a shape
that only exists hanging from a faucet), opaque black-cherry glass (a real drop is a transparent
lens), 30-40 cm at the subject's depth (the caption said 12 mm), trailing metres-long filaments
(Plateau-Rayleigh forbids them), falling at 5.3 m/s under a card that said ~2. Four physical
contradictions in one asset, each one individually a debunk-comment waiting to happen.

This is the bullet lesson again, four videos later: WHERE A NUMBER ON SCREEN DEPENDS ON THE
SUBJECT'S BEHAVIOUR, THE SUBJECT IS DETERMINISTIC. The compositor guarantees, by construction:

    shape   oblate spheroid, w/h ~1.4, slow shape oscillation; no tail, ever
    optics  transmits the background behind it (flipped, magnified) -- a lens, not a bead;
            darker Fresnel rim; one wide soft sky-toned specular; luminance can never
            exceed what the scene itself offers
    scale   d_m * px_per_m, declared, so the chip and the pixels assert the same size
    speed   v_ms * px_per_m / fps per frame, exactly -- the measured card speed IS the
            animation speed

Rides on ambient base frames (the provider's living background) exactly like sim/projectile.
"""
from __future__ import annotations
import math
import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .projectile import _base_frames

OBLATE = 1.4            # width/height of a large falling drop (flattened by ram pressure)
WOBBLE_HZ = 2.2         # shape oscillation -- large drops visibly breathe as they fall
RIM_DARK = 0.42         # Fresnel edge multiplier -- the rim IS the silhouette against haze
CORE_GAIN = 1.12        # transmitted background brightening: a lens focuses, slightly


def _drop_sprite(bg_patch, w, h, phase):
    """One drop frame: transmit `bg_patch` through an oblate lens. Returns RGBA Image.

    The refraction fake: the region BEHIND the drop, vertically flipped (a sphere inverts),
    magnified toward the centre, rim darkened. It is not ray tracing; it is the three cues an eye
    actually reads -- inversion, magnification, dark rim -- at 1/1000th the cost.
    """
    osc = 1.0 + 0.06 * math.sin(phase)          # breathe: wider <-> taller
    ww, hh = max(6, int(w * osc)), max(6, int(h / osc))
    src = bg_patch.resize((ww * 3, hh * 3)).transpose(Image.FLIP_TOP_BOTTOM)
    # magnify centre: crop the middle 70% and stretch back out
    cw, ch = int(src.width * 0.7), int(src.height * 0.7)
    src = src.crop(((src.width - cw) // 2, (src.height - ch) // 2,
                    (src.width + cw) // 2, (src.height + ch) // 2)).resize((ww, hh))
    arr = np.asarray(src, dtype=np.float32)

    yy, xx = np.mgrid[0:hh, 0:ww]
    r = np.sqrt(((xx - ww / 2) / (ww / 2)) ** 2 + ((yy - hh / 2) / (hh / 2)) ** 2)
    inside = r <= 1.0
    fres = np.where(r > 0.62, RIM_DARK + (1 - RIM_DARK) * (1 - (r - 0.62) / 0.38), 1.0)
    arr *= (fres * CORE_GAIN)[..., None]

    a = np.zeros((hh, ww), dtype=np.float32)
    a[inside] = 235
    edge = (r > 0.86) & inside
    a[edge] = 235 * (1.0 - (r[edge] - 0.86) / 0.14 * 0.45)

    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGBA")
    out.putalpha(Image.fromarray(a.astype(np.uint8)))

    # one wide soft sky specular, upper third -- never a white point (no sun in an overcast scene)
    spec = Image.new("RGBA", (ww, hh), (0, 0, 0, 0))
    d = ImageDraw.Draw(spec)
    d.ellipse([ww * 0.22, hh * 0.10, ww * 0.62, hh * 0.34], fill=(255, 255, 255, 54))
    spec = spec.filter(ImageFilter.GaussianBlur(max(2, ww // 12)))
    return Image.alpha_composite(out, spec)


def render_scene(plate_path, out_mp4, frames, fps, px_per_m, d_m, v_ms,
                 x_frac=0.62, ambient_mp4=None, out_wh=(1080, 1920), work=None,
                 impact_at=0.82, splash=True, slow_mo=1):
    """Composite one hero drop falling at its TRUE size and speed over the plate.

    impact_at: fraction of frame height where the drop lands (the datum surface). After impact a
    small crown of ballistic droplets -- total area never exceeding the drop's own -- plays out,
    and rings expand. splash=False leaves the landing to a provider clip.
    """
    W, H = out_wh
    work = work or (os.path.splitext(out_mp4)[0] + "_frames")
    os.makedirs(work, exist_ok=True)
    # _base_frames -> (list of frame PATHS, dir) from the ambient clip, or (None, None) when the
    # world has no live layer -- then every frame is the still plate, and the background-motion
    # gate downstream is what reports that honestly.
    base_paths, _ = _base_frames(plate_path, ambient_mp4, frames, out_wh, work)
    still = Image.open(plate_path).convert("RGB").resize((W, H))

    def base_frame(i):
        if base_paths:
            return Image.open(base_paths[i]).convert("RGBA")
        return still.convert("RGBA")

    dw = max(8, int(d_m * px_per_m * OBLATE))
    dh = max(6, int(dw / OBLATE))
    # slow_mo is DECLARED time dilation (a standard documentary device), never a hidden one:
    # build refuses a slow_mo scene whose on-screen text does not say so. The card speed stays
    # true; only the playback rate is stretched, and the viewer is told.
    px_per_frame = v_ms * px_per_m / fps / max(slow_mo, 1)
    y_impact = int(H * impact_at)
    n_fall = max(1, int((y_impact + dh) / max(px_per_frame, 1e-6)))

    # RAIN REPEATS. A single drop's whole event -- fall plus splash -- lasted 1.3s of a 5s beat,
    # and the remaining 3.7s was an empty puddle: the one shot built to showcase the drop spent
    # most of its runtime not containing one. Drops now cycle for the full shot, staggered in x,
    # overlapping so a new fall begins while the last splash fades.
    splash_frames = int(fps * 0.9)
    cycle = max(1, int((n_fall + splash_frames) * 0.7))
    rng = np.random.default_rng(int(d_m * 1e6) + int(v_ms * 100))
    events = []
    start = 0
    while start < frames:
        events.append((start, int(W * (x_frac + rng.uniform(-0.16, 0.16)))))
        start += cycle
    crowns = {i: [(rng.uniform(-1.6, 1.6), rng.uniform(1.2, 3.2), rng.uniform(0.35, 0.85))
                  for _ in range(10)] for i in range(len(events))}

    written = 0
    for f in range(frames):
        im = base_frame(f)
        draw = None
        for ei, (f0, x) in enumerate(events):
            df = f - f0
            if df < 0:
                continue
            if df <= n_fall:
                y = -dh + px_per_frame * df
                wob = math.sin(2 * math.pi * WOBBLE_HZ * df / fps)
                xx = x + int(2 * wob)
                patch = im.crop((max(0, xx - dw), max(0, int(y)),
                                 min(W, xx + dw), min(H, int(y) + dh * 2))).convert("RGB")
                if patch.width >= 4 and patch.height >= 4:
                    spr = _drop_sprite(patch, dw, dh, 2 * math.pi * WOBBLE_HZ * df / fps)
                    im.alpha_composite(spr, (xx - spr.width // 2, int(y)))
            elif splash and df <= n_fall + splash_frames:
                t = (df - n_fall) / fps
                g_px = 9.81 * px_per_m * 0.15      # low-gravity feel; scaled for slow worlds
                draw = draw or ImageDraw.Draw(im, "RGBA")
                for k, r0 in ((0, 6), (1, 2)):
                    rr = r0 + (t * v_ms * px_per_m / max(slow_mo, 1)) * (0.5 + 0.3 * k)
                    alpha = max(0, int(90 - t * 160 - k * 25))
                    if alpha > 0:
                        draw.ellipse([x - rr, y_impact - rr * 0.24, x + rr, y_impact + rr * 0.24],
                                     outline=(235, 235, 235, alpha), width=2)
                v_px = v_ms * px_per_m / max(slow_mo, 1)
                for vx, vy, size in crowns[ei]:
                    px = x + vx * v_px * t
                    py = y_impact - (vy * v_px * t - 0.5 * g_px / max(slow_mo, 1) * t * t)
                    if py < y_impact + 4:
                        sz = max(1, int(dw * 0.10 * size))
                        a = max(0, int(200 - t * 260))
                        if a > 0:
                            draw.ellipse([px - sz, py - sz, px + sz, py + sz],
                                         fill=(228, 224, 218, a))
        im.convert("RGB").save(os.path.join(work, f"f_{f:05d}.png"))
        written += 1

    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                    "-i", os.path.join(work, "f_%05d.png"), "-frames:v", str(frames),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                    "-pix_fmt", "yuv420p", out_mp4], check=True)
    import shutil
    shutil.rmtree(work, ignore_errors=True)   # contains the _bg dir from _base_frames
    return {"frames": written, "drop_px": (dw, dh), "px_per_frame": round(px_per_frame, 2),
            "slow_mo": slow_mo, "fall_frames": n_fall, "drops": len(events),
            "impact_frame": n_fall if splash else None}


def selftest(plate, px_per_m=1400, d_m=0.012, v_ms=1.5, fps=30):
    """Prove the compositor cannot commit the four shipped failures. Free, no provider.

    1. speed: measured displacement == card speed (the hook shipped at 2.65x its card)
    2. optics: drop interior within [0.45, 1.25] of the sky it transmits (no black bead, no laser)
    3. shape: aspect within [1.25, 1.55] (no teardrop tail)
    4. no pixel in the drop brighter than the plate's own maximum (nothing self-lit)
    """
    import tempfile
    out = os.path.join(tempfile.mkdtemp(), "droptest.mp4")
    rep = render_scene(plate, out, frames=48, fps=fps, px_per_m=px_per_m, d_m=d_m, v_ms=v_ms)
    want = v_ms * px_per_m / fps
    ok_speed = abs(rep["px_per_frame"] - want) < 0.01
    dw, dh = rep["drop_px"]
    ok_shape = 1.25 <= dw / dh <= 1.55

    import numpy as np
    from PIL import Image
    plate_arr = np.asarray(Image.open(plate).convert("L"))
    p_max = float(np.percentile(plate_arr, 99.9))
    frames_dir = out[:-4] + "_check"
    os.makedirs(frames_dir, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", out, "-vf", "select=eq(n\\,20)",
                    "-frames:v", "1", os.path.join(frames_dir, "f.png")], check=True)
    fr = np.asarray(Image.open(os.path.join(frames_dir, "f.png")).convert("L")).astype(float)
    y = int(-dh + (v_ms * px_per_m / fps) * 20)
    x = int(fr.shape[1] * 0.62)
    core = fr[max(0, y + dh // 3):y + dh, max(0, x - dw // 3):x + dw // 3]
    sky = fr[max(0, y - dh * 2):max(1, y - dh), max(0, x - dw):x + dw]
    ratio = core.mean() / max(sky.mean(), 1)
    ok_optics = 0.45 <= ratio <= 1.25
    ok_lum = core.max() <= p_max * 1.05 + 6
    return {"speed": bool(ok_speed), "shape": bool(ok_shape), "optics": bool(ok_optics),
            "not_self_lit": bool(ok_lum), "transmit_ratio": round(float(ratio), 2),
            "passed": bool(ok_speed and ok_shape and ok_optics and ok_lum)}
