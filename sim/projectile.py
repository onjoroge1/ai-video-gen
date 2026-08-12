"""Composite ONE projectile, identically, onto every world -- driven by the integrated trajectory.

The previous revision's projectile changed appearance on every planet: a blue sparkle on Earth, a
dark blob on Venus, a rocket plume on Mars, a laser on Mercury. Nothing read as one controlled
variable, because nothing WAS one. Here a single sprite is drawn once and reused everywhere, so
"same projectile" is enforced by construction rather than asked for in a prompt.

The trail is evidence, not decoration:
  * rho = 0  -> NO trail at all. That absence is the visual proof of "no air".
  * dense    -> a short, fast-decaying disturbance, because the air is taking the energy.
  * thin     -> a long, faint line.
Trail length is derived from the atmosphere, so Venus looks throttled and Mercury looks clean for
the same reason the numbers say they are.

Motion blur is proportional to the projectile's CURRENT speed, so the Venus slowdown is visible
rather than asserted.
"""
from __future__ import annotations
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import board_pipeline as BP


def _F(size, bold=True):
    """Same typeface family the overlay chips use, so the ruler reads as part of the instrument."""
    return BP._F(BP._ARIAL_B if bold else BP._ARIAL, size)

# SCALE IS THE ONE DELIBERATE LIE, AND IT IS ONLY THE OBJECT.
# A 7.62mm round at true scale on a planetary vista is a sub-pixel speck -- physically honest and
# completely unwatchable, which is exactly why the source artwork drew a glowing comet instead. So
# the projectile is drawn ~4x oversize for legibility while the TRAJECTORY stays exactly as
# integrated. Scientific visualisation does this routinely; what has to stay true is the path, the
# relative ranges and the presence or absence of a trail, and all three do.
BULLET_PX = 104


def sprite(length=BULLET_PX, ss=5):
    """One brass projectile, drawn once, supersampled then reduced so the silhouette stays crisp.

    Procedural rather than generated: a generated bullet would differ between calls, and the whole
    claim of this piece is that the object does NOT change between worlds.

    Readability comes from silhouette and rim light, not from size alone -- the previous attempt was
    a fat blurred sliver that read as a banana. A 3.4:1 spitzer profile with a dark base, a specular
    band and a bright rim reads as a machined object even at phone size.
    """
    ratio = 0.29                                     # 3.4:1, an ordinary spitzer profile
    L, Wd = length * ss, max(4, int(length * ratio)) * ss
    im = Image.new("RGBA", (L, Wd), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    nose = int(L * 0.46)
    body = L - nose
    # ogive nose approximated by a smooth polygon, plus cylindrical body, pointing +x
    ogive = [(L, Wd / 2)]
    for t in range(1, 13):
        f = t / 12.0
        ogive.append((L - nose * f, Wd / 2 - (Wd / 2) * math.sin(f * math.pi / 2) ** 0.72))
    ogive += [(body, 0), (0, 0), (0, Wd), (body, Wd)]
    for t in range(12, 0, -1):
        f = t / 12.0
        ogive.append((L - nose * f, Wd / 2 + (Wd / 2) * math.sin(f * math.pi / 2) ** 0.72))
    d.polygon(ogive, fill=(176, 138, 78, 255))
    d.rectangle([0, 0, int(L * 0.10), Wd], fill=(132, 100, 56, 255))       # driving band
    # specular band along the upper third, shadow along the lower quarter
    sh = Image.new("RGBA", (L, Wd), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle([0, int(Wd * 0.16), L, int(Wd * 0.34)],
                                 fill=(255, 244, 214, 200))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(ss * 1.1)))
    dk = Image.new("RGBA", (L, Wd), (0, 0, 0, 0))
    ImageDraw.Draw(dk).rectangle([0, int(Wd * 0.74), L, Wd], fill=(26, 18, 8, 170))
    im.alpha_composite(dk.filter(ImageFilter.GaussianBlur(ss * 1.3)))
    # rim light so the silhouette survives against both bright sky and black space
    rim = im.filter(ImageFilter.FIND_EDGES).convert("L").point(lambda v: min(255, int(v * 1.5)))
    glow = Image.new("RGBA", (L, Wd), (255, 248, 226, 0))
    glow.putalpha(rim.filter(ImageFilter.GaussianBlur(ss * 0.8)))
    im.alpha_composite(Image.blend(Image.new("RGBA", (L, Wd), (0, 0, 0, 0)), glow, 0.5))
    return im.resize((length, max(3, int(length * ratio))), Image.LANCZOS)


