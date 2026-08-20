"""HEALTH LISTICLE social-short pipeline — a fourth format ("N Foods That May Support X").

A proven high-demand YouTube format (competitor channels pull 100K–1M+ views): a fast hook, then a
COUNTDOWN of N everyday foods that "may support" a general-wellness goal, each with a one-line
evidence-based reason, then a recap + comment CTA. Bolt hosts on a bright kitchen/wellness set.

⚠️ HEALTH = YMYL (Your Money or Your Life) content. Two hard safety rails, both enforced here:
  1. GENERATION rail: `_HEALTH_SYSTEM` forbids disease/treatment claims, dosages, and "cures"; forces
     hedged "may support" language, whole-foods only, and a spoken + on-screen disclaimer.
  2. VERIFICATION rail: `run_health_pipeline(script=...)` takes a pre-audited script so the bench's
     adversarial safety pass (evidence / harm-contraindication / overstatement / policy lenses) is what
     actually ships. Do NOT ship a health video that skipped the verification pass.

Reuses quiz_pipeline primitives (_dur/_still/_safe_image/_composite/_fit/_motion_clip/_t/_font) +
explainer_pipeline (TTS / i2v / mascot). Best-effort throughout. Portrait 9:16.
"""
import os, json, subprocess
from PIL import Image, ImageDraw
import explainer_pipeline as ep
import quiz_pipeline as qp

FF = qp.FF
W, H, FPS = qp.W, qp.H, qp.FPS
NAVY, WHITE, CYAN, YEL, RED = qp.NAVY, qp.WHITE, qp.CYAN, qp.YEL, qp.RED
GREEN = (72, 190, 120)
_dur, _still, _safe_image, _composite, _fit, _motion_clip = (
    qp._dur, qp._still, qp._safe_image, qp._composite, qp._fit, qp._motion_clip)

STY_FOOD = (" Bright, vibrant, appetizing, high detail, professional food styling, centered on a clean "
            "solid pastel background, soft studio light, no text, no letters, no numbers.")
STY_BOLT = " Polished 3D cartoon, vibrant, high production value, vertical 9:16, no text or letters."
BOLT_REF = ("Use the attached reference image: keep Bolt the rounded matte-white robot with mint-green "
            "accents. ")
_CARD_BG = [(247, 191, 42), (255, 122, 99), (34, 199, 190), (86, 170, 240), (150, 205, 80), (176, 148, 236)]

_HEALTH_SYSTEM = (
    "You are a careful, evidence-minded YouTube Shorts writer for 'Bolt', a friendly robot who explains "
    "the world. Write a '{n} Foods That May Support {TOPIC}' listicle for a GENERAL WELLNESS goal.\n"
    "\n=== HARD SAFETY RULES (a violation makes the video unpublishable) ===\n"
    "1. HEDGE ALWAYS: say foods 'may support' / 'may help' a general function. NEVER claim any food "
    "cures, treats, reverses, prevents, or 'fixes' a disease or symptom. No diagnoses. No 'instead of "
    "medication'. No dosages, grams, or 'eat X times a day'. No promises of results.\n"
    "2. GENERAL WELLNESS ONLY: frame around an everyday function (focus, energy, sleep, hydration, skin "
    "glow, digestion comfort) — NOT a medical condition, organ disease, or diagnosis.\n"
    "3. REAL MECHANISM: each food must have a genuine, mainstream nutrition-science basis — name the "
    "actual nutrient/compound and the plausible general mechanism (e.g. 'omega-3 fats', 'nitrates', "
    "'magnesium', 'flavonoids', 'fiber'). NO pseudoscience (no 'detox', 'cleanse', 'boosts immunity', "
    "'alkalizing', 'fights parasites').\n"
    "4. WHOLE, COMMON, SAFE FOODS: everyday whole foods a general adult audience can eat. Do NOT feature "
    "supplements, extracts, alcohol, high-caffeine items, grapefruit, or anything with well-known drug "
    "interactions as a star item. If a food is a common allergen (nuts, fish), that's fine — just make "
    "no medical claim.\n"
    "5. DISCLAIMER: write a short spoken 'disclaimer' line ('This is general info, not medical advice — "
    "talk to your doctor about what's right for you.').\n"
    "\n=== FORMAT ===\n"
    "Order the foods as a COUNTDOWN from #{n} down to #1, with #1 the most compelling/surprising (best "
    "last, to hold the viewer). Hook = ONE tight, curiosity-gap spoken line that flows into food #{n} "
    "and names the goal. Each 'benefit' is a SHORT hedged spoken reason (<= 12 words). Each 'caption' is "
    "a punchy <= 5-word on-screen version of the benefit. 'recap' = one line naming the goal again; "
    "'cta' = one comment-bait line ('Which will you try? Comment below.').\n"
    "Return ONLY JSON: {\"title\":\"5 Foods That May Support Focus\",\"topic_label\":\"MAY SUPPORT "
    "FOCUS\",\"hook\":\"...\",\"disclaimer\":\"...\",\"recap\":\"...\",\"cta\":\"...\",\"items\":["
    "{\"rank\":5,\"food\":\"Walnuts\",\"nutrient\":\"omega-3 fats\",\"benefit\":\"spoken hedged reason "
    "<=12 words\",\"caption\":\"<=5 word on-screen line\",\"image_visual\":\"a small pile of shelled "
    "walnut halves\"}]}. List items in countdown order (rank {n} first ... rank 1 last)."
)


