"""Depth format: render narrated footage as a shot list of painted stills, I2V clips, text cards and
explainer graphics (operator standard since 2026-11-08, from the Chernobyl horses 60 s pilot).

A film is one JSON spec (see docs/DEPTH_FILM_FORMAT.md). The narration and music are cut, unchanged,
from an existing mix; only the pictures are new. This module is pure local work ($0): stills and
clips are bought by scripts/make_depth_film.py, which reads the same spec and enforces its cap.

Coordinates:
  * screen positions are pixels on a 1920x1080 canvas (the render is upscaled to 2560x1440);
  * points on a source picture ("pt", camera centres, callouts) are 0-1 fractions of that picture,
    or the name of an entry in the spec's "points" table.
Times are seconds, a spoken word ("Poison", "Mongolia#2" for the 2nd occurrence, "barn+0.3"),
or "+x" for x seconds after the start of the shot.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

W, H, FPS = 1920, 1080, 30
OUT_W, OUT_H = 2560, 1440
FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)
COLORS = {"red": (214, 40, 40), "green": (60, 190, 90), "orange": (222, 110, 40), "white": (255, 255, 255),
          "gold": (255, 200, 70), "dim": (70, 70, 76)}
CARD_BG = {"dark": (12, 12, 14, 225), "red": (214, 40, 40, 240), "tag": (12, 12, 14, 170)}


class SpecError(ValueError):
    pass


# ---------------------------------------------------------------- words and time
_TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    t = text.lower().replace("’", "'").replace("'s", "").replace("colour", "color")
    return _TOKEN.findall(t)


@dataclass
class Words:
    """Narration word timings on the film's timeline."""
    words: list[tuple[str, float, float]]          # (token, start, end)
    texts: list[tuple[float, float, str]] = field(default_factory=list)   # (start, end, narration)

    @classmethod
    def from_job(cls, job_dir: str) -> "Words":
        """Concatenate audio/scene_NN.mp3.word_times.json, offset by the cumulative scene durations."""
        adir = os.path.join(job_dir, "audio")
        names = sorted(n for n in os.listdir(adir) if re.fullmatch(r"scene_\d+\.mp3", n))
        out, texts, off = [], [], 0.0
        for n in names:
            wt = os.path.join(adir, n + ".word_times.json")
            if not os.path.exists(wt):
                raise SpecError(f"missing word timings {wt}")
            d = json.load(open(wt))
            for w, s, e in d["word_times"]:
                for tok in tokens(str(w)):
                    out.append((tok, off + float(s), off + float(e)))
            dur = media_duration(os.path.join(adir, n))
            texts.append((off, off + dur, d.get("narration", "")))
            off += dur
        return cls(out, texts)

    def find(self, ref: str, after: float | None = None) -> float:
        """Start of a spoken word/phrase. "word#n" counts from the top of the film; a plain word
        means the first occurrence at or after `after` (the shot being written)."""
        m = re.fullmatch(r"\s*([^#+\-]+?)(?:#(\d+))?\s*([+-]\s*[\d.]+)?\s*", ref)
        if not m:
            raise SpecError(f"bad time reference {ref!r}")
        toks = tokens(m.group(1))
        if not toks:
            raise SpecError(f"bad time reference {ref!r}")
        nth = int(m.group(2) or 1)
        floor = after if (after is not None and not m.group(2)) else None
        delta = float(m.group(3).replace(" ", "")) if m.group(3) else 0.0
        seen = 0
        for i in range(len(self.words) - len(toks) + 1):
            if [w[0] for w in self.words[i:i + len(toks)]] == toks:
                if floor is not None and self.words[i][1] < floor - 0.02:
                    continue
                seen += 1
                if seen == nth:
                    return round(self.words[i][1] + delta, 3)
        raise SpecError(f"word {ref!r} not spoken (occurrence {nth})")

    def spoken_near(self, tok: str, t: float, window: float) -> bool:
        if any(w == tok and abs(s - t) <= window for w, s, _ in self.words):
            return True
        if any(w == tok for w, _, _ in self.words):
            return False              # spoken, but not near this card
        # Word timings can tokenise differently from the script ("sand-coloured"): fall back to the
        # narration text of the scene playing at t.
        return any(a - window <= t <= b + window and tok in tokens(txt) for a, b, txt in self.texts)


def resolve_time(v, words: Words | None, shot_start: float | None = None, after: float | None = None) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v.strip().startswith("+"):
        if shot_start is None:
            raise SpecError(f"relative time {v!r} outside a shot")
        return shot_start + float(v.strip()[1:])
    if words is None:
        raise SpecError(f"word time {v!r} needs narration word timings")
    return words.find(str(v), after if after is not None else shot_start)


