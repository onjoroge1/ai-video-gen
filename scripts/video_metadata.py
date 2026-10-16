"""Read-only metadata lookup: how successful videos structure their titles, tags and descriptions.

Replaces pasting links one at a time into mattw.io/youtube-metadata. Takes any mix of video links,
video IDs, channel links and @handles, expands each channel to its latest uploads, and records per
video what that tool shows (tags, languages, localizations, category, caption flag, license,
thumbnail) plus an analysis of the title and description and the video's standing on its own
channel (outlier multiple = views / that channel's median for the same kind, long-form or Short).
Across the set it reports patterns, a top vs bottom quartile comparison for channel inputs, and,
with --compare-ours, the same features for our World and History public long-form films.

    python3 scripts/video_metadata.py https://youtu.be/49_Ph2q6uIM @inkexplainer96 \\
        [--channel-uploads 50] [--captions] [--compare-ours] [--name ink-explainer] \\
        [--out DIR] [--channel world|history] [--no-baseline] [--json]

Writes <out>/<YYYY-MM-DD>_<name>/report.md and videos.json, prints a one-screen summary, the
report path and the API quota units used.

Read-only by construction: every call goes through ReadOnlyYouTube, which exposes only
<resource>().list() for videos, channels, playlistItems, videoCategories and captions, refuses
anything else, and counts quota units (1 per list call; captions.list is 50, so --captions is
capped by --captions-max). Credentials come from youtube_upload._creds. No model is called.

Inputs: youtube.com/watch?v=ID (any extra params), youtu.be/ID, /shorts/ID, /embed/ID, /live/ID,
m./music. hosts, bare 11-character IDs; youtube.com/channel/UC..., youtube.com/@handle (with
/videos etc.), bare @handle, bare UC IDs, /user/NAME and /c/NAME (tried as @NAME).

A channel seen only through a video input gets its latest uploads fetched as a baseline for the
median (about 3 units per channel); --no-baseline skips that, and such a video then has no
outlier multiple. All numbers are observations about the fetched set, not causes.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import statistics
import sys
import unicodedata
from urllib.parse import parse_qs, unquote, urlparse

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPTS)
if SCRIPTS not in sys.path:
    sys.path[:0] = [SCRIPTS]     # (slice assignment: this module names no write-like method)
import youtube_upload  # noqa: E402  (credentials and our channel's upload list; stdlib-only import)
from youtube_channels import CHANNELS  # noqa: E402

SHORT_MAX_SEC = 180          # same line as youtube_channel_report.py: <= 3 minutes is a Short
MEDIAN_MIN = 3               # fewer videos of a kind than this gives no channel median
QUARTILE_MIN_LONG = 8        # a channel needs this many long-form uploads for a quartile split
QUARTILE_MIN_AGE_DAYS = 28   # younger uploads are still collecting views: left out of that split
CAPTIONS_MAX_DEFAULT = 10
VIDEO_PARTS = "snippet,contentDetails,statistics,status,topicDetails,localizations"
CHANNEL_PARTS = "snippet,statistics,contentDetails"
LOCAL_CLONE_YT = os.path.expanduser("~/ai-video-gen-local/jobs/yt")

# videoCategories for regionCode=US. Unknown ids fall back to one videoCategories.list call.
CATEGORY_NAMES = {
    "1": "Film & Animation", "2": "Autos & Vehicles", "10": "Music", "15": "Pets & Animals",
    "17": "Sports", "18": "Short Movies", "19": "Travel & Events", "20": "Gaming",
    "21": "Videoblogging", "22": "People & Blogs", "23": "Comedy", "24": "Entertainment",
    "25": "News & Politics", "26": "Howto & Style", "27": "Education",
    "28": "Science & Technology", "29": "Nonprofits & Activism", "30": "Movies",
    "31": "Anime/Animation", "32": "Action/Adventure", "33": "Classics", "34": "Comedy",
    "35": "Documentary", "36": "Drama", "37": "Family", "38": "Foreign", "39": "Horror",
    "40": "Sci-Fi/Fantasy", "41": "Thriller", "42": "Shorts", "43": "Shows", "44": "Trailers",
}

# ---------------------------------------------------------------------------------------------
# Quota and the read-only client
# ---------------------------------------------------------------------------------------------

UNIT_COST = {"videos": 1, "channels": 1, "playlistItems": 1, "videoCategories": 1, "captions": 50}


class Quota:
    """Data API units spent by this run (every list call costs its unit even when it fails)."""

    def __init__(self):
        self.calls: collections.Counter = collections.Counter()

    def add(self, resource: str) -> None:
        self.calls[resource] += 1

    @property
    def units(self) -> int:
        return sum(UNIT_COST[name] * count for name, count in self.calls.items())

    def by_method(self) -> dict:
        return {f"{name}.list": {"calls": count, "units": UNIT_COST[name] * count}
                for name, count in sorted(self.calls.items())}

    def summary(self) -> str:
        if not self.calls:
            return "0 units"
        parts = ", ".join(f"{name}.list x{count}" + (f" @{UNIT_COST[name]}" if UNIT_COST[name] != 1 else "")
                          for name, count in sorted(self.calls.items()))
        return f"{self.units} units ({parts})"


class ReadOnlyYouTube:
    """The only door to YouTube: <resource>().list(...).execute() for the read resources, counted."""

    def __init__(self, yt, quota: Quota | None = None):
        self._yt = yt
        self.quota = quota if quota is not None else Quota()

    def __getattr__(self, resource):
        if resource.startswith("_") or resource not in UNIT_COST:
            raise AttributeError(f"video_metadata is read-only and does not use {resource!r}")

        def factory():
            return _ListOnly(getattr(self._yt, resource)(), resource, self.quota)
        return factory


class _ListOnly:
    def __init__(self, inner, resource: str, quota: Quota):
        self._inner, self._resource, self._quota = inner, resource, quota

    def list(self, **kwargs):
        return _Counted(self._inner.list(**kwargs), self._resource, self._quota)

    def __getattr__(self, method):
        if method.startswith("_"):
            raise AttributeError(method)
        raise PermissionError(f"{self._resource}.{method} refused: video_metadata only lists")


class _Counted:
    def __init__(self, request, resource: str, quota: Quota):
        self._request, self._resource, self._quota = request, resource, quota

    def execute(self):
        self._quota.add(self._resource)
        return self._request.execute()


# ---------------------------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------------------------

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
DASH_VIDEO_ID_RE = re.compile(r"^-[A-Za-z0-9_][A-Za-z0-9_-]{9}$")   # a bare ID argparse would misread
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
HANDLE_RE = re.compile(r"^@[\w.\-\u00b7]{3,100}$")
YT_HOSTS = {"youtube.com", "youtu.be", "youtube-nocookie.com"}
VIDEO_PATH_KINDS = {"shorts", "embed", "live", "v", "e"}
# Invisible characters that ride along when a link or handle is copied from a phone or a web page.
ZERO_WIDTH_RE = re.compile("[​‌‍‎‏⁠﻿­]")


def normalize_input(text: str) -> str:
    """NFKC (full-width '＠', '／', '：' and digits become ASCII) without zero-width characters,
    surrounding whitespace or wrapping quotes/angle brackets."""
    text = ZERO_WIDTH_RE.sub("", unicodedata.normalize("NFKC", text or ""))
    return text.strip().strip("<>\"'").strip()


def parse_input(text: str) -> tuple[str, str]:
    """('video', id) | ('channel', UC id) | ('handle', '@name') | ('username', name); else ValueError."""
    raw = normalize_input(text)
    if not raw:
        raise ValueError("empty input")
    if raw.startswith("@"):
        handle = unquote(re.split(r"[/?#]", raw, maxsplit=1)[0])
        if HANDLE_RE.match(handle):
            return "handle", handle
        raise ValueError(f"not a valid @handle: {text!r}")
    if CHANNEL_ID_RE.match(raw):
        return "channel", raw
    if VIDEO_ID_RE.match(raw):
        return "video", raw
    url = raw if re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I) else "https://" + raw
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    for prefix in ("www.", "m.", "music.", "gaming."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    if host not in YT_HOSTS:
        raise ValueError(f"not a YouTube video or channel: {text!r}")
    segments = [unquote(part) for part in parsed.path.split("/") if part]
    query = parse_qs(parsed.query)
    if host == "youtu.be":
        candidate = segments[0] if segments else ""
    elif (segments and segments[0] == "watch") or (not segments and "v" in query):
        candidate = (query.get("v") or [""])[0]
    elif len(segments) >= 2 and segments[0] in VIDEO_PATH_KINDS:
        candidate = segments[1]
    elif len(segments) >= 2 and segments[0] == "channel":
        if CHANNEL_ID_RE.match(segments[1]):
            return "channel", segments[1]
        raise ValueError(f"not a channel id in {text!r}")
    elif segments and segments[0].startswith("@"):
        if HANDLE_RE.match(segments[0]):
            return "handle", segments[0]
        raise ValueError(f"not a valid @handle in {text!r}")
    elif len(segments) >= 2 and segments[0] == "user":
        return "username", segments[1]
    elif len(segments) >= 2 and segments[0] == "c":
        return "handle", "@" + segments[1]   # custom URLs usually equal the handle; resolution says if not
    else:
        raise ValueError(f"unsupported YouTube link (playlist, search or home page?): {text!r}")
    if VIDEO_ID_RE.match(candidate):
        return "video", candidate
    raise ValueError(f"no video id in {text!r}")


def parse_inputs(texts: list[str]) -> dict:
    """{"videos": [ids], "channels": [(kind, value)], "errors": [reasons]}, input order, deduplicated."""
    videos, channels, errors, seen = [], [], [], set()
    for text in texts:
        try:
            kind, value = parse_input(text)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        key = (kind, value.lower() if kind in ("handle", "username") else value)
        if key in seen:
            continue
        seen.add(key)
        if kind == "video":
            videos.append(value)
        else:
            channels.append((kind, value))
    return {"videos": videos, "channels": channels, "errors": errors}


# ---------------------------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------------------------

def iso_duration_seconds(value: str | None) -> int:
    m = re.match(r"^P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$", value or "")
    if not m:
        return 0
    weeks, days, hours, minutes, seconds = m.groups()
    return int((int(weeks or 0) * 7 + int(days or 0)) * 86400 + int(hours or 0) * 3600
               + int(minutes or 0) * 60 + float(seconds or 0))


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def median(values) -> float | None:
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None


def _parse_time(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _rate(part, whole) -> float | None:
    return round(part / whole, 5) if part is not None and whole else None


# ---------------------------------------------------------------------------------------------
# Title analysis
# ---------------------------------------------------------------------------------------------

# One glyph: a base emoji with its optional variation selector and skin-tone modifier
# (U+1F3FB-1F3FF), and any zero-width-joiner sequence, so "\uD83D\uDC47\uD83C\uDFFE" and "\uD83D\uDC68\u200D\uD83D\uDC69\u200D\uD83D\uDC67" count once.
_EMOJI_CHAR = ("[\U0001F000-\U0001F3FA\U0001F400-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF"
               "\u2300-\u23FF\u3030\u303D\u3297\u3299]\ufe0f?[\U0001F3FB-\U0001F3FF]?")
EMOJI_RE = re.compile(f"(?:{_EMOJI_CHAR}(?:\u200D{_EMOJI_CHAR})*|[#*0-9]\ufe0f\u20e3)")
NUMBER_WORDS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                "eleven", "twelve", "thirteen", "fifteen", "twenty", "thirty", "fifty", "hundred",
                "hundreds", "thousand", "thousands", "million", "millions", "billion", "billions",
                "trillion", "dozen", "dozens"}
# "one" is not a count in "No One...", "The One Mistake", "One of the...".
ONE_NOT_A_COUNT_BEFORE = {"no", "the", "any", "every", "each", "some", "this", "that"}
# A period after these does not end a title sentence ("Mr. Smith", "Ep. 3").
TITLE_ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "mt", "jr", "sr", "vs", "ep", "pt", "vol"}
WH_WORDS = {"what", "why", "how", "when", "who", "where", "which"}
AUX_WORDS = {"is", "are", "can", "could", "do", "does", "did", "was", "were", "should", "would",
             "will", "has", "have", "had"}
HOOK_TERMS = ["actually", "real reason", "the reason", "secret", "never", "truth", "nobody",
              "no one", "hidden", "mistake", "really", "finally", "explained", "what happened",
              "surprising", "shocking", "insane", "worst", "dark", "forgotten", "untold",
              "accidentally", "backfired", "disaster", "lie", "myth", "everything", "nothing"]
HOOK_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in sorted(HOOK_TERMS, key=len, reverse=True))
                     + r")\b", re.I)
YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})s?\b")
YOU_RE = re.compile(r"\b(you|your|you're|youre|yourself|you'd|you'll|you’d|you’re|you’ll)\b", re.I)
HASHTAG_RE = re.compile(r"(?<![\w&#/])#(\w*[^\W\d_]\w*)")
SENTENCE_END_RE = re.compile(r"(?<=[a-z0-9)\"'”’])[.?!](?=\s+[A-Z0-9\"'“‘(]|\s*$)")


def _word_tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text)


def analyze_title(title: str) -> dict:
    title = title or ""
    plain = HASHTAG_RE.sub(" ", title)
    words = _word_tokens(plain)
    lowered = [w.lower() for w in words]
    first = lowered[0] if lowered else ""
    counts = [w in NUMBER_WORDS and not (w == "one" and (
        (i and lowered[i - 1] in ONE_NOT_A_COUNT_BEFORE) or lowered[i + 1:i + 2] == ["of"]))
        for i, w in enumerate(lowered)]
    if first[:1].isdigit() or (counts and counts[0]):
        starts = "number"
    elif first in WH_WORDS:
        starts = first
    elif first == "the":
        starts = "the"
    elif first in ("a", "an"):
        starts = "a/an"
    elif first in ("this", "these", "that", "those"):
        starts = "this/that"
    elif first in ("you", "your", "you're"):
        starts = "you"
    elif first in ("i", "i'm", "my", "we", "our"):
        starts = "i/we"
    elif first in AUX_WORDS:
        starts = "yes/no question"
    else:
        starts = "other"
    has_digits = bool(re.search(r"\d", plain))
    has_number_word = any(counts)
    caps_words = [w for w in words if len(w) >= 2 and sum(c.isalpha() for c in w) >= 2
                  and w.upper() == w and any(c.isupper() for c in w)]
    emoji = EMOJI_RE.findall(title)
    has_dash = bool(re.search(r"\s[-–—]\s", plain))
    # Count sentences, not terminators: "The Plan Worked. That Was the Problem" is two.
    cut = plain.strip()
    ends = [m.end() for m in SENTENCE_END_RE.finditer(cut)
            if (_word_tokens(cut[:m.start()]) or [""])[-1].lower() not in TITLE_ABBREVIATIONS]
    sentences = max(1, sum(1 for a, b in zip([0] + ends, ends + [len(cut)]) if _word_tokens(cut[a:b])))
    long_words = [w for w in words if len(w) >= 4 and w[:1].isalpha() and w[:1].lower() != w[:1].upper()]
    cap_share = (sum(w[:1].isupper() for w in long_words) / len(long_words)) if long_words else 0.0
    rest = [w for w in long_words[1:]] if long_words and words and long_words[0] == words[0] else long_words
    rest_share = (sum(w[:1].isupper() for w in rest) / len(rest)) if rest else 0.0
    cased = [c for c in plain if c.isalpha() and c.lower() != c.upper()]
    if len(words) >= 2 and cased and all(c.isupper() for c in cased):
        case_style = "upper"
    elif cap_share >= 0.8:
        case_style = "title"
    elif rest_share <= 0.4:
        case_style = "sentence"
    else:
        case_style = "mixed"
    stripped = plain.strip()
    # "What did Early Humans do when they got Sick" asks a question without the mark; "Why Ancient
    # Humans Were the Most Terrifying Animal" (wh-word, then no auxiliary) is a statement.
    has_question_mark = "?" in title
    question_shaped = first in WH_WORDS and lowered[1:2] and (lowered[1] in AUX_WORDS or lowered[1] == "happened")
    is_question = has_question_mark or bool(question_shaped)
    two_part = ":" in plain or "|" in plain or has_dash
    if is_question:
        form = "question"
    elif starts == "number":
        form = "number-led"
    elif two_part:
        form = "two-part (: | -)"
    elif sentences >= 2:
        form = "multi-sentence statement"
    else:
        form = "statement"
    return {
        "chars": len(title), "words": len(words), "is_question": is_question,
        "has_question_mark": has_question_mark,
        "ends_with": stripped[-1:] if stripped[-1:] in ("?", ".", "!") else "other",
        "starts_with": starts, "first_word": first,
        "has_digits": has_digits, "has_number_word": has_number_word,
        "has_number": has_digits or has_number_word,
        "caps_words": caps_words, "emoji": emoji, "emoji_count": len(emoji),
        "has_pipe": "|" in plain, "has_colon": ":" in plain, "has_dash": has_dash,
        "two_part": two_part, "hashtags": HASHTAG_RE.findall(title),
        "hook_words": sorted({m.lower() for m in HOOK_RE.findall(plain)}),
        "years": YEAR_RE.findall(plain), "second_person": bool(YOU_RE.search(plain)),
        "sentences": sentences, "case_style": case_style, "form": form,
    }


# ---------------------------------------------------------------------------------------------
# Description analysis
# ---------------------------------------------------------------------------------------------

URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"]+", re.I)
# A DOI ends at whitespace, a quote, or a URL query/fragment ("...001?via=ihub" is the same DOI).
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>?#&]+")
TS = r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})"
CHAPTER_START_RE = re.compile(rf"^\s*[\[(]?{TS}[\])]?(?=\s|$|[-–—:|.])")
CHAPTER_END_RE = re.compile(rf"(?:^|\s)[\[(]?{TS}[\])]?\s*$")
BULLETS = "▸►▶•·‣◦→➤➜➔✓✔-–—*>"
SEPARATOR_RE = re.compile(r"^[\s\-–—_=━─═*~.•·▬]{3,}$")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}")
SUBSCRIBE_RE = re.compile(r"\bsubscrib(?:e|ing)\b|sub_confirmation|notification bell|hit the bell|"
                          r"ring the bell|turn on notifications|join (?:this|the|our|my) channel|"
                          r"become a member", re.I)
# AI disclosure. "AI-generated", "text-to-speech" and "synthetic media" are often the topic or a
# sponsor read, so each form needs the video to be talking about itself:
#  - a label colon ("Narration: AI voice", "Voice: text-to-speech");
#  - a passive "AI illustrations were used ...", or YouTube's own "altered/synthetic" wording;
#  - a verb form ("uses AI-generated", "created with AI", "narrated using text-to-speech") only when
#    its sentence starts there, or names this video/channel, "we"/"I", or a media noun before it
#    ("This video uses ...", "Images generated with AI"). "Scammers used AI-generated voices",
#    "Deepfakes made with AI fool banks" and "the best text-to-speech apps" are not disclosures.
_AI_THING = (r"(?:AI[- ](?:generated|assisted|assistance|created|voice|voiced|narrat\w*|images?|"
             r"illustrations?|art(?:work)?|animation|visuals?|tools?)|generative AI|"
             r"synthetic\s+(?:voices?|narration|media|content|images?|visuals?)|text[- ]to[- ]speech)\b")
AI_LABEL_RE = re.compile(r":\s*" + _AI_THING, re.I)
AI_PASSIVE_RE = re.compile(r"\bAI[- ](?:generated|assisted|created|voice|voiced|narrat\w*|images?|"
                           r"illustrations?|art(?:work)?|animation|visuals?|tools?)\s+"
                           r"(?:was|were|is|are|has been|have been)\s+used\b"
                           r"|\baltered(?:/| or )synthetic\b|\b(?:with|using)\s+AI\s+assistance\b", re.I)
AI_VERB_RE = re.compile(
    r"\b(?:uses?|used|using|contains?|includes?|including|features?|featuring)\s+(?:some\s+|an?\s+)?"
    + _AI_THING
    + r"|\b(?:generated|created|made|produced|narrated|voiced|illustrated|animated|written)\s+"
      r"(?:with|using|by|via)\s+(?:the\s+help\s+of\s+|assistance\s+from\s+|an?\s+)?"
      r"(?:AI|artificial intelligence|generative AI|text[- ]to[- ]speech|synthetic\s+voices?)\b", re.I)
AI_SELF_RE = re.compile(r"\b(?:this|our)\s+(?:video|film|episode|documentary|short|channel|content|"
                        r"animation|story|narration|visuals?|images?|illustrations?|voice(?:over)?)\b"
                        r"|\b(?:we|i)\b", re.I)
AI_MEDIA_SUBJECT_RE = re.compile(
    r"(?:(?:all|the|some|most)\s+)?(?:images?|illustrations?|visuals?|art(?:work)?|animations?|"
    r"narration|voice(?:over)?s?|music|thumbnails?|footage|script|maps?)"
    r"(?:\s*(?:,|&|and)\s*\w+){0,3}(?:\s+(?:was|were|is|are|has been|have been))?", re.I)


def ai_disclosure(text: str) -> str:
    """The first AI-disclosure phrase in a description (see the comment above), or ''."""
    found = [m for m in (AI_LABEL_RE.search(text), AI_PASSIVE_RE.search(text)) if m]
    for m in AI_VERB_RE.finditer(text):
        before = re.split(r"[.!?\n]", text[:m.start()])[-1]
        core = _lead_strip(before)
        if not core or AI_SELF_RE.search(before) or AI_MEDIA_SUBJECT_RE.fullmatch(core):
            found.append(m)
            break
    return min(found, key=lambda m: m.start()).group(0) if found else ""
SPONSOR_RE = re.compile(r"\bsponsored by\b|\bfor sponsoring\b|"
                        r"\bsponsors?:|\baffiliate links?\b|\bas an amazon associate\b|\bpromo code\b|"
                        r"\bdiscount code\b|\bcoupon code\b|\buse (?:my )?code\b|\bpaid promotion\b|"
                        r"\b(?:earn|receive|get|make)s? (?:a )?(?:small )?commission\b|\bsmall commission\b|"
                        r"\bfree trial\b|amzn\.to|geni\.us", re.I)
CREDIT_RE = re.compile(r"^(?:animation|animated|animator|art(?:work)?|illustrations?|illustrated|"
                       r"illustrator|music|score|soundtrack|sound design|narration|narrated|narrator|"
                       r"voice ?over|voiced|voice|edit(?:ed|ing|or)|written|writer|writing|"
                       r"script(?:ed)?|research(?:ed|er)?|thumbnails?|produced|producer|directed|"
                       r"director|motion design|graphics|footage|credits?|special thanks)\b"
                       r"(?:(?:\s+\S+){0,3}?\s*(?:\bby\b|\bfrom\b)|[^\n:]{0,60}:\s*\S)", re.I)
# A source citation whose title happens to start with a credit word ("▸ Animation in Palaeolithic
# art: ... Azéma, 2012, Antiquity."): an "et al", a ", 2012" or a "(Cook, 2000)" marks a reference.
CREDITS_WORD_RE = re.compile(r"\bcredits?\b", re.I)    # "SOURCES & CREDITS" still lists credits
CITATION_RE = re.compile(r"\bet al\b|,\s*(?:1[5-9]|20)\d{2}\b|\([^()]*\b(?:1[5-9]|20)\d{2}[a-z]?\b[^()]*\)"
                         r"|\b10\.\d{4,9}/", re.I)
SOURCES_HEADER_RE = re.compile(r"\b(?:sources?|references?|research|bibliography|citations?|"
                               r"further reading|reading list|studies|papers|cited)\b", re.I)
PEOPLE_HEADER_RE = re.compile(r"\b(?:people|places|sites|locations|figures|characters|who'?s who|"
                              r"key players)\b", re.I)    # not a bare "mentioned": BOOKS MENTIONED
# A sources or people label in any case, with or without a colon, with a URL on the same line or the
# next: "Sources & further reading:" + link (Kurzgesagt), "References: https://ve42.co/X" (Veritasium),
# "Sources" over bullets. "Research" is left out ("Research by X", "Research shows ..."). With a colon
# the label may run 30 characters (no period: "References to the bounty appear in 1902 records." is
# prose); without one it may only add a connector ("Sources & further reading") or a word such as
# "below" or "mentioned", so "Sources say otherwise" and "Citations needed" are not labels.
_LABEL_TAIL = (r"\b(?:[^:.\n]{0,30}:|(?:\s*(?:&|and|\+|/)\s*\w+(?:\s+\w+)?)?"
               r"(?:\s+(?:below|here|used|cited|list|links?|mentioned|featured|referenced))?\s*$)")
SOURCES_LINE_RE = re.compile(r"^(?:sources?|references?|bibliography|citations?|further reading|"
                             r"reading list|works cited)" + _LABEL_TAIL, re.I)
PEOPLE_LINE_RE = re.compile(r"^(?:people|places|sites|locations|key figures|historical figures|"
                            r"characters|who'?s who|key players)" + _LABEL_TAIL, re.I)
SOCIAL_DOMAINS = {"instagram.com", "tiktok.com", "twitter.com", "x.com", "facebook.com", "fb.com",
                  "discord.gg", "discord.com", "threads.net", "linkedin.com", "reddit.com",
                  "bsky.app", "snapchat.com", "pinterest.com", "twitch.tv", "linktr.ee", "t.me",
                  "whatsapp.com"}
SUPPORT_DOMAINS = {"patreon.com", "ko-fi.com", "buymeacoffee.com", "paypal.me", "gofundme.com"}
YOUTUBE_DOMAINS = {"youtube.com", "youtu.be", "m.youtube.com"}


def _clean_url(url: str) -> str:
    url = url.rstrip(".,;:!?'\"»…")
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1].rstrip(".,;:!?")
    return url


def _domain(url: str) -> str:
    host = (urlparse(url if "://" in url else "http://" + url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _lead_strip(line: str) -> str:
    """The line without its emoji and without leading bullets or decoration."""
    return EMOJI_RE.sub("", line).strip().lstrip(BULLETS + " \u200d\ufe0f").strip()


def _is_credit(line: str) -> bool:
    """A short credit line ("Animation by X", "Music: Y"), not a citation that starts with a credit word."""
    core = _lead_strip(line)
    return len(line) <= 120 and bool(CREDIT_RE.match(core)) and not CITATION_RE.search(core)


def _is_chapter_line(line: str) -> bool:
    return bool(CHAPTER_START_RE.match(line) or CHAPTER_END_RE.search(line))


def _sources_label(line: str) -> bool:
    """A line that labels a sources section, in any layout (see SOURCES_LINE_RE)."""
    return not _is_chapter_line(line) and bool(SOURCES_LINE_RE.match(_lead_strip(line)))


def _people_label(line: str) -> bool:
    return not _is_chapter_line(line) and bool(PEOPLE_LINE_RE.match(_lead_strip(line)))


def _is_header(line: str, next_line: str = "") -> bool:
    s = line.strip()
    if not s or len(s) > 70 or URL_RE.search(s) or s.startswith("#") or s[0] in BULLETS:
        return False
    if _is_chapter_line(s) or SEPARATOR_RE.match(s):
        return False                                   # chapter lines (either timestamp side) are chapters
    core = _lead_strip(s).strip(" :-–—|")
    tokens = core.split()
    cased = [c for c in core if c.isalpha() and c.lower() != c.upper()]
    if sum(c.isalpha() for c in core) < 3:
        return False
    if cased and all(c.isupper() for c in cased) and len(tokens) <= 8:
        return True                                    # ALL-CAPS line, e.g. PEOPLE & SITES MENTIONED
    if EMOJI_RE.match(s) and len(tokens) <= 6:
        return True                                    # emoji-led short line, e.g. 🎨 Animation by X
    if len(tokens) <= 3 and CHAPTER_START_RE.match(next_line.strip()):
        return True                                    # Time stamps / Chapters, over the first timestamp
    # Sources:  Chapters:  Further reading:  -- but not a link label ("NC State Extension:" + URL
    # line), unless the label names a sources or people section ("Sources:" over a list of links)
    return (s.endswith(":") and len(tokens) <= 5
            and (not URL_RE.match(next_line.strip()) or _sources_label(s) or _people_label(s)))


def _timestamp_seconds(match) -> int:
    hours, minutes, seconds = match.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)


def _title_echo(line: str, title: str) -> bool:
    a = {w.lower() for w in _word_tokens(HASHTAG_RE.sub(" ", line))}
    b = {w.lower() for w in _word_tokens(HASHTAG_RE.sub(" ", title))}
    return bool(a and b) and len(a & b) / len(a | b) >= 0.6


def analyze_description(description: str, title: str = "") -> dict:
    text = description or ""
    lines = text.split("\n") if text else []
    nonblank = [line.strip() for line in lines if line.strip()]
    urls = [_clean_url(u) for u in URL_RE.findall(text)]
    domains = collections.Counter(_domain(u) for u in urls)
    no_urls = URL_RE.sub(" ", text)
    dois = list(dict.fromkeys(d.rstrip(".,;:)]'\"").lower() for d in DOI_RE.findall(text)))
    stamps = []
    for line in nonblank:
        match = CHAPTER_START_RE.match(line) or CHAPTER_END_RE.search(line)
        if match:
            stamps.append(_timestamp_seconds(match))
    if 0 in stamps:          # a chapter list starts at 0:00; a time in prose above it ("at 8:15") is not one
        stamps = stamps[stamps.index(0):]
    starts_zero = bool(stamps) and stamps[0] == 0
    ascending = all(b > a for a, b in zip(stamps, stamps[1:]))
    hashtags = HASHTAG_RE.findall(no_urls)
    last = nonblank[-1] if nonblank else ""
    hashtags_at_end = bool(last) and not HASHTAG_RE.sub("", last).strip(" ,.·|")
    credit_at = {i for i, line in enumerate(nonblank) if _is_credit(line)}
    # a credit ("🎨 Animation by X", "🎵 Music: Y") is listed as a credit, not as a section header
    header_at = {i for i, line in enumerate(nonblank) if i not in credit_at
                 and _is_header(line, nonblank[i + 1] if i + 1 < len(nonblank) else "")}
    headers = [nonblank[i] for i in sorted(header_at)]
    fold_lines = nonblank[:2]
    above_fold = " / ".join(fold_lines)
    if len(above_fold) > 150:
        above_fold = above_fold[:149].rstrip() + "…"
    ai = ai_disclosure(text)
    credit_lines, in_sources = [], False
    for i, line in enumerate(nonblank):
        if i in header_at or _sources_label(line):
            in_sources = ((bool(SOURCES_HEADER_RE.search(line)) or _sources_label(line))
                          and not CREDITS_WORD_RE.search(line))
        elif SEPARATOR_RE.match(line):
            in_sources = False
        if in_sources and line[0] in BULLETS:
            continue                                   # a bulleted reference under a Sources header
        if i in credit_at:
            credit_lines.append(line)
            in_sources = False                         # a credit line closes a sources list
    return {
        "chars": len(text), "words": len(_word_tokens(text)), "lines": len(lines),
        "nonblank_lines": len(nonblank),
        "above_fold": above_fold,
        "above_fold_has_url": any(URL_RE.search(line) for line in fold_lines),
        "above_fold_has_hashtag": any(HASHTAG_RE.search(URL_RE.sub(" ", line)) for line in fold_lines),
        "first_line_echoes_title": bool(nonblank) and bool(title) and _title_echo(nonblank[0], title),
        "section_headers": headers,
        "separator_lines": sum(1 for line in nonblank if SEPARATOR_RE.match(line)),
        "bullet_lines": sum(1 for line in nonblank if line[0] in BULLETS and len(line) > 2
                            and line[1] == " " and not SEPARATOR_RE.match(line)),
        "urls": urls, "url_count": len(urls), "domains": dict(domains.most_common()),
        "youtube_links": sum(n for d, n in domains.items() if d in YOUTUBE_DOMAINS),
        "dois": dois, "doi_count": len(dois),
        "chapter_count": len(stamps), "chapters_start_at_zero": starts_zero,
        "chapters_valid": len(stamps) >= 3 and starts_zero and ascending,
        "hashtags": hashtags, "hashtag_count": len(hashtags), "hashtags_at_end": hashtags_at_end,
        "emoji_count": len(EMOJI_RE.findall(text)),
        "has_sources": (any(SOURCES_HEADER_RE.search(h) for h in headers)
                        or any(_sources_label(line) for line in nonblank)),
        "has_people_places": (any(PEOPLE_HEADER_RE.search(h) for h in headers)
                              or any(_people_label(line) for line in nonblank)),
        "subscribe_cta": bool(SUBSCRIBE_RE.search(text)),
        "ai_disclosure": bool(ai), "ai_disclosure_phrase": ai,
        "sponsor_markers": sorted({m.lower() for m in SPONSOR_RE.findall(text)}),
        "social_links": sorted({d for d in domains if d in SOCIAL_DOMAINS}),
        "support_links": sorted({d for d in domains if d in SUPPORT_DOMAINS}),
        "credit_lines": credit_lines,
        "has_contact_email": bool(EMAIL_RE.search(no_urls)),
    }


# ---------------------------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------------------------

def _kind(duration: int, live: bool) -> str:
    if live or duration <= 0:
        return "other"
    return "short" if duration <= SHORT_MAX_SEC else "long"


def video_record(item: dict, now: dt.datetime, categories: dict | None = None,
                 caption_tracks: list | None = None) -> dict:
    """One videos.list item (parts VIDEO_PARTS) as a flat record with title/description analysis."""
    sn = item.get("snippet") or {}
    cd = item.get("contentDetails") or {}
    st = item.get("statistics") or {}
    status = item.get("status") or {}
    title, desc = sn.get("title") or "", sn.get("description") or ""
    published = _parse_time(sn.get("publishedAt") or "")
    age = round(max((now - published).total_seconds(), 0) / 86400, 1) if published else None
    duration = iso_duration_seconds(cd.get("duration"))
    live = (sn.get("liveBroadcastContent") or "none") != "none"
    views, likes, comments = (_int(st.get("viewCount")), _int(st.get("likeCount")),
                              _int(st.get("commentCount")))
    tags = list(sn.get("tags") or [])
    loc = item.get("localizations") or {}
    localized_titles = {code: (value or {}).get("title", "") for code, value in sorted(loc.items())}
    translated_titles = [c for c, t in localized_titles.items() if t and t.strip() != title.strip()]
    translated_descs = [c for c, value in sorted(loc.items())
                        if (value or {}).get("description")
                        and value["description"].strip() != desc.strip()]
    thumbs = sn.get("thumbnails") or {}
    best = next((k for k in ("maxres", "standard", "high", "medium", "default")
                 if (thumbs.get(k) or {}).get("url")), None)
    category_id = sn.get("categoryId") or ""
    names = categories or CATEGORY_NAMES
    vid = item.get("id", "")
    return {
        "id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "title": title,
        "channel_id": sn.get("channelId", ""), "channel_title": sn.get("channelTitle", ""),
        "published_at": sn.get("publishedAt", ""), "age_days": age,
        "duration_sec": duration, "kind": _kind(duration, live),
        "likely_short": 0 < duration <= SHORT_MAX_SEC,
        "shorts_hashtag": "#shorts" in (title + " " + desc).lower(),
        "views": views, "likes": likes, "comments": comments,
        "views_per_day": round(views / max(age or 0, 1.0), 1) if views is not None else None,
        "like_rate": _rate(likes, views), "comment_rate": _rate(comments, views),
        "category_id": category_id, "category_name": names.get(category_id, f"unknown ({category_id})"),
        "tags": tags, "tag_count": len(tags), "tag_chars": sum(len(t) for t in tags),
        "tag_limit_chars": (sum(len(t) + (2 if " " in t else 0) for t in tags)
                            + max(0, len(tags) - 1)),
        "default_language": sn.get("defaultLanguage"),
        "default_audio_language": sn.get("defaultAudioLanguage"),
        "localizations": list(localized_titles), "localization_count": len(localized_titles),
        "localized_titles": localized_titles,
        "translated_title_count": len(translated_titles),
        "localized_titles_differ": bool(translated_titles),
        "translated_description_count": len(translated_descs),
        "caption_flag": str(cd.get("caption", "")).lower() == "true",
        "caption_tracks": caption_tracks,
        "definition": cd.get("definition"), "licensed_content": cd.get("licensedContent"),
        "license": status.get("license"), "made_for_kids": status.get("madeForKids"),
        "privacy": status.get("privacyStatus"),
        "topic_categories": [unquote(u.rsplit("/", 1)[-1]).replace("_", " ")
                             for u in (item.get("topicDetails") or {}).get("topicCategories") or []],
        "thumbnail": (thumbs.get(best) or {}).get("url") if best else None,
        "thumbnail_size": best, "has_maxres_thumbnail": best == "maxres",
        "title_analysis": analyze_title(title),
        "description_analysis": analyze_description(desc, title),
        "description": desc,
        "outlier_multiple": None, "channel_median_views": None,
        "vpd_rank": None, "vpd_rank_of": None,
    }


def channel_record(item: dict, source: str) -> dict:
    sn = item.get("snippet") or {}
    st = item.get("statistics") or {}
    cid = item.get("id", "")
    return {
        "id": cid, "title": sn.get("title", ""), "handle": sn.get("customUrl"),
        "url": f"https://www.youtube.com/channel/{cid}",
        "subs": None if st.get("hiddenSubscriberCount") else _int(st.get("subscriberCount")),
        "total_views": _int(st.get("viewCount")), "video_count": _int(st.get("videoCount")),
        "created": (sn.get("publishedAt") or "")[:10], "country": sn.get("country"),
        "uploads_playlist": ((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads"),
        "source": source,
    }


def add_channel_context(records: list[dict], channels: dict, uploads: dict) -> None:
    """Channel medians per kind and each video's outlier multiple and views-per-day rank, in place.

    `records` is the analyzed set; `uploads` maps channel id to that channel's fetched upload
    records (they may be the same dicts). The median is over the fetched uploads; with none, over
    the analyzed videos of that channel. Fewer than MEDIAN_MIN videos of a kind gives no median."""
    by_channel: dict = collections.defaultdict(list)
    for record in records:
        by_channel[record["channel_id"]].append(record)
    for cid in list(dict.fromkeys(list(by_channel) + list(uploads))):
        own, ups = by_channel.get(cid, []), uploads.get(cid) or []
        basis = ups or own
        if cid not in channels:
            channels[cid] = {"id": cid, "source": "seen",
                             "title": next((r["channel_title"] for r in own + ups), cid)}
        channel = channels[cid]
        channel["median_basis"] = (f"latest {len(ups)} uploads" if ups
                                   else f"{len(own)} analyzed video(s) only")
        for kind in ("long", "short"):
            views = [r["views"] for r in basis if r["kind"] == kind and r["views"] is not None]
            channel[f"n_{kind}"] = len(views)
            channel[f"median_{kind}"] = median(views) if len(views) >= MEDIAN_MIN else None
        pool = list({r["id"]: r for r in ups + own}.values())
        ranked = sorted(pool, key=lambda r: -(r["views_per_day"] or 0))
        ranks = {r["id"]: i + 1 for i, r in enumerate(ranked)}
        for record in own + ups:
            med = channel.get(f"median_{record['kind']}")
            record["channel_median_views"] = med
            record["outlier_multiple"] = (round(record["views"] / med, 2)
                                          if med and record["views"] is not None else None)
            record["vpd_rank"], record["vpd_rank_of"] = ranks[record["id"]], len(pool)


# ---------------------------------------------------------------------------------------------
# Group features, comparisons and patterns
# ---------------------------------------------------------------------------------------------

def _t(key):
    return lambda r: r["title_analysis"][key]


def _d(key):
    return lambda r: r["description_analysis"][key]


# (key, label, type, getter, minimum absolute difference worth stating for numbers)
FEATURES = [
    ("title_chars", "title length (chars)", "num", _t("chars"), 5),
    ("title_words", "title words", "num", _t("words"), 2),
    ("tag_count", "tags", "num", lambda r: r["tag_count"], 2),
    ("tag_limit_chars", "tag characters (approx, of 500)", "num", lambda r: r["tag_limit_chars"], 30),
    ("localization_count", "localizations", "num", lambda r: r["localization_count"], 1),
    ("duration_min", "duration (min)", "num", lambda r: round(r["duration_sec"] / 60, 1), 1),
    ("desc_chars", "description length (chars)", "num", _d("chars"), 200),
    ("desc_urls", "description URLs", "num", _d("url_count"), 1),
    ("desc_hashtags", "description hashtags", "num", _d("hashtag_count"), 1),
    ("desc_dois", "DOIs", "num", _d("doi_count"), 1),
    ("desc_headers", "description section headers", "num", lambda r: len(r["description_analysis"]["section_headers"]), 1),
    ("age_days", "age in days (confound: older videos accumulate views)", "num", lambda r: r["age_days"], 7),
    ("title_question", "title is a question", "bool", _t("is_question"), 0),
    ("title_number", "title has a number", "bool", _t("has_number"), 0),
    ("title_two_part", "title split by ':' '|' or a dash", "bool", _t("two_part"), 0),
    ("title_multi_sentence", "title has 2+ sentences", "bool", lambda r: r["title_analysis"]["sentences"] >= 2, 0),
    ("title_you", "title says 'you'", "bool", _t("second_person"), 0),
    ("title_hook", "title has a hook word (actually, secret, never...)", "bool", lambda r: bool(r["title_analysis"]["hook_words"]), 0),
    ("title_year", "title mentions a year", "bool", lambda r: bool(r["title_analysis"]["years"]), 0),
    ("title_caps", "title has an ALL-CAPS word", "bool", lambda r: bool(r["title_analysis"]["caps_words"]), 0),
    ("title_emoji", "title has emoji", "bool", lambda r: r["title_analysis"]["emoji_count"] > 0, 0),
    ("translated", "translated titles (localizations)", "bool", lambda r: r["translated_title_count"] > 0, 0),
    ("audio_language", "default audio language set", "bool", lambda r: bool(r["default_audio_language"]), 0),
    ("captions_flag", "caption flag set", "bool", lambda r: r["caption_flag"], 0),
    ("desc_sources", "sources/references section", "bool", _d("has_sources"), 0),
    ("desc_people", "people/places section", "bool", _d("has_people_places"), 0),
    ("desc_chapters", "valid chapters (0:00 start, 3+)", "bool", _d("chapters_valid"), 0),
    ("desc_subscribe", "subscribe CTA", "bool", _d("subscribe_cta"), 0),
    ("desc_ai", "AI disclosure line", "bool", _d("ai_disclosure"), 0),
    ("desc_sponsor", "sponsor/affiliate marker", "bool", lambda r: bool(r["description_analysis"]["sponsor_markers"]), 0),
    ("desc_social", "social links", "bool", lambda r: bool(r["description_analysis"]["social_links"]), 0),
    ("desc_credits", "credit line (e.g. 'Animation by')", "bool", lambda r: bool(r["description_analysis"]["credit_lines"]), 0),
    ("desc_yt_links", "links to other YouTube videos", "bool", lambda r: r["description_analysis"]["youtube_links"] > 0, 0),
    ("desc_echo", "description opens by restating the title", "bool", _d("first_line_echoes_title"), 0),
    ("desc_fold_url", "URL above the fold", "bool", _d("above_fold_has_url"), 0),
    ("title_form", "title form", "cat", _t("form"), 0),
    ("title_start", "title opener", "cat", _t("starts_with"), 0),
    ("category", "category", "cat", lambda r: r["category_name"], 0),
    ("default_language", "default language", "cat", lambda r: r["default_language"] or "(none)", 0),
]


def summarize_group(records: list[dict]) -> dict:
    """{feature key: summary} — median for numbers, k/n for flags, distribution for categories."""
    out = {}
    for key, label, kind, getter, _ in FEATURES:
        values = [getter(r) for r in records]
        if kind == "num":
            vals = [v for v in values if v is not None]
            med = median(vals)
            out[key] = {"label": label, "type": kind, "n": len(vals),
                        "value": round(med, 1) if med is not None else None}
        elif kind == "bool":
            k = sum(1 for v in values if v)
            out[key] = {"label": label, "type": kind, "n": len(values), "k": k,
                        "value": round(k / len(values), 3) if values else None}
        else:
            dist = collections.Counter(values).most_common()
            out[key] = {"label": label, "type": kind, "n": len(values),
                        "value": dist[0][0] if dist else None, "k": dist[0][1] if dist else 0,
                        "dist": dict(dist)}
    return out


def _fmt_num(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value:,}" if isinstance(value, int) else f"{value:,.1f}"


CONTEXT_FEATURES = {"age_days"}   # stated after the differences, never as one


def compare_groups(a: list[dict], b: list[dict], a_label: str, b_label: str,
                   min_share_diff: float = 0.25, min_ratio: float = 1.25) -> dict:
    """Side-by-side feature summaries and the differences worth stating, largest first.

    Stated: a flag whose shares differ by >= min_share_diff with at least 2 videos behind the
    larger count (one video in a group of two is not a pattern); a median that differs by a ratio
    >= min_ratio and the feature's minimum step; a most-common category that differs (each held
    by 2+ videos). Full-separation flags sort before medians; age is listed last as context."""
    sa, sb = summarize_group(a), summarize_group(b)
    min_abs = {key: m for key, _, _, _, m in FEATURES}
    rows, observations = [], []
    for key, label, kind, _, _ in FEATURES:
        x, y = sa[key], sb[key]
        rows.append({"key": key, "label": label, "type": kind, a_label: x, b_label: y})
        if not a or not b or x["value"] is None or y["value"] is None:
            continue
        observation = None
        if kind == "num":
            hi, lo = max(x["value"], y["value"]), min(x["value"], y["value"])
            if min(x["n"], y["n"]) >= 2 and hi - lo >= min_abs[key] and (lo <= 0 or hi / lo >= min_ratio):
                observation = {
                    "score": min((hi - lo) / hi, 0.95) if hi else 0,
                    "text": (f"{label}: median {_fmt_num(x['value'])} in {a_label} (n={x['n']}) vs "
                             f"{_fmt_num(y['value'])} in {b_label} (n={y['n']})")}
        elif kind == "bool":
            diff = abs(x["value"] - y["value"])
            if diff >= min_share_diff and max(x["k"], y["k"]) >= 2:
                observation = {
                    "score": diff,
                    "text": (f"{label}: {x['k']}/{x['n']} in {a_label} vs {y['k']}/{y['n']} "
                             f"in {b_label}")}
        else:
            share_x, share_y = x["k"] / x["n"], y["dist"].get(x["value"], 0) / y["n"]
            differs = x["value"] != y["value"] and min(x["k"], y["k"]) >= 2
            shifts = (x["value"] == y["value"] and abs(share_x - share_y) >= min_share_diff
                      and max(x["k"], y["k"]) >= 2)
            if differs or shifts:
                observation = {
                    "score": max(abs(share_x - share_y), 0.3),
                    "text": (f"{label}: most often '{x['value']}' in {a_label} ({x['k']}/{x['n']}); "
                             f"'{y['value']}' in {b_label} ({y['k']}/{y['n']})")}
        if observation:
            if key in CONTEXT_FEATURES:
                observation = {"score": -1.0, "text": "context, not a difference to copy: " + observation["text"]}
            observations.append({"key": key, **observation})
    observations.sort(key=lambda o: -o["score"])
    return {"labels": [a_label, b_label], "n": {a_label: len(a), b_label: len(b)},
            "rows": rows, "observations": observations}


FEATURE_BY_KEY = {key: (kind, getter) for key, _, kind, getter, _ in FEATURES}


def _era_note(key: str, long_form: list[dict]) -> str:
    """' (era: ...)' when the videos on the rarer side of a flag are all among a channel's oldest or
    newest uploads -- a template change over time, which a quartile split can mistake for performance.

    The rarer side (the videos with the flag, or without it) needs 2+ videos and must sit entirely
    within the oldest or newest max(m, n // 4) uploads; '' otherwise. A count (URLs, DOIs, tags) is
    read as a flag "has any": the 4 oldest uploads having no URLs at all is a template era too."""
    kind, getter = FEATURE_BY_KEY.get(key, (None, None))
    dated = [r for r in long_form if r.get("age_days") is not None]
    if kind not in ("bool", "num") or len(dated) < QUARTILE_MIN_LONG:
        return ""
    by_age = sorted(dated, key=lambda r: r["age_days"])          # newest first
    have = {r["id"] for r in by_age if (getter(r) or 0) > 0}
    lack = {r["id"] for r in by_age} - have
    words = ("with it", "without it") if kind == "bool" else ("with any", "with none")
    side, ids = (words[0], have) if len(have) <= len(lack) else (words[1], lack)
    m, n = len(ids), len(by_age)
    if m < 2:
        return ""
    span = max(m, n // 4)
    for end, group in (("newest", by_age[:span]), ("oldest", by_age[-span:])):
        if ids <= {r["id"] for r in group}:
            return f" (era: the {m} uploads {side} are all among the {span} {end} of {n})"
    return ""


def quartile_comparison(channel: dict, uploads: list[dict]) -> dict:
    """Top vs bottom quartile of a channel's long-form uploads by outlier multiple."""
    measured = [r for r in uploads if r["kind"] == "long" and r.get("outlier_multiple") is not None]
    # Lifetime views of a 10-day-old upload are not comparable with a 5-month-old one's: an upload
    # younger than QUARTILE_MIN_AGE_DAYS would sit in the bottom quartile only for being new.
    young = [r for r in measured if r.get("age_days") is not None and r["age_days"] < QUARTILE_MIN_AGE_DAYS]
    young_ids = {r["id"] for r in young}
    long_form = [r for r in measured if r["id"] not in young_ids]

    def brief(rows):
        return [{"id": r["id"], "title": r["title"], "outlier_multiple": r["outlier_multiple"],
                 "views": r["views"], "age_days": r["age_days"]} for r in rows]
    base = {"channel_id": channel.get("id"), "channel_title": channel.get("title"),
            "n_long": len(long_form), "min_age_days": QUARTILE_MIN_AGE_DAYS,
            "young": brief(sorted(young, key=lambda r: r["age_days"]))}
    if len(long_form) < QUARTILE_MIN_LONG:
        return {**base, "skipped": f"{len(long_form)} long-form uploads with a median"
                                   + (f" and {QUARTILE_MIN_AGE_DAYS}+ days old" if young else "")
                                   + f"; needs {QUARTILE_MIN_LONG}"}
    ranked = sorted(long_form, key=lambda r: (-r["outlier_multiple"], -(r["views"] or 0)))
    q = len(ranked) // 4
    top, bottom = ranked[:q], ranked[-q:]
    compared = compare_groups(top, bottom, "top", "bottom")
    rows = {row["key"]: row for row in compared["rows"]}
    for observation in compared["observations"]:
        row = rows.get(observation["key"]) or {}
        if row.get("type") == "num" and 0 not in (row["top"]["value"], row["bottom"]["value"]):
            continue                    # a count gets an era note only when one side has none at all
        note = _era_note(observation["key"], long_form)
        if note:
            observation["text"] += note
            observation["era"] = note.strip(" ()")
    return {**base, "q": q, "top": brief(top), "bottom": brief(bottom), **compared}


def compare_with_ours(theirs: list[dict], ours: dict) -> dict:
    """Theirs (the analyzed long-form) against our public long-form films, per channel and combined."""
    theirs_long = [r for r in theirs if r["kind"] == "long"]
    ours_all = [r for entry in ours.values() for r in entry.get("videos") or []]
    result = compare_groups(theirs_long, ours_all, "theirs", "ours")
    result["columns"] = {name: summarize_group(entry.get("videos") or [])
                         for name, entry in ours.items()}
    result["n_columns"] = {name: len(entry.get("videos") or []) for name, entry in ours.items()}
    return result


def _dist(values) -> dict:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0, "min": None, "median": None, "max": None}
    return {"n": len(vals), "min": min(vals), "median": median(vals), "max": max(vals)}


