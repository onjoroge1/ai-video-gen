"""Researched YouTube tags: as deliberate as the title, description and thumbnail.

The operator's own measurement outranks the platform's statement that tags matter little: Shorts
went from a few views to thousands after a tag change (2026-10-11). The pipeline's tags were a
model's guess written into the description; these are harvested from the videos that already win
the topic, weighted by their views, and kept only when the film can honestly claim them.

    harvest(search, api_key)      -> competitor videos with their public tags (Data API, ~101 units)
    select_tags(videos, ...)      -> {"tags": [...], "sources": {...}} -- pure, provider-free

Rules, in order:
  * API-safe: at most 30 characters, no < > or quotes, at most 30 tags and 480 characters in all.
  * No other channel's name: a competitor's brand tag sends our film to their audience under a
    false pretence, which YouTube treats as misleading metadata.
  * Honest: every content word of a competitor tag must be spoken in our film (or our title), and
    one of them must belong to the film's core topic (its title and its own topic tags); or four
    or more winning videos carry the tag and it shares a word with the film (the category tag).
  * Ranked by evidence: summed log10(views) across the winning videos that carry the tag.
  * Then the pipeline's own topic tags fill what the market did not cover, then the audience
    layer and the channel name, whose room is reserved first.
  * Refused everywhere (channel audit, 2026-10-13): single-word fragments ("bees", "killer",
    "carp"), tool-generated entity labels ("bee (animal)"), format words ("documentary",
    "explainer video"), "news", and hobby or cooking intent ("carp fishing", "eating carp").
"""
from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request

MAX_TAG_CHARS = 30
MAX_TAGS = 22
MAX_TOTAL_CHARS = 480
MIN_VIEWS = 5_000
CONSENSUS_CARRIERS = 4
CHANNEL_TAG = "bolt explains the world"
# The brand tag is the channel's own name. A History film tagged "bolt explains the world" would
# point YouTube at the other channel's audience (2026-10-14, first History upload).
CHANNEL_TAGS = {"world": CHANNEL_TAG, "history": "bolt explains history"}
_JUNK = {"video", "videos", "youtube", "viral", "trending", "fyp", "foryou", "subscribe",
         "new", "latest", "best", "top", "amazing", "shorts", "short", "ytshorts", "news",
         "breaking news"}
# A format word names no topic and no audience; "nature documentary" names an audience and
# is added deliberately by the audience layer instead.
_FORMAT = {"documentary", "documentaries", "full documentary", "explainer", "explainer video",
           "explainer videos", "educational", "educational video", "education", "educational shorts",
           "animated explainer", "science shorts", "documentary film"}
# The carp film's harvest carried anglers and cooks to a film about an invasion (2026-10-13).
_HOBBY = {"fishing", "angling", "angler", "recipe", "recipes", "cooking", "cook", "eating",
          "bait", "lure"}
_STOP = {"the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with", "how", "why",
         "what", "when", "is", "are", "was", "were", "it", "its", "this", "that", "from", "by",
         "vs", "explained", "documentary", "history", "story", "facts"}
_API = "https://www.googleapis.com/youtube/v3/"


def _norm(tag: str) -> str:
    return re.sub(r"\s+", " ", (tag or "").strip().lstrip("#").strip().lower())


def _stem(word: str) -> str:
    """Light stem: one plural or verb suffix off, then six characters (bees/bee, invasive/invasion)."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    return word[:6]


def _vocab(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) >= 3}


def _content_words(tag: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", tag) if w not in _STOP and len(w) >= 3]


def api_safe(tag: str) -> bool:
    return bool(tag) and len(tag) <= MAX_TAG_CHARS and not any(ch in tag for ch in '<>"')


def tags_chars(tags: list[str]) -> int:
    """YouTube's count: a tag with a space is sent quoted, and tags are comma-separated."""
    return sum(len(t) + (2 if " " in t else 0) for t in tags) + max(0, len(tags) - 1)


def excluded(tag: str) -> str | None:
    """Why a tag is refused whatever its source, or None. `tag` is normalized."""
    if not api_safe(tag):
        return "not API-safe"
    if tag in _JUNK or not _content_words(tag):
        return "generic"
    if "(" in tag or ")" in tag:
        return "entity label"
    if len(tag.split()) == 1:
        return "single-word fragment"
    if tag in _FORMAT:
        return "format word"
    if any(word in _HOBBY for word in re.findall(r"[a-z]+", tag)):
        return "hobby or cooking intent"
    return None


def _get(path: str, api_key: str, **params) -> dict:
    params["key"] = api_key
    with urllib.request.urlopen(_API + path + "?" + urllib.parse.urlencode(params), timeout=30) as r:
        return json.load(r)


