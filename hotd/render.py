"""The render engine: script + playlists + rail states -> one mp4, plus the shot ledger.

Episode-agnostic. The properties that make this format work, and the defects behind each:
  * a PLAYLIST of shots per segment, so the picture changes every ~6s (the baseline it replaced
    held one image for 1,184 frames)
  * duration-aware drift (step = 0.055/frames); a fixed step hits the zoom ceiling on long shots
    and the picture freezes
  * diagrams fitted to 86% of the oversized canvas, or the drift clips their edge labels
  * cards scaled into the 1086px column left of the rail; at native size they run under it
  * the 0.12s dip applied to the ART BEFORE the rail composites, or the always-on rail blinks at
    every cut
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
# Asset and render paths in every episode config are repo-relative. The original
# single-episode builder chdir'd to the repo root; the package split dropped that, which
# would have silently written renders wherever the caller happened to be standing.
if os.path.abspath(os.getcwd()) != REPO:
    os.chdir(REPO)
if os.path.exists(".env"):
    for _l in open(".env", encoding="utf8"):
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _, _v = _l.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

from PIL import Image, ImageDraw, ImageFilter

import board_pipeline as bp

W, H, FPS = 1920, 1080, 30
CONTENT_W = 1086                          # rail scrim begins here; art must stay left of it
BGW, BGH = int(W * 1.15), int(H * 1.15)   # pre-scale so zoompan never reveals an edge
DIAGRAM_FIT = 0.86                        # whole diagram stays inside the frame at MAX zoom
CARD_W, CARD_Y = 1018, 155
PAIR_W, PAIR_Y1, PAIR_Y2 = 818, 55, 545
LINE_H, HEAD_BOTTOM = 66, H - 96



# ----------------------------------------------------------------------------- image build
def _cover(path, w, h):
    im = Image.open(path).convert("RGB")
    s = max(w / im.width, h / im.height)
    im = im.resize((max(w, int(im.width * s + 0.5)), max(h, int(im.height * s + 0.5))), Image.LANCZOS)
    return im.crop(((im.width - w) // 2, (im.height - h) // 2,
                    (im.width - w) // 2 + w, (im.height - h) // 2 + h))


def _vignette(im, strength=0.55):
    w, h = im.size
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).ellipse([-w * 0.25, -h * 0.35, w * 1.25, h * 1.35], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(w // 8))
    return Image.composite(im, Image.blend(im, Image.new("RGB", (w, h), (0, 0, 0)), strength), m)


def build_bg(ep, kind, name, out):
    if kind in ("full", "map"):
        # A diagram's edge labels ARE the content, so it must survive the drift: fitted to 86% of
        # the oversized canvas and floated on a blurred mat, it grows slightly and never clips.
        im = Image.open(ep.asset(name)).convert("RGB")
        s = min(BGW * DIAGRAM_FIT / im.width, BGH * DIAGRAM_FIT / im.height)
        r = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
        bg = _cover(ep.asset(name), BGW, BGH).filter(ImageFilter.GaussianBlur(44))
        bg = Image.blend(bg, Image.new("RGB", (BGW, BGH), (4, 5, 8)), 0.74)
        bg.paste(r, ((BGW - r.width) // 2, (BGH - r.height) // 2))
        im = bg
    elif kind == "plate":
        im = _vignette(_cover(ep.asset(name), BGW, BGH), 0.45)
    else:
        im = _cover(ep.asset(name), BGW, BGH).filter(ImageFilter.GaussianBlur(14))
        im = Image.blend(im, Image.new("RGB", (BGW, BGH), (5, 6, 10)), 0.62)
        im = _vignette(im, 0.5)
    im.save(out)


def _paste_card(canvas, path, box_h, x, y):
    c = Image.open(path).convert("RGBA")
    s = box_h / c.height
    c = c.resize((int(c.width * s), box_h), Image.LANCZOS)
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle([x + 10, y + 14, x + c.width + 14, y + box_h + 16],
                                 fill=(0, 0, 0, 150))
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(16)))
    canvas.alpha_composite(c, (x, y))
    return c.width


def _canon_chip(d, label, x0=0):
    f = bp._F(bp._ARIAL, 19)
    tw = d.textlength(label, font=f)
    x, y = x0 + 54, H - 62
    d.rounded_rectangle([x, y, x + tw + 34, y + 34], radius=6,
                        fill=(10, 12, 18, 225), outline=bp.GOLD, width=1)
    d.text((x + 17, y + 8), label, font=f, fill=bp.GOLD)


def _headline(ov, text, x0=0):
    d = ImageDraw.Draw(ov)
    f = bp._F(bp._COPPER, 52)
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if d.textlength(t, font=f) > CONTENT_W - 140 and cur:
            lines.append(cur); cur = word
        else:
            cur = t
    lines.append(cur)
    sc = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sc)
    top = HEAD_BOTTOM - LINE_H * len(lines) - 60
    for y in range(top, H):
        sd.line([(x0, y), (x0 + CONTENT_W + 60, y)],
                fill=(4, 5, 9, int(190 * min(1.0, (y - top) / 150.0))))
    ov.alpha_composite(sc)
    d = ImageDraw.Draw(ov)
    y = HEAD_BOTTOM - LINE_H * len(lines)
    d.rectangle([x0 + 54, y - 14, x0 + 58, y + LINE_H * len(lines) - 8], fill=bp.GOLD)
    for i, ln in enumerate(lines):
        d.text((x0 + 84, y + LINE_H * i), ln, font=f, fill=(240, 232, 216, 255))


def content_x0(ep):
    """Left edge of the picture column, which depends on which side the rail is on.

    Card geometry was written for a right-hand rail. When the rail moved to the left, cards kept
    being drawn at x=34 and the rail was composited on top of them -- a quarter of the shots showed
    a card with its left half hidden. Anything positioned relative to the picture area must ask.
    """
    return (W - CONTENT_W) if getattr(ep, "rail_side", "right") == "left" else 0


def build_overlay(ep, kind, spec, out, rail_png=None, headline=None, canon=None):
    """Static RGBA overlay: cards + rail + captions. Never drifts -- stable UI, moving art."""
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    x0 = content_x0(ep)
    if kind == "card":
        ch = int(CARD_W * H / W)
        y = CARD_Y if headline else (H - ch) // 2
        _paste_card(ov, ep.asset(spec), ch, x0 + (CONTENT_W - CARD_W) // 2, y)
    elif kind == "cards":
        if headline:
            raise ValueError("a stacked pair leaves no room for the caption; open the segment on a "
                             "plate or a single card instead")
        h = int(PAIR_W * H / W)
        for n, y in zip(spec, (PAIR_Y1, PAIR_Y2)):
            _paste_card(ov, ep.asset(n), h, x0 + (CONTENT_W - PAIR_W) // 2, y)
    if rail_png:
        ov.alpha_composite(Image.open(rail_png).convert("RGBA"))
    if headline:
        _headline(ov, headline, x0)
    if canon:
        _canon_chip(ImageDraw.Draw(ov), canon, x0)
    ov.save(out)


# ----------------------------------------------------------------------------- render
def _drift_vf(idx, frames):
    """Duration-aware drift: a fixed per-frame step hits the zoom ceiling on long shots and the
    picture freezes. Rate is derived from the shot's own length instead."""
    step = 0.055 / max(frames, 1)
    z_in = f"min(1.0+{step:.7f}*on,1.055)"
    z_out = f"max(1.055-{step:.7f}*on,1.0)"
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    n = max(frames, 1)
    pan = [(z_in, cx, cy), (z_out, cx, cy),
           (z_in, f"iw/2-(iw/zoom/2)+(on/{n})*90", cy),
           (z_in, f"iw/2-(iw/zoom/2)-(on/{n})*90", cy),
           (z_out, cx, f"ih/2-(ih/zoom/2)+(on/{n})*70"),
           (z_in, cx, f"ih/2-(ih/zoom/2)-(on/{n})*70")][idx % 6]
    return (f"zoompan=z='{pan[0]}':x='{pan[1]}':y='{pan[2]}':d=1:s={W}x{H}:fps={FPS},"
            f"trim=end_frame={frames}")