def _bucket(value: float, edges: list[tuple[float, str]], last: str) -> str:
    for edge, label in edges:
        if value <= edge:
            return label
    return last


TAG_BUCKETS = ([(0, "0"), (5, "1-5"), (10, "6-10"), (20, "11-20")], "21+")
DURATION_BUCKETS = ([(60, "<=1 min"), (180, "1-3 min"), (480, "3-8 min"), (720, "8-12 min"),
                     (1200, "12-20 min")], "20+ min")
DESCRIPTION_FLAGS = [
    ("section headers", lambda a: bool(a["section_headers"])),
    ("sources/references section", lambda a: a["has_sources"]),
    ("people/places section", lambda a: a["has_people_places"]),
    ("DOIs", lambda a: a["doi_count"] > 0),
    ("any URL", lambda a: a["url_count"] > 0),
    ("chapters (any)", lambda a: a["chapter_count"] > 0),
    ("valid chapters", lambda a: a["chapters_valid"]),
    ("hashtags", lambda a: a["hashtag_count"] > 0),
    ("hashtag block at the end", lambda a: a["hashtags_at_end"]),
    ("emoji", lambda a: a["emoji_count"] > 0),
    ("subscribe CTA", lambda a: a["subscribe_cta"]),
    ("AI disclosure", lambda a: a["ai_disclosure"]),
    ("sponsor/affiliate marker", lambda a: bool(a["sponsor_markers"])),
    ("social links", lambda a: bool(a["social_links"])),
    ("support links (Patreon etc.)", lambda a: bool(a["support_links"])),
    ("credit lines", lambda a: bool(a["credit_lines"])),
    ("links to other YouTube videos", lambda a: a["youtube_links"] > 0),
    ("contact email", lambda a: a["has_contact_email"]),
    ("opens by restating the title", lambda a: a["first_line_echoes_title"]),
    ("URL above the fold", lambda a: a["above_fold_has_url"]),
]


