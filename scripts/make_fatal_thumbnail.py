#!/usr/bin/env python3
"""Build a FATAL-series split thumbnail for a finished job, then feed-test it (docs/FATAL_THUMBNAIL_PLAYBOOK.md).

    python3 scripts/make_fatal_thumbnail.py jobs/elephants-foot --word FUEL --name v2 \
        --left "a 1996-style black-and-white photo of a man beside the wrinkled mass" \
        --right "the same mass today, cracks glowing like embers, a glove holding a dosimeter pinned red"
    python3 scripts/make_fatal_thumbnail.py jobs/elephants-foot --feed-test a.jpg b.jpg
    python3 scripts/make_fatal_thumbnail.py jobs/elephants-foot --set jobs/elephants-foot/thumbs/v2_fatal_fuel.jpg

The image model draws two panels and nothing else; backfire_packaging.compose adds the divider,
the red ring, the arrow and the two-word headline. FATAL is refused unless the film's own
transcript documents a death or lethal danger: a FATAL headline on a film where nobody died is
the overpromise PACKAGING_PLAYBOOK.md warns loses Test & Compare on watch-time share.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

REFERENCE = os.path.join(ROOT, "jobs", "chernobyl-today", "thumbs", "split", "B_hazmat_fatal_test.jpg")
FEED_WIDTH = 360

# Whole words that document a death or lethal danger in the narration. "fatal" itself counts: a
# film that says so has made the claim the headline repeats.
_LETHAL = re.compile(r"\b(died|dies|dead|death|deaths|killed|kill|kills|lethal|fatal|fatally|deadly)\b", re.I)

SPLIT = ("A photoreal, cinematic YouTube thumbnail background split into two panels by a straight diagonal "
         "line running from top-center to bottom-center-left, slightly tilted. Designed to read instantly at "
         "350 pixels wide on a phone: ONE large, high-contrast subject per panel, simple dark backgrounds, "
         "no clutter. ")
ILLUSTRATED = ("A hand-drawn editorial illustration in layered torn cut-paper with ink contour lines and flat "
               "gouache colour, never a photograph, used as a YouTube thumbnail background split into two "
               "panels by a straight diagonal line running from top-center to bottom-center-left. Designed to "
               "read instantly at 350 pixels wide on a phone: ONE large, high-contrast subject per panel. ")
LEFT_RULE = ("LEFT PANEL (about 45% of the width): {left} The subject is large, sharp and centred in the lower "
             "two-thirds of the panel so a circle around the middle frames it; the background falls away. "
             "No faces in the left panel. ")
RIGHT_RULE = ("RIGHT PANEL (about 55% of the width): {right} The person or hand is LARGE in the near "
              "foreground, close to the danger. ")
TAIL = ("Keep the TOP 22% of the RIGHT panel simple and dark so a headline can be placed there. Absolutely "
        "NO text, letters, numbers, logos, arrows, borders or watermarks. Do NOT draw any red circle, ring, "
        "cross or prohibition sign. No gore, no injuries; grounded, realistic fear, never a cartoon "
        "expression. People are anonymous, never recognizable real people.")


def fatal_allowed(transcript: str) -> tuple[bool, str]:
    """(allowed, evidence): the first narration sentence that documents a death or lethal danger."""
    for sentence in re.split(r"(?<=[.!?])\s+", transcript or ""):
        if _LETHAL.search(sentence):
            return True, sentence.strip()
    return False, ""


def headline_ok(first: str, word: str, max_chars: int = 18) -> bool:
    """Two single uppercase words that fit the headline band (backfire_packaging.HEADLINE_MAX_CHARS)."""
    parts = (first or "", word or "")
    return (all(p and p == p.upper() and " " not in p and p.replace("'", "").isalpha() for p in parts)
            and len(first) + 1 + len(word) <= max_chars)


def build_prompt(left: str, right: str, style: str = "photoreal") -> str:
    head = ILLUSTRATED if style == "illustrated" else SPLIT
    return (head + LEFT_RULE.format(left=left.strip().rstrip(".") + ".")
            + RIGHT_RULE.format(right=right.strip().rstrip(".") + ".") + TAIL)


def feed_sheet(paths: list[str], out: str, width: int = FEED_WIDTH) -> str:
    """Every candidate at feed size, side by side, labelled with its file name."""
    from PIL import Image, ImageDraw
    height = round(width * 9 / 16)
    pad, label = 14, 22
    sheet = Image.new("RGB", (pad + (width + pad) * len(paths), height + label + 2 * pad), (15, 15, 15))
    draw = ImageDraw.Draw(sheet)
    for index, path in enumerate(paths):
        tile = Image.open(path).convert("RGB").resize((width, height), Image.LANCZOS)
        x = pad + index * (width + pad)
        sheet.paste(tile, (x, pad))
        draw.text((x, pad + height + 4), os.path.basename(path)[:48], fill=(220, 220, 220))
    sheet.save(out, quality=92)
    return out


def install_thumbnail(job: str, path: str) -> str:
    """Copy the chosen thumbnail to <job>/thumbnail.jpg, keeping the pipeline's first version."""
    target = os.path.join(job, "thumbnail.jpg")
    backup = os.path.join(job, "thumbnail_pipeline.jpg")
    if os.path.isfile(target) and not os.path.isfile(backup):
        shutil.copyfile(target, backup)
    shutil.copyfile(path, target)
    return target


