"""QUIZ social-short pipeline — a third format alongside explainer/simulation.

Bolt hosts a rapid "What is it?" quiz: the first clue is frame zero, then three rounds of
[AI-safe visual clue + timer -> answer reveal]. There is no standalone intro, outro, or subscribe card.
  - AI-SAFE items only (silhouettes / clear photos of animals, planets, objects) — NEVER flags, logos,
    signs, or maps, because gpt-image garbles baked-in text/symbols and a wrong clue breaks the quiz.
  - Answers are FACT-CHECKED (a wrong answer destroys trust).
  - SINGLE audio timeline (narration placed at exact beat offsets) so audio locks to the visuals.
  - Tick on each countdown second + a ding on each reveal + a low music bed.
  - Every clue/reveal drifts subtly; cards never freeze for multi-second stretches.

Standalone module; reuses explainer_pipeline for image/TTS gen + the mascot. Best-effort throughout.
"""
import os, re, shutil, subprocess, wave, math, json, base64
from io import BytesIO
import numpy as np
from PIL import Image, ImageDraw, ImageOps
import explainer_pipeline as ep
from bolt_video.formats.quiz import (
    QUIZ_V2,
    clamp_quiz_items,
    clue_zoom,
    final_reveal_narration,
    round_narration,
)
from font_utils import load_font
from music_assets import get_music_path

FF = os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FP = os.environ.get("FFPROBE_BIN") or shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
FONT = os.environ.get("QUIZ_FONT", "/System/Library/Fonts/Supplemental/Arial Bold.ttf")
W, H, FPS = 1080, 1920, 30
# Habitat is the primary format: the silhouette sits where the animal actually lives, and the
# reveal wakes the same frame. QUIZ_HABITAT=0 falls back to the flat-colour format, which is
# kept deliberately as the A/B control rather than deleted.
HABITAT = os.environ.get("QUIZ_HABITAT", "1") == "1"
FAL_OPENER = os.environ.get("QUIZ_FAL_OPENER", "0") == "1"
FAL_OPENER_RATE_SEC = float(os.environ.get("QUIZ_FAL_RATE_SEC", "0.056"))
NAVY=(14,20,40); WHITE=(255,255,255); CYAN=(120,230,255); YEL=(255,210,70); RED=(255,90,80)
_COLORS = {"gold":(245,190,40),"teal":(30,150,150),"lavender":(160,140,210),"coral":(235,120,110),
           "sky":(120,180,230),"mint":(150,210,180),"amber":(240,170,60),"rose":(225,130,160)}

# ── content generation ───────────────────────────────────────────────────────────
_QUIZ_SYSTEM = (
    "You are a YouTube Shorts writer for a fun 'What is it?' guessing quiz hosted by Bolt, a cute robot "
    "teacher. Given a CATEGORY, produce a quiz.\n"
    "VISUAL RULE #1 — AI-SAFE: no text, letters, numbers, logos, FLAGS, MAPS, or road signs in any clue "
    "(an AI image model garbles those and a wrong clue ruins the quiz). Good categories: animals, "
    "planets, fruits/vegetables, everyday objects, musical instruments, sports gear, body parts, dinosaurs.\n"
    "VISUAL RULE #2 — GUESSABLE, NOT TRIVIAL: the clue must be identifiable yet a fun challenge. CHOOSE "
    "THE CLUE STYLE BY CATEGORY: for things with a DISTINCTIVE OUTLINE (animals, instruments, tools) use "
    "a bold black SILHOUETTE. For things distinguished by COLOR / PATTERN / TEXTURE rather than outline "
    "(planets, fruits, materials, textures) use a REAL close-up or partial view showing that "
    "colour/pattern (e.g. a planet's actual banded, colored surface; a fruit's cross-section) — NEVER a "
    "plain silhouette that is just an unguessable circle or blob. Make the TITLE match the clue style you "
    "chose (only say 'shadow'/'silhouette' if you actually used silhouettes).\n"
    "DIFFICULTY LADDER — order items MEDIUM -> HARD -> EXPERT and set each item's \"difficulty\". Item 1 "
    "must create real thought immediately. NEVER choose silhouette clichés such as elephant, giraffe, "
    "kangaroo, rabbit, camel, flamingo, seahorse, butterfly, shark, dolphin, cat, dog, horse, lion, zebra, "
    "or snake. Choose animals a broad audience knows, but whose PARTIAL outline is not instantly obvious. The final "
    "item is EXPERT: genuinely tricky or slightly deceptive. Each spoken line SHORT and punchy.\n"
    "CONSISTENT REVEALS: keep EVERY reveal the SAME isolated style AND the EXACT SAME profile, pose, scale, "
    "and composition as its clue so the black shape can fill with color. Use a clean SOLID colorful studio "
    "background, NO habitat/scene/water. \"reaction\" is a 2-4 word reveal punch flavored by difficulty ('Too easy!' / 'Tricky one!' / "
    "'Almost nobody gets this!').\n"
    "HABITAT: also give each item a \"habitat\" — the real environment that species lives in, written as a "
    "cinematic wide shot with depth and natural light (e.g. 'a misty rainforest clearing at dawn, shafts of "
    "sunlight through the canopy, wet leaves in the foreground'). Describe ONLY the environment: no animal, "
    "no text, no people. It must be somewhere the animal genuinely belongs and must leave an obvious place "
    "for a large animal to sit in the middle distance. Also give \"pose\" — a few words for how the animal "
    "sits in that scene (e.g. 'swimming low through shallow water, seen side-on').\n"
    "Return ONLY JSON: {\"title\":\"clickable title, e.g. 'Can You Name All 3 From the Shadow?'\","
    "\"category\":\"e.g. animals\",\"hook\":\"a maximum five-word cold-open challenge\","
    "\"outro\":\"\",\"items\":[{\"subject\":\"camel\","
    "\"difficulty\":\"medium|hard|expert\",\"clue_visual\":\"a clean bold black silhouette of a camel in "
    "profile\",\"reveal_visual\":\"a cute friendly 3D camel centered on a clean solid background\","
    "\"habitat\":\"a windswept desert dune field at golden hour, long shadows, heat haze on the horizon\","
    "\"pose\":\"standing side-on in the middle distance\","
    "\"answer\":\"CAMEL\",\"reaction\":\"Too easy!\",\"fact\":\"one short fun fact\","
    "\"color\":\"gold|teal|lavender|coral|sky|mint|amber|rose\"}]}."
)


def generate_quiz(category: str, n_items: int = 3, cost_sink: list | None = None, operator_direction: str = "") -> dict:
    """LLM quiz for `category`, hard-filtered to AI-safe items. Best-effort ({} on failure)."""
    try:
        r = ep._claude().messages.create(
            model="claude-opus-4-8", max_tokens=1800, system=_QUIZ_SYSTEM,
            messages=[{"role": "user", "content": f"Category: {category}. Make {n_items} items. Return JSON."
                       + ep._operator_block(operator_direction)}])
        if cost_sink is not None:
            cost_sink.append(ep._msg_cost(r.usage))
        q, _ = ep._parse_script_json(r.content[0].text)
        items = [it for it in (q.get("items") or []) if isinstance(it, dict)
                 and ep._s(it.get("answer")).strip() and ep._s(it.get("clue_visual")).strip()][:n_items]
        if not items:
            return {}
        q["items"] = items
        return q
    except Exception as e:
        print(f"[quiz] generate failed: {e}")
        return {}