def screen_path(pts, muzzle_xy, frame_wh, span=0.80, apex_frac=0.72):
    """Map metres to pixels so the WHOLE arc is on screen.

    The first version scaled x and y independently against loose limits and pushed the apex off the
    top of the frame, so most of the flight happened where nobody could see it. Now one isotropic
    scale is chosen as the tighter of two explicit constraints: the range must fit `span` of the
    frame width, and the apex must sit no higher than `apex_frac` of the muzzle's height above the
    frame top. Isotropic matters -- scaling x and y differently would distort the arc's SHAPE, and
    the shape is the finding.
    """
    W, H = frame_wh
    mx, my = muzzle_xy[0] * W, muzzle_xy[1] * H
    xs = [p[1] for p in pts]
    ys = [p[2] for p in pts]
    rng = max(max(xs), 1e-6)
    top = max(max(ys), 1e-6)
    s = min((W * span - mx) / rng, (my * apex_frac) / top)
    return [(mx + x * s, my - y * s) for x, y in zip(xs, ys)], s


def nice_bar(scale_px_per_m, frame_w, want=(0.16, 0.42)):
    """Pick a round distance whose on-screen bar occupies a sensible slice of the frame.

    The NUMBER is the information. Each world is drawn at whatever zoom fits its arc -- a 3,890x
    spread between Venus and Pluto -- so a bar of fixed physical length is either off-frame or
    invisible. Instead the bar stays a similar size and its LABEL changes: 1 km on Earth, 100 km on
    Mercury. That is what makes the rescaling honest rather than hidden.
    """
    lo, hi = want[0] * frame_w, want[1] * frame_w
    for m in (10, 20, 50, 100, 200, 500, 1_000, 2_000, 5_000, 10_000, 20_000, 50_000,
              100_000, 200_000, 500_000):
        px = m * scale_px_per_m
        if lo <= px <= hi:
            return m, px
    m = 10
    best = None
    for cand in (10, 20, 50, 100, 200, 500, 1_000, 2_000, 5_000, 10_000, 20_000, 50_000,
                 100_000, 200_000, 500_000):
        px = cand * scale_px_per_m
        err = abs(px - (lo + hi) / 2)
        if best is None or err < best[0]:
            best, m = (err, cand), cand
    return m, m * scale_px_per_m


def _fmt_dist(metres):
    """Readable precision, not float precision. 375.516 km is a measurement; 376 km is a fact."""
    if metres >= 100_000:
        return f"{metres/1000:.0f} km"
    if metres >= 10_000:
        return f"{metres/1000:.0f} km"
    if metres >= 1000:
        return f"{metres/1000:.1f} km"
    return f"{round(metres):.0f} m"


def draw_scale_bar(im, scale_px_per_m, travelled_m, y_frac=0.735):
    """A ruler that states the zoom, plus a live distance readout.

    Both are deliberate: the ruler makes the per-world scale explicit, and the readout turns the
    flight into a number that keeps climbing, which is a semantic change every frame rather than
    just a moving dot.
    """
    W, H = im.size
    unit_m, bar_px = nice_bar(scale_px_per_m, W)
    x0 = int(W * 0.075)
    y = int(H * y_frac)
    lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    # scrim so the ruler survives a bright sky
    d.rounded_rectangle([x0 - 22, y - 52, x0 + bar_px + 26, y + 26], radius=12,
                        fill=(6, 8, 12, 165))
    d.line([(x0, y), (x0 + bar_px, y)], fill=(238, 242, 248, 245), width=4)
    for xx in (x0, x0 + bar_px):
        d.line([(xx, y - 13), (xx, y + 13)], fill=(238, 242, 248, 245), width=4)
    f = _F(30)
    d.text((x0, y - 46), _fmt_dist(unit_m), font=f, fill=(240, 226, 190, 255))
    fr = _F(27)
    lab = f"RANGE  {_fmt_dist(round(travelled_m))}"
    tw = d.textlength(lab, font=fr)
    d.rounded_rectangle([W - tw - 64, y - 46, W - 34, y + 8], radius=10, fill=(6, 8, 12, 165))
    d.text((W - tw - 48, y - 40), lab, font=fr, fill=(214, 232, 255, 255))
    im.alpha_composite(lay)
    return im


