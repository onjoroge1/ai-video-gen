"""Packaging for the world channel's backfire films: one title formula, one thumbnail grammar.

Reference set (operator, 2026-09-28): three published thumbnails share a grammar and their titles
share a formula.

  Thumbnail: a split frame. LEFT, the mistake in action (v2, 2026-10-09: the species being
  released, introduced or removed, e.g. a gloved hand lifting a hive screen as bees climb out)
  inside a plain red ring. RIGHT, one frightened invented person with the consequence closing in.
  A yellow curved arrow points from the ring into the consequence. A fixed two-word headline
  "FATAL ERROR" (yellow FATAL, white ERROR, heavy black stroke) sits on top.
  Title: "The <quantified object> Mistake That <consequence>" -- e.g. "The 2-Billion Bird Mistake
  That Starved a Nation", "The Rat Bounty Mistake That Created Millions More".

The image model draws only the two scenes. Ring, divider, arrow and headline are drawn here so they
are identical from film to film, and the headline can never be garbled by the model. Every number
in the title must be spoken in the narration, the same rule the nature channel applies to thumbnail
headlines: the source gates checked the narration, not the packaging.
"""
from __future__ import annotations

import inspect
import json
import math
import os
import re
import shutil

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

import nature_channel

# Both world-channel intervention shapes: "we introduced X" and "we removed X". The reference set
# has one of each (a rat bounty that bred rats; sparrows and cats removed, locusts and rabbits
# exploded). Indictment and power-reversal films are a different promise and keep the default look.
ENGINES = frozenset({"backfiring_solution", "removed_keystone"})
HEADLINE = ("FATAL", "ERROR")
YELLOW = (250, 232, 20)
RED = (255, 28, 28)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
TITLE_MAX_CHARS = 70
TITLE_ATTEMPTS = 2
VERSION = "backfire_packaging_v2"

_HEADLINE_FONTS = (
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts",
                 "LuckiestGuy-Regular.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)

_TITLE_RE = re.compile(r"^The .+ Mistake That .+$")


def enabled() -> bool:
    return (os.environ.get("BACKFIRE_PACKAGING", "1") or "").strip().lower() not in (
        "0", "false", "no", "off")


def applies(script: dict | None, video_format: str = "landscape") -> bool:
    """Only the backfire engine in landscape carries this packaging; every other film is unchanged."""
    return bool(enabled() and isinstance(script, dict) and script.get("_story_engine") in ENGINES
                and (video_format or "landscape") == "landscape")


_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
          "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
          "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
          "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
          "seventy": 70, "eighty": 80, "ninety": 90, "a": 1}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}


def spoken_numbers(text: str) -> set[str]:
    """Digits plus spelled-out numbers, including compounds ("one hundred and two" -> "102").

    The nature rule maps single words only, so "102 toads" over a narration that says "one
    hundred and two" would be refused for the wrong reason. Compounds are read left to right
    the way a narrator speaks them; each partial total is also kept, so "two thousand" still
    supports "2".
    """
    found = set(nature_channel.numbers_in(text or ""))
    words = re.findall(r"[A-Za-z]+|\d[\d,.]*", (text or "").lower())
    total = current = 0
    active = False

    def flush():
        nonlocal total, current, active
        if active:
            found.add(str(total + current))
        total = current = 0
        active = False

    for word in words:
        if word in _UNITS and not (word == "a" and not active):
            current += _UNITS[word]
            active = True
        elif word in _SCALES:
            if not active:
                current = 1
            elif current and _SCALES[word] > 100:
                found.add(str(current))  # "twenty-four million" also supports a "$24M" title
            if _SCALES[word] == 100:
                current *= 100
            else:
                total += current * _SCALES[word]
                current = 0
            active = True
        elif word == "and" and active:
            continue
        else:
            flush()
    flush()
    return found


def numbers_supported(headline: str, transcript: str) -> bool:
    return spoken_numbers(headline) <= spoken_numbers(transcript)


# ── Title ──────────────────────────────────────────────────────────────────────

