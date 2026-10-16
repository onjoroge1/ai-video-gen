#!/usr/bin/env python3
"""Translated titles, descriptions and subtitles for a live video (operator, 2026-10-11).

    python3 scripts/localize_video.py eWJr_iwUNx4 --job jobs/asian-carp [--langs es,pt,id,hi,de,fr,it]
                                      [--channel world] [--no-captions] [--if-changed] [--dry-run]

YouTube shows a localized title and description to viewers whose YouTube language matches, in
search, suggestions and the home feed. The narration stays English, so each language also gets a
subtitle track translated from <job>/captions.srt: a viewer who clicks a Spanish title can follow
an English film. Translates the video's LIVE title and description (the operator edits them in
Studio after upload), checks every translation keeps each number, URL and chapter timestamp, and
writes <job>/localizations.json. Needs the youtube.force-ssl scope (scripts/youtube_oauth_setup.py).
Existing localizations in other languages and existing caption tracks are left as they are.

The film description template (description_template, 2026-10-14) survives translation: each
source's citation line stays in its original language, its "↳" finding and the People & Places
lines are translated, every number the English states must still be there, and no "↳" or People
& Places line may state a number the English does not. A translation over YouTube's 5000-byte
description limit (Hindi takes about 2.5 times the bytes) sheds, until it fits, "↳" findings one
at a time from the least-used source up, then its People & Places section, then whole source
entries from the end (fit_translation); only what it shed is excused from the checks. A
language skipped for an unchanged English source is not retried until the English changes.
--if-changed re-translates each language translated from a different English than the live title
and description (each language records the hash of its own source), plus the languages not yet done.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

LANG_NAMES = {"es": "Spanish (Latin American)", "pt": "Portuguese (Brazilian)",
              "id": "Indonesian", "hi": "Hindi", "de": "German", "fr": "French", "it": "Italian",
              "tr": "Turkish", "ko": "Korean", "ja": "Japanese", "ar": "Arabic"}
# German, French and Italian added 2026-10-14 (operator); the routine passes its own --langs.
DEFAULT_LANGS = "es,pt,id,hi,de,fr,it"
# YouTube's description limit is 5000 BYTES (videos resource); one localization over it fails
# the whole videos.update that carries every language.
MAX_DESCRIPTION_BYTES = 5000
FINDING_MARK = "↳"
PEOPLE_MARK = "📍"
RESEARCH_HEADER = "RESEARCH & SOURCES"
MODEL = os.environ.get("LOCALIZE_MODEL", "claude-sonnet-5-5")
_URL = re.compile(r"https?://\S+")
_YOUTUBE = re.compile(r"(?:youtube\.com|youtu\.be)/", re.I)
_TIMESTAMP = re.compile(r"^\s*(\d{1,2}:\d{2}(?::\d{2})?)\b", re.M)


# A number however a language groups or points it: 60,000 / 60.000 / 60 000 are 60000, 1.5 and
# 1,5 are 1.5 (but 15 is not 1.5); native digits (Devanagari) read as ASCII. A grouped number never
# starts right after a digit or a ':' -- "3:39 150 to 200" is 3, 39, 150 and 200, not 39150 -- and
# chapter timestamps (checked on their own) are taken out of descriptions before numbers are
# compared. Used for the title, the description and every subtitle cue alike: a literal compare
# failed German/French/Italian (and es/pt/id) "1,5 Millionen" against "1.5 million".
_GROUPED_NUMBER = re.compile(r"(?<![\d:])\d{1,3}(?:[,.\u00a0\u202f\u2009 ]\d{3})+(?!\d)"
                             r"|\d+(?:[.,]\d+)?")
_TIMESTAMP_PREFIX = re.compile(r"(?m)^\s*\d{1,2}:\d{2}(?::\d{2})?\b")


def _ascii_digits(text: str) -> str:
    return "".join(str(unicodedata.decimal(ch)) if ch.isdecimal() and not ch.isascii() else ch
                   for ch in text or "")


def _number_forms(token: str) -> frozenset[str]:
    """The values a written number can mean. "60,000" and "60.000" are 60000 in one convention and
    60.000 in the other, so both; "60 000" is only 60000; "1.5" and "1,5" are only 1.5."""
    groups = re.split(r"\D", token)
    forms = set()
    if len(groups) == 1:
        forms.add(groups[0].lstrip("0") or "0")
    else:
        if len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:]):
            forms.add("".join(groups).lstrip("0") or "0")
        if len(groups) == 2 and token[len(groups[0])] in ".,":
            forms.add(f"{groups[0].lstrip('0') or '0'}.{groups[1]}")
    return frozenset(forms)


def number_tokens(text: str, timestamps: bool = True) -> list[tuple[str, frozenset[str]]]:
    """(as written, its possible values) for each number in `text`; `timestamps` False first takes
    out line-leading chapter timestamps."""
    text = _ascii_digits(text)
    if not timestamps:
        text = _TIMESTAMP_PREFIX.sub("", text)
    return [(m.group(0), _number_forms(m.group(0))) for m in _GROUPED_NUMBER.finditer(text)]


def lost_numbers(source: str, translated: str, timestamps: bool = True) -> list[str]:
    """The numbers of `source` (as written) that `translated` does not state in any convention."""
    have: set[str] = set()
    for _, forms in number_tokens(translated, timestamps):
        have |= forms
    return sorted({token for token, forms in number_tokens(source, timestamps) if not forms & have})


def description_numbers(text: str) -> set[str]:
    """Every value the numbers of a description (timestamps aside) can mean."""
    return set().union(*(forms for _, forms in number_tokens(text, timestamps=False)))


def _blocks(text: str) -> list[list[str]]:
    return [b.split("\n") for b in re.split(r"\n[ \t]*\n", (text or "").strip()) if b.strip()]


def _join(blocks: list[list[str]]) -> str:
    return "\n\n".join("\n".join(b) for b in blocks if any(l.strip() for l in b))


def _bare_url(line: str) -> str:
    line = line.strip()
    return line if re.fullmatch(r"https?://\S+", line) else ""


def research_entries(blocks: list[list[str]]) -> list[dict]:
    """The template's research entries, in order: {"block", "url", "citation", "finding"}.

    The section starts at the block whose first line starts with 📚 (in any language) and runs
    through the following blocks shaped like an entry: a citation line, a bare URL, optionally a
    "↳" finding. The first entry shares the header's block. A YouTube link (a Short, a playlist)
    is never a source: it ends the section, so a two-line "Short version:" block is not shed."""
    start = next((i for i, b in enumerate(blocks) if b and b[0].strip().startswith("📚")), None)
    if start is None:
        return []
    out = []
    for index in range(start, len(blocks)):
        lines = blocks[index][1:] if index == start else blocks[index]
        urls = [(n, _bare_url(l)) for n, l in enumerate(lines) if _bare_url(l)]
        if urls and _YOUTUBE.search(urls[0][1]):
            break
        if not urls or urls[0][0] == 0:
            if index == start:
                continue
            break
        n, url = urls[0]
        after = [l.strip() for l in lines[n + 1:]]
        out.append({"block": index, "url": url, "citation": lines[n - 1].strip(),
                    "finding": next((l for l in after if l.startswith(FINDING_MARK)), "")})
    return out


def _people_block(blocks: list[list[str]]) -> int | None:
    return next((i for i, b in enumerate(blocks) if b and b[0].strip().startswith(PEOPLE_MARK)), None)


def strip_sections(text: str, findings=(), sources=(), people: bool = False) -> str:
    """`text` without the "↳" lines under the URLs in `findings`, the whole entries of the URLs
    in `sources` (the 📚 header too once no entry is left), and the People & Places block."""
    findings, sources = set(findings) | set(sources), set(sources)
    blocks = _blocks(text)
    entries = research_entries(blocks)
    for entry in entries:
        block = blocks[entry["block"]]
        if entry["url"] in sources:
            header = block[0] if entry["block"] == entries[0]["block"] else None
            others = [e for e in entries if e["url"] not in sources]
            blocks[entry["block"]] = [header] if header is not None and others else []
        elif entry["url"] in findings:
            blocks[entry["block"]] = [l for l in block if not l.strip().startswith(FINDING_MARK)]
    if people:
        index = _people_block(blocks)
        if index is not None:
            blocks[index] = []
    return _join(blocks)


def fit_translation(translated: dict, limit: int = MAX_DESCRIPTION_BYTES) -> dict:
    """A translated description cut to YouTube's byte limit, shedding only as much as it must: "↳"
    findings one at a time from the last (least-used) source up, then the People & Places
    section, then whole source entries from the end. The summary, chapters, links and footer are
    never cut. `_removed` records what went, for check_translation; main() copies only the title
    and description into the localization."""
    desc = translated.get("description", "")
    removed = {"findings": [], "people": False, "sources": []}

    def over(text):
        return len(text.encode("utf-8")) > limit

    while over(desc):
        entries = research_entries(_blocks(desc))
        with_finding = [e for e in entries if e["finding"]]
        if with_finding:
            removed["findings"].append(with_finding[-1]["url"])
            desc = strip_sections(desc, findings=[with_finding[-1]["url"]])
        elif not removed["people"] and _people_block(_blocks(desc)) is not None:
            removed["people"] = True
            desc = strip_sections(desc, people=True)
        elif entries:
            removed["sources"].append(entries[-1]["url"])
            desc = strip_sections(desc, sources=[entries[-1]["url"]])
        else:
            break
    out = {**translated, "description": desc}
    if any(removed.values()):
        out["_removed"] = removed
    return out


def citations(description: str) -> dict[str, str]:
    """{url: citation line} for the template's research section: a source's citation stays in its
    own language. An older description's free-form labels are not held to it."""
    if RESEARCH_HEADER not in (description or ""):
        return {}
    return {e["url"]: e["citation"] for e in research_entries(_blocks(description))
            if e["citation"] and not _URL.search(e["citation"])
            and not e["citation"].startswith(("📚", "📍", "⏱", FINDING_MARK))}


