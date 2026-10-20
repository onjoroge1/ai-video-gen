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


def build(short_dir: str, search: str = "", harvest=None, channel: str = "world") -> dict:
    """Select tags for the Short and write them into its package.json. `harvest` is injectable."""
    import tag_strategy
    import upload_job
    spec = json.load(open(os.path.join(short_dir, "spec.json")))
    pkg_path = os.path.join(short_dir, "package.json")
    pkg = json.load(open(pkg_path))
    job = film_job(short_dir)
    text = narration(spec)
    search = search or market_search(job) or " ".join((spec.get("tags") or [])[:2])
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
    pkg.setdefault("tags_spec", pkg.get("tags") or spec.get("tags") or [])
    pkg["tags"] = result["tags"]
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