_TITLE_SYSTEM = (
    "You write YouTube titles for a documentary channel about interventions that backfired. "
    "Every title uses exactly this formula: \"The <object> Mistake That <consequence>\". "
    "<object> is the concrete thing the intervention attacked, paid for, or introduced, ideally "
    "quantified with a number the narration speaks (\"2-Billion Bird\", \"$24M\", \"Rat Bounty\", "
    "\"102-Toad\"). <consequence> is the literal outcome in 3-6 plain words (\"Starved a Nation\", "
    "\"Created Millions More\", \"Poisoned Australia's Predators\"). Rules: at most 70 characters; "
    "no colon, question mark, quotation marks or emoji; every number must appear in the transcript; "
    "no claim the transcript does not make; name the real animal or thing, not a metaphor. "
    "Return ONLY JSON: {\"title\": \"...\"}"
)


def title_valid(candidate: str, transcript: str) -> bool:
    text = (candidate or "").strip()
    if not text or len(text) > TITLE_MAX_CHARS or not _TITLE_RE.match(text):
        return False
    if any(ch in text for ch in ':?"“”\n'):
        return False
    return numbers_supported(text, transcript or "")


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
            log(f"Packaging title: provider call failed ({type(exc).__name__})")
            return None
        candidate = str((parsed or {}).get("title") or "").strip() if isinstance(parsed, dict) else ""
        if title_valid(candidate, transcript):
            return candidate
        unsupported = sorted(spoken_numbers(candidate) - spoken_numbers(transcript or ""))
        feedback = (f'REJECTED: "{candidate}". ' + (
            f"These numbers are not spoken in the transcript: {', '.join(unsupported)}. "
            if unsupported else "It did not follow the formula or exceeded 70 characters. ")
            + "Return a corrected title.\n")
        log(f"Packaging title rejected: {candidate!r}")
    return None


# ── Thumbnail strategy and scene prompt ───────────────────────────────────────

# v2 (operator, 2026-10-09). The v1 left panel crossed out one animal, and on the killer bees
# film YouTube's own review read a ringed bee as a pest-control story: the ring said "kill this",
# not "this was the mistake". The right panel was a carpet of animals with no reaction in it, so
# the consequence had size but no fear. The operator's mockup fixed both: the ring circles the ACT
# (a gloved hand lifting the hive screen as the bees climb out) and the right panel is one
# frightened person with the swarm closing in.
_STRATEGY_SYSTEM = (
    "You are the thumbnail art director for a documentary channel about interventions that "
    "backfired. Each thumbnail is a split frame. LEFT: the MISTAKE IN ACTION -- the moment "
    "people released, introduced, removed or enforced the thing, with that thing visibly at work "
    "(e.g. a gloved hand lifting a hive screen as bees climb out; a crate tipped into a pond as "
    "fish pour out; a brush dipped in glowing paint at a watch-dial bench; a pump nozzle pouring "
    "additive into a fuel tank). Hands and tools may appear, faces may not; the named species, "
    "substance or rule must be clearly visible in the act. A plain red ring will circle this act. RIGHT: "
    "the FEAR -- ONE ordinary person, invented and anonymous, close in the foreground, reacting "
    "in shock (wide eyes, open mouth, a raised hand) as the consequence (the animals that "
    "multiplied or spread, or the damage they did) closes in on them from behind. Never a real, "
    "named or famous person, never anyone the story names. Real species with correct anatomy, real objects and period details, "
    "the story's real setting, no gore, blood, corpses, injuries, text, logos, maps or symbols. "
    "Propose TWO different pairs so the better one can be chosen: the same mistake on the left, "
    "and two different threats on the right (e.g. a swarm in a field vs. animals at a farmhouse "
    "door). Return ONLY JSON: "
    "{\"pairs\": [{\"crossed_out_subject\": \"3-6 words, the species in the act\", "
    "\"crossed_out_scene\": \"one sentence, close, the act that fills the left panel\", "
    "\"consequence_subject\": \"3-6 words, the threat\", \"consequence_scene\": \"one sentence: "
    "the frightened person in the foreground and the threat closing in\"}, {...}]}"
)