def harvest(search: str, api_key: str, max_results: int = 25) -> list[dict]:
    """The topic's winning videos with their public tags: one search (100 units) + one list."""
    found = _get("search", api_key, part="snippet", q=search, type="video",
                 maxResults=max_results, relevanceLanguage="en")
    ids = [item["id"]["videoId"] for item in found.get("items") or []
           if item.get("id", {}).get("videoId")]
    if not ids:
        return []
    listed = _get("videos", api_key, part="snippet,statistics", id=",".join(ids))
    return [{"id": v["id"], "title": v["snippet"].get("title", ""),
             "channel": v["snippet"].get("channelTitle", ""),
             "views": int((v.get("statistics") or {}).get("viewCount") or 0),
             "tags": v["snippet"].get("tags") or []}
            for v in listed.get("items") or []]


def select_tags(videos: list[dict], transcript: str, title: str, pipeline_tags: list[str],
                short: bool = False, audience: list[str] | None = None,
                brand: str = CHANNEL_TAG) -> dict:
    """`audience` is the fixed layer that tells YouTube who the film is for ("unintended
    consequences", "nature documentary"); with "shorts" and the channel name its room is
    reserved before the topic tags are chosen, so a long harvest cannot crowd it out."""
    vocab = _vocab(transcript) | _vocab(title)
    # The film's core topic: its title and its own topic tags. A competitor tag must touch it,
    # so a word the narration happens to contain ("watch", "channel", "wild") cannot carry a
    # generic or off-topic tag in on its own (Asian carp and killer bees trials, 2026-10-11).
    core = {_stem(w) for w in _content_words(_norm(title) + " " + " ".join(
        _norm(t) for t in pipeline_tags or []))}
    brands = {re.sub(r"[^a-z0-9]", "", (v.get("channel") or "").lower()) for v in videos}
    brands.discard("")
    score: dict[str, float] = {}
    carriers: dict[str, int] = {}
    for video in videos:
        if int(video.get("views") or 0) < MIN_VIEWS:
            continue
        weight = math.log10(max(10, int(video["views"])))
        for tag in {_norm(t) for t in video.get("tags") or []}:
            score[tag] = score.get(tag, 0.0) + weight
            carriers[tag] = carriers.get(tag, 0) + 1
    sources: dict[str, dict] = {}
    rejected: dict[str, str] = {}
    chosen: list[str] = []

    reserved = [_norm(t) for t in audience or [] if _norm(t)]
    if short:
        reserved.append("shorts")
    brand = _norm(brand) or CHANNEL_TAG
    reserved.append(brand)
    reserved = list(dict.fromkeys(reserved))
    topic_tags = MAX_TAGS - len(reserved)
    topic_chars = MAX_TOTAL_CHARS - tags_chars(reserved) - 1

    def admit(tag: str, source: str, **extra) -> None:
        if tag in sources or len(chosen) >= topic_tags or tag in reserved:
            return
        if tags_chars(chosen + [tag]) > topic_chars:
            return
        chosen.append(tag)
        sources[tag] = {"source": source, **extra}

    competitor_cap = topic_tags - 5    # leave room for the film's own topic tags
    for tag in sorted(score, key=lambda t: (-score[t], t)):
        if sum(1 for t in chosen if sources[t]["source"] == "competitor") >= competitor_cap:
            break
        squashed = re.sub(r"[^a-z0-9]", "", tag)
        words = _content_words(tag)
        reason = excluded(tag)
        if reason:
            rejected[tag] = reason
        elif squashed in brands or any(b and len(b) >= 5 and b in squashed for b in brands):
            rejected[tag] = "another channel's name"
        elif carriers[tag] >= CONSENSUS_CARRIERS and any(_stem(w) in vocab for w in words):
            # The topic's category tag: four or more winners agree on it ("invasive species" on
            # six carp videos), and the film shares a word with it.
            admit(tag, "competitor", score=round(score[tag], 2), videos=carriers[tag],
                  rule="consensus")
        elif not any(_stem(w) in core for w in words):
            rejected[tag] = "off the film's core topic"
        elif all(_stem(w) in vocab for w in words):
            # Measured on the Asian carp film (2026-10-11): admitting a tag that shared ONE word
            # if two winners used it let in "blue catfish", "living fossil" and "carp fishing" --
            # popular, and not this film. Every content word must be ours.
            admit(tag, "competitor", score=round(score[tag], 2), videos=carriers[tag])
        else:
            rejected[tag] = "not claimed by our film"
    # (A tag that is on-topic but carries a word the film never says is rejected above.)
    for tag in (_norm(t) for t in pipeline_tags or []):
        reason = excluded(tag)
        if reason:
            rejected.setdefault(tag, reason)
        else:
            admit(tag, "pipeline")
    for tag in reserved:
        if tag not in sources:
            chosen.append(tag)
            sources[tag] = {"source": "brand" if tag == brand else
                            "format" if tag == "shorts" else "audience"}
    return {"tags": chosen, "sources": sources, "rejected": rejected,
            "harvested_videos": len(videos)}