def citation_lines(description: str) -> list[str]:
    return list(citations(description).values())


def check_translation(source: dict, translated: dict) -> list[str]:
    """Reasons a translated title/description cannot be used; [] when it can."""
    problems = []
    title, desc = translated.get("title", ""), translated.get("description", "")
    if not title.strip() or len(title) > 100:
        problems.append(f"title empty or over 100 characters ({len(title)})")
    size = len(desc.encode("utf-8"))
    if size > MAX_DESCRIPTION_BYTES:
        problems.append(f"description over {MAX_DESCRIPTION_BYTES} bytes ({size})")
    missing = lost_numbers(source["title"], title)
    if missing:
        problems.append(f"title lost numbers {missing}")
    # The English is held to the translation minus ONLY what fit_translation removed, never
    # minus whatever the model happened to drop (a lost "↳" or 📍 marker is a lost section).
    removed = translated.get("_removed") or {}
    gone_findings = set(removed.get("findings") or [])
    gone_sources = set(removed.get("sources") or [])
    english = strip_sections(source["description"], findings=gone_findings, sources=gone_sources,
                             people=bool(removed.get("people")))
    for url in _URL.findall(english):
        if url not in desc:
            problems.append(f"description lost URL {url}")
    lost = set(_TIMESTAMP.findall(english)) - set(_TIMESTAMP.findall(desc))
    if lost:
        problems.append(f"description lost chapter timestamps {sorted(lost)}")
    lost = lost_numbers(english, desc, timestamps=False)
    if lost:
        problems.append(f"description lost numbers {lost}")
    english_blocks, desc_blocks = _blocks(english), _blocks(desc)
    have = {e["url"]: e for e in research_entries(desc_blocks)}
    for entry in research_entries(english_blocks):
        if entry["finding"] and not (have.get(entry["url"]) or {}).get("finding"):
            problems.append(f"description lost the finding under {entry['url']}")
    expected = sum(1 for l in english.split("\n") if l.strip().startswith(FINDING_MARK))
    found = sum(1 for l in desc.split("\n") if l.strip().startswith(FINDING_MARK))
    if found != expected:
        problems.append(f"description has {found} '{FINDING_MARK}' finding lines, not {expected}")
    people_en, people_tr = _people_block(english_blocks), _people_block(desc_blocks)
    if people_en is not None:
        if people_tr is None:
            problems.append("description lost the People & Places section")
        elif len(desc_blocks[people_tr]) != len(english_blocks[people_en]):
            problems.append(f"description has {len(desc_blocks[people_tr]) - 1} People & Places "
                            f"lines, not {len(english_blocks[people_en]) - 1}")
    # A finding or People & Places line may not state a number the English never does.
    claimed = [l for l in desc.split("\n") if l.strip().startswith(FINDING_MARK)]
    if people_tr is not None:
        claimed += desc_blocks[people_tr][1:]
    added = lost_numbers("\n".join(claimed), source["description"], timestamps=False)
    if added:
        problems.append(f"description added numbers {added}")
    kept = {l.strip() for l in desc.split("\n")}
    for url, line in citations(source["description"]).items():
        if url not in gone_sources and line not in kept:
            problems.append(f"description changed a source citation: {line[:80]}")
    return problems