def strategy(title: str, question: str, transcript: str, cost_sink: list | None = None) -> list[dict]:
    """Two candidate scene pairs from the narration; [] on any failure (caller falls back)."""
    import explainer_pipeline as ep

    try:
        user = (f'TITLE: "{title}"\nTOPIC: {question}\n\nTRANSCRIPT:\n{transcript[:5000]}')
        response = ep._claude().messages.create(
            model=ep.ANTHROPIC_MODEL, max_tokens=700, system=_STRATEGY_SYSTEM,
            messages=[{"role": "user", "content": user}])
        if cost_sink is not None:
            cost_sink.append(ep._msg_cost(response.usage))
        parsed, _ = ep._parse_script_json(response.content[0].text)
    except Exception:
        return []
    pairs = (parsed or {}).get("pairs") if isinstance(parsed, dict) else None
    keep = []
    for pair in pairs or []:
        if not isinstance(pair, dict):
            continue
        if all(str(pair.get(key) or "").strip() for key in
               ("crossed_out_subject", "crossed_out_scene", "consequence_subject",
                "consequence_scene")):
            keep.append({key: str(pair[key]).strip() for key in
                         ("crossed_out_subject", "crossed_out_scene", "consequence_subject",
                          "consequence_scene")})
    return keep[:2]


def fallback_pair(question: str) -> dict:
    return {"crossed_out_subject": question, "crossed_out_scene": f"a close-up of {question}",
            "consequence_subject": "the aftermath", "consequence_scene": f"the aftermath of {question}"}


def image_prompt(pair: dict, illustrated: bool = False) -> str:
    """The model draws two scenes and nothing else; overlays are composited afterwards.

    `illustrated` makes the thumbnail match the film. The delivered killer bees thumbnail was a
    photoreal bee macro in front of a hand-drawn cut-paper film: side by side they read as two
    different products, and a viewer who clicks the photo arrives at an illustration.
    """
    medium = (
        "A hand-drawn editorial illustration in layered torn cut-paper with visible deckled "
        "edges, ink contour lines, flat gouache colour and paper grain -- unmistakably a hand-made "
        "collage drawing and never a photograph or a 3D render -- used as a YouTube thumbnail "
        "background split into two panels by a straight "
        if illustrated else
        "A photoreal, cinematic YouTube thumbnail background split into two panels by a straight ")
    # The tail asked for a "documentary photography look" and "no cartoon or vector styling" in
    # BOTH media, so the illustrated prompt opened with "never a photograph" and closed by asking
    # for one. The model split the difference: delivered illustrated thumbnails came back as a
    # photo-textured drawing with neither medium's contrast, and the grader called them muddy.
    # The photoreal tail is unchanged byte for byte; only the illustrated branch swaps its look.
    look = (
        "Flat gouache colour, high contrast, strong figure/ground separation, bold readable "
        "cut-paper shapes, designed to read instantly on a small mobile screen. "
        if illustrated else
        "Documentary photography look, high contrast, saturated but realistic color, strong "
        "subject-to-background separation, designed to read instantly on a small mobile screen. ")
    no_vector = "" if illustrated else " No cartoon or vector styling."
    return (
        medium +
        "diagonal line running from top-center to bottom-center-left, slightly tilted. "
        # BOTH panels need a dominant foreground subject. A delivered thumbnail (2026-10-05) put
        # a distant hillside in the right panel: at feed size it read as green texture with a
        # yellow arrow pointing at nothing, and the left panel was a mat of small insects with no
        # single thing to look at. A thumbnail is looked at for under a second at about 350px.
        f"LEFT PANEL (about 45% of the width): {pair['crossed_out_scene']} The "
        f"{pair['crossed_out_subject']} and the act are close, sharp and centred in the lower "
        "two-thirds of the panel, so a circle around the middle of the panel frames the whole "
        "act; the background falls away out of focus. No faces in the left panel. "
        f"RIGHT PANEL (about 55% of the width): {pair['consequence_scene']} ONE frightened "
        "ordinary person, invented and anonymous, head and shoulders, LARGE in the near "
        "foreground of the right half of the panel, face turned three-quarters to the camera, "
        "shock readable at thumbnail size: wide eyes, open mouth, a hand raised. "
        f"{pair['consequence_subject']} surges toward them from the left and behind, dark against "
        "a bright sky or ground so the threat reads as one shape. Keep small foreground details "
        "sparse so the face stays the clearest thing in the panel. "
        "Keep the TOP 22% of the RIGHT panel simple and uncluttered (sky, dark ground or blurred "
        "background) so a headline can be placed there. "
        + look +
        "Absolutely NO text, letters, numbers, logos, arrows, borders or watermarks. "
        # The renderer composites the prohibition ring. The model drawing its own produced a
        # thumbnail with TWO crossed-out symbols stacked on the same subject (2026-10-05).
        "CRITICALLY: do NOT draw any prohibition sign, red circle, ring, cross, X, slash or "
        "crossed-out marking anywhere in the image. The subject is shown plain and unmarked; the "
        "red circle is added afterwards by the renderer and a second one ruins the thumbnail. "
        "No gore, blood, corpses or injuries. The person is never a real, named or famous "
        "individual." + no_vector
    )