def media_duration(path: str) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).strip())


# ---------------------------------------------------------------- drawing helpers
def ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def lerp(a, b, u):
    return a + (b - a) * u


def color(c):
    if isinstance(c, str):
        return COLORS[c]
    return tuple(c)


class Renderer:
    def __init__(self, spec: dict, spec_path: str, words: Words | None = None):
        self.spec = spec
        self.base = os.path.dirname(os.path.abspath(spec_path))
        self.job = os.path.normpath(os.path.join(self.base, spec.get("job", "..")))
        self.words = words if words is not None else Words.from_job(self.job)
        self.points = spec.get("points", {})
        self._cache: dict = {}
        self.font_path = next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
        a = spec["audio"]
        self.start = resolve_time(a.get("start", 0), self.words)
        self.end = resolve_time(a["end"], self.words)
        self.shots = self._layout(spec["shots"])

    # -- paths
    def path(self, ref: str) -> str:
        if ref.startswith("@"):
            return os.path.join(self.base, "stills", ref[1:] + ".png")
        return ref if os.path.isabs(ref) else os.path.join(self.job, ref)

    def img(self, ref: str) -> Image.Image:
        k = ("img", ref)
        if k not in self._cache:
            p = self.path(ref)
            if not os.path.exists(p):
                raise SpecError(f"picture {ref!r} not found at {p} (run stills first?)")
            self._cache[k] = Image.open(p).convert("RGB")
        return self._cache[k]

    def font(self, size: int):
        k = ("font", size)
        if k not in self._cache:
            self._cache[k] = (ImageFont.truetype(self.font_path, size) if self.font_path
                              else ImageFont.load_default(size))
        return self._cache[k]

    def frac(self, pt) -> tuple[float, float]:
        if isinstance(pt, str):
            if pt not in self.points:
                raise SpecError(f"unknown point {pt!r}")
            pt = self.points[pt]
        return float(pt[0]), float(pt[1])

    # -- layout
    def _layout(self, shots: list[dict]) -> list[dict]:
        starts, prev = [], None
        for s in shots:
            prev = resolve_time(s["start"], self.words, after=prev)
            starts.append(prev)
        if not starts or abs(starts[0] - self.start) > 1e-6:
            raise SpecError("the first shot must start at audio.start")
        out = []
        for i, s in enumerate(shots):
            t0 = starts[i]
            t1 = starts[i + 1] if i + 1 < len(shots) else self.end
            if t1 <= t0:
                raise SpecError(f"shot {i + 1} ({s.get('name', '')}) has no duration: {t0:.2f}-{t1:.2f}")
            bg = s["bg"] if isinstance(s["bg"], list) else [s["bg"]]
            segs = []
            for j, g in enumerate(bg):
                g = dict(g)
                g["_from"] = resolve_time(g.get("from", t0), self.words, t0)
                segs.append(g)
            for j, g in enumerate(segs):
                g["_to"] = segs[j + 1]["_from"] + segs[j + 1].get("xfade", 0) if j + 1 < len(segs) else t1
            ovs = []
            for o in s.get("overlays", []):
                o = dict(o)
                o["_at"] = resolve_time(o.get("at", t0), self.words, t0)
                if "until" in o:
                    o["_until"] = resolve_time(o["until"], self.words, t0)
                if o.get("type") == "icon_rows":
                    for r in o["rows"]:
                        for k in ("at", "count_at"):
                            if k in r:
                                r["_" + k] = resolve_time(r[k], self.words, t0)
                        r["_build"] = [resolve_time(x, self.words, t0) for x in r["build"]]
                if o.get("type") == "chart":
                    for pnt in o["points"]:
                        pnt["_at"] = resolve_time(pnt["at"], self.words, None, after=0.0)
                if o.get("type") == "dots":
                    o["_build"] = [resolve_time(x, self.words, None, after=0.0) for x in o["build"]]
                    for st in o.get("states", []):
                        st["_at"] = resolve_time(st["at"], self.words, None, after=0.0)
                if o.get("type") == "bars":
                    o["rows"] = [dict(r) for r in o["rows"]]
                    for r in o["rows"]:
                        r["_at"] = resolve_time(r.get("at", o["_at"]), self.words, t0)
                if o.get("type") == "path" and "label" in o:
                    o["label"]["_at"] = resolve_time(o["label"].get("at", o.get("at", t0)), self.words, t0)
                ovs.append(o)
            out.append({"name": s.get("name", f"shot{i + 1}"), "t0": t0, "t1": t1, "bg": segs, "overlays": ovs,
                        "vignette": s.get("vignette", 0), "carry": s.get("carry", []),
                        "shows": s.get("shows")})
        return out

    # -- camera
    def camera(self, src: Image.Image, g: dict, t: float):
        win = g.get("window")
        a = resolve_time(win[0], self.words, g["_from"]) if win else g["_from"]
        b = resolve_time(win[1], self.words, g["_from"]) if win else g["_to"]
        u = (t - a) / (b - a) if b > a else 1.0
        u = ease(u) if g.get("ease") else min(1.0, max(0.0, u))
        z = g.get("z", [1.0, 1.0]); z = z if isinstance(z, list) else [z, z]
        c = g.get("c", [[0.5, 0.5], [0.5, 0.5]])
        if isinstance(c[0], (int, float)) or isinstance(c, str):
            c = [c, c]
        c0, c1 = self.frac(c[0]), self.frac(c[1])
        sw, sh = src.size
        zz = lerp(z[0], z[1], u)
        cx, cy = lerp(c0[0], c1[0], u) * sw, lerp(c0[1], c1[1], u) * sh
        bw = min(sw, sh * 16 / 9) / zz
        bh = bw * 9 / 16
        x0 = min(max(cx - bw / 2, 0), sw - bw)
        y0 = min(max(cy - bh / 2, 0), sh - bh)
        box = (x0, y0, x0 + bw, y0 + bh)
        return src.resize((W, H), Image.BICUBIC, box=box), box

    def grade(self, f: Image.Image, g: dict) -> Image.Image:
        if "blur" in g:
            f = f.filter(ImageFilter.GaussianBlur(g["blur"]))
        if "color" in g:
            f = ImageEnhance.Color(f).enhance(g["color"])
        if "bright" in g:
            f = ImageEnhance.Brightness(f).enhance(g["bright"])
        return f

    def clip_path(self, name: str) -> str:
        return os.path.join(self.base, "clips", name + ".mp4")

    def segment(self, si: int, gi: int, g: dict, t: float):
        """(frame, box-of-source-or-None, source-size)"""
        kind = g.get("type", "clip" if "clip" in g else "still")
        if kind == "clip" and os.path.exists(self.clip_path(g["clip"])) and not g.get("_force_still"):
            f = self.clip_frame((si, gi), self.clip_path(g["clip"]), g, t)
            return self.grade(f, g), (0, 0, W, H), (W, H)
        if kind in ("still", "clip"):
            src = self.img(g["still"])
            f, box = self.camera(src, g, t)
            return self.grade(f, g), box, src.size
        if kind == "split":
            prev = g["_prev"]
            f, box, size = prev
            u = ease((t - g["_from"]) / g.get("wipe", 0.35))
            f = f.copy()
            half = W // 2
            right = ImageOps.fit(self.img(g["right"]["still"]), (half, H), centering=tuple(g["right"].get("centering", (0.5, 0.5))))
            left = ImageOps.fit(self.img(g["left"]["still"]), (half, H), centering=tuple(g["left"].get("centering", (0.5, 0.5))))
            if u > 0:
                f.paste(right, (half, 0))
                x = int(-half + half * u)
                f.paste(left, (x, 0))
                ImageDraw.Draw(f).line([(x + half, 0), (x + half, H)], fill=(255, 255, 255), width=8)
            return f, None, None
        raise SpecError(f"unknown background type {kind!r}")

    def clip_frame(self, key, path, g, t):
        st = self._cache.get(("clip", key))
        dur = g["_to"] - g["_from"]
        if st is None or st["t"] > t + 1e-6:
            start = float(g.get("clip_start", 0))
            speed = min(1.0, (media_duration(path) - start) / dur) if g.get("fit", True) else 1.0
            p = subprocess.Popen(
                ["ffmpeg", "-v", "error", "-ss", str(start), "-i", path, "-vf",
                 f"setpts=PTS/{speed},fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                 "tpad=stop=-1:stop_mode=clone", "-frames:v", str(int(dur * FPS) + 4),
                 "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            if st is not None:
                st["p"].kill()
            st = {"p": p, "n": 0, "last": None, "t": t}
            self._cache[("clip", key)] = st
        want = int(round((t - g["_from"]) * FPS))
        while st["n"] <= want:
            b = st["p"].stdout.read(W * H * 3)
            if len(b) < W * H * 3:
                break
            st["last"] = Image.frombuffer("RGB", (W, H), b)
            st["n"] += 1
        st["t"] = t
        if st["last"] is None:
            raise SpecError(f"clip {path} produced no frames")
        return st["last"].copy()

    # -- overlays
    def card_img(self, text, size=72, style="dark", mark=None):
        k = ("card", text, size, style, mark)
        if k in self._cache:
            return self._cache[k]
        f = self.font(size)
        l, t, r, b = f.getbbox(text)
        tw, th = r - l, b - t
        pad = int(size * 0.32)
        mw = int(size * 0.9) if mark else 0
        im = Image.new("RGBA", (tw + 2 * pad + mw, th + 2 * pad), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, im.width, im.height], fill=CARD_BG[style])
        d.text((pad - l, pad - t), text, font=f, fill=(255, 255, 255))
        if mark:
            s = th * 0.8
            x = pad + tw + int(size * 0.25)
            y = pad + (th - s) / 2
            lw = max(4, size // 10)
            if mark == "check":
                d.line([(x, y + s * 0.55), (x + s * 0.35, y + s * 0.9), (x + s * 0.95, y + s * 0.05)],
                       fill=COLORS["green"], width=lw, joint="curve")
            elif mark == "x":
                d.line([(x, y), (x + s * 0.8, y + s)], fill=COLORS["red"], width=lw)
                d.line([(x + s * 0.8, y), (x, y + s)], fill=COLORS["red"], width=lw)
            else:
                raise SpecError(f"unknown mark {mark!r}")
        self._cache[k] = im
        return im

    @staticmethod
    def pop(frame, im, xy, age, anchor="lt", fade=None):
        if age < 0:
            return
        u = ease(age / 0.18)
        s = 0.86 + 0.14 * u
        if fade is not None:
            u *= min(1.0, max(0.0, fade / 0.2))
        w, h = max(1, int(im.width * s)), max(1, int(im.height * s))
        a = im.resize((w, h), Image.BICUBIC)
        if u < 1:
            a.putalpha(a.getchannel("A").point(lambda v: int(v * u)))
        x, y = xy
        if anchor[0] == "c": x -= w / 2
        if anchor[0] == "r": x -= w
        if anchor[1] == "c": y -= h / 2
        if anchor[1] == "b": y -= h
        x = min(max(x, 24), W - w - 24)
        y = min(max(y, 24), H - h - 24)
        frame.paste(a, (int(x), int(y)), a)

    def screen(self, ctx, pt, offset=(0, 0)):
        """A source point (fraction or name) -> screen pixels through the current camera box."""
        box, size = ctx["box"], ctx["size"]
        if box is None:
            raise SpecError("a source point needs a still background in this shot")
        fx, fy = self.frac(pt)
        px, py = fx * size[0], fy * size[1]
        x0, y0, x1, y1 = box
        return ((px - x0) / (x1 - x0) * W + offset[0], (py - y0) / (y1 - y0) * H + offset[1])

    def pos(self, ctx, o):
        if "pt" in o:
            return self.screen(ctx, o["pt"], o.get("offset", (0, 0)))
        return tuple(o.get("pos", (W / 2, 120)))

    def overlay(self, f: Image.Image, o: dict, t: float, ctx: dict):
        age = t - o["_at"]
        if age < 0:
            return
        fade = (o["_until"] - t) if "_until" in o else None
        if fade is not None and fade <= 0:
            return
        typ = o.get("type", "card")
        d = ImageDraw.Draw(f)
        if typ == "card":
            im = self.card_img(o["text"], o.get("size", 72), o.get("style", "dark"), o.get("mark"))
            self.pop(f, im, self.pos(ctx, o), age, o.get("anchor", "ct"), fade)
        elif typ == "callout":
            p = self.screen(ctx, o["pt"])
            lab = (p[0] + o["label"][0], p[1] + o["label"][1])
            u = ease(age / 0.3)
            d.line([p, (lerp(p[0], lab[0], u), lerp(p[1], lab[1], u))], fill=(255, 255, 255), width=5)
            r = 11
            d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=(255, 255, 255), outline=(0, 0, 0), width=3)
            if age > 0.22:
                im = self.card_img(o["text"], o.get("size", 60))
                self.pop(f, im, lab, age - 0.22, "rc" if lab[0] < p[0] else "lc")
        elif typ == "pin":
            p = self.pos(ctx, o)
            r = o.get("r", 12); c = color(o.get("color", "orange"))
            d.ellipse([p[0] - r * 2.2, p[1] - r * 2.2, p[0] + r * 2.2, p[1] + r * 2.2], outline=c, width=4)
            d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=c, outline=(255, 255, 255), width=3)
        elif typ == "ring":
            p = self.pos(ctx, o); R = o.get("radius", 170)
            d.arc([p[0] - R, p[1] - R, p[0] + R, p[1] + R], -90, -90 + 360 * ease(age / o.get("dur", 0.7)),
                  fill=color(o.get("color", "red")), width=9)
        elif typ == "glow":
            p = self.pos(ctx, o); g = ease(age / 0.5)
            rx, ry = o.get("rx", 190) * g, o.get("ry", 120) * g
            ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(ov).ellipse([p[0] - rx, p[1] - ry, p[0] + rx, p[1] + ry], fill=(255, 210, 90, 90),
                                       outline=(255, 230, 140, 230), width=5)
            f.paste(ov, (0, 0), ov)
        elif typ == "inset":
            c = self.pos(ctx, o); g = ease(age / 0.25)
            r = int(o.get("radius", 170) * (0.6 + 0.4 * g))
            s = ImageOps.fit(self.img(o["still"]), (2 * r, 2 * r))
            m = Image.new("L", (2 * r, 2 * r), 0)
            ImageDraw.Draw(m).ellipse([0, 0, 2 * r - 1, 2 * r - 1], fill=int(255 * g))
            f.paste(s, (int(c[0] - r), int(c[1] - r)), m)
            ImageDraw.Draw(f).ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], outline=(255, 255, 255), width=6)
        elif typ == "path":
            a, b = self.screen(ctx, o["from"]), self.screen(ctx, o["to"])
            pts = bezier(a, b, o.get("lift", 200))
            dotted(d, pts, ease(age / o.get("dur", 2.0)), color(o.get("color", "white")), 8)
            lb = o.get("label")
            if lb:
                mid = pts[len(pts) // 2]
                self.pop(f, self.card_img(lb["text"], lb.get("size", 120), lb.get("style", "dark")),
                         (mid[0], mid[1] + lb.get("dy", -40)), t - lb["_at"], "cc")
        elif typ == "icon_rows":
            self.icon_rows(f, d, o, t)
        elif typ == "chart":
            self.chart(f, d, o, t)
        elif typ == "dots":
            self.dots(f, d, o, t)
        elif typ == "statement":
            self.statement(f, o, age, fade)
        elif typ == "bars":
            self.bars(f, d, o, t)
        else:
            raise SpecError(f"unknown overlay type {typ!r}")

    def statement(self, f, o, age, fade):
        """One or two spoken words filling the frame over a darkened picture: the answer to a
        question the narration just asked ("SQUID.", "YES."). Busy paintings stay out of its way."""
        u = ease(age / 0.2)
        if fade is not None:
            u *= min(1.0, max(0.0, fade / 0.2))
        f.paste(Image.blend(f, Image.new("RGB", f.size, (6, 8, 12)), o.get("dim", 0.78) * u))
        font = self.font(o.get("size", 230))
        l, tp, r, b = font.getbbox(o["text"])
        im = Image.new("RGBA", (r - l + 8, b - tp + 8), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((4 - l, 4 - tp), o["text"], font=font, fill=color(o.get("color", "white")) + (255,))
        self.pop(f, im, tuple(o.get("pos", (W / 2, H / 2))), age, "cc", fade)

    def bars(self, f, d, o, t):
        """Horizontal bars on one scale, each filling when its number is spoken (YOU vs the animal)."""
        x0, y0, w = o.get("x", 620), o.get("y", 380), o.get("w", 900)
        bh, gap = o.get("bar", 64), o.get("gap", 150)
        vmax = float(o.get("vmax", max(r["v"] for r in o["rows"])))
        for i, r in enumerate(o["rows"]):
            age = t - r["_at"]
            if age < 0:
                continue
            y = y0 + i * gap
            self.pop(f, self.card_img(r["label"], o.get("size", 66)), (x0 - 36, y + bh / 2), age, "rc")
            d.rectangle([x0, y, x0 + w, y + bh], fill=(12, 12, 14), outline=(255, 255, 255), width=3)
            fill_w = w * (r["v"] / vmax) * ease((age - 0.15) / o.get("dur", 0.7))
            if fill_w >= 1:
                d.rectangle([x0 + 3, y + 3, x0 + max(4, fill_w - 3), y + bh - 3], fill=color(r.get("color", "white")))
            if r.get("value") and age > 0.5:
                self.pop(f, self.card_img(r["value"], o.get("size", 66), r.get("style", "dark")),
                         (x0 + w * r["v"] / vmax + 30, y + bh / 2), age - 0.5, "lc")

    def chart(self, f, d, o, t):
        """A line that grows point by point. Points are spaced evenly: it shows order, not a time scale."""
        x0, y0, w, h = o.get("box", (260, 200, 1400, 640))
        vmax = float(o.get("vmax", max(p["v"] for p in o["points"])))
        pts = o["points"]
        n = len(pts)
        xy = [(x0 + (i + 0.5) * w / n, y0 + h - h * p["v"] / vmax) for i, p in enumerate(pts)]
        d.line([(x0, y0 + h), (x0 + w, y0 + h)], fill=(255, 255, 255), width=4)
        for i, p in enumerate(pts):
            if t < p["_at"]:
                break
            age = t - p["_at"]
            if i:
                u = ease(age / 0.45)
                a, b = xy[i - 1], xy[i]
                d.line([a, (lerp(a[0], b[0], u), lerp(a[1], b[1], u))], fill=color(p.get("color", "gold")), width=9)
            if age >= 0.3 or i == 0:
                c = xy[i]; r = 15
                col = color(p.get("color", "gold"))
                d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=col, outline=(255, 255, 255), width=4)
                lab_y, anc = (c[1] + 40, "ct") if p.get("below") else (c[1] - 40, "cb")
                self.pop(f, self.card_img(p["label"], 66, p.get("style", "dark")), (c[0], lab_y), age - 0.3, anc)
                if p.get("sub"):
                    self.pop(f, self.card_img(p["sub"], 46, "tag"), (c[0], y0 + h + 22), age - 0.3, "ct")

    def dots(self, f, d, o, t):
        """n dots that build in, then change colour in groups (eight lost, seventeen bred...)."""
        n, per, r, gap = o["n"], o.get("per_row", 16), o.get("r", 26), o.get("gap", 78)
        x0 = o.get("x", (W - (per - 1) * gap) / 2)
        y0 = o.get("y", 300)
        b0, b1 = o["_build"]
        shown = int(n * ease((t - b0) / max(0.2, b1 - b0))) if t > b0 else 0
        cols = [(235, 235, 240)] * n
        for st in o.get("states", []):
            if t < st["_at"]:
                continue
            first, cnt = st.get("first", 0), st.get("count", n)
            k = int(cnt * ease((t - st["_at"]) / st.get("dur", 0.5)))
            for i in range(first, min(n, first + k)):
                cols[i] = color(st["color"])
        for i in range(shown):
            cx, cy = x0 + (i % per) * gap, y0 + (i // per) * gap
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=cols[i], outline=(0, 0, 0), width=2)

    def icon_rows(self, f, d, o, t):
        s, gap, x0, per = o.get("icon", 46), o.get("gap", 58), o.get("x", 700), o.get("per_row", 16)
        for r in o["rows"]:
            y = r["y"]
            if "_at" in r:
                self.pop(f, self.card_img(r["label"], r.get("size", 76)), (x0 - 50, y + 40), t - r["_at"], "rc")
            b0, b1 = r["_build"]
            n = r["n"]
            shown = int(n * ease((t - b0) / max(0.2, b1 - b0))) if t > b0 else 0
            for i in range(shown):
                cx = x0 + (i % per) * gap + s / 2
                cy = y + (i // per) * o.get("row_gap", 85)
                hi = r.get("highlight_last") and i == n - 1
                if hi:
                    pul = 1 + 0.18 * math.sin((t - b1) * 9) * max(0, 1 - (t - b1) / 1.5)
                    chromo(d, cx, cy, s * 1.3 * pul, COLORS["red"])
                    d.ellipse([cx - 44, cy - 44, cx + 44, cy + 44], outline=COLORS["red"], width=4)
                else:
                    chromo(d, cx, cy, s, (235, 235, 240))
            if "_count_at" in r:
                self.pop(f, self.card_img(r["count"], 64, r.get("count_style", "dark")), (x0 - 50, y + 130),
                         t - r["_count_at"], "rc")

    def close(self):
        """Stop any clip readers still open (they are reused across consecutive frames)."""
        for k, v in list(self._cache.items()):
            if isinstance(k, tuple) and k[0] == "clip":
                v["p"].kill(); v["p"].wait()
                del self._cache[k]

    # -- frames
    def frame(self, t: float) -> Image.Image:
        for si, s in enumerate(self.shots):
            if s["t0"] <= t < s["t1"] or (si == len(self.shots) - 1 and t >= s["t0"]):
                return self.shot_frame(si, s, t)
        raise ValueError(t)

    def shot_frame(self, si: int, s: dict, t: float) -> Image.Image:
        frame, ctx = None, {"box": None, "size": None}
        prev = None
        first = 0                     # skip segments fully covered by a later opaque one
        for gi, g in enumerate(s["bg"]):
            if g.get("type") != "split" and g["_from"] + g.get("xfade", 0) <= t:
                first = gi
        for gi, g in enumerate(s["bg"]):
            if gi < first:
                continue
            if t < g["_from"]:
                break
            if g.get("type") == "split":
                g["_prev"] = prev
            f, box, size = self.segment(si, gi, g, t)
            xf = g.get("xfade", 0)
            if frame is not None and xf and t < g["_from"] + xf:
                f = Image.blend(frame, f, ease((t - g["_from"]) / xf))
            frame = f
            if box is not None:
                ctx = {"box": box, "size": size}
            prev = (f, box, size)
        if frame is None:
            raise SpecError(f"shot {s['name']} has no background at {t:.2f}")
        for o in s["overlays"]:
            self.overlay(frame, o, t, ctx)
        if s["vignette"]:
            frame = vignette(frame, s["vignette"], self._cache)
        return frame

    # -- checks
    def check_cards(self, window: float = 8.0) -> list[str]:
        """Operator rule: a card says only words spoken around it. Returns problems (empty = pass)."""
        bad = []
        for s in self.shots:
            for o in s["overlays"]:
                texts = []
                if s["t0"] - 0.05 > o["_at"] or o["_at"] >= s["t1"]:
                    if not o.get("carry"):
                        bad.append(f"{s['name']}: overlay at {o['_at']:.2f}s is outside the shot {s['t0']:.2f}-{s['t1']:.2f}")
                if o.get("recap"):                 # repeats a line already spoken earlier in the film
                    for tok in tokens(o["text"]):
                        known = any(w == tok for w, _, _ in self.words.words)
                        earlier = any(w == tok and st <= o["_at"] + window for w, st, _ in self.words.words)
                        scripted = any(st <= o["_at"] + window and tok in tokens(txt) for st, _, txt in self.words.texts)
                        if not (earlier or (not known and scripted)):
                            bad.append(f"{s['name']}: recap card {o['text']!r} says {tok!r}, never spoken before it")
                    continue
                if o.get("type") == "chart":
                    for pnt in o["points"]:
                        for tok in tokens(pnt["label"] + " " + pnt.get("sub", "")):
                            if not self.words.spoken_near(tok, pnt["_at"], window):
                                bad.append(f"{s['name']}: chart point {pnt['label']!r} says {tok!r}, not spoken near {pnt['_at']:.1f}s")
                if o.get("type", "card") in ("card", "callout", "statement"):
                    texts.append(o["text"])
                if o.get("type") == "bars":
                    for r in o["rows"]:
                        for tok in tokens(r["label"] + " " + r.get("value", "")):
                            if not self.words.spoken_near(tok, r["_at"], window):
                                bad.append(f"{s['name']}: bar {r['label']!r} says {tok!r}, not spoken near {r['_at']:.1f}s")
                if o.get("type") == "path" and o.get("label"):
                    texts.append(o["label"]["text"])
                if o.get("type") == "icon_rows":
                    texts += [r.get("label", "") for r in o["rows"]] + [r.get("count", "") for r in o["rows"]]
                for txt in texts:
                    for tok in tokens(txt):
                        if not self.words.spoken_near(tok, o["_at"], window):
                            bad.append(f"{s['name']}: card {txt!r} says {tok!r}, not spoken within {window:g}s of {o['_at']:.1f}s")
        return bad

    PRESENCE = {"animal": 20.0, "you": 90.0}

    def check_presence(self) -> list[str]:
        """Stretches where the film's subject or the viewer's stand-in is off screen for too long.

        A shot lists who is in the picture: "shows": ["animal", "you"] (or [] for neither). The spec's
        "presence" table sets the longest allowed gap in seconds per name; the defaults come from the
        2026-11-12 read of the reference film, where the animal is almost never off screen and the
        diver keeps returning. A spec with no "shows" at all is not checked."""
        if not any(s["shows"] is not None for s in self.shots):
            return []
        limits = {**self.PRESENCE, **self.spec.get("presence", {})}
        out = [f"{s['name']}: no \"shows\" list (use [] when neither is in the picture)"
               for s in self.shots if s["shows"] is None]
        for who, limit in limits.items():
            if not limit:
                continue
            last, names = self.start, []
            for s in self.shots + [None]:
                if s is None or who in (s["shows"] or []):
                    end = self.end if s is None else s["t0"]
                    if end - last > limit + 1e-6:
                        out.append(f"{who} off screen {end - last:.0f}s ({last:.1f}-{end:.1f}, limit {limit:g}s): "
                                   + ", ".join(names))
                    if s is not None:
                        last, names = s["t1"], []
                else:
                    names.append(s["name"])
        return out

    def sample_times(self) -> list[float]:
        ts = []
        for s in self.shots:
            ats = [o["_at"] for o in s["overlays"] if o["_at"] < s["t1"]]
            t = max(ats) + 0.45 if ats else (s["t0"] + s["t1"]) / 2
            ts.append(round(min(t, s["t1"] - 0.05), 2))
        return ts

    def contact_sheet(self, out: str, times=None):
        times = times or self.sample_times()
        cols = 6
        sheet = Image.new("RGB", (480 * cols, 270 * math.ceil(len(times) / cols)))
        for i, t in enumerate(times):
            im = self.frame(t).resize((480, 270))
            ImageDraw.Draw(im).text((8, 6), f"{t:.1f}s", fill=(255, 255, 0))
            sheet.paste(im, ((i % cols) * 480, (i // cols) * 270))
        sheet.save(out, quality=88)
        self.close()
        return out

    def render(self, out: str, log=print):
        a = self.spec["audio"]
        src = os.path.join(self.job, a["source"])
        dur = self.end - self.start
        audio = out[:-4] + "_audio.m4a"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(self.start), "-i", src, "-t", f"{dur:.3f}", "-vn",
                        "-af", f"afade=t=out:st={max(0, dur - 0.35):.3f}:d=0.35", "-c:a", "aac", "-b:a", "192k", audio],
                       check=True)
        enc = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
             "-i", "-", "-i", audio, "-vf", f"scale={OUT_W}:{OUT_H}:flags=lanczos", "-c:v", "libx264",
             "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest",
             "-movflags", "+faststart", out], stdin=subprocess.PIPE)
        n = int(dur * FPS)
        for i in range(n):
            enc.stdin.write(self.frame(self.start + i / FPS).convert("RGB").tobytes())
            if i % 300 == 0:
                log(f"frame {i}/{n}")
        enc.stdin.close()
        self.close()
        if enc.wait():
            raise RuntimeError("encoder failed")
        os.remove(audio)
        return out

    def side_by_side(self, film: str, out: str, labels=("NOW", "NEW")):
        lab = Image.new("RGBA", (2560, 720), (0, 0, 0, 0))
        for x, txt in ((24, labels[0]), (1280 + 24, labels[1])):
            c = self.card_img(txt, 54); lab.paste(c, (x, 20), c)
        lp = out[:-4] + "_labels.png"; lab.save(lp)
        dur = self.end - self.start
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(self.start), "-t", f"{dur:.3f}",
                        "-i", os.path.join(self.job, self.spec["audio"]["source"]), "-i", film, "-i", lp,
                        "-filter_complex", "[0:v]scale=1280:720[a];[1:v]scale=1280:720[b];[a][b]hstack[s];[s][2:v]overlay=0:0[v]",
                        "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                        "-pix_fmt", "yuv420p", "-c:a", "copy", "-t", f"{dur:.3f}", "-movflags", "+faststart", out], check=True)
        os.remove(lp)
        return out


def chromo(d, x, y, s, col):
    w = max(5, int(s * 0.28))
    d.line([(x - s * 0.32, y - s * 0.5), (x + s * 0.32, y + s * 0.5)], fill=col, width=w)
    d.line([(x + s * 0.32, y - s * 0.5), (x - s * 0.32, y + s * 0.5)], fill=col, width=w)


def vignette(frame, strength, cache):
    k = ("vig", strength)
    if k not in cache:
        y, x = np.ogrid[-1:1:H * 1j, -1:1:W * 1j]
        cache[k] = (1 - strength * np.clip((x ** 2 + y ** 2) / 2, 0, 1) ** 1.2)[..., None]
    a = np.asarray(frame, dtype=np.float32) * cache[k]
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def bezier(a, b, lift, n=40):
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - lift
    return [((1 - s) ** 2 * a[0] + 2 * (1 - s) * s * mx + s * s * b[0],
             (1 - s) ** 2 * a[1] + 2 * (1 - s) * s * my + s * s * b[1]) for s in (i / n for i in range(n + 1))]


def dotted(d, pts, upto, col, width=7, dash=22, gap=14):
    seg = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    lens = [math.dist(a, b) for a, b in seg]
    total = sum(lens) * upto
    run, on, left = 0.0, True, dash
    for (a, b), L in zip(seg, lens):
        pos = 0.0
        while pos < L and run < total:
            step = min(left, L - pos, total - run)
            if on:
                p0 = (lerp(a[0], b[0], pos / L), lerp(a[1], b[1], pos / L))
                p1 = (lerp(a[0], b[0], (pos + step) / L), lerp(a[1], b[1], (pos + step) / L))
                d.line([p0, p1], fill=col, width=width)
            pos += step; run += step; left -= step
            if left <= 1e-9:
                on = not on
                left = dash if on else gap


def load(spec_path: str, words: Words | None = None) -> Renderer:
    return Renderer(json.load(open(spec_path)), spec_path, words)