def render_visual(bg, ov, frames, idx, out):
    # Fade BEFORE the rail composites, or the always-on rail dips to black at every cut.
    vf = (f"[0:v]{_drift_vf(idx, frames)},fade=t=in:st=0:d=0.12[b];"
          f"[b][1:v]overlay=0:0:format=auto,format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-loop", "1", "-framerate", str(FPS), "-i", bg,
                    "-loop", "1", "-framerate", str(FPS), "-i", ov,
                    "-filter_complex", vf, "-map", "[v]",
                    "-frames:v", str(frames), "-r", str(FPS),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                    "-pix_fmt", "yuv420p", out], check=True, capture_output=True)


def render_visual_from_clip(clip, ov, frames, out, fps=FPS):
    """Animated source. The clip is RETIMED to the shot length (setpts) rather than padded with a
    cloned frame: padding would drop a freeze inside a shot the manifest calls animated."""
    have = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", clip], capture_output=True, text=True).stdout)
    need = frames / fps
    ratio = need / max(have, 0.001)
    vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"setpts={ratio:.6f}*PTS,fps={fps},trim=end_frame={frames},setpts=N/{fps}/TB,"
          f"fade=t=in:st=0:d=0.12[b];"
          f"[b][1:v]overlay=0:0:format=auto,format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip,
                    "-loop", "1", "-framerate", str(fps), "-i", ov,
                    "-filter_complex", vf, "-map", "[v]",
                    "-frames:v", str(frames), "-r", str(fps),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                    "-pix_fmt", "yuv420p", out], check=True, capture_output=True)


