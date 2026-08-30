"""QUIZ social-short pipeline — a third format alongside explainer/simulation.

Bolt hosts a rapid "What is it?" quiz: the first clue is frame zero, then three rounds of
[AI-safe visual clue + timer -> answer reveal]. There is no standalone intro, outro, or subscribe card.
  - AI-SAFE items only (silhouettes / clear photos of animals, planets, objects) — NEVER flags, logos,
    signs, or maps, because gpt-image garbles baked-in text/symbols and a wrong clue breaks the quiz.
  - Answers are FACT-CHECKED (a wrong answer destroys trust).
  - SINGLE audio timeline (narration placed at exact beat offsets) so audio locks to the visuals.
  - Tick on each countdown second + a ding on each reveal + a low music bed.
  - Every clue/reveal drifts subtly; cards never freeze for multi-second stretches.

Standalone module; reuses explainer_pipeline for image/TTS generation. The shipping quiz has no mascot layer.
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
    tier_label,
)
from font_utils import load_font
from music_assets import get_music_path

FF = os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FP = os.environ.get("FFPROBE_BIN") or shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
FONT = os.environ.get("QUIZ_FONT", "/System/Library/Fonts/Supplemental/Arial Bold.ttf")
# A game show, not a dashboard. Arial Bold reads as software chrome, and every card in this format
# is three short shouted words — exactly what a display face is for. Bundled under assets/fonts so
# the cards keep their shape on any checkout; see the NOTICE there for the licence.
_BUNDLED_DISPLAY = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "assets", "fonts", "LuckiestGuy-Regular.ttf")
DISPLAY_FONT = os.environ.get("QUIZ_DISPLAY_FONT", "").strip() or (
    _BUNDLED_DISPLAY if os.path.exists(_BUNDLED_DISPLAY) else FONT)
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
    "You are a YouTube Shorts writer for a fast visual 'What is it?' guessing quiz. Given a "
    "CATEGORY, produce a quiz.\n"
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
    "DIFFICULTY IS CONFUSABILITY, NOT OBSCURITY. This is the single most important rule. Difficulty is "
    "how many OTHER species the silhouette could plausibly belong to — never how rare or unfamiliar the "
    "animal is. An obscure animal nobody can name is a BAD item: the viewer cannot play, they can only "
    "lose. A familiar animal whose outline could equally be three other things is an EXCELLENT item: the "
    "viewer thinks they have it, then doubts themselves. Aim for doubt, not ignorance.\n"
    "Give every item \"confusables\": 2-4 REAL species a viewer could genuinely mistake this silhouette "
    "for. If you cannot name three plausible confusables for a hard or expert item, the animal is wrong — "
    "choose a different one. Order items MEDIUM -> HARD -> EXPERT and set each item's \"difficulty\":\n"
    "  MEDIUM: one or two confusables; the full silhouette resolves it. Item 1 must still create thought.\n"
    "  HARD: at least three confusables that stay plausible even once the WHOLE silhouette is visible.\n"
    "  EXPERT: at least three confusables AND the true answer must NOT be the most obvious first guess — "
    "a viewer's instinctive answer should be one of the confusables, not the real one.\n"
    "REJECT ANY ANIMAL WITH A SELF-IDENTIFYING OUTLINE, whatever difficulty you were going to label it. "
    "If one glance at the black shape settles it, it is an easy item wearing a hard label. Banned outright, "
    "in addition to the obvious clichés (elephant, giraffe, kangaroo, rabbit, camel, flamingo, seahorse, "
    "butterfly, shark, dolphin, cat, dog, horse, lion, zebra, snake): CROCODILE, ALLIGATOR, HIPPOPOTAMUS, "
    "RHINOCEROS, BUFFALO, BISON, WALRUS, MOOSE, PENGUIN, OSTRICH, GORILLA, and any big cat in side profile. "
    "Every one of these has been used and was identified instantly.\n"
    "POSE CARRIES DIFFICULTY TOO. A side-on profile is the most identifying view there is, so spend it on "
    "the MEDIUM item only. For HARD and EXPERT, choose a pose that withholds the diagnostic feature: "
    "angled towards or away from the camera, head lowered or turned, body foreshortened, or partly behind "
    "terrain — while keeping the animal wholly visible and its outline clean. Each spoken line SHORT and "
    "punchy.\n"
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
    "HABITAT LOOP — the FINAL item must live in the SAME habitat as item 1, and you must give the two of "
    "them the IDENTICAL \"habitat\" text, word for word. A Short loops instantly, so the video closes on "
    "the place it opened and the join reads as the game resetting rather than as a cut to somewhere else. "
    "Choose the final animal to genuinely live there: pick the shared environment FIRST, then the hardest "
    "animal that truly belongs in it. Never relocate a species to make the loop work. Item 2 is free to "
    "use a different habitat, and its contrast is what makes the return to the opening scene land.\n"
    "The title must either OMIT a numeric item count or match the exact requested item count; never "
    "promise a count that differs from the rendered rounds. Return ONLY JSON: {\"title\":\"clickable title, "
    "e.g. 'Can You Name Them From the Shadow?'\","
    "\"category\":\"e.g. animals\",\"hook\":\"a maximum five-word cold-open challenge\","
    "\"outro\":\"\",\"items\":[{\"subject\":\"camel\","
    "\"difficulty\":\"medium|hard|expert\",\"clue_visual\":\"a clean bold black silhouette of a camel in "
    "profile\",\"reveal_visual\":\"a cute friendly 3D camel centered on a clean solid background\","
    "\"habitat\":\"a windswept desert dune field at golden hour, long shadows, heat haze on the horizon\","
    "\"confusables\":[\"llama\",\"alpaca\",\"guanaco\"],"
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


_TITLE_COUNT_WORDS = {2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six"}


def normalize_quiz_title(title: str, item_count: int, category: str = "items") -> str:
    """Keep generated packaging truthful when the format's round count changes."""
    count = clamp_quiz_items(item_count)
    title = ep._s(title).strip() or f"Can You Name These {category.title()} From the Shadow?"
    title = re.sub(r"\b[2-6]/[2-6]\b", f"{count}/{count}", title)
    for number, word in _TITLE_COUNT_WORDS.items():
        if number != count:
            title = re.sub(rf"\b{number}\b", str(count), title)
            title = re.sub(rf"(?i)\b{word}\b", _TITLE_COUNT_WORDS[count], title)
    return title


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
def _font(s): return load_font(DISPLAY_FONT, s, bold=True)


def _t_two(d, xy, left, right, size, fill_left, fill_right, stroke=8, sc=NAVY):
    """One headline, two colours, still centred as a whole.

    The second half carries the verb the viewer is meant to act on, so it gets the accent colour;
    a single-colour banner gives every word the same weight and reads as a label rather than an
    instruction. Both halves are measured before drawing so the pair centres on ``xy`` — drawing
    them independently would centre each one and split the line apart.
    """
    font = _font(size)
    wl, wr = font.getlength(left), font.getlength(right)
    x0 = xy[0] - (wl + wr) / 2
    d.text((x0, xy[1]), left, font=font, fill=fill_left, anchor="lm",
           stroke_width=stroke, stroke_fill=sc)
    d.text((x0 + wl, xy[1]), right, font=font, fill=fill_right, anchor="lm",
           stroke_width=stroke, stroke_fill=sc)
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