def _client():
    import anthropic
    return anthropic.Anthropic()


class ReplyTruncated(RuntimeError):
    """The model stopped at max_tokens, so its JSON is cut off: raise the cap, do not parse it."""


def _ask(system: str, user: str, max_tokens: int, lang: str, part: str) -> dict:
    response = _client().messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                                         messages=[{"role": "user", "content": user}])
    # A cut reply used to surface as json.loads' "Unterminated string" (5Kh7BiFDJMU, 2026-10-16).
    if getattr(response, "stop_reason", None) == "max_tokens":
        raise ReplyTruncated(f"{lang}: the {part} reply stopped at max_tokens={max_tokens} before "
                             "its JSON closed; raise the cap")
    text = next(b.text for b in response.content if getattr(b, "type", "") == "text")
    match = re.search(r"\{.*\}", text, re.S)
    return json.loads(match.group(0) if match else text)


# Output tokens for one title + description. A 4,866-character template description took more than
# 4,000 in de/fr/it/id/hi (only es and pt fit; 5Kh7BiFDJMU, 2026-10-16) and Hindi fit in 12,000;
# Devanagari is the most token-hungry. Three tokens per English character, never below 12,000 and
# never above 20,000: the SDK refuses a non-streaming request over about 21,333 (10 minutes).
METADATA_MIN_TOKENS = 12000
METADATA_MAX_TOKENS = 20000
METADATA_TOKENS_PER_CHAR = 3


