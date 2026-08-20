"""QUIZ social-short pipeline — a third format alongside explainer/simulation.

Bolt hosts a "What is it?" quiz: a hook, then N rounds of [AI-safe visual clue -> 3-2-1 countdown ->
answer reveal + running score], then a comment-bait outro. Design decisions proven in prototypes:
  - AI-SAFE items only (silhouettes / clear photos of animals, planets, objects) — NEVER flags, logos,
    signs, or maps, because gpt-image garbles baked-in text/symbols and a wrong clue breaks the quiz.
  - Answers are FACT-CHECKED (a wrong answer destroys trust).
  - SINGLE audio timeline (narration placed at exact beat offsets) so audio locks to the visuals.
  - Tick on each countdown second + a ding on each reveal + a low music bed.
  - Bolt hook/outro use a LIVELY animated game-show stage (Kling i2v motion, Ken-Burns fallback) —
    chosen over a static talking-head-with-mouth because the energetic stage reads far more engaging.

Standalone module; reuses explainer_pipeline for image/TTS gen + the mascot. Best-effort throughout.
"""
import os, re, subprocess, wave, math, json
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
import explainer_pipeline as ep
from music_assets import get_music_path

FF = "/opt/homebrew/bin/ffmpeg"; FP = "/opt/homebrew/bin/ffprobe"
FONT = os.environ.get("QUIZ_FONT", "/System/Library/Fonts/Supplemental/Arial Bold.ttf")
W, H, FPS = 1080, 1920, 30
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
    "DIFFICULTY LADDER — this is what keeps viewers watching: order items EASY -> HARD -> EXPERT and set "
    "each item's \"difficulty\". Item 1 is EASY but NOT trivially obvious — it should need ~1 second of "
    "thought (e.g. camel/rhino/flamingo, NOT elephant; a pear/pomegranate, NOT a red apple). The final "
    "item is EXPERT: genuinely tricky or slightly deceptive. Each spoken line SHORT and punchy.\n"
    "CONSISTENT REVEALS: keep EVERY reveal the SAME isolated style — the subject centered on a clean SOLID "
    "colorful studio background, NO habitat/scene/water (don't put one animal underwater and another on "
    "white). \"reaction\" is a 2-4 word reveal punch flavored by difficulty ('Too easy!' / 'Tricky one!' / "
    "'Almost nobody gets this!').\n"
    "Return ONLY JSON: {\"title\":\"clickable title, e.g. 'Can You Name All 3 From the Shadow?'\","
    "\"category\":\"e.g. animals\",\"hook\":\"one tight spoken line that flows straight into round one AND "
    "promises the last is hardest, e.g. 'Guess all three from their shadows — the last one is nearly "
    "impossible.'\",\"outro\":\"a short spoken comment-bait line\",\"items\":[{\"subject\":\"camel\","
    "\"difficulty\":\"easy|hard|expert\",\"clue_visual\":\"a clean bold black silhouette of a camel in "
    "profile\",\"reveal_visual\":\"a cute friendly 3D camel centered on a clean solid background\","
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
def _font(s): return ImageFont.truetype(FONT, s)
def _t(d, xy, s, sz, fill, anchor="mm", stroke=10, sc=NAVY):
    d.text(xy, s, font=_font(sz), fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=sc)

_DIFF_COLORS = {"easy": (80, 200, 120), "hard": (245, 180, 60), "expert": (240, 80, 80)}