def draw_frame(plate, pts, screen, idx_frac, world, bullet, trail_px_full=420, scale=None):
    """One composited frame: plate + physics trail up to the current point + the projectile."""
    im = plate.convert("RGBA").copy()
    n = len(screen)
    i = max(1, min(n - 1, int(idx_frac * (n - 1))))
    x, y = screen[i]

    # --- trail: only where there is air, and only just behind the projectile
    if world.rho > 0:
        # denser air -> shorter, more quickly consumed trail
        dens = min(1.0, world.rho / 1.225)
        tail_px = trail_px_full * (0.30 + 0.70 * (1.0 - min(1.0, math.log10(1 + world.rho) / 2)))
        layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        acc = 0.0
        j = i
        while j > 1 and acc < tail_px:
            x0, y0 = screen[j - 1]
            x1, y1 = screen[j]
            seg = math.hypot(x1 - x0, y1 - y0)
            acc += seg
            f = 1.0 - acc / max(tail_px, 1)
            a = int(215 * max(0.0, f) ** 1.05 * (0.55 + 0.45 * dens))
            wdt = max(2, int(9.0 * max(0.18, f)))
            d.line([(x0, y0), (x1, y1)], fill=(236, 240, 246, a), width=wdt)
            d.line([(x0, y0), (x1, y1)], fill=(255, 255, 255, int(a * 0.75)),
                   width=max(1, wdt // 3))
            j -= 1
        im.alpha_composite(layer.filter(ImageFilter.GaussianBlur(2.2)))

    # --- projectile, oriented along its velocity, blurred by its speed
    if i + 1 < n:
        dx = screen[min(i + 2, n - 1)][0] - screen[i - 1][0]
        dy = screen[min(i + 2, n - 1)][1] - screen[i - 1][1]
    else:
        dx, dy = 1.0, 0.0
    ang = math.degrees(math.atan2(-dy, dx))
    spd = pts[i][3] / max(pts[0][3], 1e-6)                 # 1.0 at muzzle, falls with drag
    b = bullet.rotate(ang, expand=True, resample=Image.BICUBIC)
    # Just enough blur to read as fast; more than ~1.5px and the machined silhouette turns to mush,
    # which is what made the first pass look like a gold sliver.
    if spd > 0.30:
        b = b.filter(ImageFilter.GaussianBlur(0.25 + 1.25 * spd))
    im.alpha_composite(b, (int(x - b.width / 2), int(y - b.height / 2)))
    if scale:
        draw_scale_bar(im, scale, pts[i][1])
    return im.convert("RGB")


def _base_frames(plate_path, ambient_mp4, frames, out_wh, work):
    """Frames of the WORLD layer: the ambient clip if there is one, else the still plate.

    A still base is why the physics render measured 0.002 background motion against the generated
    plates' 0.081-0.238 -- a live world replaced by a photograph. The ambient clip is decoded once
    and index-mapped onto the shot's length, so a 5s plate covers a 3s or 6s shot. The mapping
    ping-pongs rather than loops: a hard wrap back to frame 0 reads as a cut in the middle of a shot.
    """
    import subprocess as _sp
    W, H = out_wh
    if ambient_mp4 and os.path.exists(ambient_mp4):
        d = os.path.join(work, "_bg")
        os.makedirs(d, exist_ok=True)
        _sp.run(["ffmpeg", "-y", "-loglevel", "error", "-i", ambient_mp4,
                 "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
                 os.path.join(d, "b_%05d.png")], check=True)
        got = sorted(os.listdir(d))
        if got:
            n = len(got)
            idx = []
            for i in range(frames):
                k = i % max(2 * n - 2, 1)
                idx.append(k if k < n else 2 * n - 2 - k)
            return [os.path.join(d, got[min(j, n - 1)]) for j in idx], d
    return None, None


def render_scene(plate_path, world, muzzle_xy, frames, out_mp4, fps=30,
                 out_wh=(1080, 1920), ambient_mp4=None, scale_bar=False, progress=None):
    """Render one world's shot: the integrated arc, travelled by the one projectile."""
    import os
    import subprocess

    from . import ballistics as B

    plate = Image.open(plate_path).convert("RGB")
    work = out_mp4 + "_f"
    os.makedirs(work, exist_ok=True)
    # world layer: live if an ambient plate exists, still otherwise (and the gate will say so)
    bases, bgdir = _base_frames(plate_path, ambient_mp4, frames, out_wh, work)
    ref = Image.open(bases[0]).convert("RGB") if bases else plate
    pts, stats = B.integrate(world)
    screen, scale = screen_path(pts, muzzle_xy, ref.size)
    bullet = sprite()
    for f in range(frames):
        frac = (f + 1) / frames
        base = Image.open(bases[f]).convert("RGB") if bases else plate
        img = draw_frame(base, pts, screen, frac, world, bullet,
                         scale=(scale if scale_bar else None))
        img.save(os.path.join(work, f"f_{f:05d}.png"))
    stats["world_layer"] = "ambient clip" if bases else "still plate"
    # The supplied plates are 941x1672 -- an ODD width, which libx264 refuses outright. Scale to the
    # delivery frame here rather than leaving a trap for every future asset pack.
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                    "-i", os.path.join(work, "f_%05d.png"), "-frames:v", str(frames),
                    "-vf", f"scale={out_wh[0]}:{out_wh[1]}:force_original_aspect_ratio=increase,"
                           f"crop={out_wh[0]}:{out_wh[1]}",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                    "-pix_fmt", "yuv420p", out_mp4], check=True)
    if bgdir and os.path.isdir(bgdir):
        for f in os.listdir(bgdir):
            os.remove(os.path.join(bgdir, f))
        os.rmdir(bgdir)
    for f in os.listdir(work):
        os.remove(os.path.join(work, f))
    os.rmdir(work)
    return stats
