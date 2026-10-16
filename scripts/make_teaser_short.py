"""Cut a vertical (1080x1920) teaser Short from a delivered illustrated film's job directory.

The short is the film's own opening -- its narration, music, cut points and pictures -- ending
on a sentence boundary near the target length, with large phrase captions, a persistent
headline, and a closing "full story" card. Two picture modes, chosen automatically:

  reframe   the job still has its accepted scene images (images/ or images_keep/): each shot of
            the film's rendered shot plan is re-cut as a 9:16 window of its own image with a
            slow push, so the teaser is a true vertical edit of the same verified pictures.
  pillarbox the images are gone: the finished landscape frame sits in the middle third of the
            canvas over a blurred, enlarged copy of itself. Lower quality; still correct.

Pacing (2026-10-16): a Short is judged on "viewed vs swiped away", and the film's shot plan
re-frames one still several times (push to detail, pull to wide, pan) -- which the old reframe
flattened into one centred window, so the Chernobyl Short held its first picture for 10.6 s.
Now every hold longer than --max-hold seconds is split, and consecutive shots of the same
image get different 9:16 windows (wide left/centre/right, or a close-up on the image's busiest
detail) with varied movement. --inserts adds extra pictures (e.g. native vertical images) over
exact time ranges.

    python3 scripts/make_teaser_short.py jobs/canetoad01 [--seconds 55] [--out teaser.mp4]
                                         [--headline "THE 101-CANE-TOAD MISTAKE"] [--mode auto]
                                         [--max-hold 2.6] [--inserts inserts.json]

Writes <job>/teaser.mp4 and <job>/teaser_package.json (title, description, tags). Buys nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from media_binaries import ffmpeg as _ffmpeg_bin, ffprobe as _ffprobe_bin  # noqa: E402

W, H, FPS = 1080, 1920, 30
MAX_HOLD = 2.6               # longest a Short holds one framing (s)
MIN_PART = 1.1               # a split part is never shorter than this (s)
CLOSE = 0.62                 # close-up window height as a share of the image height
SAFE_BOTTOM = 330            # Shorts UI (title, buttons) covers roughly the bottom 17%
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
YELLOW = (255, 230, 0)
WHITE = (255, 255, 255)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _duration(path: str) -> float:
    out = subprocess.run([_ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True, check=True)
    return float(out.stdout.strip() or 0)


def _srt(path: str) -> list[dict]:
    text = open(path, encoding="utf-8").read()
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", lines[1])
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(x) for x in m.groups())
        cues.append({"start": h1 * 3600 + m1 * 60 + s1 + ms1 / 1000,
                     "end": h2 * 3600 + m2 * 60 + s2 + ms2 / 1000,
                     "text": " ".join(lines[2:]).strip()})
    return cues


def _cut_point(cues: list[dict], target: float, floor: float = 35.0) -> float:
    """The latest sentence end at or before the target; the target itself if none qualifies."""
    best = None
    for cue in cues:
        for sentence_end in re.finditer(r"[.!?](?=\s|$)", cue["text"]):
            frac = (sentence_end.end()) / max(1, len(cue["text"]))
            t = cue["start"] + frac * (cue["end"] - cue["start"])
            if floor <= t <= target and (best is None or t > best):
                best = t
    return round(best if best is not None else target, 2)


def _phrases(cues: list[dict], until: float, words_per_chunk: int = 4) -> list[dict]:
    """Split each cue into short chunks timed proportionally to their character share.

    Timed across the cue's FULL span, then cut at `until`. Timing a cut cue over only the part
    before the cut squeezed all of its words into that window: a one-cue-per-scene caption file
    (Chernobyl, 2026-10-16) showed "EMERGENCY SHUTDOWN BUTTON" 6 s before the cut it never
    reaches. Chunks also end at sentence ends, so a caption never straddles two sentences."""
    out = []
    for cue in cues:
        if cue["start"] >= until:
            break
        words = cue["text"].split()
        if not words:
            continue
        chunks, cur = [], []
        for w in words:
            cur.append(w)
            if len(cur) >= words_per_chunk or re.search(r"[.!?]$", w):
                chunks.append(cur); cur = []
        if cur:
            chunks.append(cur)
        total_chars = sum(len(" ".join(c)) for c in chunks) or 1
        t = cue["start"]
        span = cue["end"] - cue["start"]
        for chunk in chunks:
            share = len(" ".join(chunk)) / total_chars
            start, end = t, t + share * span
            t = end
            if start < until:
                out.append({"start": round(start, 3), "end": round(min(end, until), 3),
                            "text": " ".join(chunk)})
    return out


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _text_png(path: str, lines: list[list[tuple[str, tuple]]], size: int, y: int,
              stroke: int = 8, pill: bool = False) -> None:
    """Render centred lines of (word, colour) runs onto a transparent 1080x1920 PNG."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _font(size)
    line_h = int(size * 1.18)
    if pill:
        widths = [sum(draw.textlength(w + " ", font=font) for w, _ in line) for line in lines]
        pw, ph = int(max(widths)) + 60, line_h * len(lines) + 40
        draw.rounded_rectangle([(W - pw) // 2, y - 20, (W + pw) // 2, y - 20 + ph],
                               radius=28, fill=(10, 10, 14, 200))
    for i, line in enumerate(lines):
        total = sum(draw.textlength(w + " ", font=font) for w, _ in line)
        x = (W - total) / 2
        yy = y + i * line_h
        for word, colour in line:
            draw.text((x, yy), word, font=font, fill=colour, stroke_width=stroke,
                      stroke_fill=(0, 0, 0))
            x += draw.textlength(word + " ", font=font)
    img.save(path)


def _headline_lines(headline: str, size: int) -> list[list[tuple[str, tuple]]]:
    """Headline wrapped to the frame, first line yellow, rest white: the thumbnail grammar."""
    probe = ImageDraw.Draw(Image.new("RGBA", (W, H)))
    # "|" forces a line break ("CHERNOBYL|40 YEARS LATER"); each part still wraps to the frame.
    lines = [ln for part in headline.upper().split("|")
             for ln in _wrap(probe, part.strip(), _font(size), W - 140)][:3]
    return [[(w, YELLOW if i == 0 else WHITE) for w in line.split()]
            for i, line in enumerate(lines)]


def _shots_until(job: str, until: float) -> list[dict]:
    plan_path = os.path.join(job, "rendered_contract_full.json")
    if not os.path.isfile(plan_path):
        plan_path = os.path.join(job, "rendered_contract.json")
    frames = json.load(open(plan_path)).get("inspection", {}).get("frames") or []
    assets = {}
    for scene in json.load(open(os.path.join(job, "evidence_asset_plan.json")))["scenes"]:
        for state in scene.get("states") or []:
            assets[state.get("asset_id")] = state.get("asset_path") or ""
    shots = []
    for fr in frames:
        start = float(fr.get("global_start_sec") or 0)
        if start >= until:
            break
        path = assets.get(fr.get("source"), "")
        for candidate in (path, path.replace("/images/", "/images_keep/")):
            if candidate and os.path.isfile(candidate):
                path = candidate
                break
        else:
            return []          # any missing picture -> fall back to pillarbox for the whole cut
        shots.append({"start": start, "end": min(until, start + float(fr.get("duration") or 0)),
                      "image": path, "motion": fr.get("motion") or "",
                      "transition": fr.get("transition") or ""})
    return shots


def split_long(shots: list[dict], max_hold: float = MAX_HOLD, min_part: float = MIN_PART) -> list[dict]:
    """Split every hold longer than max_hold into equal parts no shorter than min_part."""
    out = []
    for shot in shots:
        d = shot["end"] - shot["start"]
        n = max(1, min(int(-(-d // max_hold)), int(d // min_part) or 1))
        for k in range(n):
            part = dict(shot, start=shot["start"] + d * k / n, end=shot["start"] + d * (k + 1) / n)
            if k:
                part["transition"] = "split"
            out.append(part)
    return out


def apply_inserts(shots: list[dict], inserts: list[dict]) -> list[dict]:
    """Lay extra pictures over exact [start, end) ranges, trimming the shots they cover."""
    out = list(shots)
    for ins in sorted(inserts or [], key=lambda x: float(x["start"])):
        a, b = float(ins["start"]), float(ins["end"])
        kept = []
        for s in out:
            if s["end"] <= a or s["start"] >= b:
                kept.append(s)
                continue
            if s["start"] < a:
                kept.append(dict(s, end=a))
            if s["end"] > b:
                kept.append(dict(s, start=b, transition="hard_cut"))
        kept.append({"start": a, "end": b, "image": ins["image"], "motion": ins.get("motion", ""),
                     "transition": "hard_cut", "inserted": True})
        out = sorted((s for s in kept if s["end"] - s["start"] > 0.05), key=lambda s: s["start"])
    return out


def candidate_windows(image_path: str) -> dict:
    """9:16 windows of a picture, scored by edge density so a crop lands on the subject.

    Returns {"wide": [...], "close": [...]}, each a list of (score, (x, y, w, h)) best first, in
    source pixels. A picture already narrower than 9:16 has one wide window: itself."""
    with Image.open(image_path) as im:
        iw, ih = im.size
        small = im.convert("L").resize((max(1, iw // 4), max(1, ih // 4)))
    edges = small.filter(ImageFilter.FIND_EDGES)
    px = edges.load(); sw, sh = edges.size

    def score(x, y, w, h):
        x0, y0, x1, y1 = x // 4, y // 4, max(x // 4 + 1, (x + w) // 4), max(y // 4 + 1, (y + h) // 4)
        tot = n = 0
        for yy in range(y0, min(y1, sh), 2):
            for xx in range(x0, min(x1, sw), 2):
                tot += px[xx, yy]; n += 1
        return tot / max(1, n)

    wide, close = [], []
    cw = min(iw, int(ih * 9 / 16))
    free = iw - cw
    for f in ((0.5,) if free <= 0 else (0.0, 0.5, 1.0)):
        x = int(free * f)
        wide.append((score(x, 0, cw, ih), (x, 0, cw, ih)))
    ch = int(ih * CLOSE); ccw = min(iw, int(ch * 9 / 16))
    for fy in (0.0, 0.5, 1.0):
        for fx in (0.0, 0.25, 0.5, 0.75, 1.0):
            x, y = int((iw - ccw) * fx), int((ih - ch) * fy)
            close.append((score(x, y, ccw, ch), (x, y, ccw, ch)))
    wide.sort(key=lambda t: -t[0]); close.sort(key=lambda t: -t[0])
    return {"wide": wide, "close": close}


_MOVES = ("push_in", "pull_out", "pan_right", "pan_left")


def assign_framing(shots: list[dict]) -> list[dict]:
    """Give each shot a window and a move; repeats of one picture never reuse a framing back to
    back, and the film's hints (push_to_detail, pull_to_wide, pan_*) steer the choice."""
    cache, used, out, prev_img, run, last = {}, {}, [], None, 0, None
    for i, shot in enumerate(shots):
        img = shot["image"]
        if img not in cache:
            cache[img] = candidate_windows(img)
        cands = cache[img]
        run = run + 1 if img == prev_img else 0
        hint = f"{shot.get('transition', '')} {shot.get('motion', '')}"
        wide = [w for _, w in cands["wide"]]
        close = [w for _, w in cands["close"]]
        if shot.get("inserted"):
            # An inserted picture may carry blank paper margins: take the busiest window of any kind.
            pool = [w for _, w in sorted(cands["wide"] + cands["close"], key=lambda t: -t[0])]
        elif "push_to_detail" in hint:
            pool = close
        elif "pull_to_wide" in hint or run == 0 or not close:
            pool = wide
        else:
            pool = close if run % 2 else wide
        # Next-best window of this kind not yet used for this picture, cycling once all are used.
        seen = used.setdefault(img, [])
        fresh = [w for w in pool if w not in seen and w != last]
        window = fresh[0] if fresh else next((w for w in pool if w != last), pool[0])
        seen.append(window)
        if "pan_right" in hint:
            move = "pan_right"
        elif "pan_left" in hint:
            move = "pan_left"
        elif "pull_to_wide" in hint:
            move = "pull_out"
        else:
            move = _MOVES[(i + run) % len(_MOVES)]
        out.append(dict(shot, window=window, move=move))
        prev_img, last = img, window
    return out


def _reframe_video(shots: list[dict], out_path: str, tmp: str) -> None:
    parts = []
    for i, shot in enumerate(shots):
        d = max(0.4, shot["end"] - shot["start"])
        n = max(1, int(round(d * FPS)))
        with Image.open(shot["image"]) as im:
            iw, ih = im.size
        x, y, cw, ch = shot.get("window") or ((iw - int(ih * 9 / 16)) // 2, 0, int(ih * 9 / 16), ih)
        move = shot.get("move") or "push_in"
        z = {"push_in": f"min(1+0.08*on/{n},1.08)", "pull_out": f"max(1.08-0.08*on/{n},1)"}.get(move, "1.08")
        if move == "pan_right":
            px = f"(iw-iw/zoom)*on/{n}"
        elif move == "pan_left":
            px = f"(iw-iw/zoom)*(1-on/{n})"
        else:
            px = "iw/2-(iw/zoom/2)"
        clip = os.path.join(tmp, f"shot_{i:03d}.mp4")
        vf = (f"crop={cw}:{ch}:{x}:{y},scale=2160:3840,"
              f"zoompan=z='{z}':x='{px}':y='ih/2-(ih/zoom/2)'"
              f":d={n}:s={W}x{H}:fps={FPS},format=yuv420p")
        _run([_ffmpeg_bin(), "-v", "error", "-y", "-loop", "1", "-i", shot["image"],
              "-t", f"{d:.3f}", "-vf", vf, "-r", str(FPS), "-an", clip])
        parts.append(clip)
    with open(os.path.join(tmp, "concat.txt"), "w") as handle:
        handle.write("".join(f"file '{p}'\n" for p in parts))
    _run([_ffmpeg_bin(), "-v", "error", "-y", "-f", "concat", "-safe", "0",
          "-i", os.path.join(tmp, "concat.txt"), "-c", "copy", out_path])


def _pillarbox_video(film: str, until: float, out_path: str) -> None:
    vf = (f"[0:v]split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},boxblur=30:6,eq=brightness=-0.08[bg];[b]scale={W}:-2[fg];"
          f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p")
    _run([_ffmpeg_bin(), "-v", "error", "-y", "-t", f"{until:.3f}", "-i", film,
          "-filter_complex", vf, "-r", str(FPS), "-an", out_path])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job")
    ap.add_argument("--seconds", type=float, default=55.0)
    ap.add_argument("--out", default="")
    ap.add_argument("--headline", default="")
    ap.add_argument("--mode", choices=("auto", "reframe", "pillarbox"), default="auto")
    ap.add_argument("--max-hold", type=float, default=MAX_HOLD,
                    help="longest a single framing is held, seconds (reframe mode)")
    ap.add_argument("--inserts", default="",
                    help="JSON list of {start, end, image[, motion]} laid over exact time ranges")
    args = ap.parse_args()
    job = os.path.abspath(args.job)
    film = os.path.join(job, "explainer.mp4")
    srt = os.path.join(job, "captions.srt")
    for needed in (film, srt):
        if not os.path.isfile(needed):
            sys.exit(f"missing {needed}")
    out_path = args.out or os.path.join(job, "teaser.mp4")

    cues = _srt(srt)
    until = _cut_point(cues, args.seconds)
    phrases = _phrases(cues, until)
    run_result = {}
    if os.path.isfile(os.path.join(job, "run_result.json")):
        run_result = json.load(open(os.path.join(job, "run_result.json")))
    title = run_result.get("title") or os.path.basename(job)
    # On-screen headline: the act, not the whole story. "The X Mistake That Y" keeps "The X
    # Mistake"; a story-sentence title (backfire packaging v3, 2026-10-11) keeps its first
    # sentence or the clause before its parenthetical turn.
    headline = args.headline or re.split(r"\.\s|\s\(", re.sub(r"\s+That\s.*$", "", title,
                                                              flags=re.I))[0].rstrip(".")

    shots = _shots_until(job, until) if args.mode != "pillarbox" else []
    mode = "reframe" if shots else "pillarbox"
    if shots:
        inserts = json.load(open(args.inserts)) if args.inserts else []
        shots = assign_framing(split_long(apply_inserts(shots, inserts), args.max_hold))
    if args.mode == "reframe" and not shots:
        sys.exit("reframe requested but the job's scene images are missing")

    with tempfile.TemporaryDirectory(prefix="teaser_") as tmp:
        base = os.path.join(tmp, "base.mp4")
        if mode == "reframe":
            _reframe_video(shots, base, tmp)
        else:
            _pillarbox_video(film, until, base)
        audio = os.path.join(tmp, "audio.m4a")
        _run([_ffmpeg_bin(), "-v", "error", "-y", "-t", f"{until:.3f}", "-i", film, "-vn",
              "-af", f"afade=t=out:st={max(0, until - 0.7):.3f}:d=0.7", "-c:a", "aac",
              "-b:a", "160k", audio])

        overlays = []       # (png, start, end)
        head_png = os.path.join(tmp, "headline.png")
        # Largest size whose wrap is at most two lines with no orphaned single word.
        head_size = 70
        for candidate in (92, 84, 76, 70):
            lines = _headline_lines(headline, candidate)
            # A forced break ("|") is intentional, so a one-word line there is not an orphan.
            if len(lines) <= 2 and ("|" in headline
                                    or all(len(line) > 1 or len(lines) == 1 for line in lines)):
                head_size = candidate
                break
        head_lines = _headline_lines(headline, head_size)
        head_y = 150 if mode == "reframe" else 110
        _text_png(head_png, head_lines, size=head_size, y=head_y, stroke=10)
        overlays.append((head_png, 0.0, until))
        cap_y = H - SAFE_BOTTOM - 260
        end_card_at = max(0.0, until - 2.6)
        # The closing card owns the caption band; the last phrase fragment yields to it.
        phrases = [dict(ph, end=min(ph["end"], end_card_at)) for ph in phrases
                   if ph["start"] < end_card_at]
        for i, ph in enumerate(phrases):
            png = os.path.join(tmp, f"cap_{i:03d}.png")
            probe = ImageDraw.Draw(Image.new("RGBA", (W, H)))
            lines = _wrap(probe, ph["text"].upper(), _font(68), W - 160)
            _text_png(png, [[(w, WHITE) for w in line.split()] for line in lines[:3]],
                      size=68, y=cap_y, stroke=7, pill=True)
            overlays.append((png, ph["start"], ph["end"]))
        end_png = os.path.join(tmp, "end.png")
        _text_png(end_png, [[("FULL", YELLOW), ("STORY", YELLOW)],
                            [("ON", WHITE), ("THE", WHITE), ("CHANNEL", WHITE)]],
                  size=84, y=cap_y - 40, stroke=9, pill=True)
        overlays.append((end_png, end_card_at, until))

        cmd = [_ffmpeg_bin(), "-v", "error", "-y", "-i", base, "-i", audio]
        for png, _, _ in overlays:
            cmd += ["-i", png]
        chain, prev = [], "[0:v]"
        for k, (_, start, end) in enumerate(overlays):
            nxt = f"[v{k}]"
            chain.append(f"{prev}[{k + 2}:v]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'{nxt}")
            prev = nxt
        cmd += ["-filter_complex", ";".join(chain), "-map", prev, "-map", "1:a",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                "-r", str(FPS), "-c:a", "copy", "-movflags", "+faststart", "-shortest", out_path]
        _run(cmd)

    description = ""
    desc_path = os.path.join(job, "description.txt")
    if os.path.isfile(desc_path):
        first = open(desc_path, encoding="utf-8").read().strip().split("\n\n")[0]
        description = first[:300].rstrip() + "\n\nFull story on the channel. #Shorts"
    package = {
        "teaser": out_path, "mode": mode, "seconds": until, "source_title": title,
        "shots": len(shots), "pictures": len({s["image"] for s in shots}),
        "longest_hold": round(max((s["end"] - s["start"] for s in shots), default=0.0), 2),
        "title": (title if not re.search(r"\sMistake\s+That\s", title, re.I) else
                  (headline.title() if headline.isupper() else headline))[:88] + " #Shorts",
        "description": description, "phrases": len(phrases),
        "tags": ["shorts", "animal history", "invasive species", "ecology", "backfire"],
    }
    with open(os.path.join(job, "teaser_package.json"), "w", encoding="utf-8") as handle:
        json.dump(package, handle, indent=1, ensure_ascii=False)
    print(json.dumps({k: package[k] for k in ("teaser", "mode", "seconds", "title")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