def factcheck_quiz(quiz: dict, cost_sink: list | None = None) -> tuple[dict, list]:
    """Verify each answer matches its subject and the fact is true; correct in place. Best-effort."""
    items = quiz.get("items", [])
    try:
        payload = [{"i": i, "subject": it.get("subject"), "answer": it.get("answer"), "fact": it.get("fact")}
                   for i, it in enumerate(items)]
        r = ep._claude().messages.create(
            model="claude-opus-4-8", max_tokens=1200,
            system=("You fact-check a kids' quiz. For each item confirm the ANSWER correctly names the "
                    "SUBJECT and the FACT is TRUE — and verify EVERY NUMBER in the fact (dates, sizes, "
                    "counts, distances, records) is accurate, correcting any that are wrong. Return ONLY JSON {\"fixes\":[{\"i\":int,"
                    "\"answer\":\"corrected answer\",\"fact\":\"corrected true fact\"}]} — include an "
                    "item ONLY if it needs a correction."),
            messages=[{"role": "user", "content": json.dumps(payload)}])
        if cost_sink is not None:
            cost_sink.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text)
        fixes = o.get("fixes", []) if isinstance(o, dict) else []
        for f in fixes:
            i = f.get("i")
            if isinstance(i, int) and 0 <= i < len(items):
                if ep._s(f.get("answer")).strip(): items[i]["answer"] = f["answer"]
                if ep._s(f.get("fact")).strip():   items[i]["fact"] = f["fact"]
        return quiz, fixes
    except Exception as e:
        print(f"[quiz] factcheck skipped: {e}")
        return quiz, []


# ── render helpers ─────────────────────────────────────────────────────────────
def _font(s): return load_font(FONT, s, bold=True)
def _t(d, xy, s, sz, fill, anchor="mm", stroke=10, sc=NAVY):
    d.text(xy, s, font=_font(sz), fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=sc)


def _save_png_atomic(image, path):
    tmp = path + ".tmp.png"
    image.save(tmp, format="PNG")
    os.replace(tmp, path)

_DIFF_COLORS = {"medium": (80, 200, 120), "hard": (245, 180, 60), "expert": (240, 80, 80)}

def _fit_text_size(text, maximum, width, minimum=34):
    size = maximum
    while size > minimum and _font(size).getlength(text) > width:
        size -= 4
    return size