def _text_png(path, top=None, answer=None, score=None, difficulty=None, cd_left=None, subscribe=False):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    if subscribe:                                          # YouTube-style subscribe CTA (teaser beat)
        sw = int(_font(78).getlength("SUBSCRIBE")) + 190; cyp = int(H * 0.72)
        d.rounded_rectangle([W//2-sw//2, cyp-72, W//2+sw//2, cyp+72], radius=38, fill=(230, 33, 42, 255))
        tri = W//2 - sw//2 + 66                             # white play-triangle
        d.polygon([(tri, cyp-34), (tri, cyp+34), (tri+58, cyp)], fill=(255, 255, 255, 255))
        _t(d, (W//2 + 46, cyp), "SUBSCRIBE", 78, WHITE, stroke=4)
    if top:
        d.rounded_rectangle([40, 70, W-40, 240], radius=30, fill=(*NAVY, 255)); _t(d, (W//2, 155), top, 70, WHITE, stroke=6)
    if difficulty:                                          # difficulty ladder badge (EASY/HARD/EXPERT)
        dc = _DIFF_COLORS.get(difficulty.lower(), (245, 180, 60)); lbl = difficulty.upper()
        bw = int(_font(54).getlength(lbl)) + 72
        d.rounded_rectangle([W//2-bw//2, 258, W//2+bw//2, 344], radius=24, fill=(*dc, 255)); _t(d, (W//2, 301), lbl, 54, WHITE, stroke=5)
    if cd_left is not None:                                 # 3-segment timer bar — keeps the CLUE unobstructed
        segw = (W-200)//3; y0 = H-500
        for k in range(3):
            x0 = 100 + k*segw + 8; col = CYAN if k < cd_left else (60, 66, 84)
            d.rounded_rectangle([x0, y0, x0+segw-16, y0+48], radius=16, fill=(*col, 255), outline=(*NAVY, 255), width=4)
    if answer:
        d.rounded_rectangle([40, H-360, W-40, H-200], radius=30, fill=(*NAVY, 255), outline=(*CYAN, 255), width=6); _t(d, (W//2, H-280), answer, 92, CYAN, stroke=8)
    if score:
        d.rounded_rectangle([W-330, 280, W-40, 400], radius=26, fill=(*RED, 255)); _t(d, (W-185, 340), score, 74, WHITE, stroke=6)
    im.save(path)

def _fit(src, out, mode="fit", bg=(0, 0, 0)):
    im = Image.open(src).convert("RGB")
    (ImageOps.pad(im, (W, H), color=bg) if mode == "pad" else ImageOps.fit(im, (W, H))).save(out)

def _composite(base, textpng, out):
    Image.alpha_composite(Image.open(base).convert("RGBA"), Image.open(textpng).convert("RGBA")).convert("RGB").save(out)

def _dur(p):
    return float(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of",
                                 "default=nw=1:nk=1", p], capture_output=True, text=True).stdout.strip() or 0)

def _still(img, out, d):
    subprocess.run([FF, "-y", "-loop", "1", "-i", img, "-t", f"{d}", "-an", "-vf", "fps=30,format=yuv420p",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out], capture_output=True)

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


_QUIZ_DESC_SYSTEM = (
    "You are a YouTube Shorts packaging editor. Write the DESCRIPTION for a QUIZ / guessing-game Short "
    "(host mascot 'Bolt' shows a clue, a 5-second countdown runs, then the answer is revealed). "
    "Register: vivid, confident, curiosity-driven, direct 2nd-person ('YOU'), specific, ZERO fluff — no "
    "'get ready to test your knowledge' filler. The arc is the escalating CHALLENGE and a dare to the "
    "viewer.\n"
    "STRUCTURE: (a) 'body' = TWO short punchy paragraphs — para 1 sets the challenge and frames the "
    "HARDEST/last round as the one that 'stumps almost everyone'; para 2 escalates the difficulty ladder "
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
        usr = (f'Category: "{category}". Title: "{title}". Hook line: "{ep._s(hook)}".\n'
               f'The {len(items)} answers, in order (put these in the TAGS for search; do NOT map them '
               f'to clues in the body): {ordered}.\nWrite the description now.')
        r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=1600,
                                         system=_QUIZ_DESC_SYSTEM,
                                         messages=[{"role": "user", "content": usr}])
        if cost_sink is not None:
            cost_sink.append(ep._msg_cost(r.usage))
        o, _ = ep._parse_script_json(r.content[0].text)
        if not isinstance(o, dict) or not ep._s(o.get("body")).strip():
            return ""
        parts = [ep._s(o.get("body")).strip()]
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
    Image.fromarray(res.astype(np.uint8)).save(out)


def make_silhouette_clue(clue_visual, dst, size, cost_sink, idx=0):
    """Render a TRUE guess-from-the-shadow clue: a pure-black silhouette on a flat bright background
    (bypasses the vibrant style that was giving the answer away). Returns the chosen bg RGB so the caller
    pads the frame with the SAME colour for a seamless panel."""
    name, rgb = _SIL_BG[idx % len(_SIL_BG)]
    _safe_image(_sil_prompt(clue_visual, name), dst, size, cost_sink)   # fallback_label="" → never leak the answer
    try:
        _silhouette_clean(dst, dst, rgb)
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
    log("stage:Writing quiz...")
    quiz = generate_quiz(category, n_items, cost_sink=costs, operator_direction=operator_direction)
    if not quiz or not quiz.get("items"):
        raise RuntimeError("quiz generation failed")
    quiz, fixes = factcheck_quiz(quiz, cost_sink=costs)
    if fixes: log(f"Fact-check corrected {len(fixes)} answer(s)")
    items = quiz["items"]; title = ep._s(quiz.get("title")) or f"Guess the {category}"
    log(f"Quiz: \"{title}\" — {len(items)} items")

    STY = " Polished 3D cartoon, vibrant, high production value, vertical 9:16, no text or letters."
    BOLT = ("Use the attached reference image: keep Bolt the rounded matte-white robot with mint-green "
            "accents. ")
    mascot = [ep.MASCOT_REF] if os.path.exists(ep.MASCOT_REF) else None

    # LIVELY game-show stage Bolt for an animated hook + outro (Kling motion — more engaging than a
    # static talking-head; user preferred the energetic stage look over exact mouth-sync).
    log("stage:Generating images & voiceover...")
    _safe_image(BOLT + "Bolt stands on a colorful glowing game-show quiz stage like an excited host, "
                "one arm raised presenting, a big glowing question mark beside him, spotlights and "
                "confetti, energetic and fun." + STY, f"{A}/hook_img.png", "1024x1536", costs,
                reference_paths=mascot)
    _safe_image(BOLT + "Bolt gives a big two-thumbs-up toward the viewer on the colorful game-show "
                "stage, confetti bursting, celebratory and lively." + STY, f"{A}/outro_img.png",
                "1024x1536", costs, reference_paths=mascot)
    _fit(f"{A}/hook_img.png", f"{A}/hook_b.png", "fit"); _fit(f"{A}/outro_img.png", f"{A}/outro_b.png", "fit")

    # narration (keep the exact spoken TEXT so the .srt is built deterministically — no transcription)
    hook_text = ep._s(quiz.get("hook")) or f"Can you guess these {category}?"
    outro_text = ep._s(quiz.get("outro")) or "How many did you get? Comment below!"
    n_hook = f"{A}/n_hook.mp3"; ep.generate_tts(hook_text, n_hook, voice=voice)
    n_out = f"{A}/n_out.mp3"; ep.generate_tts(outro_text, n_out, voice=voice)
    q_texts = {}; r_texts = {}
    for i, it in enumerate(items, 1):
        q_texts[i] = f"Number {['one','two','three','four','five','six'][i-1]}. What is it?"
        ep.generate_tts(q_texts[i], f"{A}/n_q{i}.mp3", voice=voice)
        react = ep._s(it.get("reaction")) or "Nice!"        # punchy reveal reaction (was the long fact → dragged)
        r_texts[i] = f"{ep._s(it.get('answer'))}! {react}"
        ep.generate_tts(r_texts[i], f"{A}/n_r{i}.mp3", voice=voice)

    CDN = 0.8                                                # per-number countdown tick (0.8*3 = 2.4s, snappier)
    clips = []; audio = []; caps = []; t = 0.0; i2v_flags = []   # caps = (start_sec, dur_sec, text) for the .srt

    # HOOK (lively animated game-show Bolt) — trimmed so gameplay starts fast
    _text_png(f"{A}/hook_t.png", top=f"GUESS THE {category.upper()}", answer="THE LAST IS HARDEST")
    hook_d = _dur(n_hook) + 0.4
    HOOKD = _motion_clip(f"{A}/hook_b.png", f"{A}/hook_t.png", f"{A}/c00_hook.mp4", hook_d,
                         "the robot host points confidently at the viewer then gestures to the puzzle, confetti drifts", i2v_sink=i2v_flags)
    clips.append(f"{A}/c00_hook.mp4"); audio.append((n_hook, t, "narr")); caps.append((t, _dur(n_hook), hook_text)); t += HOOKD

    for i, it in enumerate(items, 1):
        bg = _COLORS.get(ep._s(it.get("color")).strip().lower(), (40, 90, 140))
        clue = f"{A}/clue{i}.png"; rev = f"{A}/rev{i}.png"
        if is_silhouette_clue(it.get("clue_visual")):
            # "from the shadow" → a TRUE black silhouette; pad with the same bright bg for a seamless panel
            bg = make_silhouette_clue(ep._s(it.get("clue_visual")), clue, "1024x1536", costs, idx=i)
        else:
            _safe_image(ep._s(it.get("clue_visual")) + ", centered with margin, on a flat bright "
                        "background, bold clean shape, no text." + STY, clue, "1024x1536", costs)
        _safe_image(ep._s(it.get("reveal_visual")) + ", centered, clean bright background, appealing, sharp." + STY,
                    rev, "1024x1536", costs, fallback_label=ep._s(it.get("answer")))
        _fit(clue, f"{A}/clue{i}_b.png", "pad", bg=bg); _fit(rev, f"{A}/rev{i}_b.png", "fit")
        diff = ep._s(it.get("difficulty")).lower() or ("easy" if i == 1 else "expert" if i == len(items) else "hard")
        # question (difficulty ladder badge; countdown timer will be a bottom bar, not a number over the clue)
        _text_png(f"{A}/q{i}_t.png", top=f"#{i}  WHAT IS IT?", difficulty=diff)
        _composite(f"{A}/clue{i}_b.png", f"{A}/q{i}_t.png", f"{A}/q{i}.png")
        dq = _dur(f"{A}/n_q{i}.mp3") + 0.4
        _still(f"{A}/q{i}.png", f"{A}/c{i}0_q.mp4", dq); clips.append(f"{A}/c{i}0_q.mp4")
        audio.append((f"{A}/n_q{i}.mp3", t, "narr")); caps.append((t, _dur(f"{A}/n_q{i}.mp3"), q_texts[i])); t += dq
        # countdown — 3-segment bar depletes over the CLUE (animal stays the hero); ticks in the audio
        audio.append(("CD", t, "cd"))
        for k in (3, 2, 1):
            _text_png(f"{A}/cd{i}_{k}_t.png", top=f"#{i}  WHAT IS IT?", difficulty=diff, cd_left=k)
            _composite(f"{A}/clue{i}_b.png", f"{A}/cd{i}_{k}_t.png", f"{A}/cd{i}_{k}.png")
            _still(f"{A}/cd{i}_{k}.png", f"{A}/c{i}1_{k}.mp4", CDN); clips.append(f"{A}/c{i}1_{k}.mp4")
        t += CDN * 3
        # reveal — punchy reaction + score, kept SHORT
        _text_png(f"{A}/r{i}_t.png", answer=ep._s(it.get("answer")).upper() + "!", score=f"{i}/{len(items)}")
        _composite(f"{A}/rev{i}_b.png", f"{A}/r{i}_t.png", f"{A}/r{i}.png")
        dr = _dur(f"{A}/n_r{i}.mp3") + 0.4
        _still(f"{A}/r{i}.png", f"{A}/c{i}2_r.mp4", dr); clips.append(f"{A}/c{i}2_r.mp4")
        audio.append((f"{A}/n_r{i}.mp3", t, "narr")); audio.append(("DING", t, "ding")); caps.append((t, _dur(f"{A}/n_r{i}.mp3"), r_texts[i])); t += dr

    # OUTRO (lively animated game-show Bolt) — trimmed
    _text_png(f"{A}/out_t.png", top="HOW MANY?", answer="COMMENT YOUR SCORE")
    out_d = _dur(n_out) + 0.4
    OUTD = _motion_clip(f"{A}/outro_b.png", f"{A}/out_t.png", f"{A}/c99_out.mp4", out_d,
                        "the robot host cheers with a big thumbs up, confetti bursts, celebratory", i2v_sink=i2v_flags)
    clips.append(f"{A}/c99_out.mp4"); audio.append((n_out, t, "narr")); caps.append((t, _dur(n_out), outro_text)); t += OUTD

    # LOOP TEASER — a mystery clue for the NEXT episode (promotes the series + loops the viewer)
    try:
        sing = category[:-1] if category.endswith("s") else category
        tbg = make_silhouette_clue(f"a surprising, hard-to-guess {sing}", f"{A}/teaser.png",
                                   "1024x1536", costs, idx=len(items))
        _fit(f"{A}/teaser.png", f"{A}/teaser_b.png", "pad", bg=tbg)
        _text_png(f"{A}/teaser_t.png", top="CAN YOU GUESS THIS?", subscribe=True)
        _composite(f"{A}/teaser_b.png", f"{A}/teaser_t.png", f"{A}/teaser_c.png")
        n_teaser = f"{A}/n_teaser.mp3"
        teaser_text = "Could you guess this one? Subscribe for a new quiz every day!"
        ep.generate_tts(teaser_text, n_teaser, voice=voice)
        td = _dur(n_teaser) + 0.4
        _still(f"{A}/teaser_c.png", f"{A}/c99b_teaser.mp4", td); clips.append(f"{A}/c99b_teaser.mp4")
        audio.append((n_teaser, t, "narr")); caps.append((t, _dur(n_teaser), teaser_text)); t += td
    except Exception as e:
        log(f"teaser skipped: {e}")
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
    lst = f"{A}/list.txt"; open(lst, "w").write("".join(f"file '{c}'\n" for c in clips))
    vsil = f"{A}/video_silent.mp4"
    subprocess.run([FF, "-y", "-f", "concat", "-safe", "0", "-i", lst, "-an", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", vsil], capture_output=True)
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
    subprocess.run([FF, "-y", *ins, "-filter_complex", ";".join(parts), "-map", "[aout]", "-t", f"{TOTAL}",
                    "-c:a", "aac", "-b:a", "192k", faud], capture_output=True)

    out_mp4 = os.path.join(output_dir, "quiz.mp4")
    subprocess.run([FF, "-y", "-i", vsil, "-i", faud, "-c:v", "copy", "-c:a", "aac", "-shortest",
                    "-movflags", "+faststart", out_mp4], capture_output=True)

    # Ready-to-paste YouTube description + tags (best-effort). Runs BEFORE the cost sum so its cost is
    # counted; the app persists description_path → {job}.desc exactly like the explainer path.
    log("stage:Writing description...")
    description_path = generate_quiz_description(category, title, items, quiz.get("hook"), A, cost_sink=costs)
    if description_path:
        log("YouTube description written")
    cost = round(sum(costs), 3)
    _n_fb = i2v_flags.count(False)
    _deg = ([f"{_n_fb} of {len(i2v_flags)} hero clips (hook/outro) fell back to a static Ken-Burns still"]
            if _n_fb else [])
    if not os.path.exists(out_mp4):
        _deg = ["final video file was not produced — assembly failed"] + _deg
    log(f"Complete — quiz short assembled · ${cost}" + (f" · {_n_fb} static fallback(s)" if _n_fb else ""))
    # Shape matches run_explainer_pipeline so the app's save/index path consumes it unchanged.
    return {"output_path": out_mp4, "title": title, "category": quiz.get("category", category),
            "scene_count": len(clips), "duration_sec": round(_dur(out_mp4), 1),
            "items": [{"answer": it.get("answer"), "fact": it.get("fact")} for it in items],
            "script": quiz, "hook": ep._s(quiz.get("hook")), "video_format": "social",
            "srt_path": srt_path, "transcript_path": transcript_path,   # app copies these → {job}.srt/.txt
            "description_path": description_path,                        # app copies → {job}.desc
            "status": ("degraded" if _deg else "ok"), "degraded_reasons": _deg,
            "actual_cost": cost, "est_cost": cost}