def metadata_max_tokens(title: str, description: str) -> int:
    wanted = METADATA_TOKENS_PER_CHAR * (len(title) + len(description))
    return min(METADATA_MAX_TOKENS, max(METADATA_MIN_TOKENS, wanted))


def translate_metadata(title: str, description: str, lang: str) -> dict:
    system = (
        f"You localize YouTube metadata into {LANG_NAMES.get(lang, lang)} for a documentary channel. "
        "Write the title the way a native YouTube creator in that language would: natural, "
        "curiosity-led, the same story and the same claim, never a word-for-word gloss, at most "
        "100 characters. Never add a qualifier to a number (more than, over, about, nearly) the "
        "English does not plainly mean: 'It Took Over 45 States' means it conquered 45 states, "
        "not more than 45 (es and id read it that way, 2026-10-11). "
        "Translate the description faithfully: keep every number exactly, every "
        "URL unchanged, every chapter line's timestamp unchanged (translate only its label), "
        "hashtags unchanged, line breaks and blank lines kept, every emoji kept. In the research "
        "and sources section, the line just above each URL names the source: copy it exactly as "
        "written, in its original language; translate only the lines that start with '↳' (keep "
        "the '↳'). In the people and places section, keep each name as spelled, keep the ' — ' "
        "after it and translate the rest of the line. Add no claim the English does not make. "
        "Return ONLY JSON {\"title\": \"...\", \"description\": \"...\"}.")
    return _ask(system, json.dumps({"title": title, "description": description}, ensure_ascii=False),
                metadata_max_tokens(title, description), lang, "title and description")


def parse_srt(text: str) -> list[dict]:
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        if len(lines) >= 3 and "-->" in lines[1]:
            cues.append({"index": lines[0].strip(), "time": lines[1].strip(),
                         "text": " ".join(line.strip() for line in lines[2:])})
    return cues


def render_srt(cues: list[dict]) -> str:
    return "\n\n".join(f"{c['index']}\n{c['time']}\n{c['text']}" for c in cues) + "\n"


