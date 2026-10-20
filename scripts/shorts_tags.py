#!/usr/bin/env python3
"""Researched tags for a native Short: the topic's winning tags the Short can claim, filling ~480 chars.

    python3 scripts/shorts_tags.py jobs/<job>/shorts/<name>              # writes package.json tags
    python3 scripts/shorts_tags.py jobs/<job>/shorts/<name> --search "chernobyl animals"

Operator rule (2026-10-20): Shorts use the whole tag allowance (YouTube's 500 characters; the API
check here stops at 480) with high-return tags that describe the video. The same engine as the films
(tag_strategy): tags harvested from the topic's top videos, kept only when the Short's narration or
title can claim them, plus the fixed audience layer, "shorts" and the channel name. The search phrase
is the measured market search for the film's topic (topics/schedule.json), else the spec's own tags.
The spec's hand-written tags are kept as tags_spec. About 101 quota units per Short.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def film_job(short_dir: str) -> str:
    """jobs/<job>/shorts/<name> -> jobs/<job>."""
    return os.path.dirname(os.path.dirname(os.path.abspath(short_dir)))


def market_search(job: str) -> str:
    """The film's measured market search from either schedule, or ""."""
    slug = os.path.basename(job)
    for name in ("schedule.json", "history_schedule.json"):
        path = os.path.join(ROOT, "topics", name)
        if not os.path.exists(path):
            continue
        for item in json.load(open(path)).get("items") or []:
            if os.path.basename(str(item.get("job") or "")) == slug or item.get("slug") == slug:
                search = (item.get("market") or {}).get("search")
                if search:
                    return search
    return ""


def narration(spec: dict) -> str:
    return " ".join(b.get("text", "") for b in spec.get("beats") or [])


# Tags about other media or other creators' formats: they describe the TV series, a game or a vlog,
# not our Short (measured on the Chernobyl Shorts, 2026-10-20: "chernobyl hbo", "ep 5", "official
# trailer", "shadow of chernobyl", "vox borders colombia", "sneaking into chernobyl").
import re as _re
OFF_MEDIA = _re.compile(r"\b(hbo|miniseries|series|season|episode|ep \d+|trailer|movie|film \d|show|game|gameplay|stalker|"
                        r"shadow of|vox|borders|vlog|tour|tourist|sneaking|reaction|react|podcast|full documentary|finale|soundtrack|ost|scene|scenes|clip|hindi|urdu|tamil|meeting|bomb|mutated|mutant|mutation|mutations|last of us|"
                        r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec) ?\d*\b|\b(201[5-9]|202\d)\b|\b\d{1,2}$")


DESCRIPTIVE = {"today", "now", "history", "documentary", "explained", "explanation", "abandoned", "disaster", "story",
               "facts", "inside", "exploring", "what", "happened", "why", "how", "real", "truth", "mystery", "secret", "lost", "after", "years", "later", "zone", "documentaries"}


def off_media(tag: str) -> bool:
    return bool(OFF_MEDIA.search(tag))