# ── Composition ───────────────────────────────────────────────────────────────

def _font(size: int):
    for path in _HEADLINE_FONTS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _bezier(p0, p1, p2, steps=48):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1])
            for t in (i / steps for i in range(steps + 1))]


def _glow(base: Image.Image, draw_fn, color, blur: int, alpha: int = 200) -> None:
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer), (*color, alpha))
    base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def geometry(tw: int, th: int) -> dict:
    """Every overlay position, in pixels, derived from the frame so tests and the renderer agree."""
    return {
        "divider": ((int(tw * 0.53), 0), (int(tw * 0.45), th)),
        "ring_center": (int(tw * 0.235), int(th * 0.55)),
        "ring_radius": int(th * 0.31),
        "ring_width": max(6, int(th * 0.032)),
        "arrow": ((int(tw * 0.36), int(th * 0.86)), (int(tw * 0.48), int(th * 0.96)),
                  (int(tw * 0.63), int(th * 0.70))),
        "arrow_width": max(6, int(th * 0.03)),
        "headline_box": (int(tw * 0.47), int(th * 0.03), int(tw * 0.985), int(th * 0.26)),
    }


def compose(bg_path: str, out_path: str, tw: int = 1280, th: int = 720,
            headline: tuple[str, str] = HEADLINE, ring_overlay: bool = True,
            slash: bool = False) -> str:
    """Fit the two-scene background and draw divider, prohibition ring, arrow and headline.

    `ring_overlay=False` leaves the ring out, for a background that already contains one. The
    delivered killer bees thumbnail carried TWO crossed-out circles: the prompt tells the model
    not to draw one and it drew one anyway, and the renderer then added its own on top. An
    instruction the model can ignore is not a guarantee, so the count is now enforced here.
    """
    geo = geometry(tw, th)
    base = ImageOps.fit(Image.open(bg_path).convert("RGB"), (tw, th)).convert("RGBA")

    # Divider: a thin white line with a soft shadow so the two panels read as a split frame.
    (x0, y0), (x1, y1) = geo["divider"]
    _glow(base, lambda d, c: d.line([(x0, y0), (x1, y1)], fill=c, width=14), BLACK, 6, 150)
    ImageDraw.Draw(base).line([(x0, y0), (x1, y1)], fill=(*WHITE, 235), width=5)

    # Red ring, glowing, drawn over the left panel's act.
    cx, cy = geo["ring_center"]
    r, w = geo["ring_radius"], geo["ring_width"]
    box = [cx - r, cy - r, cx + r, cy + r]
    off = r / math.sqrt(2)
    diagonal = [(cx - off, cy - off), (cx + off, cy + off)]

    # v2 draws the ring without its slash: it circles the act that caused the story ("here is
    # the mistake"); a slash over a released animal read as "exterminate this" (2026-10-09).
    def ring(d, c, width):
        d.ellipse(box, outline=c, width=width)
        if slash:
            d.line(diagonal, fill=c, width=width)

    if ring_overlay:
        _glow(base, lambda d, c: ring(d, c, w + 14), RED, 14, 170)
        ring(ImageDraw.Draw(base), (*RED, 255), w)

    # Curved yellow arrow from under the ring into the consequence panel, black outlined.
    p0, p1, p2 = geo["arrow"]
    path = _bezier(p0, p1, p2)
    aw = geo["arrow_width"]
    (ex, ey), (px, py) = path[-1], path[-4]
    angle = math.atan2(ey - py, ex - px)
    head = aw * 4.0
    tip = (ex + math.cos(angle) * head * 1.1, ey + math.sin(angle) * head * 1.1)
    left = (ex + math.cos(angle + 2.55) * head, ey + math.sin(angle + 2.55) * head)
    right = (ex + math.cos(angle - 2.55) * head, ey + math.sin(angle - 2.55) * head)
    shaft = path[:-4]

    def arrow(d, c, extra):
        d.line(shaft, fill=c, width=aw + extra, joint="curve")
        d.polygon([tip, left, right], fill=c, outline=c, width=max(1, extra // 2))

    _glow(base, lambda d, c: arrow(d, c, 12), BLACK, 5, 190)
    arrow(ImageDraw.Draw(base), (*BLACK, 255), 10)
    arrow(ImageDraw.Draw(base), (*YELLOW, 255), 0)

    # Headline: two words, yellow then white, heavy black stroke, sized to the right panel.
    bx0, by0, bx1, by1 = geo["headline_box"]
    avail_w, avail_h = bx1 - bx0, by1 - by0
    size = int(th * 0.22)
    d = ImageDraw.Draw(base)
    stroke = max(4, int(size * 0.075))
    while size > 20:
        font = _font(size)
        stroke = max(4, int(size * 0.075))
        gap = int(size * 0.28)
        widths = [d.textlength(word, font=font) for word in headline]
        total_w = sum(widths) + gap * (len(headline) - 1) + 2 * stroke
        text_h = d.textbbox((0, 0), "".join(headline), font=font, stroke_width=stroke)[3]
        if total_w <= avail_w and text_h <= avail_h:
            break
        size -= 4
    x = bx0 + (avail_w - total_w) / 2 + stroke
    y = by0 + (avail_h - text_h) / 2
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    cursor = x
    for word, width in zip(headline, widths):
        sd.text((cursor + 5, y + 7), word, font=font, fill=(0, 0, 0, 160),
                stroke_width=stroke + 2, stroke_fill=(0, 0, 0, 160))
        cursor += width + gap
    base.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(4)))
    colors = (YELLOW, WHITE)
    cursor = x
    for index, (word, width) in enumerate(zip(headline, widths)):
        ImageDraw.Draw(base).text((cursor, y), word, font=font, fill=(*colors[index % 2], 255),
                                  stroke_width=stroke, stroke_fill=(*BLACK, 255))
        cursor += width + gap
    base.convert("RGB").save(out_path, "JPEG", quality=92)
    return out_path