def _normalize_header(header: str) -> str:
    return re.sub(r"\s+", " ", _lead_strip(header).strip(" :-–—|.")).upper()


def patterns(records: list[dict]) -> dict:
    n = len(records)
    titles = [r["title_analysis"] for r in records]
    descs = [r["description_analysis"] for r in records]
    count = collections.Counter
    return {
        "n": n, "kinds": dict(count(r["kind"] for r in records).most_common()),
        "tags": {
            "count": _dist([r["tag_count"] for r in records]),
            "buckets": dict(count(_bucket(r["tag_count"], *TAG_BUCKETS) for r in records).most_common()),
            "limit_chars": _dist([r["tag_limit_chars"] for r in records]),
            "most_common": dict(count(t.lower() for r in records for t in r["tags"]).most_common(15)),
        },
        "title": {
            "forms": dict(count(t["form"] for t in titles).most_common()),
            "starts_with": dict(count(t["starts_with"] for t in titles).most_common()),
            "case_style": dict(count(t["case_style"] for t in titles).most_common()),
            "chars": _dist([t["chars"] for t in titles]),
            "words": _dist([t["words"] for t in titles]),
            "flags": {
                "question": sum(t["is_question"] for t in titles),
                "number": sum(t["has_number"] for t in titles),
                "two-part (: | -)": sum(t["two_part"] for t in titles),
                "2+ sentences": sum(t["sentences"] >= 2 for t in titles),
                "says 'you'": sum(t["second_person"] for t in titles),
                "hook word": sum(bool(t["hook_words"]) for t in titles),
                "year": sum(bool(t["years"]) for t in titles),
                "ALL-CAPS word": sum(bool(t["caps_words"]) for t in titles),
                "emoji": sum(t["emoji_count"] > 0 for t in titles),
                "hashtag": sum(bool(t["hashtags"]) for t in titles),
            },
            "hook_words": dict(count(w for t in titles for w in t["hook_words"]).most_common()),
        },
        "languages": {
            "default_language": dict(count(r["default_language"] or "(none)" for r in records).most_common()),
            "default_audio_language": dict(count(r["default_audio_language"] or "(none)" for r in records).most_common()),
            "with_translated_titles": sum(r["translated_title_count"] > 0 for r in records),
            "localization_count": _dist([r["localization_count"] for r in records]),
            "localization_codes": dict(count(c for r in records for c in r["localizations"]).most_common()),
        },
        "categories": dict(count(r["category_name"] for r in records).most_common()),
        "duration": {
            "seconds": _dist([r["duration_sec"] for r in records if r["duration_sec"]]),
            "buckets": dict(count(_bucket(r["duration_sec"], *DURATION_BUCKETS)
                                  for r in records if r["duration_sec"]).most_common()),
        },
        "description": {
            "chars": _dist([a["chars"] for a in descs]),
            "url_count": _dist([a["url_count"] for a in descs]),
            "hashtag_count": _dist([a["hashtag_count"] for a in descs]),
            "features": {label: sum(1 for a in descs if test(a)) for label, test in DESCRIPTION_FLAGS},
            "headers": dict(count(_normalize_header(h) for a in descs
                                  for h in dict.fromkeys(a["section_headers"])).most_common(15)),
            "domains": dict(count(d for a in descs for d in a["domains"]).most_common(12)),
            "hashtags": dict(count(h.lower() for a in descs for h in a["hashtags"]).most_common(15)),
        },
    }