def generate_health_listicle(topic: str, n: int = 5, cost_sink=None) -> dict:
    """LLM health-listicle for `topic` (general wellness). Best-effort ({} on failure). NOTE: the output
    MUST still go through the adversarial safety verification before rendering."""
    try:
        sys = _HEALTH_SYSTEM.replace("{n}", str(n)).replace("{TOPIC}", topic)
        r = ep._claude().messages.create(
            model="claude-opus-4-8", max_tokens=2200, system=sys,
            messages=[{"role": "user", "content": f"Goal/topic: {topic}. Make exactly {n} foods. Return JSON."}])
        if cost_sink is not None:
            cost_sink.append(ep._msg_cost(r.usage))
        q, _ = ep._parse_script_json(r.content[0].text)
        items = [it for it in (q.get("items") or []) if isinstance(it, dict)
                 and ep._s(it.get("food")).strip() and ep._s(it.get("benefit")).strip()][:n]
        if not items:
            return {}
        q["items"] = items
        return q
    except Exception as e:
        print(f"[health] generation failed: {e}")
        return {}


# ── overlays ────────────────────────────────────────────────────────────────────
def _wrap(draw, text, font, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def _pill(d, box, fill, radius=30):
    d.rounded_rectangle(box, radius=radius, fill=fill)


def _hook_overlay(path, title, sub):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    lines = _wrap(d, title.upper(), qp._font(104), W - 150)
    y = 210
    for ln in lines:
        qp._t(d, (W // 2, y), ln, 104, YEL, stroke=10); y += 120
    _pill(d, [70, y + 10, W - 70, y + 130], (*NAVY, 235))
    qp._t(d, (W // 2, y + 70), sub.upper(), 58, WHITE, stroke=6)
    im.save(path)


def _food_overlay(path, rank, n, topic_label, food, caption):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    # top: topic label
    lbl = topic_label.upper()
    lw = int(qp._font(52).getlength(lbl)) + 80
    _pill(d, [W // 2 - lw // 2, 70, W // 2 + lw // 2, 168], (*NAVY, 235), radius=28)
    qp._t(d, (W // 2, 119), lbl, 52, WHITE, stroke=5)
    # rank badge (big circle top-left)
    d.ellipse([60, 196, 250, 386], fill=(*GREEN, 255), outline=(*WHITE, 255), width=8)
    qp._t(d, (155, 291), f"#{rank}", 96, WHITE, stroke=8)
    # bottom cluster: food name + caption
    fl = _wrap(d, food.upper(), qp._font(112), W - 130)
    cl = _wrap(d, caption, qp._font(64), W - 170)
    block_h = 40 + len(fl) * 128 + 24 + len(cl) * 78 + 40
    y0 = H - 300 - block_h
    _pill(d, [40, y0, W - 40, H - 250], (*NAVY, 232), radius=40)
    y = y0 + 60
    for ln in fl:
        qp._t(d, (W // 2, y), ln, 112, YEL, stroke=9); y += 128
    y += 14
    for ln in cl:
        qp._t(d, (W // 2, y), ln, 64, CYAN, stroke=6); y += 78
    # PERSISTENT compliance footer on every food card (YMYL: the disclaimer must actually reach the viewer)
    qp._t(d, (W // 2, H - 150), "GENERAL INFO · NOT MEDICAL ADVICE", 34, (232, 232, 232), stroke=4, sc=(0, 0, 0))
    im.save(path)


def _outro_overlay(path, recap, cta, disclaimer):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    y = 230
    for ln in _wrap(d, recap.upper(), qp._font(92), W - 150):
        qp._t(d, (W // 2, y), ln, 92, YEL, stroke=9); y += 108
    y += 30
    for ln in _wrap(d, cta.upper(), qp._font(70), W - 160):
        qp._t(d, (W // 2, y), ln, 70, WHITE, stroke=7); y += 84
    # disclaimer band pinned near the bottom
    dl = _wrap(d, disclaimer, qp._font(42), W - 150)
    band_h = 40 + len(dl) * 54 + 30
    _pill(d, [50, H - 250 - band_h, W - 50, H - 250], (*RED, 210), radius=28)
    yy = H - 250 - band_h + 46
    for ln in dl:
        qp._t(d, (W // 2, yy), ln, 42, WHITE, stroke=3); yy += 54
    im.save(path)


# ── description ───────────────────────────────────────────────────────────────────
def generate_health_description(topic, title, items, out_dir, disclaimer, cost_sink=None) -> str:
    """Ready-to-paste YouTube description with hedged framing + a NOT-MEDICAL-ADVICE disclaimer + the
    AI-synthetic disclosure. Best-effort; returns path or ''."""
    try:
        foods = ", ".join(ep._s(it.get("food")) for it in items)
        body = (f"{ep._s(title)}.\n\n"
                f"We're counting down {len(items)} everyday foods that may help support {topic.lower()} — "
                f"and the simple nutrients behind each one. This is general wellness info to explore, not a "
                f"prescription: {foods}. Which one will you add to your plate? Tell us in the comments.\n\n"
                "⚠️ " + ep._s(disclaimer or "This video is general information, not medical advice. "
                "Talk to a qualified healthcare professional about what's right for you."))
        t = topic.lower().replace(" ", "")
        hashtags = [f"#{t}", "#healthyeating", "#nutrition", "#wellness", "#foodie", "#healthyfood"]
        tags = [f"foods for {topic.lower()}", f"{topic.lower()} foods", f"best foods for {topic.lower()}",
                f"foods that support {topic.lower()}", f"natural {topic.lower()} support",
                *[ep._s(it.get("food")).lower() for it in items],
                "healthy foods", "nutrition tips", "wellness shorts", "healthy eating", "health shorts"]
        parts = [body, " ".join(hashtags), "Tags: " + ", ".join(tags[:18]), ep._DESC_DISCLOSURE]
        path = os.path.join(out_dir, "description.txt")
        with open(path, "w") as f:
            f.write("\n\n".join(parts) + "\n")
        return path
    except Exception as e:
        print(f"[health] description skipped: {e}")
        return ""


# ── render ──────────────────────────────────────────────────────────────────────
def run_health_pipeline(topic: str, output_dir: str, n: int = 5, voice: str = "echo",
                        progress_cb=None, script: dict = None) -> dict:
    """Render a '{n} Foods That May Support {topic}' short. Pass `script=` to inject a PRE-AUDITED script
    (bench pattern) — required for health so the adversarial safety pass is what ships. Returns an
    explainer-shaped dict."""
    def log(m):
        if progress_cb:
            progress_cb(m)
    os.makedirs(output_dir, exist_ok=True)
    A = output_dir; costs = []

    q = script or generate_health_listicle(topic, n, cost_sink=costs)
    if not q or not q.get("items"):
        raise RuntimeError("health listicle generation failed")
    items = q["items"][:n]
    title = ep._s(q.get("title")) or f"{n} Foods That May Support {topic}"
    topic_label = ep._s(q.get("topic_label")) or f"MAY SUPPORT {topic.upper()}"
    disclaimer = ep._s(q.get("disclaimer")) or ("This is general info, not medical advice — "
                                                "talk to your doctor about what's right for you.")
    log(f"Health listicle: \"{title}\" — {len(items)} foods")

    mascot = [ep.MASCOT_REF] if os.path.exists(ep.MASCOT_REF) else None
    log("stage:Generating images & voiceover...")
    _safe_image(BOLT_REF + "Bolt stands in a bright cheerful kitchen full of fresh colorful fruits and "
                "vegetables, presenting with one arm raised, warm and friendly." + STY_BOLT,
                f"{A}/hook_img.png", "1024x1536", costs, reference_paths=mascot)
    _safe_image(BOLT_REF + "Bolt gives a warm thumbs-up in the bright kitchen surrounded by fresh healthy "
                "food, encouraging and cheerful." + STY_BOLT, f"{A}/outro_img.png", "1024x1536", costs,
                reference_paths=mascot)
    _fit(f"{A}/hook_img.png", f"{A}/hook_b.png", "fit"); _fit(f"{A}/outro_img.png", f"{A}/outro_b.png", "fit")

    # narration (exact text kept → deterministic .srt). SHORT spoken disclaimer keeps the outro punchy;
    # the FULL written disclaimer (allergens + drug-interaction caveats) is shown on-screen + in the desc.
    hook_text = ep._s(q.get("hook")) or f"{n} everyday foods that may help support your {topic.lower()}."
    recap = ep._s(q.get("recap")) or f"{n} simple foods that may support {topic.lower()}."
    cta = ep._s(q.get("cta")) or "Which will you try? Comment below and follow for more."
    disclaimer_spoken = "Remember — this is general information, not medical advice."
    outro_text = f"{recap} {cta} {disclaimer_spoken}"
    n_hook = f"{A}/n_hook.mp3"; ep.generate_tts(hook_text, n_hook, voice=voice)
    n_out = f"{A}/n_out.mp3"; ep.generate_tts(outro_text, n_out, voice=voice)
    _NUM = ["", "one", "two", "three", "four", "five", "six", "seven", "eight"]
    for it in items:
        rk = int(it.get("rank") or 0)
        vo = f"Number {_NUM[rk] if 0 < rk < len(_NUM) else rk}: {ep._s(it.get('food'))}. {ep._s(it.get('benefit'))}"
        ep.generate_tts(vo, f"{A}/n_f{rk}.mp3", voice=voice)
        it["_vo"] = vo

    clips = []; audio = []; caps = []; t = 0.0

    # HOOK (animated Bolt in the kitchen)
    _hook_overlay(f"{A}/hook_t.png", title, "SAVE THIS FOR LATER")
    hook_d = _dur(n_hook) + 0.4
    HOOKD = _motion_clip(f"{A}/hook_b.png", f"{A}/hook_t.png", f"{A}/c00_hook.mp4", hook_d,
                         "the friendly robot gestures warmly to the fresh food, gentle motion")
    clips.append(f"{A}/c00_hook.mp4"); audio.append((n_hook, t, "narr")); caps.append((t, _dur(n_hook), hook_text)); t += HOOKD

    # FOOD CARDS (countdown)
    for idx, it in enumerate(items):
        rk = int(it.get("rank") or (len(items) - idx))
        col = _CARD_BG[idx % len(_CARD_BG)]
        img = f"{A}/f{rk}.png"
        _safe_image(ep._s(it.get("image_visual")) + STY_FOOD, img, "1024x1536", costs,
                    fallback_label=ep._s(it.get("food")))
        _fit(img, f"{A}/f{rk}_b.png", "pad", bg=col)
        _food_overlay(f"{A}/f{rk}_t.png", rk, len(items), topic_label,
                      ep._s(it.get("food")), ep._s(it.get("caption")) or ep._s(it.get("nutrient")))
        _composite(f"{A}/f{rk}_b.png", f"{A}/f{rk}_t.png", f"{A}/f{rk}_c.png")
        df = _dur(f"{A}/n_f{rk}.mp3") + 0.5
        _still(f"{A}/f{rk}_c.png", f"{A}/c{idx+1}_f.mp4", df); clips.append(f"{A}/c{idx+1}_f.mp4")
        audio.append((f"{A}/n_f{rk}.mp3", t, "narr")); audio.append(("POP", t, "pop"))
        caps.append((t, _dur(f"{A}/n_f{rk}.mp3"), it["_vo"])); t += df

    # OUTRO (animated Bolt) with a persistent disclaimer band
    _outro_overlay(f"{A}/out_t.png", recap, cta, disclaimer)
    out_d = _dur(n_out) + 0.5
    OUTD = _motion_clip(f"{A}/outro_b.png", f"{A}/out_t.png", f"{A}/c99_out.mp4", out_d,
                        "the friendly robot gives a warm thumbs up in the bright kitchen, gentle motion")
    clips.append(f"{A}/c99_out.mp4"); audio.append((n_out, t, "narr")); caps.append((t, _dur(n_out), outro_text)); t += OUTD
    TOTAL = t

    # captions (.srt) + transcript — deterministic from the narration timeline
    def _srt_ts(s):
        s = max(0.0, s); h = int(s // 3600); m = int((s % 3600) // 60); sec = int(s % 60)
        ms = int(round((s - int(s)) * 1000))
        if ms == 1000: sec += 1; ms = 0
        return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
    srt_path = f"{A}/captions.srt"; transcript_path = f"{A}/transcript.txt"
    try:
        cs = sorted(caps, key=lambda c: c[0])
        with open(srt_path, "w") as fsrt:
            for k, (st, du, txt) in enumerate(cs, 1):
                fsrt.write(f"{k}\n{_srt_ts(st)} --> {_srt_ts(st + max(0.7, du))}\n{txt.strip()}\n\n")
        with open(transcript_path, "w") as ftx:
            ftx.write(" ".join(c[2].strip() for c in cs) + "\n")
    except Exception as e:
        log(f"caption write skipped: {e}"); srt_path = transcript_path = None

    log("stage:Assembling final video...")
    # absolute paths so ffmpeg's concat demuxer resolves them regardless of the list file's location
    # (relative paths are resolved relative to list.txt's dir → path-doubling if output_dir is relative)
    lst = f"{A}/list.txt"; open(lst, "w").write("".join(f"file '{os.path.abspath(c)}'\n" for c in clips))
    vsil = f"{A}/video_silent.mp4"
    subprocess.run([FF, "-y", "-f", "concat", "-safe", "0", "-i", lst, "-an", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", vsil],
                   capture_output=True)
    # soft "pop" on each food reveal (gentle, not a game buzzer)
    pop = f"{A}/pop.wav"
    subprocess.run([FF, "-y", "-filter_complex", "sine=520:d=0.12,volume=0.9,afade=t=out:st=0.05:d=0.07[o]",
                    "-map", "[o]", pop], capture_output=True)
    ins = []; parts = []; i = 0
    for f, off, kind in audio:
        src = pop if kind == "pop" else f
        ins += ["-i", src]; ms = int(off * 1000); vol = 1.0 if kind == "narr" else 0.5
        parts.append(f"[{i}:a]adelay={ms}|{ms},volume={vol}[s{i}]"); i += 1
    music_path = qp.get_music_path("upbeat", progress_cb=log)
    mus = i; music_ok = bool(music_path)
    if music_ok:
        ins += ["-stream_loop", "-1", "-i", music_path]
        parts.append(f"[{mus}:a]atrim=0:{TOTAL},volume=0.08,afade=t=out:st={max(0,TOTAL-1.3):.2f}:d=1.3[mus]")
    mix = "".join(f"[s{k}]" for k in range(i)) + ("[mus]" if music_ok else "")
    parts.append(f"{mix}amix=inputs={i + (1 if music_ok else 0)}:normalize=0,alimiter=limit=0.95,aresample=48000[aout]")
    faud = f"{A}/full_audio.m4a"
    subprocess.run([FF, "-y", *ins, "-filter_complex", ";".join(parts), "-map", "[aout]", "-t", f"{TOTAL}",
                    "-c:a", "aac", "-b:a", "192k", faud], capture_output=True)

    out_mp4 = os.path.join(output_dir, "health.mp4")
    subprocess.run([FF, "-y", "-i", vsil, "-i", faud, "-c:v", "copy", "-c:a", "aac", "-shortest",
                    "-movflags", "+faststart", out_mp4], capture_output=True)

    log("stage:Writing description...")
    description_path = generate_health_description(topic, title, items, A, disclaimer, cost_sink=costs)
    cost = round(sum(costs), 3)
    log(f"Complete — health short assembled · ${cost}")
    return {"output_path": out_mp4, "title": title, "topic": topic, "scene_count": len(clips),
            "duration_sec": round(_dur(out_mp4), 1),
            "items": [{"food": it.get("food"), "benefit": it.get("benefit")} for it in items],
            "script": q, "hook": ep._s(q.get("hook")), "video_format": "social",
            "srt_path": srt_path, "transcript_path": transcript_path, "description_path": description_path,
            "status": "ok", "degraded_reasons": [], "actual_cost": cost, "est_cost": cost}