# ── Orchestration ─────────────────────────────────────────────────────────────

_RING_QUESTION = (
    "Look at this artwork. Does it ALREADY CONTAIN a drawn prohibition symbol -- a red or black "
    "circle, ring, oval outline, crossed-out sign, diagonal slash, X or no-entry symbol -- drawn "
    "as part of the picture? A round object that is simply part of the scene (the sun, a plate, a "
    "wheel, a honeycomb cell) is NOT a prohibition symbol. "
    'Return ONLY JSON: {"ring": true|false}.'
)


def detect_drawn_ring(image_path: str, cost_sink: list | None = None,
                      log=lambda message: None) -> bool:
    """Did the model draw a prohibition symbol the renderer is about to duplicate?

    Best-effort: on any failure this returns False and the renderer behaves as it always has,
    because a missing vision call must not cost a finished film its packaging. It SAYS so,
    though -- an earlier version swallowed a missing ANTHROPIC_API_KEY and reported "no ring",
    which is the same silent-fallback shape that let two circles reach YouTube in the first place.
    """
    import base64

    import explainer_pipeline as ep
    try:
        with open(image_path, "rb") as handle:
            b64 = base64.b64encode(handle.read()).decode()
        rsp = ep._claude().messages.create(
            model=ep.ANTHROPIC_MODEL, max_tokens=100,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": b64}},
                {"type": "text", "text": _RING_QUESTION}]}])
        if cost_sink is not None:
            cost_sink.append(ep._msg_cost(rsp.usage))
        out, _ = ep._parse_script_json(rsp.content[0].text)
        return bool(isinstance(out, dict) and out.get("ring"))
    except Exception as exc:               # noqa: BLE001 - never block packaging on this
        log(f"ring check unavailable ({type(exc).__name__}); assuming the artwork has none")
        return False