# ---------------------------------------------------------------------------------------------
# Fetch layer (takes an injected client; reaches YouTube only through .list().execute())
# ---------------------------------------------------------------------------------------------

def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def resolve_channels(yt, refs: list[tuple[str, str]]) -> tuple[dict, list[str]]:
    """{(kind, value): channels.list item} for channel ids, @handles and usernames, plus errors."""
    found, errors = {}, []
    ids = [value for kind, value in refs if kind == "channel"]
    for chunk in _chunks(ids, 50):
        items = {it["id"]: it for it in
                 yt.channels().list(part=CHANNEL_PARTS, id=",".join(chunk)).execute().get("items") or []}
        for cid in chunk:
            if cid in items:
                found[("channel", cid)] = items[cid]
            else:
                errors.append(f"channel {cid} not found")
    for kind, value in refs:
        if kind == "handle":
            response = yt.channels().list(part=CHANNEL_PARTS, forHandle=value).execute()
        elif kind == "username":
            response = yt.channels().list(part=CHANNEL_PARTS, forUsername=value).execute()
        else:
            continue
        items = response.get("items") or []
        if items:
            found[(kind, value)] = items[0]
        else:
            errors.append(f"{kind} {value} did not resolve to a channel")
    return found, errors


def upload_ids(yt, playlist_id: str, limit: int) -> list[str]:
    """The latest `limit` video ids of an uploads playlist (newest first)."""
    ids, token = [], None
    while len(ids) < limit:
        response = yt.playlistItems().list(part="contentDetails", playlistId=playlist_id,
                                           maxResults=min(50, limit - len(ids)),
                                           pageToken=token).execute()
        ids += [it["contentDetails"]["videoId"] for it in response.get("items") or []]
        token = response.get("nextPageToken")
        if not token:
            break
    return list(dict.fromkeys(ids))[:limit]