def _paste_bolt_badge(canvas, xy=(70, 1210), size=190):
    """Small reveal-only brand cue; never delays frame-zero gameplay."""
    try:
        mascot = Image.open(ep.MASCOT_REF).convert("RGB")
        w, h = mascot.size
        head = mascot.crop((int(w * .27), int(h * .01), int(w * .73), int(h * .72)))
        head = ImageOps.fit(head, (size, size), method=Image.Resampling.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((4, 4, size - 4, size - 4), fill=255)
        badge = Image.new("RGBA", (size, size), (*NAVY, 255))
        badge.paste(head.convert("RGBA"), (0, 0), mask)
        ImageDraw.Draw(badge).ellipse((3, 3, size - 4, size - 4), outline=(*CYAN, 255), width=8)
        canvas.alpha_composite(badge, xy)
    except Exception:
        pass


def _text_png(path, top=None, answer=None, score=None, difficulty=None, cd_left=None,
              subscribe=False, round_label=None, bolt=False):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    if subscribe:                                          # integrated CTA, not a standalone scene
        # Opens with the question the viewer is already answering in their head, which is what
        # earns the comment; the ask rides along after it. The reason to come back is spoken
        # over this same card, so the two channels complement instead of repeating.
        top = top or "GOT ALL 3? · SUBSCRIBE"
    if top:
        # Trimmed ~20% against the flat-colour layout. On a habitat the banner competes with the
        # thing the viewer is supposed to be searching, so it gives the scene back its top third.
        d.rounded_rectangle([95, 158, W-95, 302], radius=28, fill=(*NAVY, 240))
        title_size = _fit_text_size(top, 58, W - 240)
        _t(d, (W//2, 218), top, title_size, WHITE, stroke=5)
    if round_label:
        dc = _DIFF_COLORS.get(difficulty.lower(), (245, 180, 60)); lbl = difficulty.upper()
        sub = f"{round_label} · {lbl}"
        sub_size = _fit_text_size(sub, 36, W - 300)
        sw = int(_font(sub_size).getlength(sub)) + 60
        d.rounded_rectangle([W//2-sw//2, 258, W//2+sw//2, 326], radius=20, fill=(*dc, 255))
        _t(d, (W//2, 293), sub, sub_size, WHITE, stroke=3)
    elif difficulty:                                       # compatibility for any standalone caller
        dc = _DIFF_COLORS.get(difficulty.lower(), (245, 180, 60)); lbl = difficulty.upper()
        bw = int(_font(48).getlength(lbl)) + 64
        d.rounded_rectangle([W//2-bw//2, 278, W//2+bw//2, 360], radius=22, fill=(*dc, 255))
        _t(d, (W//2, 319), lbl, 48, WHITE, stroke=4)
    if cd_left is not None:                                 # unmistakable single countdown bar + numeral
        x0, x1, y0 = 155, W - 185, H - 610
        d.rounded_rectangle([x0, y0, x1, y0+52], radius=20, fill=(60, 66, 84, 235),
                            outline=(*NAVY, 255), width=4)
        fill_x = x0 + int((x1 - x0) * max(0, min(3, cd_left)) / 3)
        d.rounded_rectangle([x0, y0, fill_x, y0+52], radius=20, fill=(*CYAN, 255))
        d.ellipse([W-160, y0-25, W-65, y0+75], fill=(*NAVY, 255), outline=(*CYAN, 255), width=5)
        _t(d, (W-112, y0+25), str(cd_left), 58, WHITE, stroke=4)
    if answer:
        if bolt:
            _paste_bolt_badge(im)
        x0 = 285 if bolt else 70
        y0, y1 = H-650, H-475
        d.rounded_rectangle([x0, y0, W-70, y1], radius=30, fill=(*NAVY, 248),
                            outline=(*CYAN, 255), width=6)
        answer_size = _fit_text_size(answer, 88, W - x0 - 130)
        _t(d, ((x0 + W - 70)//2, (y0+y1)//2), answer, answer_size, CYAN, stroke=7)
    if score:
        d.rounded_rectangle([W-330, 280, W-40, 400], radius=26, fill=(*RED, 255)); _t(d, (W-185, 340), score, 74, WHITE, stroke=6)
    _save_png_atomic(im, path)

def _fit(src, out, mode="fit", bg=(0, 0, 0)):
    im = Image.open(src).convert("RGB")
    fitted = ImageOps.pad(im, (W, H), color=bg) if mode == "pad" else ImageOps.fit(im, (W, H))
    _save_png_atomic(fitted, out)


def _dim(src, out, brightness, saturation):
    """Scale brightness and saturation. Used to put the habitat to sleep during the guess and
    wake it on the reveal, which is the payoff the flat-colour format has no way to deliver."""
    im = Image.open(src).convert("RGB")
    a = np.asarray(im).astype(np.float32)
    grey = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    a = (grey[..., None] + (a - grey[..., None]) * float(saturation)) * float(brightness)
    _save_png_atomic(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)), out)


def _edge_background(src):
    """Median generated edge color for seamless portrait padding."""
    im = Image.open(src).convert("RGB")
    a = np.asarray(im)
    k = max(4, min(im.size)//80)
    border = np.concatenate([a[:k].reshape(-1, 3), a[-k:].reshape(-1, 3),
                             a[:, :k].reshape(-1, 3), a[:, -k:].reshape(-1, 3)])
    return tuple(int(v) for v in np.median(border, axis=0))


def _progressive_crop(src, out, zoom):
    """Reveal a centered detail first, then widen to the full clue across the three ticks."""
    im = Image.open(src).convert("RGB")
    zoom = max(1.0, float(zoom))
    cw, ch = max(2, int(im.width / zoom)), max(2, int(im.height / zoom))
    left, top = (im.width - cw) // 2, (im.height - ch) // 2
    crop = im.crop((left, top, left + cw, top + ch)).resize((W, H), Image.Resampling.LANCZOS)
    _save_png_atomic(crop, out)


def _vision_image(path):
    im = Image.open(path).convert("RGB")
    im.thumbnail((512, 910), Image.Resampling.LANCZOS)
    buf = BytesIO(); im.save(buf, format="JPEG", quality=82)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                           "data": base64.b64encode(buf.getvalue()).decode()}}


def grade_quiz_visuals(first_crop, full_clue, reveal, answer, difficulty, cost_sink=None):
    """Blind-ish mobile QA for difficulty, fairness, identity, anatomy, and pose continuity."""
    try:
        r = ep._claude().messages.create(
            model="claude-opus-4-8", max_tokens=450,
            system=(
                "You are a ruthless QA grader for a fast mobile animal quiz. You receive: IMAGE 1, the "
                "first partial clue shown for 0.8 seconds; IMAGE 2, the full final silhouette clue; IMAGE 3, "
                "the color answer reveal. The intended answer and difficulty are supplied. Judge at PHONE "
                "SIZE. The first crop should create uncertainty; the full clue must still be fair; the reveal "
                "must unmistakably be the answer with correct anatomy and roughly the same pose/composition. "
                "Return ONLY JSON: {\"first_crop_confidence\":0-100,\"first_guess\":\"...\","
                "\"too_easy\":bool,\"full_clue_fair\":bool,\"reveal_matches_answer\":bool,"
                "\"anatomy_ok\":bool,\"pose_continuity\":bool,\"biggest_fix\":\"...\"}. "
                "For medium, too_easy means confidence above 80; hard above 65; expert above 50."
            ),
            messages=[{"role": "user", "content": [
                _vision_image(first_crop), _vision_image(full_clue), _vision_image(reveal),
                {"type": "text", "text": f'Answer: "{answer}". Intended difficulty: {difficulty}.'},
            ]}],
        )
        if cost_sink is not None:
            cost_sink.append(ep._msg_cost(r.usage))
        result, _ = ep._parse_script_json(r.content[0].text)
        return result if isinstance(result, dict) else None
    except Exception as exc:
        return {"qa_error": f"{type(exc).__name__}: {str(exc)[:120]}"}


def _composite(base, textpng, out):
    composite = Image.alpha_composite(Image.open(base).convert("RGBA"),
                                      Image.open(textpng).convert("RGBA")).convert("RGB")
    _save_png_atomic(composite, out)

def _dur(p):
    return float(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of",
                                 "default=nw=1:nk=1", p], capture_output=True, text=True).stdout.strip() or 0)

def _still(img, out, d, drift=True):
    """Keep cards alive with a duration-aware 5% drift; never hit a zoom cap and freeze early."""
    if drift:
        n = max(2, int(round(d * FPS)))
        step = 0.05 / n
        vf = (f"scale=1300:-1,fps={FPS},"
              f"zoompan=z='min(1.0+{step:.6f}*on,1.05)':x='iw/2-(iw/zoom/2)':"
              f"y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},"
              f"trim=end_frame={n},format=yuv420p")
    else:
        vf = f"fps={FPS},format=yuv420p"
    try:
        os.remove(out)
    except OSError:
        pass
    cmd = [FF, "-y", "-loop", "1", "-i", img, "-t", f"{d}", "-an", "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0 or _dur(out) < max(0.1, d - 0.08):
        # Encoding occasionally left a zero-byte MP4 while the old pipeline continued and produced a
        # deceptively "successful" 1.6-second final. Retry deterministically, then fail hard.
        fallback_vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},format=yuv420p"
        result = subprocess.run([FF, "-y", "-loop", "1", "-i", img, "-t", f"{d}", "-an",
                                 "-vf", fallback_vf, "-c:v", "libx264", "-preset", "veryfast",
                                 "-crf", "20", out], capture_output=True)
    if result.returncode != 0 or _dur(out) < max(0.1, d - 0.08):
        raise RuntimeError(f"quiz clip encode failed: {os.path.basename(out)}")


# Drift is expressed per SECOND, not per card. The old fixed 5%-per-card rule made a 2.4s
# final reveal drift three times slower on screen than a 0.8s countdown card, so the video
# visibly lost energy exactly where the payoff needed it most.
_DRIFT_PER_SEC = 0.0625        # 5% across a 0.8s countdown card
_DRIFT_MAX = 0.11              # keep a long card from cropping its own safe zone
_EASE_SEC = 0.28               # progressive-crop widening eases instead of cutting
# The closing card is the payoff and the longest card in the video, and it read as static:
# a slow push on a mostly-flat reveal barely moves. It gets its own faster rate and a higher
# ceiling. Safe to push harder here than on a clue card because overlays composite *after*
# the zoom, so the answer and CTA never travel toward the frame edge.
_DRIFT_CLOSING_PER_SEC = 0.105
_DRIFT_CLOSING_MAX = 0.24


def _zoom_expr(duration, z_from=None, z_to=None, drift=_DRIFT_PER_SEC, drift_max=None):
    """zoompan `z` that eases z_from -> z_to, then holds, with duration-aware drift on top.

    The widening between countdown stages used to be a hard jump between two pre-cropped
    PNGs — a per-frame delta ~17x the ambient drift, i.e. a visible jolt three times per
    round. Easing it over `_EASE_SEC` keeps the reveal on the same 0.8s beat while removing
    the jolt. The curve is smoothstep (3u^2-2u^3), which starts *and* ends at zero velocity;
    a plain ease-out begins at full speed and still reads as a snap on the first frame.
    No `pow()` needed — smoothstep is only multiplication.
    """
    frames = max(2, int(round(duration * FPS)))
    target = float(z_to if z_to else 1.0)
    if z_from is not None and z_to is not None and abs(float(z_from) - float(z_to)) > 1e-6:
        ease_frames = max(1, int(round(_EASE_SEC * FPS)))
        progress = f"(on/{ease_frames})"
        smoothstep = f"({progress}*{progress}*(3-2*{progress}))"
        eased = (f"({float(z_from):.4f}+({float(z_to) - float(z_from):.4f})*{smoothstep})")
        base = f"if(lt(on,{ease_frames}),{eased},{target:.4f})"
    else:
        base = f"{target:.4f}"
    ceiling = _DRIFT_MAX if drift_max is None else float(drift_max)
    total_drift = min(ceiling, drift * duration) if drift else 0.0
    if total_drift:
        return f"({base})*(1+{total_drift:.6f}*on/{frames})"
    return f"({base})"


def _render_sequence(specs, out, expected_duration):
    """Encode all cards in one FFmpeg process; avoids fragile twelve-MP4 concat intermediates.

    A spec is ``(path, duration, is_video)`` or ``(path, duration, is_video, opts)``. ``opts``
    may carry ``overlay`` — a text PNG composited *after* the zoom, so a widening clue never
    drags the header, timer or answer out of the Shorts safe zone — plus ``z_from``/``z_to``
    for the eased progressive crop.
    """
    inputs = []; filters = []; labels = []; slot = 0
    for i, spec in enumerate(specs):
        path, duration, is_video = spec[0], spec[1], spec[2]
        opts = spec[3] if len(spec) > 3 else {}
        index = slot
        if is_video:
            inputs += ["-i", path]; slot += 1
            filters.append(f"[{index}:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                           f"crop={W}:{H},fps={FPS},trim=duration={duration:.3f},"
                           f"setpts=PTS-STARTPTS[v{i}]")
            labels.append(f"[v{i}]"); continue
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{duration:.3f}", "-i", path]
        slot += 1
        zoom = _zoom_expr(duration, opts.get("z_from"), opts.get("z_to"),
                          opts.get("drift", _DRIFT_PER_SEC), opts.get("drift_max"))
        stage = (f"[{index}:v]scale=1300:-1,zoompan=z='{zoom}':"
                 f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},"
                 f"trim=duration={duration:.3f},setpts=PTS-STARTPTS")
        overlay = opts.get("overlay")
        if overlay:
            over_index = slot
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{duration:.3f}", "-i", overlay]
            slot += 1
            filters.append(stage + f"[bg{i}]")
            filters.append(f"[bg{i}][{over_index}:v]overlay=0:0:format=auto,"
                           f"trim=duration={duration:.3f},setpts=PTS-STARTPTS[v{i}]")
        else:
            filters.append(stage + f"[v{i}]")
        labels.append(f"[v{i}]")
    filters.append("".join(labels) + f"concat=n={len(specs)}:v=1:a=0,format=yuv420p[out]")
    try:
        os.remove(out)
    except OSError:
        pass
    result = subprocess.run(
        [FF, "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[out]",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), out],
        capture_output=True)
    actual = _dur(out)
    if result.returncode != 0 or actual < expected_duration - 0.2:
        err = result.stderr.decode(errors="replace")[-400:] if result.stderr else ""
        raise RuntimeError(f"quiz sequence render failed: expected {expected_duration:.2f}s, "
                           f"got {actual:.2f}s; {err}")

def _fal_countdown_opener(clean_img, overlays, outputs, segment_d, i2v_sink=None):
    """Animate the first clue once with fal, then split it under the changing 3-2-1 overlays.

    This is opt-in because Kling bills a five-second minimum. The visible output uses only the first
    2.4 seconds, and any provider/key failure cleanly returns False for the local drift fallback.
    """
    raw = outputs[0] + ".fal.raw.mp4"
    ok, _, err = ep._animate_one(
        "fal", clean_img,
        "A very slow camera push with subtle depth. Preserve the subject's exact outline, identity, "
        "colors, pose, and composition. No morphing, no new objects, no cuts, no text.",
        raw, W, H, 5,
    )
    used = bool(ok and os.path.exists(raw))
    if i2v_sink is not None:
        i2v_sink.append({"used": used, "error": "" if used else err})
    if not used:
        return False

    for index, (overlay, out) in enumerate(zip(overlays, outputs)):
        start = index * segment_d
        subprocess.run([
            FF, "-y", "-ss", f"{start:.3f}", "-i", raw, "-loop", "1", "-i", overlay,
            "-filter_complex",
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}[v];"
            "[v][1:v]overlay=0:0,format=yuv420p[o]",
            "-map", "[o]", "-an", "-t", f"{segment_d}", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "20", out,
        ], capture_output=True)
        if not os.path.exists(out) or _dur(out) <= 0:
            return False
    return True

def _motion_clip(clean_img, textpng, out, d, motion, i2v_sink=None):
    """LIVELY hook/outro: Kling-animate the game-show Bolt scene, overlay static text. Falls back to a
    slow zoom (Ken Burns) if i2v is unavailable. Returns a SILENT clip of `d`s (audio is the timeline)."""
    raw = out + ".raw.mp4"
    if os.path.exists(raw):
        try: os.remove(raw)
        except OSError: pass
    ok = False
    try:
        ok, _, _ = ep._animate_one("fal", clean_img, motion, raw, W, H, 5)
    except Exception:
        ok = False
    was_i2v = bool(ok) and os.path.exists(raw)
    if i2v_sink is not None:
        i2v_sink.append(was_i2v)
    if not was_i2v:                                          # Ken-Burns fallback keeps it "a video"
        subprocess.run([FF, "-y", "-loop", "1", "-i", clean_img, "-t", f"{d}", "-vf",
            f"scale=1300:-1,zoompan=z='min(zoom+0.0009,1.2)':d={int(d*FPS)}:s={W}x{H},fps={FPS},format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", raw], capture_output=True)
    # The i2v (Kling) raw is ~5s; if the narration slot `d` is longer, freeze the last frame (tpad) to
    # fill the FULL d so the clip length matches the audio-timeline accounting (else audio drifts ahead).
    raw_dur = _dur(raw) or d
    pad = max(0.0, d - raw_dur)
    subprocess.run([FF, "-y", "-i", raw, "-i", textpng, "-filter_complex",
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"tpad=stop_mode=clone:stop_duration={pad:.3f},fps={FPS}[v];"
        "[v][1:v]overlay=0:0,format=yuv420p[o]", "-map", "[o]", "-an", "-t", f"{d}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out], capture_output=True)
    return d


_QUIZ_DESC_HABITAT = (
    "FORMAT — HIDDEN IN HABITAT: each clue is a black silhouette standing in the real environment that "
    "species lives in (rainforest, savanna, creek), dimmed while the timer runs; on the answer the SAME "
    "frame brightens and the animal returns to full colour. The viewer is SEARCHING A SCENE, not reading "
    "an outline on a plain background. Lead on the hiding-in-plain-sight angle and on where each animal "
    "lives — never describe the clues as floating on flat or solid colour.\n"
)

_QUIZ_DESC_SYSTEM = (
    "You are a YouTube Shorts packaging editor. Write the DESCRIPTION for a QUIZ / guessing-game Short "
    "(the first clue appears on frame zero, a rapid timer runs, then the answer is revealed). "
    "Register: vivid, confident, curiosity-driven, direct 2nd-person ('YOU'), specific, ZERO fluff — no "
    "'get ready to test your knowledge' filler. The arc is the escalating CHALLENGE and a dare to the "
    "viewer.\n"
    "DIFFICULTY INTEGRITY: honor the supplied medium/hard/expert labels. Never call a medium round easy or "
    "a warm-up, and never make unsupported percentage/popularity claims.\n"
    "STRUCTURE: (a) 'body' = TWO short punchy paragraphs — para 1 sets the challenge and clearly saves "
    "the HARDEST round for last; para 2 escalates the difficulty ladder "
    "and lands a direct participation dare ('how many did YOU get?') plus a comment prompt. (b) "
    "'hashtags' = 5-6 (WITHOUT the # sign). (c) 'tags' = 15-18 in this ORDER: 5 EXACT-PREMISE (mirror the "
    "title + how people search this quiz), 5 CONSEQUENCE/CONTENT (the challenge, silhouette/clue "
    "guessing, plus the specific ITEM NAMES), 3 SUBJECT-CATEGORY (the real topic + its field), 2-4 FORMAT "
    "(trivia shorts, quiz shorts, guessing game — SHORTS tags, NEVER long-form/documentary tags).\n"
    "SPOILER DISCIPLINE: NEVER reveal in the BODY which clue is which answer, and never map answers to "
    "rounds — that kills the guess. You MAY name the featured items ONCE as a tease, and PUT THE ITEM "
    "NAMES IN THE TAGS for search. Do NOT depict or claim real people/brands. "
    'Return ONLY JSON: {"body":"...","hashtags":[...],"tags":[...]}.'
)


def generate_quiz_description(category, title, items, hook, out_dir, cost_sink=None) -> str:
    """Ready-to-paste YouTube description + 5/5/3/2-4 architecture tags for a quiz Short. Best-effort:
    writes description.txt and returns its path, or '' on any failure (never blocks a render). The app
    persists the returned description_path → {job}.desc exactly like the explainer path."""
    try:
        ordered = "; ".join(
            f"{i+1}. {ep._s(it.get('answer'))} ({ep._s(it.get('difficulty')) or 'harder'})"
            for i, it in enumerate(items))
        habitats = "; ".join(
            f"{ep._s(it.get('answer'))}: {ep._s(it.get('habitat'))}"
            for it in items if ep._s(it.get("habitat")).strip())
        usr = (f'Category: "{category}". Title: "{title}". Hook line: "{ep._s(hook)}".\n'
               f'The {len(items)} answers, in order (put these in the TAGS for search; do NOT map them '
               f'to clues in the body): {ordered}.\n'
               + (f'Each animal is hidden in its own habitat — {habitats}.\n' if habitats else "")
               + 'Write the description now.')
        r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=1600,
                                         system=(_QUIZ_DESC_SYSTEM + _QUIZ_DESC_HABITAT
                                                 if HABITAT else _QUIZ_DESC_SYSTEM),
                                         messages=[{"role": "user", "content": usr}])
        if cost_sink is not None:
            cost_sink.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text)
        if not isinstance(o, dict) or not ep._s(o.get("body")).strip():
            return ""
        body = ep._s(o.get("body")).strip()
        # Models can echo tempting but unsupported challenge clichés despite the system rule. Keep
        # difficulty and popularity claims honest before metadata reaches YouTube.
        body = re.sub(r"\bmedium\s+warm[- ]?up\b", "medium opener", body, flags=re.I)
        body = re.sub(r"\bstumps?\s+almost\s+everyone\b", "is the hardest of the three", body, flags=re.I)
        parts = [body]
        hashtags = [ep._s(h).strip().lstrip("#").strip() for h in (o.get("hashtags") or []) if ep._s(h).strip()]
        if hashtags:
            parts.append(" ".join("#" + h.replace(" ", "") for h in hashtags[:6]))
        tags = [ep._s(t).strip() for t in (o.get("tags") or []) if ep._s(t).strip()]
        if tags:
            parts.append("Tags: " + ", ".join(tags[:18]))
        parts.append(ep._DESC_DISCLOSURE)
        path = os.path.join(out_dir, "description.txt")
        with open(path, "w") as f:
            f.write("\n\n".join(parts) + "\n")
        return path
    except Exception:
        return ""


def _safe_image(prompt, path, size, cost_sink, fallback_label="", **kw):
    """ep.generate_image, but a MODERATION block (or any final image failure) never kills the render:
    retry once with a defused, family-safe prompt, then fall back to a local card (labeled for reveals).
    A quiz image is decorative / an answer visual — one blocked image should degrade, not crash the video
    (OpenAI's output moderation false-positives on some clean animal/creature depictions)."""
    try:
        ep.generate_image(prompt, path, size=size, cost_sink=cost_sink, **kw)
        return
    except ep.ContentBlocked:
        try:
            ep.generate_image("A friendly, wholesome, family-safe, non-violent, clean illustration. " + prompt,
                              path, size=size, cost_sink=cost_sink, **kw)
            return
        except Exception:
            pass
    except Exception:
        pass
    w, h = 1024, 1536
    try:
        w, h = (int(x) for x in str(size).lower().split("x"))
    except Exception:
        pass
    ep.make_fallback_frame(path, fallback_label, w=w, h=h)


def _generate_reveal(answer, clue_visual, clue_path, output_path, size, cost_sink,
                     reference_first=True, strict=False, bg_name=""):
    """Prefer silhouette-guided image edit, but never turn an edit incompatibility into a blank reveal.

    ``bg_name`` pins the flat backdrop to a named colour. The final reveal uses it to land on the
    same field the video opened on, so the instant Shorts loop does not cut across a colour flip.
    """
    pose = _SIL_STRIP.sub("", ep._s(clue_visual)).strip() or ep._s(clue_visual)
    field = f"flat, evenly lit, bright {bg_name}" if bg_name else "flat clean colorful"
    ref_prompt = (
        f"Transform the attached black silhouette into an unmistakable, anatomically correct full-color "
        f"3D {answer}. Keep the exact same outline, profile/pose, scale, position, and framing. Place it "
        f"on a {field} background, completely flat with no gradient. Add detail inside the existing shape "
        "only. No habitat, props, text, or watermark."
    )
    text_prompt = (
        f"An unmistakable, anatomically correct full-color 3D {answer}, {pose}. Match that exact profile, "
        f"pose, scale, and framing on a {field} background. The entire animal must be visible "
        "with correct species-defining anatomy. Premium cohesive 3D cartoon, no habitat, props, text, "
        "letters, or watermark."
    )
    if strict:
        text_prompt += f" It must clearly read as {answer} in one second on a phone."
    if reference_first:
        try:
            ep.generate_image(ref_prompt, output_path, size=size, cost_sink=cost_sink,
                              reference_paths=[clue_path])
            return "reference_edit"
        except Exception:
            pass
    try:
        ep.generate_image(text_prompt, output_path, size=size, cost_sink=cost_sink)
        return "text_fallback" if reference_first else "text_regeneration"
    except Exception:
        w, h = (int(x) for x in str(size).lower().split("x"))
        ep.make_fallback_frame(output_path, answer, w=w, h=h)
        return "local_fallback"


# ── SILHOUETTE ("name it from the shadow") clue rendering ───────────────────────────────────────────
# A silhouette clue must be a TRUE solid-black shape on a bright background so the SHAPE is guessable but
# the answer isn't given away. The default vibrant "polished 3D cartoon" style overrode the word
# "silhouette" and rendered a full-colour animal (elephant bug), which defeated the guess. These helpers
# force a real silhouette via prompt AND guarantee it via a 2-tone post-process. Shared by both the Shorts
# quiz (quiz_pipeline) and the long-form quiz (longform_quiz).
_SIL_BG = [("golden yellow", (247, 191, 42)), ("warm coral", (255, 122, 99)),
           ("bright teal", (34, 199, 190)), ("sky blue", (86, 170, 240)),
           ("fresh lime", (150, 205, 80)), ("soft lavender", (176, 148, 236))]
_SIL_STRIP = re.compile(r"^\s*(an?\s+)?(bold\s+)?(solid\s+)?(clean\s+)?(jet[-\s]?)?(black\s+)?silhouettes?\s+of\s+", re.I)


def is_silhouette_clue(clue_visual, round_type="") -> bool:
    """True if this clue is a guess-from-the-shadow silhouette (round type says so, or the visual asks
    for a silhouette/shadow). Close-up/detail/young rounds are meant to stay full colour → False."""
    t = (ep._s(round_type) + " " + ep._s(clue_visual)).lower()
    return "silhouette" in t or "shadow" in t


def _sil_prompt(clue_visual, color_name):
    """Forceful pure-black-silhouette prompt. Strips any leading 'silhouette of' from the LLM clue (keeps
    the recognisable pose/angle) and does NOT append the vibrant style suffix that caused the leak."""
    subj = _SIL_STRIP.sub("", ep._s(clue_visual)).strip() or ep._s(clue_visual)
    return (
        f"A single, solid, pure-black silhouette of {subj}. Fill the entire shape with flat opaque black "
        "— NO interior detail, NO texture, NO shading, NO eyes or facial features, NO colour inside the "
        "shape — exactly like a clean paper cut-out or a cast shadow. Only the recognisable OUTLINE "
        "matters. Center the shape with generous margin on a completely flat, evenly lit, bright "
        f"{color_name} background. Bold graphic poster style, maximum contrast, crisp clean edges, no "
        "gradient, no ground shadow, no reflection, no text, no letters, no numbers.")


def _silhouette_clean(src, out, bg_rgb, lo=45.0, hi=95.0):
    """Flatten a 'dark subject on flat bright bg' render into a GUARANTEED 2-tone silhouette: subject →
    pure black, background → exact bg_rgb, via a soft alpha ramp that keeps edges smooth. Also forces the
    bg to EXACTLY bg_rgb so the padded sidebars blend seamlessly. Best-effort (caller wraps in try)."""
    im = Image.open(src).convert("RGB")
    a = np.asarray(im).astype(np.float32)
    h, w, _ = a.shape
    k = max(6, min(h, w) // 60)
    border = np.concatenate([a[:k].reshape(-1, 3), a[-k:].reshape(-1, 3),
                             a[:, :k].reshape(-1, 3), a[:, -k:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    dist = np.sqrt(((a - bg) ** 2).sum(axis=2))
    alpha = np.clip((dist - lo) / (hi - lo), 0.0, 1.0)[..., None]      # 1 = subject, 0 = background
    res = (1.0 - alpha) * np.array(bg_rgb, dtype=np.float32)           # subject→black, bg→bg_rgb
    _save_png_atomic(Image.fromarray(res.astype(np.uint8)), out)


def _normalize_silhouette(src, out, bg_rgb, max_fill=.72):
    """Normalize every clue's subject scale so expert/wide animals do not look tiny."""
    im = Image.open(src).convert("RGB")
    a = np.asarray(im)
    bg = np.array(bg_rgb, dtype=np.int32)
    mask = np.sqrt(((a.astype(np.int32) - bg) ** 2).sum(axis=2)) > 45
    ys, xs = np.where(mask)
    if not len(xs):
        return
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    subject = im.crop((x0, y0, x1, y1))
    scale = min(im.width * max_fill / subject.width, im.height * max_fill / subject.height)
    nw, nh = max(2, int(subject.width * scale)), max(2, int(subject.height * scale))
    subject = subject.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", im.size, bg_rgb)
    canvas.paste(subject, ((im.width - nw)//2, (im.height - nh)//2))
    _save_png_atomic(canvas, out)


def _habitat_pair(answer, habitat, pose, clue_dst, reveal_dst, size, cost_sink):
    """Generate an in-habitat clue/reveal pair that share one camera.

    Order matters. The flat-colour format generates the silhouette first and grows a reveal out
    of it, which works because the background is a single colour and trivially reproducible. A
    habitat is not reproducible from a description twice running — two independent generations
    give two different forests, and the reveal stops being a payoff and becomes a scene change.

    So the *reveal* is authored first, and the clue is an edit of those exact pixels with the
    animal blacked out. The scene is then guaranteed identical and the reveal is a true match
    cut: only the animal changes.

    Returns ``(mode, ok)``; ``ok`` is False when the silhouette edit could not be produced, so
    the caller can fall back to the flat-colour format rather than ship an unguessable clue.
    """
    scene = ep._s(habitat).strip() or "its natural habitat, cinematic wide shot, natural light"
    stance = ep._s(pose).strip() or "in the middle distance, seen side-on"
    ep.generate_image(
        f"Cinematic wildlife photograph. A {answer} {stance} in {scene}. The animal is clearly "
        "visible, unobstructed, correct species anatomy, occupying roughly a third of the frame. "
        "Shot on a long lens with natural depth of field, photoreal, rich natural colour, "
        "volumetric light. No text, letters, numbers, watermark, people, or borders.",
        reveal_dst, size=size, cost_sink=cost_sink)
    try:
        ep.generate_image(
            "Keep this photograph EXACTLY as it is — identical camera, framing, composition, "
            "background, lighting direction and every environmental detail. Change ONLY the "
            f"{answer}: fill its silhouette with flat opaque pure black, like a subject in "
            "heavy backlit shadow. No interior detail, no texture, no eye, no rim highlight "
            "inside the shape — only its outline should read. Do not move, resize, add or "
            "remove anything else. No text or watermark.",
            clue_dst, size=size, cost_sink=cost_sink, reference_paths=[reveal_dst])
        return "habitat_pair", True
    except Exception as exc:
        print(f"[quiz] habitat silhouette edit failed: {exc}")
        return "habitat_reveal_only", False


def sil_bg_for(idx=0):
    """The (name, rgb) field colour ``make_silhouette_clue`` will pick for this round index.

    Exposed so the renderer can close the video on the same field it opened on: a Short loops
    instantly, and a full-frame colour flip between the last and first frame reads as a cut.
    """
    return _SIL_BG[idx % len(_SIL_BG)]


def make_silhouette_clue(clue_visual, dst, size, cost_sink, idx=0):
    """Render a TRUE guess-from-the-shadow clue: a pure-black silhouette on a flat bright background
    (bypasses the vibrant style that was giving the answer away). Returns the chosen bg RGB so the caller
    pads the frame with the SAME colour for a seamless panel."""
    name, rgb = _SIL_BG[idx % len(_SIL_BG)]
    _safe_image(_sil_prompt(clue_visual, name), dst, size, cost_sink)   # fallback_label="" → never leak the answer
    try:
        _silhouette_clean(dst, dst, rgb)
        _normalize_silhouette(dst, dst, rgb)
    except Exception:
        pass
    return rgb


def run_quiz_pipeline(category: str, output_dir: str, n_items: int = 3, voice: str = "echo",
                      progress_cb=None, operator_direction: str = "") -> dict:
    """Generate + render a full quiz short. Returns {output_path,title,scene_count,...}."""
    def log(m):
        if progress_cb: progress_cb(m)
    output_dir = os.path.abspath(output_dir)   # absolute so ffmpeg concat lists never double the path
    os.makedirs(output_dir, exist_ok=True)
    A = output_dir; costs = []
    n_items = clamp_quiz_items(n_items)
    log("stage:Writing quiz...")
    quiz = generate_quiz(category, n_items, cost_sink=costs, operator_direction=operator_direction)
    if not quiz or not quiz.get("items"):
        raise RuntimeError("quiz generation failed")
    quiz, fixes = factcheck_quiz(quiz, cost_sink=costs)
    if fixes: log(f"Fact-check corrected {len(fixes)} answer(s)")
    items = quiz["items"]; title = ep._s(quiz.get("title")) or f"Guess the {category}"
    log(f"Quiz: \"{title}\" — {len(items)} items")

    STY = " Polished 3D cartoon, vibrant, high production value, vertical 9:16, no text or letters."
    # The old format bought two extra host images and optional i2v, then spent the first ~4-6 seconds
    # showing a generic stage before the game began. 81% swiped. V2 spends frame zero on the first clue.
    log("stage:Generating images & voiceover...")

    # Narration is deliberately subordinate to the visual game. The timer starts immediately; there is
    # no "Number one. What is it?" pre-roll before each countdown and no reaction sentence after reveal.
    q_texts = {}; r_texts = {}
    for i, it in enumerate(items, 1):
        q_texts[i] = round_narration(category, i, len(items))
        ep.generate_tts(q_texts[i], f"{A}/n_q{i}.mp3", voice=voice)
        r_texts[i] = (final_reveal_narration(ep._s(it.get("answer"))) if i == len(items)
                      else f"{ep._s(it.get('answer'))}!")
        ep.generate_tts(r_texts[i], f"{A}/n_r{i}.mp3", voice=voice)

    CDN = QUIZ_V2.guess_window_sec / 3
    clips = []; render_specs = []; audio = []; caps = []; t = 0.0; fal_opener = []; visual_qa = []
    timing_warnings = []
    # The round badge was hardcoded to "ANIMAL", so a fruits or planets quiz labelled every
    # round ANIMAL 1/3. The category is a free parameter of this pipeline, so the badge has to
    # follow it: last word, singularised, since categories arrive plural ("wild animals").
    _noun = (ep._s(quiz.get("category")) or category or "item").strip().split()[-1].upper()
    round_noun = _noun[:-1] if len(_noun) > 3 and _noun.endswith("S") else _noun
    # "CAN YOU GET 3/3?" states the scoring rules. On a habitat clue the interesting question is
    # not how many you score, it is that something is in the frame you have not found yet.
    clue_banner = "SOMETHING IS HIDING" if HABITAT else f"CAN YOU GET {len(items)}/{len(items)}?"
    # A Short loops instantly, so the last frame sits directly against the first. Round one's
    # field is known up front, and the final reveal is generated and padded to land on it, which
    # turns the loop point from a colour flip into a match cut.
    loop_name, loop_rgb = sil_bg_for(1)

    for i, it in enumerate(items, 1):
        bg = _COLORS.get(ep._s(it.get("color")).strip().lower(), (40, 90, 140))
        clue = f"{A}/clue{i}.png"; rev = f"{A}/rev{i}.png"
        answer = ep._s(it.get("answer"))
        closes_loop = i == len(items)
        in_habitat = False
        if HABITAT:
            reveal_mode, in_habitat = _habitat_pair(
                answer, it.get("habitat"), it.get("pose"), clue, rev, "1024x1536", costs)
        if not in_habitat:
            # Flat-colour control format: silhouette first, reveal grown out of it.
            if is_silhouette_clue(it.get("clue_visual")):
                # "from the shadow" → a TRUE black silhouette; pad with the same bright bg for a seamless panel
                bg = make_silhouette_clue(ep._s(it.get("clue_visual")), clue, "1024x1536", costs, idx=i)
            else:
                _safe_image(ep._s(it.get("clue_visual")) + ", centered with margin, on a flat bright "
                            "background, bold clean shape, no text." + STY, clue, "1024x1536", costs)
            reveal_mode = _generate_reveal(answer, it.get("clue_visual"), clue, rev, "1024x1536", costs,
                                           bg_name=loop_name if closes_loop else "")
        if i == 1:
            loop_rgb = _edge_background(clue) if in_habitat else bg
        # A habitat fills the frame, so it is cropped to portrait rather than padded — a letterbox
        # would announce that the clue and the reveal are the same still.
        _fit(clue, f"{A}/clue{i}_b.png", "fit" if in_habitat else "pad", bg=bg)
        _fit(rev, f"{A}/rev{i}_b.png", "fit" if in_habitat else "pad",
             bg=loop_rgb if closes_loop else _edge_background(rev))
        if in_habitat:
            # The scene sleeps while you guess and wakes on the answer. Dimming the clue also
            # buys the black silhouette the separation it needs to stay readable against a
            # detailed background, which a flat field gave it for free.
            _dim(f"{A}/clue{i}_b.png", f"{A}/clue{i}_b.png", 0.62, 0.72)
            _dim(f"{A}/rev{i}_b.png", f"{A}/rev{i}_b.png", 1.06, 1.10)
        diff = ep._s(it.get("difficulty")).lower() or ("medium" if i == 1 else "expert" if i == len(items) else "hard")
        # Frame zero is already gameplay. Voice and timer run ON TOP of the clue instead of serially,
        # removing ~1.5-2 seconds of setup from every round.
        audio.append((f"{A}/n_q{i}.mp3", t, "narr"))
        caps.append((t, min(QUIZ_V2.guess_window_sec, _dur(f"{A}/n_q{i}.mp3")), q_texts[i]))
        audio.append(("CD", t, "cd"))
        countdown_overlays = []; countdown_outputs = []; countdown_bases = []
        # The ladder drives the eased render; the cropped PNGs still exist because the vision
        # QA pass grades the actual opening crop, and the fal opener needs flat cards.
        # A habitat clue is a scene to search, not a shape to uncrop. The flat-colour ladder
        # opens at 1.85 — on a habitat that throws away the environment the clue depends on and
        # makes frame zero the moment of least information. Habitat gets a shallow pull-back
        # instead: the whole scene reads immediately and each 0.8s stage still lands a beat.
        zoom_ladder = ([1.16, 1.08, 1.0] if in_habitat
                       else [clue_zoom(diff, stage) for stage in range(3)])
        for stage, k in enumerate((3, 2, 1)):
            stage_base = f"{A}/clue{i}_stage{stage}.png"
            _progressive_crop(f"{A}/clue{i}_b.png", stage_base, zoom_ladder[stage])
            countdown_bases.append(stage_base)
            _text_png(f"{A}/cd{i}_{k}_t.png", top=clue_banner,
                      difficulty=diff, round_label=f"{round_noun} {i}/{len(items)}", cd_left=k)
            countdown_overlays.append(f"{A}/cd{i}_{k}_t.png")
            countdown_outputs.append(f"{A}/c{i}1_{k}.mp4")
        grade = grade_quiz_visuals(countdown_bases[0], f"{A}/clue{i}_b.png", f"{A}/rev{i}_b.png",
                                   answer, diff, costs) or {}
        grade["round"] = i; grade["answer"] = answer; grade["difficulty"] = diff
        grade["reveal_generation_mode"] = reveal_mode
        if grade.get("too_easy"):
            zoom_ladder[0] = clue_zoom(diff, 0) * 1.25
            _progressive_crop(f"{A}/clue{i}_b.png", countdown_bases[0], zoom_ladder[0])
            grade["crop_deepened"] = True
            log(f"Round {i} difficulty QA deepened the opening crop")
        if grade.get("reveal_matches_answer") is False or grade.get("anatomy_ok") is False:
            grade["repair_generation_mode"] = _generate_reveal(
                answer, it.get("clue_visual"), clue, rev, "1024x1536", costs,
                reference_first=False, strict=True, bg_name=loop_name if closes_loop else "")
            _fit(rev, f"{A}/rev{i}_b.png", "pad",
                 bg=loop_rgb if closes_loop else _edge_background(rev))
            grade["reveal_regenerated"] = True
            log(f"Round {i} identity QA regenerated the answer reveal")
        visual_qa.append(grade)

        # Progressive crops and generative silhouette motion are deliberately separate experiments:
        # combining them would let Kling morph the clue while the crop changes, making the quiz unfair.
        used_fal = i == 1 and FAL_OPENER and not QUIZ_V2.progressive_clues and _fal_countdown_opener(
            f"{A}/clue{i}_b.png", countdown_overlays, countdown_outputs, CDN, fal_opener)
        if used_fal:
            costs.append(5 * FAL_OPENER_RATE_SEC)
            render_specs.extend((out, CDN, True) for out in countdown_outputs)
            clips.extend(countdown_outputs)
        else:
            # Render from the uncropped clue and let zoompan ease between ladder stops, so the
            # widening is continuous. The timer/header ride on top as a fixed overlay and never
            # inherit the zoom.
            for stage, overlay in enumerate(countdown_overlays):
                render_specs.append((f"{A}/clue{i}_b.png", CDN, False, {
                    "overlay": overlay,
                    "z_from": zoom_ladder[stage - 1] if stage else None,
                    "z_to": zoom_ladder[stage],
                }))
                clips.append(overlay)
        t += CDN * 3
        # One-word reveal, then the next clue. The final reveal carries the comment prompt so the video
        # does not grow a post-game tail that viewers abandon.
        is_final = i == len(items)
        _text_png(f"{A}/r{i}_t.png", top=None, subscribe=False, bolt=True,
                  answer=answer.upper() + "!")
        _composite(f"{A}/rev{i}_b.png", f"{A}/r{i}_t.png", f"{A}/r{i}.png")
        if is_final:
            # The card is sized from the narration and capped, so a line that outruns the cap
            # gets its last words cut off mid-word by the assembly. That used to fail silently;
            # a clipped CTA is a defect worth surfacing rather than shipping.
            narration = _dur(f"{A}/n_r{i}.mp3")
            if narration + 0.12 > QUIZ_V2.final_reveal_max_sec + 1e-6:
                timing_warnings.append(
                    f"final CTA narration is {narration:.2f}s but the closing card caps at "
                    f"{QUIZ_V2.final_reveal_max_sec:.2f}s — the spoken line was cut short")
                log(f"⚠ final CTA narration {narration:.2f}s exceeds the "
                    f"{QUIZ_V2.final_reveal_max_sec:.2f}s closing card")
            dr = min(QUIZ_V2.final_reveal_max_sec,
                     max(QUIZ_V2.final_reveal_min_sec, narration + 0.12))
        else:
            dr = min(QUIZ_V2.reveal_max_sec,
                     max(QUIZ_V2.reveal_min_sec, _dur(f"{A}/n_r{i}.mp3") + 0.1))
        if is_final:
            # The closing card used to be one static hold: no cut for its whole length, on a
            # video that had trained the viewer to expect a beat every 0.8s. Landing the answer
            # first and bringing the CTA in on the next beat keeps the pulse through the payoff.
            # Both halves render from the same reveal with a continuous push-in, so the beat
            # reads as emphasis rather than as a new card.
            _text_png(f"{A}/r{i}_cta_t.png", subscribe=True,
                      bolt=True, answer=answer.upper() + "!")
            answer_beat = CDN
            cta_beat = max(0.3, dr - answer_beat)
            answer_end_zoom = 1.0 + min(_DRIFT_CLOSING_MAX, _DRIFT_CLOSING_PER_SEC * answer_beat)
            render_specs.append((f"{A}/rev{i}_b.png", answer_beat, False,
                                 {"overlay": f"{A}/r{i}_t.png", "z_to": 1.0,
                                  "drift": _DRIFT_CLOSING_PER_SEC,
                                  "drift_max": _DRIFT_CLOSING_MAX}))
            render_specs.append((f"{A}/rev{i}_b.png", cta_beat, False,
                                 {"overlay": f"{A}/r{i}_cta_t.png", "z_to": answer_end_zoom,
                                  "drift": _DRIFT_CLOSING_PER_SEC,
                                  "drift_max": _DRIFT_CLOSING_MAX}))
            clips.append(f"{A}/r{i}.png"); clips.append(f"{A}/r{i}_cta_t.png")
            dr = answer_beat + cta_beat
        else:
            render_specs.append((f"{A}/rev{i}_b.png", dr, False,
                                 {"overlay": f"{A}/r{i}_t.png", "z_to": 1.0}))
            clips.append(f"{A}/r{i}.png")
        audio.append((f"{A}/n_r{i}.mp3", t, "narr")); audio.append(("DING", t, "ding")); caps.append((t, _dur(f"{A}/n_r{i}.mp3"), r_texts[i])); t += dr
    TOTAL = t

    # captions (.srt) + transcript — built DETERMINISTICALLY from the narration timeline (exact text +
    # real offsets), so they're perfectly accurate (no transcription, no dropped words).
    def _srt_ts(s):
        s = max(0.0, s); h = int(s // 3600); m = int((s % 3600) // 60); sec = int(s % 60)
        ms = int(round((s - int(s)) * 1000))
        if ms == 1000: sec += 1; ms = 0
        return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
    srt_path = f"{A}/captions.srt"; transcript_path = f"{A}/transcript.txt"
    try:
        cs = sorted(caps, key=lambda c: c[0])
        with open(srt_path, "w") as fsrt:
            for n, (st, du, txt) in enumerate(cs, 1):
                fsrt.write(f"{n}\n{_srt_ts(st)} --> {_srt_ts(st + max(0.7, du))}\n{txt.strip()}\n\n")
        with open(transcript_path, "w") as ftx:
            ftx.write(" ".join(c[2].strip() for c in cs) + "\n")
    except Exception as e:
        log(f"caption write skipped: {e}"); srt_path = transcript_path = None

    log("stage:Assembling final video...")
    # Overlays are separate inputs now, so a missing text PNG has to fail here too rather than
    # surfacing as an opaque filter-graph error after the cards have already been paid for.
    _required = [spec[0] for spec in render_specs]
    _required += [spec[3]["overlay"] for spec in render_specs
                  if len(spec) > 3 and spec[3].get("overlay")]
    missing_cards = [os.path.basename(path) for path in _required if not os.path.exists(path)]
    if missing_cards:
        raise RuntimeError("quiz assembly blocked by missing cards: " + ", ".join(missing_cards))
    vsil = f"{A}/video_silent.mp4"
    _render_sequence(render_specs, vsil, TOTAL)
    # sfx
    cdsfx = f"{A}/cdsfx.wav"      # 3 ticks matching the 2.4s countdown (0/0.8/1.6s), rising pitch, NO ding
    subprocess.run([FF, "-y", "-filter_complex",
        "sine=1000:d=0.06,adelay=0|0[a];sine=1000:d=0.06,adelay=800|800[b];sine=1300:d=0.09,adelay=1600|1600[c];"
        "[a][b][c]amix=inputs=3:normalize=0,volume=2,atrim=0:2.4[o]",
        "-map", "[o]", cdsfx], capture_output=True)
    ding = f"{A}/ding.wav"
    subprocess.run([FF, "-y", "-filter_complex", "sine=1600:d=0.25,volume=1.5[o]", "-map", "[o]", ding], capture_output=True)
    # single audio timeline
    ins = []; parts = []; idx = 0
    for f, off, kind in audio:
        src = cdsfx if kind == "cd" else (ding if kind == "ding" else f)
        ins += ["-i", src]; ms = int(off * 1000); vol = 1.0 if kind == "narr" else 0.7
        parts.append(f"[{idx}:a]adelay={ms}|{ms},volume={vol}[s{idx}]"); idx += 1
    music_path = get_music_path("upbeat", progress_cb=log)
    mus = idx; music_ok = bool(music_path)
    if music_ok:
        ins += ["-stream_loop", "-1", "-i", music_path]
        parts.append(f"[{mus}:a]atrim=0:{TOTAL},volume=0.11,afade=t=out:st={max(0,TOTAL-1.3):.2f}:d=1.3[mus]")
    mix = "".join(f"[s{i}]" for i in range(idx)) + ("[mus]" if music_ok else "")
    parts.append(f"{mix}amix=inputs={idx + (1 if music_ok else 0)}:normalize=0,alimiter=limit=0.95,loudnorm=I=-12:TP=-1.5,aresample=48000[aout]")   # target -12: single-pass undershoots ~2 LU -> lands ~-14
    faud = f"{A}/full_audio.m4a"
    audio_result = subprocess.run(
        [FF, "-y", *ins, "-filter_complex", ";".join(parts), "-map", "[aout]", "-t", f"{TOTAL}",
         "-c:a", "aac", "-b:a", "192k", faud], capture_output=True)
    if audio_result.returncode != 0 or _dur(faud) < TOTAL - 0.2:
        raise RuntimeError(f"quiz audio assembly failed: expected {TOTAL:.2f}s, got {_dur(faud):.2f}s")

    out_mp4 = os.path.join(output_dir, "quiz.mp4")
    mux_result = subprocess.run(
        [FF, "-y", "-i", vsil, "-i", faud, "-c:v", "copy", "-c:a", "aac", "-shortest",
         "-movflags", "+faststart", out_mp4], capture_output=True)
    actual_duration = _dur(out_mp4)
    if mux_result.returncode != 0 or actual_duration < TOTAL - 0.2:
        raise RuntimeError(f"quiz final mux failed: expected {TOTAL:.2f}s, got {actual_duration:.2f}s")

    # Ready-to-paste YouTube description + tags (best-effort). Runs BEFORE the cost sum so its cost is
    # counted; the app persists description_path → {job}.desc exactly like the explainer path.
    log("stage:Writing description...")
    description_path = generate_quiz_description(category, title, items, q_texts.get(1), A, cost_sink=costs)
    if description_path:
        log("YouTube description written")
    cost = round(sum(costs), 3)
    _deg = list(timing_warnings)
    if not os.path.exists(out_mp4):
        _deg = ["final video file was not produced — assembly failed"] + _deg
    fal_used = any(event.get("used") for event in fal_opener)
    log(f"Complete — rapid quiz assembled · ${cost} · first clue at 0.0s · {TOTAL:.1f}s planned"
        + (" · fal opener" if fal_used else ""))
    # Shape matches run_explainer_pipeline so the app's save/index path consumes it unchanged.
    return {"output_path": out_mp4, "title": title, "category": quiz.get("category", category),
            "scene_count": len(clips), "duration_sec": round(_dur(out_mp4), 1),
            "items": [{"answer": it.get("answer"), "fact": it.get("fact")} for it in items],
            "script": quiz, "hook": q_texts.get(1, ""), "video_format": "social",
            "quiz_creative": QUIZ_V2.version, "first_clue_at_sec": QUIZ_V2.first_clue_at_sec,
            "fal_opener_requested": FAL_OPENER, "fal_opener_used": fal_used,
            "progressive_clues": QUIZ_V2.progressive_clues,
            "subscribe_cta": "integrated_final_reveal", "visual_qa": visual_qa,
            "planned_duration_sec": round(TOTAL, 2),
            "srt_path": srt_path, "transcript_path": transcript_path,   # app copies these → {job}.srt/.txt
            "description_path": description_path,                        # app copies → {job}.desc
            "status": ("degraded" if _deg else "ok"), "degraded_reasons": _deg,
            "actual_cost": cost, "est_cost": cost}
