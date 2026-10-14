"""Packaging for Bolt Explains History: its own title patterns and thumbnail grammar.

The World channel's packaging (backfire_packaging) is a split frame, a red ring, an arrow and
"FATAL ERROR", with "The <X> Mistake That <Y>" titles. History films must not look like that:
the two channels share an illustrated pipeline, and a viewer who meets both should be able to
tell them apart at feed size.

  Thumbnail: ONE full-bleed scene, the single most charged human moment of the story, in the
  film's own medium. The left third darkens into a band that carries a 2-4 word serif headline in
  cream capitals, and the story's year sits on a red wax-seal stamp in the lower right. The image
  model draws only the scene; band, headline and seal are composited here so they are identical
  from film to film and the text can never be garbled.
  Title: "How <...>", "Why <...>" or "The <...> That <...>", at most 70 characters, never the
  word "Mistake" (World's brand), no colon, question mark or quotes. Every number in the title,
  the headline and the seal must be spoken in the narration -- the same rule the World packaging
  applies, for the same reason: the source gates checked the narration, not the packaging.

Selected by PACKAGING_STYLE=history (scripts/run_illustrated_local.py --packaging history),
whatever story engine the planner chose: a Salem film is a mistaken verdict, a Gunpowder Plot
film an almost-happened plan, and both belong to this channel's look.
"""
from __future__ import annotations

import inspect
import os
import re
import shutil

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

import backfire_packaging as _bp

VERSION = "history_packaging_v1"
CHECKLIST = "history_v1"
TITLE_MAX_CHARS = 70
TITLE_ATTEMPTS = 2
HEADLINE_WORDS = (2, 4)
CREAM = (246, 236, 214)
SEAL_RED = (150, 22, 22)
BLACK = (0, 0, 0)

_SERIF_FONTS = (
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
)

_TITLE_RE = re.compile(r"^(How|Why|The) .+$")
_YEAR_RE = re.compile(r"^(1[0-9]{3}|20[0-2][0-9])$")


def style() -> str:
    return (os.environ.get("PACKAGING_STYLE", "") or "").strip().lower()


def applies(video_format: str = "landscape") -> bool:
    return style() == "history" and (video_format or "landscape") == "landscape"


def title_valid(candidate: str, transcript: str) -> bool:
    text = (candidate or "").strip()
    if not text or len(text) > TITLE_MAX_CHARS or not _TITLE_RE.match(text):
        return False
    if text.startswith("The ") and " That " not in text:
        return False
    if any(ch in text for ch in ':?"“”\n') or re.search(r"\b(mistake|fatal)\b", text, re.I):
        return False
    return _bp.numbers_supported(text, transcript or "")


def headline_valid(headline: str, transcript: str) -> bool:
    words = (headline or "").split()
    if not HEADLINE_WORDS[0] <= len(words) <= HEADLINE_WORDS[1]:
        return False
    if any(ch in headline for ch in ':"“”\n') or re.search(r"\b(mistake|fatal)\b", headline, re.I):
        return False
    return _bp.numbers_supported(headline, transcript or "")


def year_valid(year: str, transcript: str) -> bool:
    return bool(_YEAR_RE.match((year or "").strip())) and year.strip() in _bp.spoken_numbers(transcript or "")


_TITLE_SYSTEM = (
    "You title films for Bolt Explains History, a channel of sourced, illustrated history stories. "
    "Write ONE title in one of three patterns: 'How <specific thing> <happened>', 'Why <specific "
    "people or place> <did something surprising>', or 'The <specific object, place or group> That "
    "<consequence>'. Lead with the most concrete, human-scale detail the narration gives (a "
    "letter, a village, a tank, a vote), then the large outcome. At most 70 characters. No colon, "
    "question mark or quotation marks. Never the words 'Mistake' or 'Fatal'. Every number must be "
    "spoken in the transcript; drop a number rather than invent one. Return ONLY JSON: "
    "{\"title\": \"...\"}"
)