def fetch_videos(yt, ids: list[str]) -> dict:
    """{id: videos.list item}, 50 ids per call (1 unit each)."""
    out = {}
    for chunk in _chunks(list(dict.fromkeys(ids)), 50):
        for item in yt.videos().list(part=VIDEO_PARTS, id=",".join(chunk)).execute().get("items") or []:
            out[item["id"]] = item
    return out


QUOTA_REASONS = ("quotaExceeded", "dailyLimitExceeded")


def _quota_exhausted(exc: Exception) -> bool:
    """A 403 that will repeat for every later call today (so a per-item catch must not continue)."""
    return any(r in f"{getattr(exc, 'error_details', '')} {exc}" for r in QUOTA_REASONS)


def fetch_categories(yt, category_ids, warn=None) -> dict:
    """The static US category names, plus one videoCategories.list call for any id not in it."""
    names = dict(CATEGORY_NAMES)
    unknown = sorted({c for c in category_ids if c and c not in names})
    if unknown:
        try:
            for item in yt.videoCategories().list(part="snippet", id=",".join(unknown)).execute().get("items") or []:
                names[item["id"]] = item["snippet"]["title"]
        except Exception as exc:  # noqa: BLE001 - a name lookup must not sink the run
            if _quota_exhausted(exc):
                raise
            if warn:
                warn(f"videoCategories.list failed for {unknown}: {str(exc)[:120]}")
    return names