def dur_of(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", p], capture_output=True, text=True).stdout)


def srt_time(t):
    return f"{int(t//3600):02d}:{int(t%3600//60):02d}:{t%60:06.3f}".replace(".", ",")


_SELF_MTIME = os.path.getmtime(os.path.abspath(__file__))


def _fresh(p, extra_mtime=0.0):
    """Reuse a clip only if it postdates the engine AND the episode config -- editing either must
    invalidate every clip, or a partial rebuild silently ships mixed output."""
    return (os.path.exists(p) and os.path.getsize(p) > 0
            and os.path.getmtime(p) > max(_SELF_MTIME, extra_mtime))


def main(ep, plan_only=False, cfg_mtime=0.0, animate=None, reveals=None):
    t0 = time.time()
    os.makedirs(ep.work, exist_ok=True)
    script = json.load(open(ep.script))
    segs = script["segments"]
    # Validation lives in hotd.gates and RAISES. render() assumes a preflighted episode; callers
    # that skip gates.preflight() are on their own.

    rails = {}
    if not plan_only:
        for k, st in ep.states.items():
            p = f"{ep.work}/rail_{k}.png"
            bp.render_board(st, p, side=getattr(ep, "rail_side", "right"))
            rails[k] = p
        print(f"rails      : {len(rails)} states", flush=True)

    # narration
    tts_cost = 0.0
    if plan_only:
        for i, s in enumerate(segs):
            p = f"{ep.work}/vo_{i:02d}.mp3"
            s["_dur"] = dur_of(p) if os.path.exists(p) else len(s["narration"].split()) / 162 * 60
    else:
        import explainer_pipeline as epl
        for i, s in enumerate(segs):
            p = f"{ep.work}/vo_{i:02d}.mp3"
            if not (os.path.exists(p) and os.path.getsize(p) > 1000):
                epl.generate_tts(s["narration"], p, voice=ep.voice)
            s["_vo"] = p
            s["_dur"] = dur_of(p)
        chars = sum(len(s["narration"]) for s in segs)
        tts_cost = chars / 1_000_000 * 30.0
        total = sum(s["_dur"] for s in segs) + ep.seg_gap * (len(segs) - 1)
        print(f"narration  : {len(segs)} segments, {chars} chars, {total/60:.2f} min, "
              f"${tts_cost:.2f}", flush=True)

    # visuals
    clips, cuts, srt, t, vi = [], [], [], 0.0, 0
    animated_skipped = []
    n_reveal_used = [0]
    for si, s in enumerate(segs):
        pl = ep.playlists[s["id"]]
        rail = rails.get(ep.seg_state[s["id"]])
        n_total = int(round(s["_dur"] * FPS)) + (int(round(ep.seg_gap * FPS))
                                                if si < len(segs) - 1 else 0)
        # Shot length follows the narration when the episode plans beats: a subject discussed for
        # three seconds gets a three-second shot. An equal split is what put the right face on the
        # wrong sentence, because a 20s segment's 6.5s slices do not line up with who is being named.
        wts = (getattr(ep, "shot_weights", None) or {}).get(s["id"])
        if wts and len(wts) == len(pl) and sum(wts) > 0:
            acc, per = 0.0, []
            for w in wts:
                acc += w
                per.append(int(round(n_total * acc / sum(wts))) - sum(per))
        else:
            per = [n_total // len(pl)] * len(pl)
        per[-1] += n_total - sum(per)
        sents = [x.strip() for x in s["narration"].replace("? ", "?|").replace(". ", ".|")
                 .replace("! ", "!|").split("|") if x.strip()]
        ct = t
        for sent in sents:
            sd = s["_dur"] * len(sent) / max(len(s["narration"]), 1)
            srt.append((ct, ct + sd, sent)); ct += sd
        for k, item in enumerate(pl):
            kind = item[0]
            clip = f"{ep.work}/c_{vi:03d}.mp4"
            src = item[1] if kind in ("plate", "full", "map") else item[-1]
            # decide the source BEFORE the ledger entry, so the ledger records what was used.
            # Diagrams prefer a REVEAL (free, deterministic, and the actual semantic change);
            # plates may use an ambient i2v clip.
            anim = None
            if kind == "full" and reveals:
                anim = (reveals.get("clips", reveals) or {}).get(f"{s['id']}#{k}")
                if anim:
                    n_reveal_used[0] += 1
            if kind == "plate" and animate and item[1] in animate.get("clips", {}):
                from hotd import animate as _an
                cp = animate["clips"][item[1]]
                fits, need, have = _an.usable_for(cp, per[k])
                if fits:
                    anim = cp
                else:
                    animated_skipped.append({"shot": vi, "asset": item[1],
                                             "need_s": need, "clip_s": have})
            cuts.append({"t": round(t, 2), "seg": s["id"], "kind": kind,
                         "asset": item[1] if isinstance(item[1], str) else "+".join(item[1]),
                         "frames": per[k], "animated": bool(anim),
                         "reveal": kind == "full" and bool(anim)})
            if not plan_only and not _fresh(clip, cfg_mtime):
                bgp, ovp = f"{ep.work}/bg_{vi:03d}.png", f"{ep.work}/ov_{vi:03d}.png"
                full_bleed = kind in ("full", "map")
                if kind == "figures":
                    # several people discussed in one breath: choosing one of them would be wrong
                    # about the others, so they share the frame as equal panels
                    from hotd import figure as FIG
                    FIG.build_bg(ep.asset(item[-1]), bgp)
                    FIG.build_overlay_ensemble(ovp, rail, [ep.figures[p] for p in item[1]],
                                               caption=s["caption"] if k == 0 else None,
                                               canon=s["canon"])
                elif kind == "figure":
                    # a supplied character portrait, presented as a framed dossier panel over the
                    # location plate, with the court board on the configured side
                    from hotd import figure as FIG
                    fg = ep.figures[item[1]]
                    FIG.build_bg(ep.asset(item[-1]), bgp)
                    FIG.build_overlay(ovp, rail, fg["portrait"], fg["name"], fg["role"],
                                      fg["status"],
                                      caption=s["caption"] if k == 0 else None,
                                      canon=s["canon"],
                                      shape=fg.get("shape", "tall"),
                                      tone=fg.get("tone", (196, 74, 66)))
                else:
                    build_overlay(ep, kind, item[1], ovp,
                                  rail_png=None if full_bleed else rail,
                                  headline=s["caption"] if k == 0 else None,
                                  canon=None if full_bleed else s["canon"])
                if anim:
                    render_visual_from_clip(anim, ovp, per[k], clip)
                else:
                    if kind not in ("figure", "figures"):
                        build_bg(ep, kind, src, bgp)
                    render_visual(bgp, ovp, per[k], vi, clip)
            clips.append(clip)
            t += per[k] / FPS
            vi += 1
        if not plan_only:
            print(f"  [{time.time()-t0:6.1f}s] {si+1:2d}/{len(segs)} {s['id']:20s} "
                  f"{s['_dur']:5.1f}s -> {len(pl)} visuals", flush=True)

    n_anim = sum(1 for c in cuts if c.get("animated") and not c.get("reveal"))
    report = {"visuals": len(clips), "cuts": cuts, "tts_cost_usd": round(tts_cost, 3),
              "animated_shots": n_anim,
              "reveal_shots": n_reveal_used[0],
              "animated_skipped_too_short": animated_skipped}
    if plan_only:
        json.dump(report, open(f"{ep.out}/plan_report.json", "w"), indent=2)
        print(f"planned    : {len(clips)} visuals, {t/60:.2f} min "
              f"(one every {t/max(len(clips),1):.1f}s)  [no encoding, no spend]")
        return report

    # hard-cut concat (stream copy)
    lst = f"{ep.work}/concat.txt"
    with open(lst, "w") as f:
        for c in clips:
            f.write(f"file '{os.path.abspath(c)}'\n")
    silent = f"{ep.work}/video_silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", silent], check=True)

    # narration track with gaps, then 2-pass loudnorm to -14 LUFS / -1 dBTP
    gap = f"{ep.work}/gap.wav"
    if not os.path.exists(gap):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "anullsrc=r=44100:cl=mono", "-t", str(ep.seg_gap), gap], check=True)
    parts = []
    for i, s in enumerate(segs):
        parts.append(s["_vo"])
        if i < len(segs) - 1:
            parts.append(gap)
    ain = []
    for p in parts:
        ain += ["-i", p]
    fg = "".join(f"[{i}:a]aformat=sample_rates=44100:channel_layouts=mono[a{i}];"
                 for i in range(len(parts)))
    fg += "".join(f"[a{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[out]"
    vo = f"{ep.work}/narration.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + ain +
                   ["-filter_complex", fg, "-map", "[out]", vo], check=True)
    m = subprocess.run(["ffmpeg", "-hide_banner", "-i", vo, "-af",
                        "loudnorm=I=-14:TP=-1:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    j = json.loads(m[m.rfind("{"):m.rfind("}") + 1])
    af = (f"loudnorm=I=-14:TP=-1:measured_I={j['input_i']}:measured_TP={j['input_tp']}"
          f":measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}"
          f":offset={j['target_offset']}:linear=true")
    final = f"{ep.out}/{ep.slug}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", vo,
                    "-af", af, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ac", "2",
                    "-shortest", "-movflags", "+faststart", final], check=True)

    with open(f"{ep.out}/{ep.slug}.srt", "w", encoding="utf8") as f:
        for i, (a, b, txt) in enumerate(srt, 1):
            f.write(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{txt}\n\n")
    report["runtime_s"] = round(dur_of(final), 2)
    json.dump(report, open(f"{ep.out}/build_report.json", "w"), indent=2)

    print(f"\nvideo      : {final}  {report['runtime_s']/60:.2f} min")
    print(f"visuals    : {len(clips)}  (one every {report['runtime_s']/len(clips):.1f}s)")
    if n_reveal_used[0]:
        print(f"reveals    : {n_reveal_used[0]} diagram shot(s) build claim-by-claim (free)")
    if animate:
        print(f"animated   : {n_anim} of {len(clips)} shots"
              + (f"  ({len(animated_skipped)} shot(s) too long for their clip, kept as stills)"
                 if animated_skipped else ""))
    print(f"spend      : ${tts_cost:.2f} (TTS only)")
    print(f"wall clock : {(time.time()-t0)/60:.1f} min")
    return report