def propose_title(title: str, question: str, transcript: str, cost_sink: list | None = None,
                  log=lambda message: None) -> str | None:
    """One or two model calls; None keeps the film's existing title."""
    import explainer_pipeline as ep

    if title_valid(title, transcript):
        return title.strip()
    feedback = ""
    for _ in range(TITLE_ATTEMPTS):
        user = (f'CURRENT TITLE: "{title}"\nTOPIC: {question}\n{feedback}'
                f"\nTRANSCRIPT (the only source of numbers and claims):\n{transcript[:6000]}")
        try:
            response = ep._claude().messages.create(
                model=ep.ANTHROPIC_MODEL, max_tokens=200, system=_TITLE_SYSTEM,
                messages=[{"role": "user", "content": user}])
            if cost_sink is not None:
                cost_sink.append(ep._msg_cost(response.usage))
            parsed, _ = ep._parse_script_json(response.content[0].text)
        except Exception as exc:  # packaging must never stop a finished film
            log(f"History title: provider call failed ({type(exc).__name__})")
            return None
        candidate = str((parsed or {}).get("title") or "").strip() if isinstance(parsed, dict) else ""
        if title_valid(candidate, transcript):
            return candidate
        unsupported = sorted(_bp.spoken_numbers(candidate) - _bp.spoken_numbers(transcript or ""))
        feedback = (f'REJECTED: "{candidate}". ' + (
            f"These numbers are not spoken in the transcript: {', '.join(unsupported)}. "
            if unsupported else "It did not follow a pattern, used a banned word or exceeded 70 "
                                "characters. ")
            + "Return a corrected title.\n")
        log(f"History title rejected: {candidate!r}")
    return None


# ── Thumbnail strategy and scene prompt ───────────────────────────────────────

_STRATEGY_SYSTEM = (
    "You are the thumbnail art director for Bolt Explains History. Each thumbnail is ONE "
    "full-bleed scene: the single most charged human moment of the story, frozen at its peak "
    "(an accusation in a crowded meeting house, a lantern finding barrels in a cellar, a wall of "
    "molasses breaking over a street). Exactly one person dominates, large in the right two-thirds "
    "of the frame, with a readable reaction (fear, defiance, shock); the setting and costume make "
    "the era and place unmistakable. The left third is quieter, darker background, because a "
    "headline will sit there. The person may be a documented figure only doing what sources "
    "record, or an invented, anonymous bystander. No gore, blood, corpses, injuries, text, "
    "logos, maps, flags or symbols. Propose TWO different moments so the better one can be "
    "chosen, and for each a 2-4 word HEADLINE in capitals that adds what the picture cannot say "
    "(a stake, a twist, a count) without repeating the title, using only facts and numbers "
    "spoken in the transcript. Also give the single YEAR (four digits) the story turns on, as "
    "spoken in the transcript, or an empty string. Return ONLY JSON: "
    "{\"year\": \"1692\", \"moments\": [{\"scene\": \"one sentence: the moment, the dominant "
    "person and their reaction, the setting\", \"subject\": \"3-6 words, the dominant person\", "
    "\"headline\": \"2-4 WORDS\"}, {...}]}"
)


def strategy(title: str, question: str, transcript: str, cost_sink: list | None = None) -> dict:
    """{"year": str, "moments": [...]} from the narration; empty on any failure."""
    import explainer_pipeline as ep

    try:
        user = f'TITLE: "{title}"\nTOPIC: {question}\n\nTRANSCRIPT:\n{transcript[:5000]}'
        response = ep._claude().messages.create(
            model=ep.ANTHROPIC_MODEL, max_tokens=700, system=_STRATEGY_SYSTEM,
            messages=[{"role": "user", "content": user}])
        if cost_sink is not None:
            cost_sink.append(ep._msg_cost(response.usage))
        parsed, _ = ep._parse_script_json(response.content[0].text)
    except Exception:
        return {"year": "", "moments": []}
    if not isinstance(parsed, dict):
        return {"year": "", "moments": []}
    year = str(parsed.get("year") or "").strip()
    moments = []
    for moment in parsed.get("moments") or []:
        if isinstance(moment, dict) and all(str(moment.get(k) or "").strip()
                                            for k in ("scene", "subject", "headline")):
            moments.append({k: str(moment[k]).strip() for k in ("scene", "subject", "headline")})
    return {"year": year if year_valid(year, transcript) else "", "moments": moments[:2]}