def fetch_caption_tracks(yt, video_id: str) -> list[dict]:
    """captions.list (50 units): the track languages and kinds, never the caption text."""
    tracks = []
    for item in yt.captions().list(part="snippet", videoId=video_id).execute().get("items") or []:
        sn = item.get("snippet") or {}
        tracks.append({"language": sn.get("language"), "kind": sn.get("trackKind"),
                       "name": sn.get("name") or "", "audio_track_type": sn.get("audioTrackType")})
    return tracks


def collect(yt, parsed: dict, *, uploads: int = 50, captions: bool = False,
            captions_max: int = CAPTIONS_MAX_DEFAULT, baseline: bool = True,
            now: dt.datetime | None = None, warn=None) -> dict:
    """Fetch everything the inputs need and build the records (no analysis across videos yet)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    warnings: list[str] = []

    def note(message):
        warnings.append(message)
        if warn:
            warn(message)

    found, errors = resolve_channels(yt, parsed["channels"])
    channel_items, channel_inputs, upload_lists = {}, [], {}
    for ref in parsed["channels"]:
        item = found.get(ref)
        if not item:
            continue
        cid = item["id"]
        channel_items[cid] = item
        if cid in upload_lists:
            continue
        channel_inputs.append({"input": ref[1], "channel_id": cid})
        playlist = ((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
        try:
            upload_lists[cid] = upload_ids(yt, playlist, uploads) if playlist and uploads > 0 else []
        except Exception as exc:  # noqa: BLE001 - one bad channel must not sink the run
            if _quota_exhausted(exc):
                raise
            errors.append(f"uploads of {ref[1]}: {str(exc)[:160]}")
            upload_lists[cid] = []
    items = fetch_videos(yt, parsed["videos"] + [v for ids in upload_lists.values() for v in ids])
    missing = [v for v in parsed["videos"] if v not in items]
    for vid in missing:
        errors.append(f"video {vid} not returned (private, deleted or a wrong id)")
    seen = [items[v]["snippet"]["channelId"] for v in parsed["videos"] if v in items]
    extra = [cid for cid in dict.fromkeys(seen) if cid not in channel_items]
    if extra:
        found_extra, errors_extra = resolve_channels(yt, [("channel", cid) for cid in extra])
        errors += errors_extra
        for (_, cid), item in found_extra.items():
            channel_items[cid] = item
    baseline_lists = {}
    if baseline and uploads > 0:
        for cid in extra:
            playlist = (((channel_items.get(cid) or {}).get("contentDetails") or {})
                        .get("relatedPlaylists") or {}).get("uploads")
            if not playlist:
                continue
            try:
                baseline_lists[cid] = upload_ids(yt, playlist, uploads)
            except Exception as exc:  # noqa: BLE001
                if _quota_exhausted(exc):
                    raise
                errors.append(f"baseline uploads of {cid}: {str(exc)[:160]}")
        more = [v for ids in baseline_lists.values() for v in ids if v not in items]
        if more:
            items = {**items, **fetch_videos(yt, more)}
    elif extra:
        note("--no-baseline: channels seen only through a video input have no upload median")
    categories = fetch_categories(yt, {(it.get("snippet") or {}).get("categoryId") for it in items.values()}, note)
    analyzed = list(dict.fromkeys([v for v in parsed["videos"] if v in items]
                                  + [v for ids in upload_lists.values() for v in ids if v in items]))
    tracks: dict = {}
    if captions and analyzed:
        take = analyzed[:max(0, captions_max)]
        note(f"--captions: captions.list costs 50 units per video; listing {len(take)} of "
             f"{len(analyzed)} (cap --captions-max {captions_max}, {50 * len(take)} units)")
        for vid in take:
            try:
                tracks[vid] = fetch_caption_tracks(yt, vid)
            except Exception as exc:  # noqa: BLE001 - e.g. 403 when the owner hides tracks
                if _quota_exhausted(exc):
                    raise
                tracks[vid] = [{"error": str(exc)[:160]}]
    records = {vid: video_record(item, now, categories, tracks.get(vid)) for vid, item in items.items()}
    channels = {cid: channel_record(item, "input" if cid in upload_lists else "seen")
                for cid, item in channel_items.items()}
    upload_records = {cid: [records[v] for v in ids if v in records]
                      for cid, ids in {**baseline_lists, **upload_lists}.items()}
    return {"now": now.isoformat(timespec="seconds"), "channels": channels, "records": records,
            "analyzed": analyzed, "inputs_videos": [v for v in parsed["videos"] if v in records],
            "channel_inputs": channel_inputs, "uploads": upload_records,
            "baseline_channels": list(baseline_lists), "missing": missing,
            "errors": errors, "warnings": warnings}


def collect_ours(clients: dict, now: dt.datetime, warn=None) -> dict:
    """Our public long-form films per channel (world/history), through youtube_upload.channel_uploads.
    A channel whose token fails (e.g. invalid_grant on the first execute) is skipped with a warning;
    the other channel's films are kept."""
    out = {}
    for name, yt in clients.items():
        cid = CHANNELS[name]["id"]
        try:
            uploads = youtube_upload.channel_uploads(yt, cid)
            public = [u["id"] for u in uploads if u.get("privacy") == "public"]
            response = yt.channels().list(part=CHANNEL_PARTS, id=cid).execute()
            channel = channel_record((response.get("items") or [{"id": cid}])[0], "ours")
            items = fetch_videos(yt, public)
            categories = fetch_categories(yt, {(it.get("snippet") or {}).get("categoryId")
                                               for it in items.values()}, warn)
        except Exception as exc:  # noqa: BLE001 - one channel's token must not drop the other's films
            if _quota_exhausted(exc):
                raise
            if warn:
                warn(f"--compare-ours: {name} failed: {str(exc)[:200]}")
            continue
        records = [video_record(items[v], now, categories) for v in public if v in items]
        long_form = [r for r in records if r["kind"] == "long"]
        channel["n_uploads"], channel["n_public"], channel["n_public_long"] = (
            len(uploads), len(public), len(long_form))
        add_channel_context(long_form, {cid: channel}, {cid: long_form})
        out[name] = {"channel": channel, "videos": long_form}
    return out


def analyze(collected: dict, *, name: str, inputs: list[str], token_channel: str,
            quota: Quota | None = None, ours: dict | None = None, ours_warnings: list | None = None,
            input_errors: list | None = None, uploads_limit: int = 50) -> dict:
    """Everything the report needs, from collected records (no I/O)."""
    records = collected["records"]
    analyzed = [records[v] for v in collected["analyzed"]]
    channels = collected["channels"]
    add_channel_context(analyzed, channels, collected["uploads"])
    quartiles = [quartile_comparison(channels[c["channel_id"]], collected["uploads"].get(c["channel_id"]) or [])
                 for c in collected["channel_inputs"]]
    result = {
        "generated": collected["now"], "name": name, "inputs": inputs,
        "token_channel": token_channel, "uploads_limit": uploads_limit,
        "input_errors": list(input_errors or []) + collected["errors"],
        "warnings": collected["warnings"] + list(ours_warnings or []),
        "channels": channels, "channel_inputs": collected["channel_inputs"],
        "inputs_videos": collected["inputs_videos"],
        "baseline_channels": collected["baseline_channels"],
        "baseline_video_count": len({r["id"] for c in collected["baseline_channels"]
                                     for r in collected["uploads"].get(c) or []}
                                    - set(collected["analyzed"])),
        "videos": analyzed, "patterns": patterns(analyzed),
        # Shorts (near-empty descriptions) would otherwise drown out how the long-form films look
        "patterns_by_kind": {kind: patterns(group) for kind in ("long", "short")
                             if (group := [r for r in analyzed if r["kind"] == kind])},
        "quartiles": quartiles,
        "ours": ours, "compare_ours": compare_with_ours(analyzed, ours) if ours else None,
    }
    if quota is not None:
        result["units"], result["quota"], result["calls"] = quota.units, quota.summary(), quota.by_method()
    return result


# ---------------------------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------------------------

def _n(value) -> str:
    return "-" if value is None else f"{value:,}" if isinstance(value, int) else _fmt_num(value)


def _abbr(value) -> str:
    if value is None:
        return "-"
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= size:
            return f"{value / size:.1f}{suffix}".replace(".0" + suffix, suffix)
    return f"{value:.0f}" if isinstance(value, float) else str(value)


def _pct(value) -> str:
    return "-" if value is None else f"{value * 100:.2f}%"