# Measured off the badge crop, as fractions of its size, so they hold at any badge dimension.
_EYE_L, _EYE_R, _EYE_Y = 0.375, 0.575, 0.479
_VISOR_RGB = (13, 25, 24)


def _draw_bolt_eyes(badge, size, mood):
    """Repaint Bolt's eyes to react to the round.

    The badge crops to head and shoulders — his arms are outside it — so a pose cannot read here
    at all: a wave would be cropped away entirely. The visor is the only expressive surface the
    viewer actually sees, which makes eyes the whole vocabulary rather than a substitute for one.

    Drawn rather than generated, so a mood costs nothing, stays exactly on-model, and renders
    identically every run. The vision QA pass grades a rendered frame, so art that varied per run
    would make that grade unreproducible.
    """
    if mood == "idle":
        return
    d = ImageDraw.Draw(badge)
    r = size * 0.031
    for cx in (_EYE_L, _EYE_R):
        x, y = cx * size, _EYE_Y * size
        # Clear the original dot to the visor's own colour before drawing over it.
        d.ellipse([x - r * 2.2, y - r * 2.4, x + r * 2.2, y + r * 2.4], fill=(*_VISOR_RGB, 255))
        if mood == "focus":            # narrowed: the clue is getting harder
            d.rounded_rectangle([x - r * 1.25, y - r * 0.42, x + r * 1.25, y + r * 0.42],
                                radius=int(r * 0.42), fill=(*CYAN, 255))
        elif mood == "alert":          # wide: the expert round
            d.ellipse([x - r * 1.5, y - r * 1.5, x + r * 1.5, y + r * 1.5], fill=(*CYAN, 255))
        elif mood == "happy":          # upward arc: the answer landed
            d.arc([x - r * 1.6, y - r * 0.4, x + r * 1.6, y + r * 2.4], 200, 340,
                  fill=(*CYAN, 255), width=max(2, int(r * 0.8)))
        else:
            d.ellipse([x - r, y - r, x + r, y + r], fill=(*CYAN, 255))


def _paste_bolt_badge(canvas, xy=(70, 1210), size=190, mood="idle"):
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
        _draw_bolt_eyes(badge, size, mood)
        ImageDraw.Draw(badge).ellipse((3, 3, size - 4, size - 4), outline=(*CYAN, 255), width=8)
        canvas.alpha_composite(badge, xy)
    except Exception:
        pass


# Bolt reacts to the round he is announcing rather than wearing one face all video. Keyed off the
# difficulty ladder so the escalation the badge already prints is also something he does.
_BOLT_MOODS = {"medium": "happy", "hard": "focus", "expert": "alert"}