def image_prompt(moment: dict, illustrated: bool = True) -> str:
    medium = (
        "A hand-drawn editorial illustration in layered torn cut-paper with visible deckled edges, "
        "ink contour lines, flat gouache colour and paper grain -- unmistakably a hand-made collage "
        "drawing and never a photograph or a 3D render -- used as a YouTube thumbnail. "
        if illustrated else
        "A cinematic, photoreal historical reconstruction used as a YouTube thumbnail. ")
    look = ("Flat gouache colour, high contrast, strong figure/ground separation, bold readable "
            "cut-paper shapes, designed to read instantly on a small mobile screen. "
            if illustrated else
            "Dramatic period lighting, high contrast, designed to read instantly on a small mobile "
            "screen. ")
    return (
        medium +
        f"ONE full-bleed scene: {moment['scene']} {moment['subject']} is LARGE in the right "
        "two-thirds of the frame, head and shoulders or waist-up, face turned toward the camera "
        "enough that the reaction reads at thumbnail size. Costume, architecture and objects are "
        "accurate to the era and place. The LEFT THIRD of the frame is darker and quieter (shadowed "
        "wall, night sky, deep interior) with no faces or important detail, because text will be "
        "placed there afterwards. Keep the lower-right corner simple. " + look +
        "Absolutely NO text, letters, numbers, dates, logos, borders, frames, seals, stamps or "
        "watermarks anywhere in the image. No gore, blood, corpses or injuries."
    )


# ── Composition ───────────────────────────────────────────────────────────────

def _font(size: int):
    for path in _SERIF_FONTS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def geometry(tw: int, th: int) -> dict:
    """Every overlay position, in pixels, derived from the frame so tests and the renderer agree."""
    return {
        "band_right": int(tw * 0.40),
        "headline_box": (int(tw * 0.035), int(th * 0.10), int(tw * 0.38), int(th * 0.90)),
        "seal_center": (int(tw * 0.885), int(th * 0.80)),
        "seal_radius": int(th * 0.115),
    }