# The grader shipped with the science channel's checklist (explainer_pipeline._THUMB_GRADE_SYSTEM).
# Its item 7 demands a "clean flat / bold-graphic / vector style -- NOT photo-cluttered", which a
# photoreal split frame fails by construction, and items 2, 3 and 6 ask whether the picture shows
# a consequence the title's CAUSE makes you need explained -- a question written for "what if"
# titles. A backfire title STATES the consequence ("...That Starved a Nation"), so those items
# grade the formula, not the picture. Every delivered backfire thumbnail scored "weak (4/8)"
# against it (2026-10-05) and only the count was kept, so a muddy render and an unpassable
# checklist were indistinguishable. This list judges what the split-frame grammar is trying to
# do. Same JSON shape as the science checklist (items: 8 booleans, fails: int, redesign_note), so
# explainer_pipeline's readers of rep["fails"] / rep["weak"] / rep["qa"] need no change.
BACKFIRE_THUMB_GRADE_SYSTEM = (
    "You are a ruthless YouTube thumbnail critic for a documentary channel about interventions "
    "that backfired, judging for MOBILE click-through. Every thumbnail uses one grammar: a split "
    "frame. LEFT, the mistake in action (the species being released, introduced or removed) "
    "inside a red ring. RIGHT, one frightened person with the consequence closing in. A yellow arrow runs from the ring into the "
    "consequence and a two-word headline sits on top. A title is given alongside. Grade each item "
    "strictly true/false:\n"
    "1. one_second: understandable in ONE second at tiny (~160px) mobile size?\n"
    "2. mistake_identifiable: does the ringed LEFT read as an ACT -- a named species, substance "
    "or rule being released, introduced, removed or enforced -- not a lone animal portrait (which reads as "
    "pest control) and not just a tool or texture?\n"
    "3. fear_foreground: does the RIGHT panel have ONE frightened person, large in the near "
    "foreground, whose fear reads at mobile size, with the threat visibly closing in?\n"
    "4. one_subject_per_panel: does each panel hold one dominant focal point (the act; the face) "
    "that passes the squint test, with the swarm or crowd reading as one background shape rather "
    "than many competing foreground things?\n"
    "5. headline_legible: is the headline exactly two words and readable at mobile size?\n"
    "6. single_ring: is there exactly ONE red ring in the frame -- no second drawn circle, "
    "slash or crossed-out sign anywhere?\n"
    "7. medium_matches: is the artwork in the EXPECTED MEDIUM stated after this list -- photoreal "
    "if the film is photoreal, cut-paper/illustrated if the film is illustrated -- and clean "
    "throughout, with strong figure/ground separation, NOT a muddy mix of photo and drawing or "
    "AI-generic noise?\n"
    "8. consequence_not_title_echo: does the RIGHT panel show a consequence the title does not "
    "already state in words (thumbnail != a picture of the title)?\n"
    "Return ONLY JSON: {\"items\":{\"one_second\":bool,...all 8...},\"fails\":int (count of false),"
    "\"redesign_note\":\"one sentence -- the single biggest fix\"}."
)


def thumb_grade_system(illustrated: bool) -> str:
    """The checklist plus the one fact the grader cannot see in the pixels: the FILM's medium.

    Item 7 asks whether the thumbnail matches the film, and the grader is shown the thumbnail and
    the title only. The killer bees thumbnail was a clean photoreal bee in front of a cut-paper
    film -- a thumbnail that would pass any "is this clean" test and still sent the viewer to a
    different product -- so the expected medium travels with the checklist.
    """
    medium = ("a hand-drawn cut-paper illustration; item 7 is false if the artwork is a "
              "photograph or a 3D render"
              if illustrated else
              "photoreal; item 7 is false if the artwork is drawn, painted or cartoon")
    return BACKFIRE_THUMB_GRADE_SYSTEM + f"\nEXPECTED MEDIUM: the film this thumbnail fronts is {medium}."