def _transcript(job: str) -> str:
    path = os.path.join(job, "transcript.txt")
    return open(path, encoding="utf-8").read() if os.path.isfile(path) else ""


def generate(job: str, name: str, first: str, word: str, left: str, right: str, style: str) -> dict:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    from openai import OpenAI
    import backfire_packaging as bp
    out_dir = os.path.join(job, "thumbs")
    os.makedirs(out_dir, exist_ok=True)
    prompt = build_prompt(left, right, style)
    reply = OpenAI().images.generate(model="gpt-image-2", prompt=prompt, size="1536x1024",
                                     quality="high", n=1)
    background = os.path.join(out_dir, f"{name}_bg.png")
    with open(background, "wb") as handle:
        handle.write(base64.b64decode(reply.data[0].b64_json))
    composed = os.path.join(out_dir, f"{name}_{first.lower()}_{word.lower()}.jpg")
    bp.compose(background, composed, headline=(first, word))
    return {"background": background, "thumbnail": composed, "prompt": prompt}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("job")
    ap.add_argument("--word", help="the white noun: the thing visible in the picture (FUEL, SLIP, TEST)")
    ap.add_argument("--first-word", default="FATAL", help="FATAL by default; another word where nobody died")
    ap.add_argument("--left", default="", help="left panel: the recognizable act or fix, one wrong detail")
    ap.add_argument("--right", default="", help="right panel: the threat close to a person, now")
    ap.add_argument("--name", default="candidate")
    ap.add_argument("--style", choices=("photoreal", "illustrated"), default="photoreal")
    ap.add_argument("--feed-test", nargs="+", metavar="IMAGE", help="feed-size sheet beside the live reference")
    ap.add_argument("--set", dest="install", metavar="IMAGE", help="install this image as <job>/thumbnail.jpg")
    ap.add_argument("--dry-run", action="store_true", help="print the prompt; no image call")
    args = ap.parse_args(argv)
    job = os.path.abspath(args.job)

    if args.install:
        print(install_thumbnail(job, args.install))
        return 0
    if args.feed_test:
        paths = ([REFERENCE] if os.path.isfile(REFERENCE) else []) + args.feed_test
        os.makedirs(os.path.join(job, "thumbs"), exist_ok=True)
        print(feed_sheet(paths, os.path.join(job, "thumbs", "feed_test.jpg")))
        return 0

    first, word = (args.first_word or "").upper(), (args.word or "").upper()
    if not headline_ok(first, word):
        sys.exit(f"headline must be two single uppercase words within 18 characters: {first!r} {word!r}")
    if not (args.left and args.right):
        sys.exit("--left and --right describe the two panels (see docs/FATAL_THUMBNAIL_PLAYBOOK.md)")
    allowed, evidence = fatal_allowed(_transcript(job))
    if first == "FATAL" and not allowed:
        sys.exit("FATAL refused: the transcript documents no death or lethal danger. "
                 "Use --first-word with another word (playbook: guardrails).")
    if args.dry_run:
        print(build_prompt(args.left, args.right, args.style))
        return 0
    result = generate(job, args.name, first, word, args.left, args.right, args.style)
    record = dict(result, headline=[first, word], fatal_evidence=evidence, left=args.left, right=args.right,
                  style=args.style)
    with open(os.path.join(job, "thumbs", f"{args.name}.json"), "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=1, ensure_ascii=False)
    print(result["thumbnail"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