def _wrap(words: list[str], font, draw, max_w: int) -> list[str]:
    lines, line = [], ""
    for word in words:
        trial = (line + " " + word).strip()
        if line and draw.textlength(trial, font=font) > max_w:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def compose(bg_path: str, out_path: str, headline: str, year: str = "",
            tw: int = 1280, th: int = 720) -> str:
    geo = geometry(tw, th)
    base = ImageOps.fit(Image.open(bg_path).convert("RGB"), (tw, th)).convert("RGBA")

    # Band: the left third darkens to near-black, fading out to the right so the scene stays whole.
    band = Image.new("L", (tw, th), 0)
    bd = ImageDraw.Draw(band)
    right = geo["band_right"]
    for x in range(right + int(tw * 0.12)):
        alpha = 215 if x <= right else int(215 * (1 - (x - right) / (tw * 0.12)))
        bd.line([(x, 0), (x, th)], fill=max(0, alpha))
    base.alpha_composite(Image.composite(Image.new("RGBA", (tw, th), (*BLACK, 255)),
                                         Image.new("RGBA", (tw, th), (0, 0, 0, 0)), band))

    # Headline: cream serif capitals, as large as the band allows, stacked one to three lines.
    bx0, by0, bx1, by1 = geo["headline_box"]
    words = headline.upper().split()
    draw = ImageDraw.Draw(base)
    size = int(th * 0.20)
    while size > 18:
        font = _font(size)
        lines = _wrap(words, font, draw, bx1 - bx0)
        line_h = int(size * 1.08)
        widest = max(draw.textlength(line, font=font) for line in lines)
        if widest <= bx1 - bx0 and line_h * len(lines) <= by1 - by0 and len(lines) <= 3:
            break
        size -= 4
    stroke = max(2, int(size * 0.045))
    y = by0 + ((by1 - by0) - line_h * len(lines)) // 2
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for i, line in enumerate(lines):
        sd.text((bx0 + 4, y + i * line_h + 6), line, font=font, fill=(0, 0, 0, 200))
    base.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(4)))
    for i, line in enumerate(lines):
        ImageDraw.Draw(base).text((bx0, y + i * line_h), line, font=font, fill=(*CREAM, 255),
                                  stroke_width=stroke, stroke_fill=(*BLACK, 255))

    # Seal: a red wax disc with a pale inner ring and the year, lower right.
    if year:
        cx, cy = geo["seal_center"]
        r = geo["seal_radius"]
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.ellipse([cx - r + 6, cy - r + 8, cx + r + 6, cy + r + 8], fill=(0, 0, 0, 150))
        base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(6)))
        d = ImageDraw.Draw(base)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*SEAL_RED, 255))
        inner = int(r * 0.80)
        d.ellipse([cx - inner, cy - inner, cx + inner, cy + inner],
                  outline=(*CREAM, 220), width=max(2, int(r * 0.05)))
        ysize = int(r * 0.78)
        yfont = _font(ysize)
        while ysize > 10 and d.textlength(year, font=yfont) > inner * 1.6:
            ysize -= 2
            yfont = _font(ysize)
        box = d.textbbox((0, 0), year, font=yfont)
        d.text((cx - (box[2] - box[0]) / 2 - box[0], cy - (box[3] - box[1]) / 2 - box[1]), year,
               font=yfont, fill=(*CREAM, 255))
    base.convert("RGB").save(out_path, "JPEG", quality=92)
    return out_path


# ── Grading and orchestration ─────────────────────────────────────────────────

HISTORY_THUMB_GRADE_SYSTEM = (
    "You are a ruthless YouTube thumbnail critic for a history documentary channel, judging for "
    "MOBILE click-through. Every thumbnail uses one grammar: ONE full-bleed scene of the story's "
    "most charged human moment, a dark band on the left carrying a 2-4 word headline, and a red "
    "wax seal with a year in the lower right. A title is given alongside. Grade each item "
    "strictly true/false:\n"
    "1. one_second: understandable in ONE second at tiny (~160px) mobile size?\n"
    "2. single_moment: does the picture show ONE dramatic moment, not a collage, montage or "
    "split frame?\n"
    "3. reaction_readable: does one dominant person's reaction (fear, defiance, shock) read at "
    "mobile size?\n"
    "4. era_identifiable: do costume, architecture and objects make the era and place clear, "
    "with nothing anachronistic?\n"
    "5. headline_legible: is the headline 2-4 words, readable at mobile size, on a dark band "
    "that does not cover the person's face?\n"
    "6. headline_not_title_echo: does the headline add something the title does not already say?\n"
    "7. medium_matches: is the artwork in the EXPECTED MEDIUM stated after this list, clean "
    "throughout, NOT a muddy mix of photo and drawing or AI-generic noise?\n"
    "8. clean_frame: is there NO stray text, garbled lettering, extra seal, border or watermark "
    "drawn into the artwork itself?\n"
    "Return ONLY JSON: {\"items\":{\"one_second\":bool,...all 8...},\"fails\":int (count of "
    "false),\"redesign_note\":\"one sentence -- the single biggest fix\"}."
)


def thumb_grade_system(illustrated: bool) -> str:
    medium = ("a hand-drawn cut-paper illustration; item 7 is false if the artwork is a "
              "photograph or a 3D render"
              if illustrated else
              "photoreal; item 7 is false if the artwork is drawn, painted or cartoon")
    return HISTORY_THUMB_GRADE_SYSTEM + f"\nEXPECTED MEDIUM: the film this thumbnail fronts is {medium}."