def fill(chosen: list[str], videos: list[dict], text: str, spec_tags: list[str], target: int = 470) -> list[str]:
    """Fill the budget (operator, 2026-10-20: use the whole allowance). After the strict layer, add the
    topic's winning tags that share at least one content word with the Short's words (a place, a
    species, the event), highest-scoring first; junk, single words, hobby intent and other channels'
    names stay out. Multi-word spec tags come before competitor ones."""
    import math
    import re
    import tag_strategy as ts
    vocab = ts._vocab(text)
    brands = {re.sub(r"[^a-z0-9]", "", (v.get("channel") or "").lower()) for v in videos} - {""}
    score = {}
    for v in videos:
        w = math.log10(max(10, int(v.get("views") or 0)))
        for t in {ts._norm(x) for x in v.get("tags") or []}:
            score[t] = score.get(t, 0.0) + w
    reserved = [t for t in chosen if t in ("shorts", ts.CHANNEL_TAG, *ts.CHANNEL_TAGS.values())]
    out = [t for t in chosen if t not in reserved and not off_media(t)]
    cands = [ts._norm(t) for t in spec_tags] + sorted(score, key=lambda t: -score[t])
    for t in cands:
        if t in out or t in reserved or ts.excluded(t) or off_media(t):
            continue
        squashed = re.sub(r"[^a-z0-9]", "", t)
        if squashed in brands or any(len(b) >= 5 and b in squashed for b in brands):
            continue
        words = ts._content_words(t)
        covered = sum(1 for w in words if ts._stem(w) in vocab or w in DESCRIPTIVE)
        # Most of the tag's words must be ours or plain descriptors: "chernobyl" alone must not carry
        # "chernobyl firefighter" or "chernobyl soundtrack" into a Short about the evacuation.
        if not any(ts._stem(w) in vocab for w in words) or covered * 3 < len(words) * 2 or covered < len(words) - 1:
            continue
        if len(out) + len(reserved) >= 30 or ts.tags_chars(out + [t] + reserved) > min(target, ts.MAX_TOTAL_CHARS):
            continue
        out.append(t)
    return out + reserved


def build(short_dir: str, search: str = "", harvest=None, channel: str = "world") -> dict:
    """Select tags for the Short and write them into its package.json. `harvest` is injectable."""
    import tag_strategy
    import upload_job
    spec = json.load(open(os.path.join(short_dir, "spec.json")))
    pkg_path = os.path.join(short_dir, "package.json")
    pkg = json.load(open(pkg_path))
    job = film_job(short_dir)
    text = narration(spec)
    search = search or " ".join(spec.get("tags_search") or []) or market_search(job) or " ".join((spec.get("tags") or [])[:2])
    if harvest is None:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.expanduser("~/ai-video-gen-local"), ".env"))
        harvest = lambda q: tag_strategy.harvest(q, os.environ["YOUTUBE_API_KEY"])  # noqa: E731
    try:
        videos, error = harvest(search), ""
    except Exception as exc:  # noqa: BLE001 - fall back to the spec's tags
        videos, error = [], f"{type(exc).__name__}: {str(exc)[:160]}"
    audience = upload_job.audience_tags(job, text, channel)
    result = tag_strategy.select_tags(videos, text, spec.get("title", pkg.get("title", "")),
                                      [t for t in spec.get("tags") or [] if t != "shorts"], short=True,
                                      audience=audience, brand=tag_strategy.CHANNEL_TAGS.get(channel, tag_strategy.CHANNEL_TAG))
    tags = fill(result["tags"], videos, text + " " + spec.get("title", ""), spec.get("tags") or [])
    broad = market_search(job)
    if tag_strategy.tags_chars(tags) < 420 and broad and broad != search:
        # A narrow search found too few winners: widen to the film's measured topic search.
        try:
            videos = videos + harvest(broad)
        except Exception:  # noqa: BLE001
            pass
        tags = fill(tags, videos, text + " " + spec.get("title", ""), spec.get("tags") or [])
    pkg.setdefault("tags_spec", pkg.get("tags") or spec.get("tags") or [])
    pkg["tags"] = tags
    result["tags"] = tags
    pkg["tags_research"] = {"search": search, "harvest_error": error, "chars": tag_strategy.tags_chars(result["tags"]),
                            "competitor_videos": len(videos)}
    json.dump(pkg, open(pkg_path, "w"), indent=1, ensure_ascii=False)
    return pkg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("short_dir", nargs="+")
    ap.add_argument("--search", default="")
    ap.add_argument("--channel", default="world", choices=["world", "history"])
    args = ap.parse_args(argv)
    for d in args.short_dir:
        pkg = build(d, args.search, channel=args.channel)
        r = pkg["tags_research"]
        print(f"{d}: {len(pkg['tags'])} tags, {r['chars']} chars, from {r['competitor_videos']} videos for {r['search']!r}"
              + (f" (harvest failed: {r['harvest_error']})" if r["harvest_error"] else ""))
        print("   ", ", ".join(pkg["tags"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