def translate_captions(cues: list[dict], lang: str) -> list[dict]:
    system = (
        f"Translate documentary narration subtitles into {LANG_NAMES.get(lang, lang)}. Keep each "
        "cue's meaning and every number exactly; natural spoken style; no additions. Return ONLY "
        "JSON {\"cues\": [\"...\", ...]} with exactly as many strings as cues given, in order.")
    out = []
    for start in range(0, len(cues), 25):
        batch = cues[start:start + 25]
        reply = _ask(system, json.dumps({"cues": [c["text"] for c in batch]}, ensure_ascii=False),
                     8000, lang, f"subtitle cues {batch[0]['index']}-{batch[-1]['index']}")
        texts = reply.get("cues") or []
        if len(texts) != len(batch):
            raise ValueError(f"{lang}: {len(texts)} caption cues back for {len(batch)} sent")
        out += [{**cue, "text": str(text).strip()} for cue, text in zip(batch, texts)]
    for source, translated in zip(cues, out):
        lost = lost_numbers(source["text"], translated["text"])
        if lost:
            raise ValueError(f"{lang}: cue {source['index']} lost a number {lost}")
    return out


def source_sha256(source: dict) -> str:
    """The hash of an English title + description, stored on each language it was translated from."""
    return hashlib.sha256(json.dumps({"title": source.get("title", ""),
                                      "description": source.get("description", "")},
                                     ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def plan_languages(previous: dict, source: dict, wanted: list[str], video_id: str,
                   if_changed: bool) -> tuple[list[str], str, bool]:
    """(languages to translate now, a note, whether existing caption tracks need nothing).

    Without --if-changed, or with no record for this video: every requested language. With it:
    each language whose metadata was translated from a different English than the live title and
    description (a retitle, or a re-described film) is re-translated, and so is each language not
    yet done (de/fr/it added 2026-10-14); the rest cost nothing. Each language is held to the
    English it was translated from (source_sha256), not to the record's "source", which is only
    the last run's: run one language at a time and a later run's English would otherwise mark an
    earlier language current (2026-10-16). An entry from before the per-language hash falls back
    to the record's "source"."""
    if not (if_changed and previous.get("video_id") == video_id):
        return wanted, "", False
    languages = previous.get("languages") or {}
    live = source_sha256(source)
    legacy = source_sha256(previous["source"]) if isinstance(previous.get("source"), dict) else None
    # A language skipped for this same English (Hindi over the byte limit, say) would fail the
    # same way again: it is done until the English changes, so unchanged runs buy nothing.
    done = {lang for lang, entry in languages.items()
            if isinstance(entry, dict) and isinstance(entry.get("metadata"), dict)
            and (entry["metadata"].get("title") or entry["metadata"].get("skipped"))}
    missing = [lang for lang in wanted if lang not in done]
    changed = [lang for lang in wanted if lang in done
               and languages[lang].get("source_sha256", legacy) != live]
    todo = [lang for lang in wanted if lang in missing or lang in changed]
    if not todo:
        return [], "unchanged: live title and description match the localized source; nothing to do", False
    if not changed:
        return todo, f"live title and description unchanged; translating the missing {missing}", False
    note = f"live title or description changed since {changed} were localized; re-translating"
    if missing:
        note += f", and translating the missing {missing}"
    # The narration and its subtitles have not changed, so existing caption tracks are kept --
    # unless a language's track failed before (captions_error), which this run may retry; main()
    # still skips every language that already has a track on YouTube.
    keep = set(todo) <= set(languages) and not any(
        isinstance(languages.get(lang), dict) and languages[lang].get("captions_error")
        for lang in todo)
    return todo, note, keep


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("video_id")
    parser.add_argument("--job", required=True)
    parser.add_argument("--langs", default=DEFAULT_LANGS)
    parser.add_argument("--channel", default="world", choices=["world", "history"])
    parser.add_argument("--no-captions", action="store_true")
    parser.add_argument("--if-changed", action="store_true",
                        help="do nothing unless the live title/description differ from the last "
                             "localized source or a requested language is missing (no model calls)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    import youtube_upload
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload

    yt = build("youtube", "v3", credentials=youtube_upload._creds(args.channel), cache_discovery=False)
    video = yt.videos().list(part="snippet,localizations", id=args.video_id).execute()["items"][0]
    snippet = video["snippet"]
    source = {"title": snippet["title"], "description": snippet.get("description", "")}
    default_lang = snippet.get("defaultLanguage") or "en"
    localizations = dict(video.get("localizations") or {})
    # The default language's entry mirrors the live English title and description; a stale one
    # kept the old title after a retitle (2026-10-11).
    localizations[default_lang] = source
    cues = []
    srt_path = os.path.join(args.job, "captions.srt")
    if not args.no_captions and os.path.isfile(srt_path):
        cues = parse_srt(open(srt_path, encoding="utf-8").read())
    existing_tracks = {c["snippet"]["language"] for c in yt.captions().list(
        part="snippet", videoId=args.video_id).execute().get("items", [])
        if c["snippet"].get("trackKind") != "asr"}
    record_path = os.path.join(args.job, "localizations.json")
    previous = {}
    if os.path.isfile(record_path):
        try:
            previous = json.load(open(record_path, encoding="utf-8"))
        except ValueError:
            previous = {}
    wanted, note, keep_captions = plan_languages(
        previous, source, [l.strip() for l in args.langs.split(",") if l.strip()],
        args.video_id, args.if_changed)
    if note:
        print(note)
    if not wanted:
        return 0
    args.no_captions = args.no_captions or keep_captions
    # Runs for a subset of languages add to the record instead of replacing it. "source" is this
    # run's English; each language keeps the source_sha256 of the English it was translated from.
    record = {"video_id": args.video_id, "source": source, "model": MODEL,
              "languages": dict(previous.get("languages") or {}) if previous.get("video_id") == args.video_id else {}}
    # An entry from before the per-language hash was translated, as far as the record knows, from
    # the previous "source": pin that before this run's English replaces it.
    if record["languages"] and isinstance(previous.get("source"), dict):
        pinned = source_sha256(previous["source"])
        record["languages"] = {lang: {**entry, "source_sha256": pinned}
                               if isinstance(entry, dict) and "source_sha256" not in entry else entry
                               for lang, entry in record["languages"].items()}
    for lang in wanted:
        entry: dict = {}
        translated = fit_translation(translate_metadata(source["title"], source["description"], lang))
        problems = check_translation(source, translated)
        # One retry, then skip the language rather than ship a broken one. Size alone is not
        # retried: fit_translation has already shed all it may, and a new call would not fit.
        if problems and not all(p.startswith("description over") for p in problems):
            translated = fit_translation(
                translate_metadata(source["title"], source["description"], lang))
            problems = check_translation(source, translated)
        if problems:
            entry["metadata"] = {"skipped": problems}
        else:
            localizations[lang] = {"title": translated["title"],
                                   "description": translated["description"]}
            entry["metadata"] = localizations[lang]
        entry["source_sha256"] = source_sha256(source)
        if cues and lang not in existing_tracks:
            try:
                translated_cues = translate_captions(cues, lang)
                path = os.path.join(args.job, f"captions.{lang}.srt")
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(render_srt(translated_cues))
                entry["captions"] = path
                if not args.dry_run:
                    media = MediaIoBaseUpload(io.BytesIO(render_srt(translated_cues).encode("utf-8")),
                                              mimetype="application/octet-stream", resumable=False)
                    track = yt.captions().insert(part="snippet", body={"snippet": {
                        "videoId": args.video_id, "language": lang, "name": "", "isDraft": False}},
                        media_body=media).execute()
                    entry["caption_track"] = track["id"]
            except Exception as exc:  # noqa: BLE001 - a failed subtitle track skips that track only
                entry["captions_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        elif lang in existing_tracks:
            entry["captions"] = "existing track kept"
        record["languages"][lang] = {**record["languages"].get(lang, {}), **entry}
        print(f"{lang}: {entry.get('metadata', {}).get('title') or entry['metadata']}"
              f" | captions: {entry.get('caption_track') or entry.get('captions') or entry.get('captions_error')}")
    if not args.dry_run:
        body = {"id": args.video_id,
                "snippet": {key: snippet[key] for key in ("title", "description", "categoryId", "tags",
                                                          "defaultAudioLanguage") if key in snippet},
                "localizations": localizations}
        body["snippet"]["defaultLanguage"] = default_lang
        yt.videos().update(part="snippet,localizations", body=body).execute()
    with open(record_path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=1)
    print("written:", os.path.join(args.job, "localizations.json"),
          "(dry run, nothing sent)" if args.dry_run else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