def _clock(seconds: int) -> str:
    hours, rest = divmod(int(seconds or 0), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _yn(value) -> str:
    return "yes" if value else "no"


def _share(k: int, n: int) -> str:
    return f"{k}/{n} ({round(100 * k / n) if n else 0}%)"


def _counts(mapping: dict, n: int | None = None, limit: int = 12) -> str:
    items = list(mapping.items())[:limit]
    if not items:
        return "-"
    return ", ".join(f"{k} {_share(v, n) if n else v}" for k, v in items)


def _md(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def render_card(index: int, r: dict, channels: dict) -> list[str]:
    t, d = r["title_analysis"], r["description_analysis"]
    channel = channels.get(r["channel_id"]) or {}
    lines = [f"### {index}. {r['title']}",
             f"`{r['id']}` · {r['channel_title']} · published {r['published_at'][:10]} "
             f"({_n(r['age_days'])} days) · {_clock(r['duration_sec'])} {r['kind']}"
             + (" · #shorts tag" if r["shorts_hashtag"] else "") + f" · {r['url']}"]
    stand = []
    if r["outlier_multiple"] is not None:
        stand.append(f"**{r['outlier_multiple']}x** channel {r['kind']} median "
                     f"({_abbr(r['channel_median_views'])}, {channel.get('median_basis', '')})"
                     + (" (young: still collecting views)" if r["age_days"] is not None
                        and r["age_days"] < QUARTILE_MIN_AGE_DAYS else ""))
    if r["vpd_rank"]:
        stand.append(f"views/day rank {r['vpd_rank']}/{r['vpd_rank_of']} on channel")
    lines.append(f"- **Stats** {_n(r['views'])} views · {_n(r['views_per_day'])}/day · likes "
                 f"{_n(r['likes'])} ({_pct(r['like_rate'])}) · comments {_n(r['comments'])} "
                 f"({_pct(r['comment_rate'])})" + (" · " + " · ".join(stand) if stand else ""))
    lines.append(f"- **Category** {r['category_id']} {r['category_name']} · license {r['license']} · "
                 f"madeForKids {r['made_for_kids']} · {r['definition'] or '-'} · topics: "
                 f"{', '.join(r['topic_categories']) or '-'} · caption flag {_yn(r['caption_flag'])}"
                 + (" · tracks: " + ", ".join(
                     f"{c.get('language')} ({c.get('kind')})" if "error" not in c else f"error: {c['error']}"
                     for c in r["caption_tracks"]) if r["caption_tracks"] is not None else ""))
    lines.append(f"- **Languages** default {r['default_language'] or '-'} · audio "
                 f"{r['default_audio_language'] or '-'} · localizations ({r['localization_count']}): "
                 f"{', '.join(r['localizations']) or '-'} · translated titles "
                 f"{r['translated_title_count']} · translated descriptions {r['translated_description_count']}")
    lines.append(f"- **Tags** ({r['tag_count']}, {r['tag_limit_chars']} of 500 chars): "
                 + (", ".join(r["tags"]) if r["tags"] else "(none)"))
    title_bits = [f"{t['chars']} chars", f"{t['words']} words", t["form"], f"opens '{t['first_word']}'"
                  f" ({t['starts_with']})", f"{t['case_style']} case"]
    if t["hook_words"]:
        title_bits.append("hooks: " + ", ".join(t["hook_words"]))
    if t["years"]:
        title_bits.append("years: " + ", ".join(t["years"]))
    if t["caps_words"]:
        title_bits.append("CAPS: " + ", ".join(t["caps_words"]))
    if t["second_person"]:
        title_bits.append("says 'you'")
    if t["emoji"]:
        title_bits.append("emoji " + "".join(t["emoji"]))
    if t["hashtags"]:
        title_bits.append("hashtags " + " ".join("#" + h for h in t["hashtags"]))
    lines.append("- **Title** " + " · ".join(title_bits))
    flags = [name for name, value in (
        ("sources", d["has_sources"]), ("people/places", d["has_people_places"]),
        ("subscribe CTA", d["subscribe_cta"]), ("AI disclosure", d["ai_disclosure"]),
        ("contact email", d["has_contact_email"]), ("restates title", d["first_line_echoes_title"]))
        if value]
    desc_bits = [f"{d['chars']:,} chars", f"{d['lines']} lines",
                 f"URLs {d['url_count']}" + (f" ({_counts(d['domains'], limit=5)})" if d["url_count"] else ""),
                 f"DOIs {d['doi_count']}",
                 f"chapters {d['chapter_count']}" + (" valid" if d["chapters_valid"] else
                                                     " (no 0:00 start)" if d["chapter_count"] and not d["chapters_start_at_zero"] else ""),
                 f"hashtags {d['hashtag_count']}" + (" at end" if d["hashtags_at_end"] else ""),
                 f"emoji {d['emoji_count']}"]
    lines.append("- **Description** " + " · ".join(desc_bits)
                 + (" · " + ", ".join(flags) if flags else ""))
    if d["section_headers"]:
        lines.append("  - headers: " + " · ".join(f"`{_md(h)}`" for h in d["section_headers"][:10]))
    extras = []
    if d["credit_lines"]:
        extras.append("credits: " + " · ".join(_md(c) for c in d["credit_lines"][:4]))
    if d["sponsor_markers"]:
        extras.append("sponsor/affiliate: " + ", ".join(d["sponsor_markers"]))
    if d["social_links"] or d["support_links"]:
        extras.append("social: " + ", ".join(d["social_links"] + d["support_links"]))
    if d["hashtags"]:
        extras.append("hashtags: " + " ".join("#" + h for h in d["hashtags"][:20]))
    for extra in extras:
        lines.append("  - " + extra)
    lines.append(f"  - above the fold: > {_md(d['above_fold']) or '(empty)'}")
    if r["thumbnail"]:
        lines.append(f"- **Thumbnail** {r['thumbnail_size']}: {r['thumbnail']}")
    return lines


def _render_comparison(columns: list[tuple[str, dict, int]]) -> list[str]:
    """A feature table with one column per (label, summary, n)."""
    head = "| feature | " + " | ".join(f"{label} (n={n})" for label, _, n in columns) + " |"
    lines = [head, "|---|" + "---|" * len(columns)]
    for key, label, kind, _, _ in FEATURES:
        cells = []
        for _, summary, _ in columns:
            s = summary[key]
            if s["value"] is None:
                cells.append("-")
            elif kind == "num":
                cells.append(_fmt_num(s["value"]))
            elif kind == "bool":
                cells.append(_share(s["k"], s["n"]))
            else:
                cells.append(f"{_md(str(s['value']))} ({s['k']}/{s['n']})")
        lines.append(f"| {_md(label)} | " + " | ".join(cells) + " |")
    return lines


def _render_patterns(p: dict) -> list[str]:
    """Section 2 lines for one patterns() result; shares are over its own n."""
    n, out = p["n"], []
    tags = p["tags"]
    out.append(f"- **Tag count** median {_fmt_num(tags['count']['median'])} (min {_n(tags['count']['min'])}, "
               f"max {_n(tags['count']['max'])}); buckets: {_counts(tags['buckets'], n)}; tag characters "
               f"median {_fmt_num(tags['limit_chars']['median'])} of 500")
    if tags["most_common"]:
        out.append(f"  - most common tags: {_counts(tags['most_common'], limit=15)}")
    title = p["title"]
    out.append(f"- **Title forms** {_counts(title['forms'], n)}")
    out.append(f"  - opener: {_counts(title['starts_with'], n)}")
    out.append(f"  - case: {_counts(title['case_style'], n)}; length median {_fmt_num(title['chars']['median'])} "
               f"chars ({_n(title['chars']['min'])}-{_n(title['chars']['max'])}), "
               f"{_fmt_num(title['words']['median'])} words")
    out.append(f"  - flags: {_counts(title['flags'], n, limit=20)}")
    if title["hook_words"]:
        out.append(f"  - hook words: {_counts(title['hook_words'])}")
    langs = p["languages"]
    out.append(f"- **Languages** default: {_counts(langs['default_language'], n)}; audio: "
               f"{_counts(langs['default_audio_language'], n)}; translated titles in "
               f"{_share(langs['with_translated_titles'], n)}; localizations per video median "
               f"{_fmt_num(langs['localization_count']['median'])}")
    out.append(f"  - localization languages: {_counts(langs['localization_codes'], n, limit=30)}")
    out.append(f"- **Category mix** {_counts(p['categories'], n)}")
    dur = p["duration"]
    out.append(f"- **Duration** median {_clock(dur['seconds']['median'] or 0)}; "
               f"{_counts(dur['buckets'], n)}")
    desc = p["description"]
    out.append(f"- **Description** length median {_fmt_num(desc['chars']['median'])} chars "
               f"({_n(desc['chars']['min'])}-{_n(desc['chars']['max'])}); URLs median "
               f"{_fmt_num(desc['url_count']['median'])}; hashtags median {_fmt_num(desc['hashtag_count']['median'])}")
    out.append(f"  - features: {_counts(desc['features'], n, limit=30)}")
    if desc["headers"]:
        out.append(f"  - section headers: {_counts({_md(k): v for k, v in desc['headers'].items()}, n)}")
    if desc["domains"]:
        out.append(f"  - linked domains (videos linking): {_counts(desc['domains'], n)}")
    if desc["hashtags"]:
        out.append(f"  - hashtags: {_counts(desc['hashtags'], n, limit=15)}")
    return out

def render_report(result: dict) -> str:
    videos, channels, p = result["videos"], result["channels"], result["patterns"]
    n = len(videos)
    out = [f"# Video metadata: {result['name']}", "",
           f"Generated {result['generated']} with the {result['token_channel']} token, read-only. "
           f"API: {result.get('quota', '-')}.",
           f"Inputs: {', '.join(result['inputs'])}",
           f"Analyzed {n} videos ({_counts(p['kinds'])}); channel uploads capped at "
           f"{result['uploads_limit']} per channel"
           + (f"; {result['baseline_video_count']} more uploads fetched only as a median baseline"
              if result["baseline_video_count"] else "") + ".",
           "Numbers describe this fetched set. Differences below are observations with their n, "
           "not causes; older videos have had longer to collect views.", ""]
    for line in result["input_errors"]:
        out.append(f"- skipped: {line}")
    for line in result["warnings"]:
        out.append(f"- note: {line}")
    out += ["", "## Channels", "",
            "| channel | handle | subs | total views | videos | created | median basis | "
            "long median (n) | Shorts median (n) |", "|---|---|---|---|---|---|---|---|---|"]
    for c in channels.values():
        out.append(f"| {_md(c.get('title', ''))} | {c.get('handle') or '-'} | {_n(c.get('subs'))} | "
                   f"{_n(c.get('total_views'))} | {_n(c.get('video_count'))} | {c.get('created') or '-'} | "
                   f"{c.get('median_basis', '-')} | {_abbr(c.get('median_long'))} ({c.get('n_long', 0)}) | "
                   f"{_abbr(c.get('median_short'))} ({c.get('n_short', 0)}) |")

    out += ["", "## 1. Videos", ""]
    order = list(result["inputs_videos"])
    for cin in result["channel_inputs"]:
        ups = [r for r in videos if r["channel_id"] == cin["channel_id"] and r["id"] not in order]
        ups.sort(key=lambda r: (r["kind"] != "long", r["outlier_multiple"] is None,
                                -(r["outlier_multiple"] or 0), -(r["views"] or 0)))
        order += [r["id"] for r in ups]
    order += [r["id"] for r in videos if r["id"] not in order]
    by_id = {r["id"]: r for r in videos}
    for index, vid in enumerate(order, 1):
        out += render_card(index, by_id[vid], channels) + [""]

    by_kind = result.get("patterns_by_kind") or {}
    out += ["## 2. Patterns across the set", ""]
    if len(p["kinds"]) > 1 and by_kind:
        out += ["Long-form and Shorts are counted separately (Shorts usually carry near-empty "
                "descriptions); shares are k/n within each block.", ""]
        for kind, label in (("long", "Long-form"), ("short", "Shorts")):
            if kind in by_kind:
                out += [f"**{label} (n={by_kind[kind]['n']})**", ""] + _render_patterns(by_kind[kind]) + [""]
        other = p["kinds"].get("other", 0)
        if other:
            out += [f"{other} live or zero-duration video(s) are in neither block.", ""]
    else:
        only = next(iter(p["kinds"]), "")
        label = {"long": "long-form", "short": "Shorts"}.get(only, "videos")
        out += [f"{n} {label}; shares are k/n.", ""] + _render_patterns(p)
    out += ["", "## 3. Top vs bottom quartile by outlier multiple", ""]
    if not result["quartiles"]:
        out.append("No channel inputs.")
    for q in result["quartiles"]:
        out.append(f"### {q['channel_title']}")
        if q.get("skipped"):
            out += [f"Skipped: {q['skipped']}.", ""]
            continue
        out.append(f"{q['n_long']} long-form uploads at least {q.get('min_age_days', QUARTILE_MIN_AGE_DAYS)} days "
                   f"old; top and bottom {q['q']} by views / channel long-form median. Observations with n, "
                   "not causes.")
        out.append("- top: " + "; ".join(f"{v['outlier_multiple']}x {_md(v['title'])} ({_abbr(v['views'])}, "
                                          f"{_n(v['age_days'])} d)" for v in q["top"]))
        out.append("- bottom: " + "; ".join(f"{v['outlier_multiple']}x {_md(v['title'])} ({_abbr(v['views'])}, "
                                             f"{_n(v['age_days'])} d)" for v in q["bottom"]))
        if q.get("young"):
            out.append("- left out, still collecting views: " + "; ".join(
                f"{v['outlier_multiple']}x {_md(v['title'])} ({_abbr(v['views'])}, {_n(v['age_days'])} d)"
                for v in q["young"]))
        out += ["", "Observations:"] + [f"- {o['text']}" for o in q["observations"]] \
            + (["- none past the thresholds"] if not q["observations"] else [])
        top_s = {row["key"]: row["top"] for row in q["rows"]}
        bottom_s = {row["key"]: row["bottom"] for row in q["rows"]}
        out += [""] + _render_comparison([("top", top_s, q["q"]), ("bottom", bottom_s, q["q"])]) + [""]

    cmp = result.get("compare_ours")
    if cmp:
        included = " + ".join(name.title() for name in result.get("ours") or {})
        out += [f"## 4. Compared with ours ({included} public long-form)", ""]
        for name, entry in (result.get("ours") or {}).items():
            c = entry["channel"]
            out.append(f"- {name}: {c.get('title')} · subs {_n(c.get('subs'))} · {c.get('n_public', 0)} public "
                       f"of {c.get('n_uploads', 0)} uploads · {c.get('n_public_long', 0)} public long-form · "
                       f"long median {_abbr(c.get('median_long'))}")
        out += ["", "Differences (theirs vs ours, observations not causes):"]
        out += [f"- {o['text']}" for o in cmp["observations"]] or ["- none past the thresholds"]
        theirs = {row["key"]: row["theirs"] for row in cmp["rows"]}
        ours_all = {row["key"]: row["ours"] for row in cmp["rows"]}
        columns = [("theirs", theirs, cmp["n"]["theirs"])]
        columns += [(name, summary, cmp["n_columns"][name]) for name, summary in cmp["columns"].items()]
        columns.append(("ours combined", ours_all, cmp["n"]["ours"]))
        out += [""] + _render_comparison(columns) + [""]
    out += ["## Method", "",
            f"- Read-only: only videos/channels/playlistItems/videoCategories/captions .list calls. {result.get('quota', '')}.",
            f"- Kind: <= {SHORT_MAX_SEC} s is a Short (the API does not expose aspect ratio for other "
            "channels' videos); '#shorts' in title/description is flagged separately.",
            f"- Channel median: over the latest uploads fetched for that channel, per kind, when it "
            f"has at least {MEDIAN_MIN}; outlier multiple = views / that median.",
            "- Quartiles: channel inputs with at least "
            f"{QUARTILE_MIN_LONG} long-form uploads that are {QUARTILE_MIN_AGE_DAYS}+ days old (younger ones are "
            "still collecting views and are listed apart); a flag difference is listed at >= 25 points, "
            "a median difference at >= 1.25x plus a minimum step. '(era: ...)' marks a flag (or a count "
            "that is zero on one side, read as 'has any') whose rarer side sits entirely among the "
            "channel's oldest or newest uploads: likely a template change over time rather than "
            "anything that tracks views.",
            "- Patterns: long-form and Shorts are counted separately when both are present.",
            "- Section headers: ALL-CAPS lines, short emoji-led lines and short lines ending in ':'; a "
            "credit line ('🎨 Animation by X') is counted as a credit, not a header. "
            "A sources or people/places section is also recognised from a label in any case "
            "('Sources & further reading:', 'References: <link>', 'Sources' over a list). "
            "Tag characters approximate YouTube's 500 count (commas, quotes around multi-word tags).",
            "- Title question: a '?' or a wh-word followed by an auxiliary ('What did ...', 'Why is ...').",
            "- AI disclosure: description text only. YouTube's altered/synthetic-content label is not "
            "returned by videos.list (not even for our own uploads), so 0/n means no disclosure line in "
            "the description, not that the label is off.",
            ""]
    return "\n".join(out)


def render_summary(result: dict, report_path: str = "") -> str:
    videos, p = result["videos"], result["patterns"]
    n = len(videos)
    lines = [f"video_metadata {result['name']}: {n} videos ({_counts(p['kinds'])}) from "
             f"{len({r['channel_id'] for r in videos})} channel(s)"]
    for c in result["channels"].values():
        lines.append(f"  {c.get('title')} {c.get('handle') or ''}: subs {_abbr(c.get('subs'))} · "
                     f"{_n(c.get('video_count'))} videos · long median {_abbr(c.get('median_long'))} "
                     f"(n={c.get('n_long', 0)}) · Shorts median {_abbr(c.get('median_short'))} "
                     f"(n={c.get('n_short', 0)})")
    ranked = sorted((r for r in videos if r["outlier_multiple"] is not None),
                    key=lambda r: -r["outlier_multiple"])[:5]
    if ranked:
        lines.append("Top by outlier multiple:")
        lines += [f"  {r['outlier_multiple']:>6}x {_abbr(r['views']):>6} {r['kind']:5} {r['title'][:70]}"
                  for r in ranked]
    by_kind = result.get("patterns_by_kind") or {}
    if "long" in by_kind and len(p["kinds"]) > 1:
        p = by_kind["long"]
        n = p["n"]
        lines.append(f"Patterns below: long-form n={n} (Shorts in the report)")
    t, langs, desc = p["title"], p["languages"], p["description"]
    if n:
        lines.append(f"Tags: median {_fmt_num(p['tags']['count']['median'])} ({_counts(p['tags']['buckets'], n)})")
        lines.append(f"Titles: {_counts(t['forms'], n, limit=4)}; median {_fmt_num(t['chars']['median'])} chars")
        lines.append(f"Languages: translated titles {_share(langs['with_translated_titles'], n)}; "
                     f"top: {_counts(langs['localization_codes'], limit=8)}")
        lines.append(f"Category: {_counts(p['categories'], n, limit=3)}")
        top_features = sorted(desc["features"].items(), key=lambda kv: -kv[1])[:6]
        lines.append("Description: " + ", ".join(f"{k} {_share(v, n)}" for k, v in top_features))
    for q in result["quartiles"]:
        if q.get("skipped"):
            lines.append(f"Quartiles {q['channel_title']}: skipped ({q['skipped']})")
        else:
            young = (f"; {len(q['young'])} younger than {q['min_age_days']} d left out"
                     if q.get("young") else "")
            lines.append(f"Quartiles {q['channel_title']} (top {q['q']} vs bottom {q['q']} of {q['n_long']}{young}):")
            lines += [f"  - {o['text']}" for o in q["observations"][:4]] or ["  - none past the thresholds"]
    cmp = result.get("compare_ours")
    if cmp:
        lines.append(f"Theirs (n={cmp['n']['theirs']}) vs ours (n={cmp['n']['ours']}):")
        lines += [f"  - {o['text']}" for o in cmp["observations"][:6]] or ["  - none past the thresholds"]
    for line in result["input_errors"]:
        lines.append(f"skipped: {line}")
    lines.append(f"API units used: {result.get('quota', '-')}")
    if report_path:
        lines.append(f"report: {report_path}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------

def default_out_root() -> str:
    for base in (os.path.join(ROOT, "jobs", "yt"), LOCAL_CLONE_YT):
        if os.path.isdir(base):
            return os.path.join(base, "metadata_lookups")
    return os.path.join(os.getcwd(), "metadata_lookups")


def default_name(collected: dict) -> str:
    """The first channel input that resolved, else the first video input that came back."""
    if collected["channel_inputs"]:
        return collected["channel_inputs"][0]["input"].lstrip("@")
    if collected["inputs_videos"]:
        return collected["inputs_videos"][0]
    return "lookup"


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "lookup"


def _client(channel: str):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=youtube_upload._creds(channel), cache_discovery=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only YouTube metadata lookup and analysis.")
    ap.add_argument("inputs", nargs="+", help="video/channel URLs, video IDs, @handles, UC IDs")
    ap.add_argument("--channel-uploads", type=int, default=50, help="latest uploads per channel (default 50)")
    ap.add_argument("--captions", action="store_true", help="list caption tracks (50 units per video)")
    ap.add_argument("--captions-max", type=int, default=CAPTIONS_MAX_DEFAULT,
                    help=f"cap on captions.list calls (default {CAPTIONS_MAX_DEFAULT})")
    ap.add_argument("--compare-ours", action="store_true",
                    help="compare with our World + History public long-form films")
    ap.add_argument("--name", default="", help="report folder name (default: first channel or video)")
    ap.add_argument("--out", default="", help="output root (default jobs/yt/metadata_lookups)")
    ap.add_argument("--channel", choices=sorted(CHANNELS), default="world", help="which token to read with")
    ap.add_argument("--no-baseline", action="store_true",
                    help="do not fetch uploads of channels seen only through a video input")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON instead of the summary")
    # A video ID may begin with "-" ("-cBcDeFgHiJ"); argparse would take it for an unknown option.
    # A leading space hides the dash from argparse and is stripped again before parsing the inputs.
    argv = list(sys.argv[1:] if argv is None else argv)
    args = ap.parse_args([" " + a if DASH_VIDEO_ID_RE.match(a) else a for a in argv])
    args.inputs = [a.strip() for a in args.inputs]

    parsed = parse_inputs(args.inputs)
    for error in parsed["errors"]:
        print(f"skipped: {error}", file=sys.stderr)
    if not parsed["videos"] and not parsed["channels"]:
        print("no usable inputs", file=sys.stderr)
        return 2

    def warn(message):
        print(f"note: {message}", file=sys.stderr)

    quota = Quota()
    now = dt.datetime.now(dt.timezone.utc)
    yt = ReadOnlyYouTube(_client(args.channel), quota)
    try:
        collected = collect(yt, parsed, uploads=args.channel_uploads, captions=args.captions,
                            captions_max=args.captions_max, baseline=not args.no_baseline, now=now, warn=warn)
    except Exception:
        print(f"video_metadata failed; API units used: {quota.summary()}", file=sys.stderr)
        raise
    ours, ours_warnings = None, []
    if args.compare_ours:
        clients = {}
        for name in ("world", "history"):
            try:
                clients[name] = yt if name == args.channel else ReadOnlyYouTube(_client(name), quota)
            except SystemExit as exc:          # _creds exits when a token slot is empty
                ours_warnings.append(f"--compare-ours: {name} skipped ({exc})")
        try:
            ours = collect_ours(clients, now, ours_warnings.append)
        except Exception as exc:  # noqa: BLE001 - the lookup itself is still worth writing
            ours_warnings.append(f"--compare-ours failed: {str(exc)[:200]}")
        for message in ours_warnings:
            warn(message)
    name = safe_name(args.name or default_name(collected))
    result = analyze(collected, name=name, inputs=args.inputs, token_channel=args.channel, quota=quota,
                     ours=ours, ours_warnings=ours_warnings, input_errors=parsed["errors"],
                     uploads_limit=args.channel_uploads)
    out_dir = os.path.join(args.out or default_out_root(), f"{dt.date.today().isoformat()}_{name}")
    os.makedirs(out_dir, exist_ok=True)
    report_path = os.path.join(out_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(render_report(result))
    with open(os.path.join(out_dir, "videos.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1, ensure_ascii=False, default=str)
    if args.json:
        print(json.dumps(result, indent=1, ensure_ascii=False, default=str))
    else:
        print(render_summary(result, report_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
