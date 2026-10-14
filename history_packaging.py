"""Packaging for Bolt Explains History: its own title patterns and thumbnail grammar.

The World channel's packaging (backfire_packaging) is a split frame, a red ring, an arrow and
"FATAL ERROR", with "The <X> Mistake That <Y>" titles. History films must not look like that:
the two channels share an illustrated pipeline, and a viewer who meets both should be able to
tell them apart at feed size.

  Thumbnail (v2, operator design 2026-10-14): CAUSE -> CONSEQUENCE. A torn-paper split frame:
  the state's programme at work on the left (vivid, with a period state symbol such as a
  propaganda poster), the place or people afterwards on the right (bleached), one anonymous
  person reacting large in the right foreground, a red arrow along the visible link between them,
  a stacked 2-4 word cream serif headline on a dark band lower-left with a red underline, and the
  story's year on a red wax seal in the top-right sky. It shares World's act -> consequence logic
  so the channels read as one family, but keeps History's own marks. The image model draws only
  the scene; band, contrast, arrow, headline and seal are composited here, so they are identical
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

import math

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

import backfire_packaging as _bp

VERSION = "history_packaging_v2"
CHECKLIST = "history_v2"
TITLE_MAX_CHARS = 70
TITLE_ATTEMPTS = 2
HEADLINE_WORDS = (2, 4)
CREAM = (246, 236, 214)
SEAL_RED = (150, 22, 22)
BLACK = (0, 0, 0)
ARROW_RED = (196, 30, 32)

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

# v2 (operator, 2026-10-14). The operator replaced the first History thumbnail (one full-bleed
# moment, "SEA FLED 150KM") with their own cause -> consequence design for the Aral Sea film: a
# Soviet poster over a sluice gate pouring water onto cotton, a red arrow along the diverted water
# to a ship stranded on cracked seabed, an elder grieving in the foreground, "COTTON KILLED A SEA".
# The headline rule below says what the film supports: that film ends on the northern sea saved
# by a dam, so its narration supports DRAINED, not KILLED.
_STRATEGY_SYSTEM = (
    "You are the thumbnail art director for Bolt Explains History. Every thumbnail is a SPLIT "
    "FRAME telling cause -> consequence. LEFT (the cause): the state's programme AT WORK, vivid "
    "and saturated -- what was built, ordered or enforced -- with the state that ordered it "
    "identifiable through a period symbol (a propaganda poster, a flag, an official seal on a "
    "building, a uniform), never the face of a real, named person. RIGHT (the consequence): the "
    "same place or people afterwards, bleached and stark, with ONE ordinary, invented, anonymous "
    "person LARGE in the foreground reacting (grief, shock, disbelief). A visible LINK runs from "
    "the cause toward the consequence's main object (water, a road, smoke, a railway line, a "
    "line of people) so an arrow can follow it. Use only what the transcript states. No gore, "
    "blood, corpses, injuries, text, logos or maps. Propose TWO different pairs so the better one "
    "can be chosen, and for each a 2-4 word HEADLINE in capitals that names the cause and what it "
    "did, in the narration's own verb (COTTON DRAINED A SEA) -- never stronger than the "
    "narration (not KILLED if the film says part of it survived) and never a number the "
    "transcript does not speak. Also give the single YEAR (four digits) the story turns on, as "
    "spoken in the transcript, or an empty string. Return ONLY JSON: {\"year\": \"1961\", "
    "\"pairs\": [{\"cause\": \"one sentence: the programme at work and the state symbol\", "
    "\"consequence\": \"one sentence: the place or people afterwards\", \"person\": \"3-10 "
    "words: the anonymous person in the foreground and their reaction\", \"link\": \"3-8 words: "
    "what visibly runs from cause to consequence\", \"headline\": \"2-4 WORDS\"}, {...}]}"
)
PAIR_KEYS = ("cause", "consequence", "person", "link", "headline")


def strategy(title: str, question: str, transcript: str, cost_sink: list | None = None) -> dict:
    """{"year": str, "pairs": [...]} from the narration; empty on any failure."""
    import explainer_pipeline as ep

    try:
        user = f'TITLE: "{title}"\nTOPIC: {question}\n\nTRANSCRIPT:\n{transcript[:5000]}'
        response = ep._claude().messages.create(
            model=ep.ANTHROPIC_MODEL, max_tokens=900, system=_STRATEGY_SYSTEM,
            messages=[{"role": "user", "content": user}])
        if cost_sink is not None:
            cost_sink.append(ep._msg_cost(response.usage))
        parsed, _ = ep._parse_script_json(response.content[0].text)
    except Exception:
        return {"year": "", "pairs": []}
    if not isinstance(parsed, dict):
        return {"year": "", "pairs": []}
    year = str(parsed.get("year") or "").strip()
    pairs = []
    for pair in parsed.get("pairs") or []:
        if isinstance(pair, dict) and all(str(pair.get(k) or "").strip() for k in PAIR_KEYS):
            pairs.append({k: str(pair[k]).strip() for k in PAIR_KEYS})
    return {"year": year if year_valid(year, transcript) else "", "pairs": pairs[:2]}


def image_prompt(pair: dict, illustrated: bool = True) -> str:
    medium = (
        "A hand-drawn editorial illustration in layered torn cut-paper with visible deckled edges, "
        "ink contour lines, flat gouache colour and paper grain -- unmistakably a hand-made collage "
        "drawing and never a photograph or a 3D render -- used as a YouTube thumbnail background, "
        if illustrated else
        "A cinematic, photoreal historical reconstruction used as a YouTube thumbnail background, ")
    look = ("Strong contrast between the saturated left and the bleached right, bold readable "
            "cut-paper shapes, designed to read instantly on a small mobile screen. "
            if illustrated else
            "Strong contrast between the saturated left and the bleached right, dramatic period "
            "lighting, designed to read instantly on a small mobile screen. ")
    return (
        medium +
        "split into two halves by a ragged torn-paper diagonal edge running from top-centre to "
        "bottom-centre-right. "
        f"LEFT HALF (the cause, VIVID and SATURATED): {pair['cause']} Keep the LOWER-LEFT "
        "QUARTER dark and simple (shadowed ground, deep shade) with no faces or important detail, "
        "because a headline will be placed there. "
        f"RIGHT HALF (the consequence, BLEACHED and STARK): {pair['consequence']} In the near "
        f"foreground, {pair['person']}: head and shoulders LARGE in the lower right, face turned "
        "three-quarters to the camera, the reaction readable at thumbnail size. "
        f"{pair['link']} runs from the left centre toward the consequence's main object in the "
        "right centre. Keep the TOP-RIGHT corner simple (sky or a plain wall). "
        + look +
        "Costume, architecture and objects are accurate to the era and place. Absolutely NO text, "
        "letters, numbers, dates, words, logos, arrows, circles, borders, seals, stamps or "
        "watermarks anywhere (a state symbol on a poster or flag is the only symbol). No gore, "
        "blood, corpses or injuries. Every person is anonymous and invented, never a real or "
        "named individual."
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
        # The torn edge the image prompt asks for, top-centre to bottom-centre-right.
        "split": ((int(tw * 0.53) + 40, 0), (int(tw * 0.53) + 90, th)),
        "band_box": (0, int(th * 0.30), int(tw * 0.62), th),
        "headline_box": (int(tw * 0.035), int(th * 0.40), int(tw * 0.50), int(th * 0.96)),
        # Cause -> consequence, along the link the prompt asks for.
        "arrow": ((int(tw * 0.367), int(th * 0.417)), (int(tw * 0.477), int(th * 0.236)),
                  (int(tw * 0.602), int(th * 0.340))),
        "arrow_width": max(8, int(th * 0.036)),
        # In the sky: lower right sat on the reacting face (Aral Sea, 2026-10-14).
        "seal_center": (int(tw * 0.905), int(th * 0.165)),
        "seal_radius": int(th * 0.115),
    }


_SHORT_WORDS = {"a", "an", "of", "to", "in", "on", "at", "by", "the"}


def stack_headline(headline: str) -> list[str]:
    """Up to three lines, a short word riding with the word after it: COTTON / DRAINED / A SEA."""
    words = (headline or "").upper().split()
    lines, carry = [], ""
    for word in words:
        if word.lower() in _SHORT_WORDS and carry == "":
            carry = word
            continue
        lines.append(f"{carry} {word}".strip())
        carry = ""
    if carry:
        lines.append(carry)
    while len(lines) > 3:
        lines[-2:] = [f"{lines[-2]} {lines[-1]}"]
    return lines


def _bezier(p0, p1, p2, steps=60):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1])
            for t in (i / steps for i in range(steps + 1))]


def compose(bg_path: str, out_path: str, headline: str, year: str = "",
            tw: int = 1280, th: int = 720) -> str:
    geo = geometry(tw, th)
    scene = ImageOps.fit(Image.open(bg_path).convert("RGB"), (tw, th))

    # Contrast: the cause vivid, the consequence bleached, blended across the torn edge.
    vivid = ImageEnhance.Color(ImageEnhance.Contrast(scene).enhance(1.12)).enhance(1.22)
    bleached = ImageEnhance.Brightness(ImageEnhance.Color(
        ImageEnhance.Contrast(scene).enhance(1.10)).enhance(0.82)).enhance(1.04)
    (sx0, _), (sx1, _) = geo["split"]
    mask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(mask).polygon([(0, 0), (sx0, 0), (sx1, th), (0, th)], fill=255)
    base = Image.composite(vivid, bleached, mask.filter(ImageFilter.GaussianBlur(18))).convert("RGBA")

    # Band: darkness rising from the lower left, fading up and to the right.
    bx0, by0, bx1, _ = geo["band_box"]
    band = Image.new("L", (tw, th), 0)
    bd = ImageDraw.Draw(band)
    for x in range(0, bx1, 2):
        across = max(0.0, min(1.0, 1 - (x / tw - 0.30) / 0.30))
        for y0 in range(by0, th, 4):
            v = max(0.0, min(1.0, (y0 / th - 0.30) / 0.45)) * across
            bd.rectangle([x, y0, x + 1, y0 + 3], fill=int(225 * v))
    zero = Image.new("L", (tw, th), 0)
    base.alpha_composite(Image.merge("RGBA", (zero, zero, zero, band.filter(ImageFilter.GaussianBlur(6)))))

    # Arrow: red, black-edged, along the link from cause to consequence.
    p0, p1, p2 = geo["arrow"]
    path = _bezier(p0, p1, p2)
    aw = geo["arrow_width"]
    (ex, ey), (px, py) = path[-1], path[-5]
    ang = math.atan2(ey - py, ex - px)
    head = aw * 2.6
    tip = (ex + math.cos(ang) * head * 0.9, ey + math.sin(ang) * head * 0.9)
    left = (ex + math.cos(ang + 2.5) * head, ey + math.sin(ang + 2.5) * head)
    right = (ex + math.cos(ang - 2.5) * head, ey + math.sin(ang - 2.5) * head)

    def arrow(d, colour, extra):
        d.line(path[:-4], fill=colour, width=aw + extra, joint="curve")
        d.polygon([tip, left, right], fill=colour)

    shadow = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    arrow(ImageDraw.Draw(shadow), (0, 0, 0, 170), 14)
    base.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))
    arrow(ImageDraw.Draw(base), (*BLACK, 255), 10)
    arrow(ImageDraw.Draw(base), (*ARROW_RED, 255), 0)

    # Headline: stacked cream serif capitals on the band, heavy black edge, red underline under
    # the verb line.
    hx0, hy0, hx1, hy1 = geo["headline_box"]
    lines = stack_headline(headline)
    draw = ImageDraw.Draw(base)
    size = int(th * 0.21)
    while size > 18:
        font = _font(size)
        if (max(draw.textlength(line, font=font) for line in lines) <= hx1 - hx0
                and int(size * 0.98) * len(lines) <= hy1 - hy0):
            break
        size -= 4
    line_h = int(size * 0.98)
    stroke = max(3, int(size * 0.06))
    y = hy1 - line_h * len(lines)
    glow = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for i, line in enumerate(lines):
        gd.text((hx0 + 6, y + i * line_h + 8), line, font=font, fill=(0, 0, 0, 210),
                stroke_width=stroke + 3, stroke_fill=(0, 0, 0, 210))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(5)))
    draw = ImageDraw.Draw(base)
    underline = len(lines) - 2 if len(lines) >= 2 else -1
    for i, line in enumerate(lines):
        draw.text((hx0, y + i * line_h), line, font=font, fill=(*CREAM, 255),
                  stroke_width=stroke, stroke_fill=(*BLACK, 255))
        if i == underline:
            uy = y + (i + 1) * line_h - int(size * 0.06)
            width = int(draw.textlength(line, font=font))
            draw.rounded_rectangle([hx0 - 4, uy - 6, hx0 + width + 30, uy + 9], radius=6,
                                   fill=(*ARROW_RED, 255), outline=(*BLACK, 255), width=3)

    # Seal: a red wax disc with a pale inner ring and the year, in the top-right sky.
    if year:
        cx, cy = geo["seal_center"]
        r = geo["seal_radius"]
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse([cx - r + 6, cy - r + 8, cx + r + 6, cy + r + 8], fill=(0, 0, 0, 160))
        base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(6)))
        d = ImageDraw.Draw(base)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*SEAL_RED, 255), outline=(*BLACK, 255), width=3)
        inner = int(r * 0.80)
        d.ellipse([cx - inner, cy - inner, cx + inner, cy + inner],
                  outline=(*CREAM, 220), width=max(2, int(r * 0.05)))
        ysize = int(r * 0.72)
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
    "MOBILE click-through. Every thumbnail uses one grammar: a SPLIT FRAME, cause -> consequence: "
    "the state's programme at work on the left (vivid, a period state symbol), the place or people "
    "afterwards on the right (bleached) with one person reacting in the foreground, a red arrow "
    "between them, a stacked 2-4 word headline on a dark band lower-left, and a red wax seal with "
    "a year in the top right. A title is given alongside. Grade each item strictly true/false:\n"
    "1. one_second: understandable in ONE second at tiny (~160px) mobile size?\n"
    "2. cause_identifiable: does the left show WHAT the state did, with who ordered it clear from "
    "a period symbol, and no real person's face?\n"
    "3. consequence_identifiable: does the right show what the place or people became?\n"
    "4. link_reads: does the arrow run from the cause to the consequence's main object?\n"
    "5. reaction_readable: does one person's reaction read at mobile size, with neither the "
    "headline nor the seal covering the face?\n"
    "6. headline_legible: is the headline 2-4 words, readable at mobile size, on the dark band?\n"
    "7. medium_matches: is the artwork in the EXPECTED MEDIUM stated after this list, clean "
    "throughout, NOT a muddy mix of photo and drawing or AI-generic noise?\n"
    "8. clean_frame: is there NO stray text, garbled lettering, extra seal, border or watermark "
    "drawn into the artwork itself (a state symbol on a poster or flag is allowed)?\n"
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
    """Render one composed thumbnail per proposed pair and keep the fewest-fails by the grader.

    `plan` overrides the model's strategy ({"year": ..., "pairs": [...]}) for an operator redo.
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
    pairs = [p for p in plan.get("pairs") or []
             if all(str(p.get(k) or "").strip() for k in PAIR_KEYS)
             and headline_valid(p.get("headline", ""), transcript)]
    if not pairs:
        pairs = [{"cause": f"the government programme at the centre of {question}, at work",
                  "consequence": "the place and the people it changed, afterwards",
                  "person": "an anonymous local person in shock",
                  "link": "the road between them", "headline": "WHAT IT COST"}]
    limit = max(1, min(2, int(os.environ.get("THUMB_VARIANTS", "2") or 2)))
    out = os.path.join(out_dir, "thumbnail.jpg")
    best_path, best_grade, fell = None, None, False
    rendered = []
    for index, pair in enumerate(pairs[:limit]):
        bg = os.path.join(out_dir, f"_thumb_history_bg_{index}.jpg")
        vpath = os.path.join(out_dir, f"_thumb_history_{index}.jpg")
        try:
            ep.generate_image(image_prompt(pair, illustrated), bg, cost_sink=cost_sink, size="1536x1024")
        except ep.ContentBlocked:
            try:
                ep.generate_image(image_prompt(pair, illustrated) + " SAFE REDRAW: calm, symbolic, "
                                  "non-graphic.", bg, cost_sink=cost_sink, size="1536x1024")
            except Exception:
                ep.make_fallback_frame(bg, "", w=1280, h=720)
                fell = True
        except Exception:
            ep.make_fallback_frame(bg, "", w=1280, h=720)
            fell = True
        compose(bg, vpath, pair["headline"], year)
        grade = ep.grade_thumbnail(vpath, title, cost_sink=cost_sink, **grade_kwargs)
        rendered.append({"pair": pair, "path": vpath, "fails": (grade or {}).get("fails"),
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
        "version": VERSION, "grammar": "history_cause_consequence", "year": year,
        "pairs": [{**item["pair"], "fails": item["fails"], "items": item["items"],
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