def generate_thumbnail(title: str, question: str, transcript: str, out_dir: str,
                       cost_sink: list | None = None, report: dict | None = None,
                       log=lambda message: None, plan: dict | None = None,
                       illustrated: bool = True) -> str:
    """Render one composed thumbnail per proposed moment and keep the fewest-fails by the grader.

    `plan` overrides the model's strategy ({"year": ..., "moments": [...]}) for an operator redo.
    """
    import explainer_pipeline as ep

    rep = report if isinstance(report, dict) else {}
    grade_kwargs: dict = {}
    checklist = "science_v1"
    try:
        if "system" in inspect.signature(ep.grade_thumbnail).parameters:
            grade_kwargs["system"] = thumb_grade_system(illustrated)
            checklist = CHECKLIST
    except (TypeError, ValueError):
        pass
    plan = plan or strategy(title, question, transcript, cost_sink=cost_sink)
    year = plan.get("year") if year_valid(plan.get("year") or "", transcript) else ""
    moments = [m for m in plan.get("moments") or [] if headline_valid(m.get("headline", ""), transcript)]
    if not moments:
        moments = [{"scene": f"the decisive moment of {question}", "subject": "one witness",
                    "headline": "WHAT REALLY HAPPENED"}]
    limit = max(1, min(2, int(os.environ.get("THUMB_VARIANTS", "2") or 2)))
    out = os.path.join(out_dir, "thumbnail.jpg")
    best_path, best_grade, fell = None, None, False
    rendered = []
    for index, moment in enumerate(moments[:limit]):
        bg = os.path.join(out_dir, f"_thumb_history_bg_{index}.jpg")
        vpath = os.path.join(out_dir, f"_thumb_history_{index}.jpg")
        try:
            ep.generate_image(image_prompt(moment, illustrated), bg, cost_sink=cost_sink, size="1536x1024")
        except ep.ContentBlocked:
            try:
                ep.generate_image(image_prompt(moment, illustrated) + " SAFE REDRAW: calm, symbolic, "
                                  "non-graphic.", bg, cost_sink=cost_sink, size="1536x1024")
            except Exception:
                ep.make_fallback_frame(bg, "", w=1280, h=720)
                fell = True
        except Exception:
            ep.make_fallback_frame(bg, "", w=1280, h=720)
            fell = True
        compose(bg, vpath, moment["headline"], year)
        grade = ep.grade_thumbnail(vpath, title, cost_sink=cost_sink, **grade_kwargs)
        rendered.append({"moment": moment, "path": vpath, "fails": (grade or {}).get("fails"),
                         "items": (grade or {}).get("items"),
                         "redesign_note": (grade or {}).get("redesign_note")})
        if best_grade is None or (grade or {}).get("fails", 99) < best_grade.get("fails", 99):
            best_path, best_grade = vpath, grade or {"fails": 99}
        try:
            os.remove(bg)
        except OSError:
            pass
    if best_path:
        shutil.copy(best_path, out)
    for item in rendered:
        try:
            os.remove(item["path"])
        except OSError:
            pass
    rep.update({
        "version": VERSION, "grammar": "history_single_moment", "year": year,
        "moments": [{**item["moment"], "fails": item["fails"], "items": item["items"],
                     "redesign_note": item["redesign_note"]} for item in rendered],
        "chosen": next((i for i, item in enumerate(rendered) if item["path"] == best_path), None),
        "qa": "skipped" if not best_grade or best_grade.get("fails") == 99 else "ok",
        "fails": None if not best_grade or best_grade.get("fails") == 99 else best_grade.get("fails"),
        "weak": bool(best_grade and best_grade.get("fails", 0) not in (None, 99)
                     and best_grade.get("fails", 0) >= 3),
        "fallback": fell, "variants": len(rendered), "checklist_version": checklist,
    })
    try:
        _bp.write_report(out_dir, rep)
    except OSError as exc:
        log(f"packaging.json not written ({type(exc).__name__})")
    log(f"History thumbnail: {len(rendered)} variant(s), chosen {rep['chosen']}, "
        f"fails {rep['fails']}, checklist {checklist}")
    return out