def generate_thumbnail(title: str, question: str, transcript: str, out_dir: str,
                       cost_sink: list | None = None, report: dict | None = None,
                       log=lambda message: None, pairs: list[dict] | None = None,
                       illustrated: bool = False) -> str:
    """Render one composed thumbnail per candidate pair, keep the fewest-fails by the vision grader.

    `pairs` overrides the model's strategy: an operator naming the crossed-out subject and the
    consequence directly (scripts/repackage_backfire.py --crossed-out/--consequence).
    """
    import explainer_pipeline as ep

    rep = report if isinstance(report, dict) else {}
    # The grader only takes a checklist once explainer_pipeline.grade_thumbnail has a `system`
    # keyword (being added in the same change set, in a file this module must not edit). Until
    # the name is in its signature the science checklist is what runs, and the report says which,
    # because a 4/8 against the wrong checklist and a 4/8 against the right one are different
    # facts. A `**kwargs` catch-all does not count: forwarding "system" into a grader that does
    # not understand it is worse than grading with the old list.
    grade_kwargs: dict = {}
    checklist = "science_v1"
    try:
        if "system" in inspect.signature(ep.grade_thumbnail).parameters:
            grade_kwargs["system"] = thumb_grade_system(illustrated)
            checklist = "backfire_v2"
    except (TypeError, ValueError):    # no introspectable signature: call it as today
        pass
    pairs = list(pairs or []) or strategy(title, question, transcript, cost_sink=cost_sink) \
        or [fallback_pair(question)]
    limit = max(1, min(2, int(os.environ.get("THUMB_VARIANTS", "2") or 2)))
    out = os.path.join(out_dir, "thumbnail.jpg")
    best_path, best_grade, fell = None, None, False
    rendered = []
    for index, pair in enumerate(pairs[:limit]):
        bg = os.path.join(out_dir, f"_thumb_backfire_bg_{index}.jpg")
        vpath = os.path.join(out_dir, f"_thumb_backfire_{index}.jpg")
        try:
            ep.generate_image(image_prompt(pair, illustrated), bg, cost_sink=cost_sink, size="1536x1024")
        except ep.ContentBlocked:
            try:
                ep.generate_image(image_prompt(pair, illustrated) + " SAFE REDRAW: calm, symbolic, non-graphic.",
                                  bg, cost_sink=cost_sink, size="1536x1024")
            except Exception:
                ep.make_fallback_frame(bg, "", w=1280, h=720)
                fell = True
        except Exception:
            ep.make_fallback_frame(bg, "", w=1280, h=720)
            fell = True
        # Exactly one crossed-out circle reaches the viewer. One redraw, then the overlay yields.
        keep_ring = True
        if detect_drawn_ring(bg, cost_sink, log):
            log("thumbnail artwork drew its own prohibition ring; redrawing once")
            try:
                ep.generate_image(
                    image_prompt(pair, illustrated)
                    + " REDRAW: the previous attempt drew a crossed-out circle. Draw the two "
                      "scenes ONLY. No ring, no circle outline, no slash, no X, no prohibition "
                      "sign anywhere in the frame.",
                    bg, cost_sink=cost_sink, size="1536x1024")
            except Exception:              # noqa: BLE001 - keep the first attempt
                pass
            if detect_drawn_ring(bg, cost_sink, log):
                log("artwork still carries a ring; leaving the overlay ring off this candidate")
                keep_ring = False
        compose(bg, vpath, ring_overlay=keep_ring)
        grade = ep.grade_thumbnail(vpath, title, cost_sink=cost_sink, **grade_kwargs)
        # Only the count used to survive this line. Every shipped backfire thumbnail logged
        # "weak (4/8)" with no record of WHICH four items failed or what the grader would change,
        # so the operator could not tell a bad render from an unpassable checklist. Keep the
        # whole verdict: it is the only evidence the next redesign has.
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
        "version": VERSION, "headline": " ".join(HEADLINE), "grammar": "fatal_error_split",
        "pairs": [{**item["pair"], "fails": item["fails"], "items": item["items"],
                   "redesign_note": item["redesign_note"]} for item in rendered],
        "chosen": next((i for i, item in enumerate(rendered) if item["path"] == best_path), None),
        "qa": "skipped" if not best_grade or best_grade.get("fails") == 99 else "ok",
        "fails": None if not best_grade or best_grade.get("fails") == 99 else best_grade.get("fails"),
        "weak": bool(best_grade and best_grade.get("fails", 0) not in (None, 99)
                     and best_grade.get("fails", 0) >= 3),
        "fallback": fell, "variants": len(rendered), "checklist_version": checklist,
    })
    # write_report had no caller outside scripts/repackage_backfire.py, so a pipeline run left no
    # packaging.json: the per-item verdicts above lived only in the in-memory report and the log
    # line below. Best-effort, like everything else here -- an unwritable job dir must not cost
    # a finished film its thumbnail.
    try:
        write_report(out_dir, rep)
    except OSError as exc:
        log(f"packaging.json not written ({type(exc).__name__})")
    log(f"Backfire thumbnail: {len(rendered)} variant(s), chosen {rep['chosen']}, "
        f"fails {rep['fails']}, checklist {checklist}")
    return out


def write_report(out_dir: str, payload: dict) -> str:
    path = os.path.join(out_dir, "packaging.json")
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2)
    return path