def _text_png(path, top=None, answer=None, score=None, difficulty=None, cd_left=None,
              subscribe=False, round_label=None, bolt=False, answer_size=None,
              bolt_mood="idle", top_accent="", difficulty_label=""):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    if subscribe:                                          # integrated CTA, not a standalone scene
        # Opens with the question the viewer is already answering in their head, which is what
        # earns the comment; the ask rides along after it. The reason to come back is spoken
        # over this same card, so the two channels complement instead of repeating.
        # The count is the caller's: this said "GOT ALL 3?" whatever the round count actually was,
        # which was invisible while the format was capped at three and wrong the moment it wasn't.
        top = top or "GOT THEM ALL? · SUBSCRIBE"
    if top:
        # Trimmed ~20% against the flat-colour layout. On a habitat the banner competes with the
        # thing the viewer is supposed to be searching, so it gives the scene back its top third.
        d.rounded_rectangle([95, 158, W-95, 302], radius=28, fill=(*NAVY, 240))
        # The display face is narrower than the old Arial Bold, so the same words fit at a larger
        # size: the headline can be shouted rather than merely legible.
        title_size = _fit_text_size(top + top_accent, 76, W - 240)
        if top_accent:
            _t_two(d, (W//2, 222), top, top_accent, title_size, WHITE, YEL, stroke=7)
        else:
            _t(d, (W//2, 222), top, title_size, WHITE, stroke=7)
    if round_label:
        # Colour still climbs with the real difficulty; only the word the viewer reads changes.
        dc = _DIFF_COLORS.get(difficulty.lower(), (245, 180, 60))
        lbl = (difficulty_label or difficulty).upper()
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
            _paste_bolt_badge(im, mood=bolt_mood)
        x0 = 285 if bolt else 70
        y0, y1 = H-650, H-475
        d.rounded_rectangle([x0, y0, W-70, y1], radius=30, fill=(*NAVY, 248),
                            outline=(*CYAN, 255), width=6)
        # Callers typing the answer in one character at a time must pin this to the size of the
        # COMPLETE word. Recomputing per frame fits each partial string on its own and the text
        # shrinks as it grows, which reads as a glitch rather than as typing.
        answer_size = answer_size or _fit_text_size(answer, 88, W - x0 - 130)
        _t(d, ((x0 + W - 70)//2, (y0+y1)//2), answer, answer_size, CYAN, stroke=7)
    if score:
        d.rounded_rectangle([W-330, 280, W-40, 400], radius=26, fill=(*RED, 255)); _t(d, (W-185, 340), score, 74, WHITE, stroke=6)
    _save_png_atomic(im, path)

def _smoothstep(p):
    p = max(0.0, min(1.0, float(p)))
    return p * p * (3 - 2 * p)


def _reveal_tint(img):
    """A burst colour taken from the scene it bursts out of.

    Sampling the reveal beats naming a colour per habitat: embers on a savanna, cold white on a
    snowfield and pale spray on a riverbank fall out of the image itself, so a habitat nobody
    anticipated still gets particles that belong in it.
    """
    a = np.asarray(Image.open(img).convert("RGB").resize((64, 64))).reshape(-1, 3).mean(axis=0)
    lifted = np.clip(a * 0.45 + 255 * 0.55, 0, 255)
    return tuple(int(v) for v in lifted)


def _draw_burst(canvas, progress, tint, count=26):
    """One frame of an expanding particle ring, composited onto the reveal.

    Deterministic by construction: angle and radius come from the particle index, never from a
    random source. The vision QA pass grades a rendered frame, so a burst that differed run to
    run would make that grade unreproducible.
    """
    if progress <= 0 or progress >= 1:
        return
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy = W // 2, int(H * 0.46)
    eased = _smoothstep(progress)
    alpha = int(235 * (1.0 - progress) ** 1.4)
    for n in range(count):
        angle = (2 * math.pi * n) / count + (n % 3) * 0.21
        reach = (0.30 + 0.055 * (n % 5)) * min(W, H)
        r = (0.18 + 0.82 * eased) * reach
        size = max(3, int((1.0 - progress) * (13 + 5 * (n % 4))))
        x, y = cx + math.cos(angle) * r, cy + math.sin(angle) * r * 1.15
        draw.ellipse([x - size, y - size, x + size, y + size], fill=(*tint, alpha))
    canvas.alpha_composite(layer)


_MASCOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "mascot", "quiz")
_MASCOT_CACHE = {}
# Bolt is a guest on the reveal, not a tenant of the frame. The critique that prompted this asked
# for <=20% of frame and for the big motion to land on the answer rather than run under the guess.
_MASCOT_FRAME_FRACTION = 0.22
_MASCOT_ENTER_SEC = 0.22


def _mascot_pose(name):
    """Load a committed RGBA cutout, or None when the library has not been generated."""
    if name not in _MASCOT_CACHE:
        path = os.path.join(_MASCOT_DIR, f"{name}.png")
        try:
            art = Image.open(path).convert("RGBA") if os.path.exists(path) else None
            if art is not None:
                # The cutout keeps the generator's 1024x1536 canvas, of which the robot is barely a
                # quarter. Sizing that whole canvas to a fraction of the frame makes the character
                # a third of the size asked for and leaves him floating off the bottom edge.
                box = art.getbbox()
                if box:
                    art = art.crop(box)
            _MASCOT_CACHE[name] = art
        except Exception:
            _MASCOT_CACHE[name] = None
    return _MASCOT_CACHE[name]


def _draw_mascot(canvas, pose, elapsed, duration, side="right"):
    """Slide Bolt in from the frame edge and let him settle with a small bob.

    Procedural rather than an animated clip: it costs nothing per video, renders identically every
    run, and needs no alpha-video path. The entrance is the point — a character arriving is motion
    where this format previously had a static frame, which is the measured gap against the
    reference (mean frame delta 3.30 against its 6.08).
    """
    if pose is None:
        return
    height = int(H * _MASCOT_FRAME_FRACTION)
    width = max(1, int(pose.width * height / pose.height))
    art = pose.resize((width, height), Image.Resampling.LANCZOS)
    rest_x = W - width - 40 if side == "right" else 40
    off_x = W + 20 if side == "right" else -width - 20
    enter = _smoothstep(min(1.0, elapsed / max(0.01, _MASCOT_ENTER_SEC)))
    # Overshoot slightly past the resting point and settle back, so the arrival has weight instead
    # of sliding to a stop.
    settle = math.sin(max(0.0, elapsed - _MASCOT_ENTER_SEC) * 11.0) * width * 0.03 * enter
    overshoot = -settle if side == "right" else settle
    x = int(off_x + (rest_x - off_x) * enter + overshoot)
    # He hovers, so he never fully stops. The first version bobbed by 1.8% of his height — under a
    # pixel once the frame is analysed, and invisible on a phone. This is the ambient motion the
    # whole variant exists to add, so it has to be big enough to see.
    hover = math.sin(elapsed * 6.2) * (height * 0.055) * enter
    # Stands ON the answer card, not on the frame edge. Anchoring to the bottom put him in the
    # lowest quarter, which is where the Shorts player draws its own title and handle — the same
    # reason the answer card itself stops at H-475 rather than running to the bottom.
    y = int((H - 650) - height - 20 + hover)
    canvas.alpha_composite(art, (x, y))


def _reveal_clip(clue_png, reveal_png, answer, out, duration, dissolve=None, bolt=True,
                 mood="idle", pose_name="", side="right"):
    """Wake the scene into its answer instead of cutting to it.

    The clue is the same photograph as the reveal with the animal blacked out and the whole frame
    dimmed to 0.62; the reveal is that frame at 1.06. Cutting between them throws away the one
    thing the habitat format has that the flat-colour one never did — the silhouette visibly
    BECOMING the animal. Crossfading them instead makes the payoff a transformation, and the
    answer types in across the same beat so the reward unfolds rather than landing whole.

    Built frame by frame in PIL rather than as a filtergraph. The alternative needs one overlay
    input per typing step plus enable windows, and ``_render_sequence`` ignores overlays on video
    specs anyway, so the text has to be burned in regardless.

    Returns True when the clip exists; callers fall back to a plain cut, which is the current
    behaviour and always correct.
    """
    frames = max(2, int(round(duration * FPS)))
    dissolve = float(dissolve or duration)
    pose = _mascot_pose(pose_name) if pose_name else None
    try:
        clue = Image.open(clue_png).convert("RGB")
        reveal = Image.open(reveal_png).convert("RGB")
        if clue.size != reveal.size:
            clue = clue.resize(reveal.size)
        tint = _reveal_tint(reveal_png)
        label = (answer or "").upper() + "!"
        # Pinned to the full word so the type-on does not resize itself mid-word.
        full_size = _fit_text_size(label, 88, W - (285 if bolt else 70) - 130)
        seq = out + ".frames"
        shutil.rmtree(seq, ignore_errors=True)
        os.makedirs(seq, exist_ok=True)
        cards = {}
        for n in range(frames):
            # Absolute seconds, not a fraction of the clip: the dissolve, burst and type-on are
            # fixed-length events, so a longer clip must extend the HOLD after them rather than
            # slowing all three down.
            elapsed = n / FPS
            base = Image.blend(
                clue, reveal, _smoothstep(min(1.0, elapsed / (dissolve * 0.72)))).convert("RGBA")
            # _render_sequence applies zoompan to STILLS only — an is_video spec is scaled,
            # cropped and passed through untouched. The still hold this clip replaces was drifting
            # at _DRIFT_PER_SEC, so without baking an equivalent push-in the "livelier" variant
            # measures flatter than the control it was meant to beat. It did, first time out:
            # 5.68 mean frame delta against the control's 6.83.
            zoom = 1.0 + min(_DRIFT_MAX, _DRIFT_PER_SEC * duration) * (elapsed / max(duration, 1e-6))
            if zoom > 1.0005:
                cw, ch = int(base.width / zoom), int(base.height / zoom)
                left, top = (base.width - cw) // 2, (base.height - ch) // 2
                base = base.crop((left, top, left + cw, top + ch)).resize(
                    (base.width, base.height), Image.Resampling.LANCZOS)
            _draw_burst(base, min(1.0, elapsed / (dissolve * 0.85)), tint)
            shown = max(1, int(round(len(label) * min(1.0, elapsed / (dissolve * 0.62)))))
            if shown not in cards:
                card = f"{seq}/card{shown:03d}.png"
                _text_png(card, answer=label[:shown], bolt=bolt, answer_size=full_size,
                          bolt_mood=mood)
                cards[shown] = card
            base.alpha_composite(Image.open(cards[shown]).convert("RGBA"))
            _draw_mascot(base, pose, elapsed, duration, side)
            base.convert("RGB").save(f"{seq}/f{n:04d}.png")
        result = subprocess.run(
            [FF, "-y", "-v", "error", "-framerate", str(FPS), "-i", f"{seq}/f%04d.png",
             "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", out], capture_output=True)
        shutil.rmtree(seq, ignore_errors=True)
        return result.returncode == 0 and os.path.exists(out) and _dur(out) > 0
    except Exception as exc:
        print(f"[quiz] reveal clip skipped: {exc}")
        return False


# Which pose greets which reveal. The ladder already escalates on screen; the mascot escalates
# with it, and the final round hands over to a wave because that is where the loop sends the
# viewer back to round one.
_MASCOT_REVEAL_POSES = {"medium": "celebrate", "hard": "amazed", "expert": "amazed"}


def performer_specs(slot, out_dir):
    """Re-cut one reveal so Bolt performs across the whole beat instead of a badge sitting in it.

    Variant A spends the reveal as a 0.42s dissolve plus a still hold, and a still hold is a dead
    frame — the measured gap against the reference is ambient motion (3.30 against 6.08 mean frame
    delta), not cut frequency, where we already lead 7 beats to 3. Extending the clip over the
    whole beat is what turns that hold into performance.

    Returns replacement specs summing to EXACTLY ``slot["total"]`` so the shared audio timeline
    still fits, or None to leave the round as it was.
    """
    index = slot["round"]
    pose = ("wave" if slot["is_final"]
            else _MASCOT_REVEAL_POSES.get(slot["difficulty"], "celebrate"))
    if _mascot_pose(pose) is None:
        return None
    side = "right" if index % 2 else "left"          # alternate, so entrances do not feel stamped
    clip = f"{out_dir}/tr{index}_perf.mp4"
    # The closing card still needs its own beat: the CTA text has to arrive, and the loop dissolve
    # is cued off the tail of that card. So on the last round the performer covers only the answer
    # portion and the CTA spec is preserved untouched.
    clip_d = round(slot["total"] - slot["cta_beat"], 3)
    if clip_d < 0.2:
        return None
    if not _reveal_clip(slot["clue"], slot["reveal"], slot["answer"], clip, clip_d,
                        dissolve=slot["dissolve"], bolt=False, mood=slot["mood"],
                        pose_name=pose, side=side):
        return None
    specs = [(clip, clip_d, True)]
    if slot["is_final"]:
        specs.append((slot["reveal"], slot["cta_beat"], False, dict(slot["cta_opts"])))
    return specs


def apply_variant(render_specs, reveal_slots, variant, out_dir, log=print):
    """Rebuild the reveal beats for a variant, leaving every other spec byte-identical.

    That identity is the experiment. Countdowns, clue images, audio, captions and the loop close
    are shared, so a retention difference between variants can only come from the reveal layer —
    which is not true of two separate generations, where the animals themselves differ.
    """
    if variant == "a":
        return list(render_specs), True
    specs = list(render_specs)
    replaced = 0
    for slot in sorted(reveal_slots, key=lambda s: s["start"], reverse=True):
        built = performer_specs(slot, out_dir)
        if not built:
            continue
        before = sum(float(spec[1]) for spec in specs[slot["start"]:slot["end"]])
        after = sum(float(spec[1]) for spec in built)
        if abs(before - after) > 0.02:
            log(f"⚠ variant {variant} round {slot['round']} would shift the timeline "
                f"{before:.2f}s → {after:.2f}s; left unchanged")
            continue
        specs[slot["start"]:slot["end"]] = built
        replaced += 1
    return specs, replaced == len(reveal_slots)


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
    """Mobile QA for difficulty, readability, identity, anatomy, and pose continuity."""
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
                "\"anatomy_ok\":bool,\"pose_continuity\":bool,"
                "\"subject_width_pct\":0-100,\"clue_contrast_score\":0-100,"
                "\"biggest_fix\":\"...\"}. subject_width_pct is the full silhouette's bounding-box "
                "width as a percentage of IMAGE 2. clue_contrast_score is phone-size separation of the "
                "silhouette from its immediate background, where 100 is unmistakable and 0 disappears. "
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


_READABILITY_WIDTH_MIN = {"medium": 28.0, "hard": 20.0, "expert": 16.0}
_READABILITY_CONTRAST_MIN = 55.0


def quiz_readability_issues(grade: dict, difficulty: str, round_number: int) -> list[str]:
    """Turn the visual grader's phone-size measurements into an explicit shipping gate."""
    issues = []
    width = grade.get("subject_width_pct")
    contrast = grade.get("clue_contrast_score")
    if not isinstance(width, (int, float)):
        issues.append(f"round {round_number} subject occupancy was not measured")
    elif width < _READABILITY_WIDTH_MIN.get(difficulty, _READABILITY_WIDTH_MIN["hard"]):
        issues.append(
            f"round {round_number} clue subject spans {width:.0f}% of frame width; "
            f"{_READABILITY_WIDTH_MIN.get(difficulty, _READABILITY_WIDTH_MIN['hard']):.0f}% required")
    if not isinstance(contrast, (int, float)):
        issues.append(f"round {round_number} clue contrast was not measured")
    elif contrast < _READABILITY_CONTRAST_MIN:
        issues.append(
            f"round {round_number} clue contrast scored {contrast:.0f}/100; "
            f"{_READABILITY_CONTRAST_MIN:.0f} required")
    return issues


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


# A Short restarts the instant it ends, so its last frame sits directly against its first with
# no cut between them. Long enough to read as the scene settling back down, short enough that it
# comes out of the closing card rather than adding to the runtime.
_LOOP_DISSOLVE_SEC = 0.4
# Held after the dissolve so the final frames are the opening frame outright, not 92% of the way
# into becoming it. Three frames: enough to resolve, too short to read as a hold.
_LOOP_SETTLE_SEC = 3 / FPS
# The closing card's text is cleared this far ahead of the picture dissolve, so the two headlines
# are never on screen together. By then it has been readable for over a second.
_LOOP_TEXT_CLEAR_SEC = 0.18
# The silhouette-to-animal crossfade. Taken OUT of the reveal beat, never added to it, so the
# pacing the round count sets is the pacing that ships.
_REVEAL_TRANSITION_SEC = 0.42
# What must survive as a still hold after it: the answer needs a beat to sit still and be read,
# and a reveal that is entirely transition never resolves.
_REVEAL_HOLD_MIN_SEC = 0.2


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

    The LAST spec may carry ``xfade_prev``: instead of being concatenated it cross-dissolves over
    the tail of everything before it. That is how the video closes on its own opening frame — a
    Short restarts instantly, so a hard cut there is a cut the viewer sees. ``xfade`` yields
    ``a + b - d`` seconds, so a closing spec whose duration equals its dissolve leaves the total
    unchanged and the audio timeline built against it stays valid.
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
            over_label = f"[{over_index}:v]"
            fade = opts.get("overlay_fade")
            if fade:
                # Fade the CARD off, not the picture. Both are text in the same rounded rect at
                # the same place, so cross-dissolving them left the two headlines superimposed
                # and unreadable for the length of the dissolve.
                fade_at, fade_for = float(fade[0]), float(fade[1])
                filters.append(f"[{over_index}:v]format=rgba,"
                               f"fade=t=out:st={fade_at:.3f}:d={fade_for:.3f}:alpha=1[ovf{i}]")
                over_label = f"[ovf{i}]"
            filters.append(f"[bg{i}]{over_label}overlay=0:0:format=auto,"
                           f"trim=duration={duration:.3f},setpts=PTS-STARTPTS[v{i}]")
        else:
            filters.append(stage + f"[v{i}]")
        labels.append(f"[v{i}]")
    closing = specs[-1][3] if len(specs) > 1 and len(specs[-1]) > 3 else {}
    dissolve = float(closing.get("xfade_prev") or 0.0)
    if dissolve > 0:
        head = sum(float(spec[1]) for spec in specs[:-1])
        closing_d = float(specs[-1][1])
        # xfade requires both inputs to be constant-frame-rate with identical frame rate,
        # timebase, resolution and pixel format. concat can advertise an undefined 1/0 frame rate
        # even when every segment was rendered at 30 fps; Vercel's bundled FFmpeg rejects that
        # before encoding frame zero. Reset timestamps first, then let fps establish explicit CFR
        # metadata, and finally put both sides on the same AV timebase.
        filters.append("".join(labels[:-1]) +
                       f"concat=n={len(specs)-1}:v=1:a=0,format=yuv420p,"
                       f"setpts=PTS-STARTPTS,fps={FPS},settb=AVTB[pre]")
        filters.append(f"{labels[-1]}format=yuv420p,setpts=PTS-STARTPTS,"
                       f"fps={FPS},settb=AVTB[loop]")
        # xfade runs out to `offset + closing_d`, so anchoring the offset at `head - closing_d`
        # makes the total exactly the head — the closing spec costs no runtime however long it
        # is, and the audio timeline built against that total stays valid.
        #
        # The dissolve must be SHORTER than the spec carrying it. xfade's frames cover the
        # transition at [0, 1), never reaching 1, so a spec exactly as long as its dissolve ends
        # ~92% of the way across and the final frame is a blend rather than the opening frame.
        # The remainder holds the resolved frame, which is the whole point: the last frame the
        # viewer sees has to BE the first one.
        filters.append(f"[pre][loop]xfade=transition=fade:duration={dissolve:.3f}:"
                       f"offset={max(0.0, head - closing_d):.3f},format=yuv420p[out]")
    else:
        filters.append("".join(labels) + f"concat=n={len(specs)}:v=1:a=0,format=yuv420p[out]")
    try:
        os.remove(out)
    except OSError:
        pass
    result = subprocess.run(
        [FF, "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[out]",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), out],
        capture_output=True)
    err = result.stderr.decode(errors="replace")[-1600:] if result.stderr else ""
    # Never probe a failed encode. The previous order called `_dur(out)` first, so an absent or
    # malformed output raised MediaBinaryError and erased the FFmpeg stderr that explained the
    # actual filter/codec failure. That made a paid quiz render impossible to diagnose.
    if result.returncode != 0:
        raise RuntimeError(
            f"quiz sequence FFmpeg failed with exit {result.returncode}: {err}")
    try:
        actual = _dur(out)
    except Exception as exc:
        size = os.path.getsize(out) if os.path.exists(out) else 0
        raise RuntimeError(
            f"quiz sequence produced an unreadable output ({size} bytes): {err}") from exc
    if actual < expected_duration - 0.2:
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


# How much frame the animal fills, by tier. The image prompt asked for "clearly visible,
# unobstructed, roughly a third of the frame" on EVERY round, which handed the script's careful
# hard/expert poses straight back: a subject rendered large, sharp and unscreened is legible
# whatever pose it was given. Distance is the format's own difficulty lever — the premise is that
# something is hiding — and it costs no obscurity, because a wildebeest is still a wildebeest.
_HABITAT_FRAMING = {
    "medium": "occupying roughly a third of the frame, clearly visible and unobstructed",
    "hard": ("occupying roughly a quarter of the frame, set back into the scene, and partly "
             "screened by grass, foliage or terrain while its outline stays unbroken and readable"),
    "expert": ("occupying roughly a fifth of the frame, well back in the middle distance, and "
               "partly screened by grass, foliage or terrain while its outline stays unbroken and "
               "readable — far enough that it must be searched for, never so far it cannot be seen"),
}


def _habitat_pair(answer, habitat, pose, clue_dst, reveal_dst, size, cost_sink, scene_ref="",
                  difficulty="medium"):
    """Generate an in-habitat clue/reveal pair that share one camera.

    Order matters. The flat-colour format generates the silhouette first and grows a reveal out
    of it, which works because the background is a single colour and trivially reproducible. A
    habitat is not reproducible from a description twice running — two independent generations
    give two different forests, and the reveal stops being a payoff and becomes a scene change.

    So the *reveal* is authored first, and the clue is an edit of those exact pixels with the
    animal blacked out. The scene is then guaranteed identical and the reveal is a true match
    cut: only the animal changes.

    ``scene_ref`` closes the loop. A Short restarts the instant it ends, so the closing reveal and
    the opening clue sit against each other with no cut between them. Generating the last scene
    from its own description gives a different place every time — the reason the loop currently
    reads as a hard scene change — so the closing round is generated as an EDIT of the opening
    scene instead: same environment, same camera, only the animal differs. The flat-colour format
    has always closed its loop this way, by landing the last card on round one's field colour.

    Returns ``(mode, ok)``; ``ok`` is False when the silhouette edit could not be produced, so
    the caller can fall back to the flat-colour format rather than ship an unguessable clue.
    """
    scene = ep._s(habitat).strip() or "its natural habitat, cinematic wide shot, natural light"
    stance = ep._s(pose).strip() or "in the middle distance, seen side-on"
    framing = _HABITAT_FRAMING.get((difficulty or "medium").strip().lower(),
                                   _HABITAT_FRAMING["medium"])
    if scene_ref and os.path.exists(scene_ref):
        # The opening scene is a photograph we already have, and re-describing it would only
        # approximate it. Editing it guarantees the viewer lands back in the same place.
        ep.generate_image(
            "Keep this photograph's environment EXACTLY as it is — identical camera, framing, "
            "composition, background, horizon, lighting direction, colour grade and every "
            f"environmental detail. Replace the animal in it with a {answer} {stance}. The "
            f"{answer} must be the ONLY animal in the shot, with correct species anatomy, "
            f"{framing}. Photoreal, rich natural colour. No text, letters, numbers, watermark, "
            "people, or borders.",
            reveal_dst, size=size, cost_sink=cost_sink, reference_paths=[scene_ref])
    else:
        ep.generate_image(
            f"Cinematic wildlife photograph. A {answer} {stance} in {scene}, {framing}. Correct "
            "species anatomy. Shot on a long lens with natural depth of field, photoreal, rich "
            "natural colour, volumetric light. No text, letters, numbers, watermark, people, "
            "or borders.",
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
        return ("habitat_loop_pair" if scene_ref else "habitat_pair"), True
    except Exception as exc:
        print(f"[quiz] habitat silhouette edit failed: {exc}")
        return "habitat_reveal_only", False


def _guessed_the_answer(guess, answer) -> bool:
    """Whether the grader's first guess names the answer.

    Compared on squashed alphanumerics so "SECRETARY BIRD" matches "secretarybird" and "Snow
    Leopard" matches "snow leopard" — the grader's casing and spacing vary run to run and a
    literal comparison silently scored every one of those as a miss.
    """
    def squash(text):
        return re.sub(r"[^a-z0-9]", "", ep._s(text).lower())
    g, a = squash(guess), squash(answer)
    if not g or not a:
        return False
    if g == a:
        return True
    # Substring only counts when the shorter side is a real word: "ox" would otherwise mark
    # "oxpecker" as guessed, turning an unrelated miss into a ladder failure.
    return min(len(g), len(a)) >= 4 and (g in a or a in g)


def _same_habitat(a, b) -> bool:
    """Whether two habitat descriptions name the same scene.

    The closing reveal is generated by editing the opening photograph, so if the script gave the
    final animal a habitat of its own, that edit would move a species somewhere it does not live
    — an okapi standing on open savanna. This pipeline fact-checks its answers precisely because
    a wrong one destroys trust, and a wrong environment is the same claim made in pictures.

    The generator is asked for the two habitats word for word, so equality is the signal. It is
    compared loosely enough to survive punctuation and spacing drift, and no more: a merely
    similar description is a different place.
    """
    def norm(text):
        return " ".join(re.sub(r"[^a-z0-9 ]+", " ", ep._s(text).strip().lower()).split())
    first, second = norm(a), norm(b)
    return bool(first) and first == second


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
                      progress_cb=None, operator_direction: str = "",
                      variants: tuple = ("a",), primary_variant: str = "a") -> dict:
    """Generate + render a full quiz short. Returns {output_path,title,scene_count,...}.

    The legacy variant arguments remain for caller compatibility, but the product flow is locked
    to mascot-free control A. Reveal energy comes from the same-frame silhouette transformation,
    type-on answer, burst, and camera drift rather than a character overlay.
    """
    def log(m):
        if progress_cb: progress_cb(m)
    output_dir = os.path.abspath(output_dir)   # absolute so ffmpeg concat lists never double the path
    os.makedirs(output_dir, exist_ok=True)
    A = output_dir; costs = []
    n_items = clamp_quiz_items(n_items)
    # The current mascot cutouts are visually off-model. Keep the compatibility parameters but
    # fail closed to the clean gameplay render even when an older caller still requests variant B.
    variants = ("a",)
    primary_variant = "a"
    log("stage:Writing quiz...")
    quiz = generate_quiz(category, n_items, cost_sink=costs, operator_direction=operator_direction)
    if not quiz or not quiz.get("items"):
        raise RuntimeError("quiz generation failed")
    quiz, fixes = factcheck_quiz(quiz, cost_sink=costs)
    if fixes: log(f"Fact-check corrected {len(fixes)} answer(s)")
    items = quiz["items"]
    title = normalize_quiz_title(quiz.get("title"), len(items), category)
    quiz["title"] = title
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
    timing_warnings = []; loop_warnings = []; opening_frame = None; reveal_slots = []
    ladder_warnings = []
    readability_warnings = []
    # The round badge was hardcoded to "ANIMAL", so a fruits or planets quiz labelled every
    # round ANIMAL 1/3. The category is a free parameter of this pipeline, so the badge has to
    # follow it: last word, singularised, since categories arrive plural ("wild animals").
    _noun = (ep._s(quiz.get("category")) or category or "item").strip().split()[-1].upper()
    round_noun = _noun[:-1] if len(_noun) > 3 and _noun.endswith("S") else _noun
    # "CAN YOU GET 3/3?" states the scoring rules. On a habitat clue the interesting question is
    # not how many you score, it is that something is in the frame you have not found yet.
    # "Something is hiding" states a situation and asks the viewer for nothing; it is also not
    # quite true, since a large black shape is right there in frame. An instruction gives them
    # something to do in the half-second they are deciding whether to stay.
    clue_banner, clue_banner_accent = (("GUESS THE ", "SHADOW!") if HABITAT
                                       else (f"CAN YOU GET {len(items)}/{len(items)}", "?"))
    # A Short loops instantly, so the last frame sits directly against the first. Round one's
    # field is known up front, and the final reveal is generated and padded to land on it, which
    # turns the loop point from a colour flip into a match cut.
    loop_name, loop_rgb = sil_bg_for(1)

    for i, it in enumerate(items, 1):
        bg = _COLORS.get(ep._s(it.get("color")).strip().lower(), (40, 90, 140))
        clue = f"{A}/clue{i}.png"; rev = f"{A}/rev{i}.png"
        answer = ep._s(it.get("answer"))
        closes_loop = i == len(items)
        # Resolved before the images are generated, not after: the habitat pair now frames the
        # animal by tier, and this used to be assigned further down. Round one would have raised
        # NameError and every later round would have quietly reused the PREVIOUS round's
        # difficulty — the silent half being much the worse of the two.
        diff = ep._s(it.get("difficulty")).lower() or ("medium" if i == 1 else "expert" if i == len(items) else "hard")
        in_habitat = False
        if HABITAT:
            habitat_text = it.get("habitat")
            scene_ref = ""
            if closes_loop and len(items) > 1:
                opening_habitat = items[0].get("habitat")
                if _same_habitat(habitat_text, opening_habitat):
                    scene_ref = f"{A}/rev1.png"     # the opening scene, as generated
                    habitat_text = opening_habitat
                else:
                    # Shipping the loop would relocate the species; shipping the cut only costs
                    # the match. Say which one happened rather than silently choosing.
                    loop_warnings.append(
                        f"the closing habitat differs from the opening one, so the video ends "
                        f"on a different place than it starts: opening "
                        f"\"{ep._s(opening_habitat)[:60]}\" vs closing \"{ep._s(habitat_text)[:60]}\"")
                    log("⚠ closing habitat does not match the opening one — loop left as a cut")
            reveal_mode, in_habitat = _habitat_pair(
                answer, habitat_text, it.get("pose"), clue, rev, "1024x1536", costs,
                scene_ref=scene_ref, difficulty=diff)
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
            _text_png(f"{A}/cd{i}_{k}_t.png", top=clue_banner, top_accent=clue_banner_accent,
                      difficulty=diff, difficulty_label=tier_label(i, len(items)),
                      round_label=f"{round_noun} {i}/{len(items)}", cd_left=k)
            countdown_overlays.append(f"{A}/cd{i}_{k}_t.png")
            countdown_outputs.append(f"{A}/c{i}1_{k}.mp4")
        grade = grade_quiz_visuals(countdown_bases[0], f"{A}/clue{i}_b.png", f"{A}/rev{i}_b.png",
                                   answer, diff, costs) or {}
        grade["round"] = i; grade["answer"] = answer; grade["difficulty"] = diff
        grade["reveal_generation_mode"] = reveal_mode
        round_readability = quiz_readability_issues(grade, diff, i)
        if round_readability:
            grade["readability_failed"] = True
            readability_warnings.extend(round_readability)
            for warning in round_readability:
                log(f"⚠ {warning}")
        if grade.get("too_easy"):
            # Deepen the ladder this clue is ACTUALLY using. Reading clue_zoom() here always
            # returned the flat-colour opener, so a habitat clue jumped 1.16 -> 2.31: the whole
            # animal became an unreadable black mass bleeding off all four edges, and the scene
            # it is hidden in disappeared. That is the "moment of least information" the habitat
            # ladder exists to avoid, applied to the one frame that decides whether anyone
            # stays. It also broke the ease, stepping 2.31 -> 1.08 instead of 1.16 -> 1.08.
            # Scaling the ladder's own opener is identical arithmetic on the flat-colour format,
            # whose opener IS clue_zoom(diff, 0), so that path is unchanged.
            zoom_ladder[0] = zoom_ladder[0] * 1.25
            _progressive_crop(f"{A}/clue{i}_b.png", countdown_bases[0], zoom_ladder[0])
            grade["crop_deepened"] = True
            log(f"Round {i} difficulty QA deepened the opening crop")
        # Cropping tighter cannot fix an animal whose whole outline gives it away — a crocodile
        # stays a crocodile at any zoom. On the tiers that are supposed to be hard, a grader that
        # NAMES the answer from the first crop is reporting that the item was chosen badly, and
        # the render has no way to re-pick the animal at this point. Say so instead of deepening
        # the crop and reporting "ok": across six earlier renders 15 of 17 hard/expert rounds were
        # identified from the first 0.6s and every one of them shipped as a clean pass.
        # Both conditions, not either. The grader NAMING the answer is what makes it an item
        # problem rather than a framing one; too_easy is what says the confidence breached this
        # tier's own calibrated bar (medium 80, hard 65, expert 50). Flagging a bare correct guess
        # marked a wolverine identified at 55% as a failed HARD round, which that bar explicitly
        # allows — two mechanisms contradicting each other, and the noisier one wins arguments it
        # should not.
        if (diff in ("hard", "expert") and grade.get("too_easy")
                and _guessed_the_answer(grade.get("first_guess"), answer)):
            grade["ladder_failed"] = True
            ladder_warnings.append(
                f"round {i} is labelled {diff} but the grader named \"{answer}\" from the first "
                f"crop at {grade.get('first_crop_confidence')}% confidence — the item is easier "
                f"than its tier claims")
            log(f"⚠ Round {i} ({diff}) was identified from the opening crop — ladder not honoured")
        if grade.get("reveal_matches_answer") is False or grade.get("anatomy_ok") is False:
            grade["repair_generation_mode"] = _generate_reveal(
                answer, it.get("clue_visual"), clue, rev, "1024x1536", costs,
                reference_first=False, strict=True, bg_name=loop_name if closes_loop else "")
            _fit(rev, f"{A}/rev{i}_b.png", "pad",
                 bg=loop_rgb if closes_loop else _edge_background(rev))
            grade["reveal_regenerated"] = True
            log(f"Round {i} identity QA regenerated the answer reveal")
        visual_qa.append(grade)
        if i == 1:
            # Frame zero, as it will actually ship: read AFTER the QA block, because a round one
            # graded too easy opens at a deepened crop and the loop has to land on the frame the
            # viewer really sees, not the one the ladder nominated.
            opening_frame = (f"{A}/clue{i}_b.png", countdown_overlays[0], zoom_ladder[0])

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
        _text_png(f"{A}/r{i}_t.png", top=None, subscribe=False,
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
        # The silhouette becoming the animal is the one payoff this format has that the
        # flat-colour one cannot stage, and it was being spent on a hard cut. The transition
        # comes OUT of the beat rather than extending it, so the pacing is unchanged.
        reveal_spec_start = len(render_specs)
        trans_clip = f"{A}/tr{i}.mp4"
        budget = (CDN if is_final else dr) - _REVEAL_HOLD_MIN_SEC
        trans_d = round(min(_REVEAL_TRANSITION_SEC, budget), 3)
        has_transition = trans_d > 0.05 and _reveal_clip(
            f"{A}/clue{i}_b.png", f"{A}/rev{i}_b.png", answer, trans_clip, trans_d,
            bolt=False)
        if has_transition:
            render_specs.append((trans_clip, trans_d, True))
            clips.append(trans_clip)
        else:
            trans_d = 0.0
        if is_final:
            # The closing card used to be one static hold: no cut for its whole length, on a
            # video that had trained the viewer to expect a beat every 0.8s. Landing the answer
            # first and bringing the CTA in on the next beat keeps the pulse through the payoff.
            # Both halves render from the same reveal with a continuous push-in, so the beat
            # reads as emphasis rather than as a new card.
            # The video signs off on the payoff, so the last face the viewer sees is a pleased
            # one rather than the expert round's wide-eyed alarm.
            # Same accent split as the clue banner: the ask gets the colour, the score question
            # stays white, so the two cards read as one channel rather than two designs.
            _text_png(f"{A}/r{i}_cta_t.png", subscribe=True,
                      top=f"GOT ALL {len(items)}? · ", top_accent="SUBSCRIBE",
                      answer=answer.upper() + "!")
            answer_beat = CDN - trans_d
            cta_beat = max(0.3, dr - CDN)
            answer_end_zoom = 1.0 + min(_DRIFT_CLOSING_MAX, _DRIFT_CLOSING_PER_SEC * answer_beat)
            render_specs.append((f"{A}/rev{i}_b.png", answer_beat, False,
                                 {"overlay": f"{A}/r{i}_t.png", "z_to": 1.0,
                                  "drift": _DRIFT_CLOSING_PER_SEC,
                                  "drift_max": _DRIFT_CLOSING_MAX}))
            cta_opts = {"overlay": f"{A}/r{i}_cta_t.png", "z_to": answer_end_zoom,
                        "drift": _DRIFT_CLOSING_PER_SEC, "drift_max": _DRIFT_CLOSING_MAX}
            # The loop dissolve eats into the tail of this card. Clear its text just before that
            # starts so the dissolve is scene-to-scene, with only the opening card's text fading
            # in. A card that merely cross-faded with the next one was illegible in both.
            text_clear_at = cta_beat - (_LOOP_DISSOLVE_SEC + _LOOP_SETTLE_SEC) - _LOOP_TEXT_CLEAR_SEC
            if opening_frame and text_clear_at > 0:
                cta_opts["overlay_fade"] = (text_clear_at, _LOOP_TEXT_CLEAR_SEC)
            render_specs.append((f"{A}/rev{i}_b.png", cta_beat, False, cta_opts))
            clips.append(f"{A}/r{i}.png"); clips.append(f"{A}/r{i}_cta_t.png")
            dr = trans_d + answer_beat + cta_beat
        else:
            render_specs.append((f"{A}/rev{i}_b.png", dr - trans_d, False,
                                 {"overlay": f"{A}/r{i}_t.png", "z_to": 1.0}))
            clips.append(f"{A}/r{i}.png")
        # Everything a variant needs to re-cut THIS reveal, captured while the numbers are in
        # scope. Durations are recorded, never recomputed: both variants must land on the same
        # timeline or the single audio track stops matching the picture.
        reveal_slots.append({
            "start": reveal_spec_start, "end": len(render_specs), "round": i,
            "clue": f"{A}/clue{i}_b.png", "reveal": f"{A}/rev{i}_b.png", "answer": answer,
            "mood": "idle", "difficulty": diff, "is_final": is_final, "total": dr,
            "dissolve": _REVEAL_TRANSITION_SEC, "cta_overlay": f"{A}/r{i}_cta_t.png",
            "cta_opts": dict(cta_opts) if is_final else None,
            "cta_beat": cta_beat if is_final else 0.0,
        })
        audio.append((f"{A}/n_r{i}.mp3", t, "narr")); audio.append(("DING", t, "ding")); caps.append((t, _dur(f"{A}/n_r{i}.mp3"), r_texts[i])); t += dr
    TOTAL = t
    if opening_frame and len(render_specs) > 1:
        # Close on the frame the video opens on. Rendered through the same base image, overlay
        # and zoom as round one's first countdown card, so it is that frame rather than a
        # reconstruction of it — drift is switched off so the dissolve settles on the exact zoom
        # frame zero starts at instead of a fraction past it. Its duration is consumed entirely
        # by the cross-dissolve, so TOTAL and the audio timeline below are unaffected.
        loop_base, loop_overlay, loop_zoom = opening_frame
        render_specs.append((loop_base, _LOOP_DISSOLVE_SEC + _LOOP_SETTLE_SEC, False, {
            "overlay": loop_overlay, "z_to": loop_zoom, "drift": 0,
            "xfade_prev": _LOOP_DISSOLVE_SEC}))
        clips.append(loop_overlay)

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
    # Three ticks, one per countdown stage, rising pitch, NO ding. Derived from CDN rather than
    # written out: these were hardcoded at 0/800/1600ms over a 2.4s trim, which was correct only
    # while the guess window was 2.4s. Shortening the window would have left the ticks marking
    # time that no longer existed — the last one landing after the answer had already appeared —
    # and nothing would have failed, it would just have sounded wrong.
    _t1, _t2 = int(CDN * 1000), int(CDN * 2000)
    cdsfx = f"{A}/cdsfx.wav"
    subprocess.run([FF, "-y", "-filter_complex",
        f"sine=1000:d=0.06,adelay=0|0[a];sine=1000:d=0.06,adelay={_t1}|{_t1}[b];"
        f"sine=1300:d=0.09,adelay={_t2}|{_t2}[c];"
        f"[a][b][c]amix=inputs=3:normalize=0,volume=2,atrim=0:{QUIZ_V2.guess_window_sec}[o]",
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
        # No tail fade. A 1.3s fade to silence is an ending cue, and it played over the very
        # beat now built to hide the ending; against a full-volume restart it was a
        # discontinuity either way. A short fade-in covers the seam on the other side.
        parts.append(f"[{mus}:a]atrim=0:{TOTAL},volume=0.11,afade=t=in:st=0:d=0.35[mus]")
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

    # Extra variants re-cut ONE layer off the assets already paid for and reuse this exact audio
    # track. Rendering a second quiz instead would change the animals, the habitats and the
    # images along with the layer under test, and no retention difference could be attributed.
    variant_outputs = {"a": out_mp4}
    for variant in [v for v in variants if v != "a"]:
        log(f"stage:Rendering variant {variant.upper()}...")
        specs, complete = apply_variant(render_specs, reveal_slots, variant, A, log=log)
        if specs == render_specs:
            log(f"⚠ variant {variant} produced no change — mascot library missing?")
            continue
        vsil_v = f"{A}/video_silent_{variant}.mp4"
        out_v = os.path.join(output_dir, f"quiz_{variant}.mp4")
        try:
            _render_sequence(specs, vsil_v, TOTAL)
            subprocess.run([FF, "-y", "-i", vsil_v, "-i", faud, "-c:v", "copy", "-c:a", "aac",
                            "-shortest", "-movflags", "+faststart", out_v], capture_output=True)
        except Exception as exc:
            log(f"⚠ variant {variant} render failed, control is unaffected: {exc}")
            continue
        if not os.path.exists(out_v) or abs(_dur(out_v) - actual_duration) > 0.15:
            # A variant of a different length is not a variant; it is a second video. Drop it
            # rather than ship a pair whose only certainty is that the comparison is invalid.
            log(f"⚠ variant {variant} length {_dur(out_v):.2f}s != control {actual_duration:.2f}s; discarded")
            continue
        if not complete:
            log(f"⚠ variant {variant} re-cut only some rounds")
            continue
        variant_outputs[variant] = out_v
        log(f"Variant {variant.upper()} rendered → {os.path.basename(out_v)}")

    selected_variant = primary_variant if primary_variant in variant_outputs else "a"
    primary_output = variant_outputs[selected_variant]
    if primary_variant not in variant_outputs:
        readability_warnings.append(
            f"preferred reveal variant {primary_variant} was unavailable; control A was selected")

    # Ready-to-paste YouTube description + tags (best-effort). Runs BEFORE the cost sum so its cost is
    # counted; the app persists description_path → {job}.desc exactly like the explainer path.
    log("stage:Writing description...")
    description_path = generate_quiz_description(category, title, items, q_texts.get(1), A, cost_sink=costs)
    if description_path:
        log("YouTube description written")
    cost = round(sum(costs), 3)
    _deg = (list(timing_warnings) + list(loop_warnings) + list(ladder_warnings)
            + list(readability_warnings))
    if not os.path.exists(primary_output):
        _deg = ["final video file was not produced — assembly failed"] + _deg
    fal_used = any(event.get("used") for event in fal_opener)
    log(f"Complete — rapid quiz assembled · ${cost} · first clue at 0.0s · {TOTAL:.1f}s planned"
        + (" · fal opener" if fal_used else ""))
    # Shape matches run_explainer_pipeline so the app's save/index path consumes it unchanged.
    return {"output_path": primary_output, "title": title, "category": quiz.get("category", category),
            "scene_count": len(clips), "duration_sec": round(_dur(primary_output), 1),
            "items": [{"answer": it.get("answer"), "fact": it.get("fact")} for it in items],
            "script": quiz, "hook": q_texts.get(1, ""), "video_format": "social",
            "quiz_creative": QUIZ_V2.version, "first_clue_at_sec": QUIZ_V2.first_clue_at_sec,
            "fal_opener_requested": FAL_OPENER, "fal_opener_used": fal_used,
            "progressive_clues": QUIZ_V2.progressive_clues,
            "subscribe_cta": "integrated_final_reveal", "visual_qa": visual_qa,
            "habitat_loop_closed": HABITAT and not loop_warnings,
            "difficulty_ladder_honoured": not ladder_warnings,
            "variants": {k: v for k, v in variant_outputs.items()},
            "primary_variant": selected_variant, "mascot_overlay": False,
            "planned_duration_sec": round(TOTAL, 2),
            "srt_path": srt_path, "transcript_path": transcript_path,   # app copies these → {job}.srt/.txt
            "description_path": description_path,                        # app copies → {job}.desc
            "status": ("degraded" if _deg else "ok"), "degraded_reasons": _deg,
            "actual_cost": cost, "est_cost": cost}
