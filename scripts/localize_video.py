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
lines are translated, and every number the English states must still be there. A translation
over YouTube's 5000-byte description limit (Hindi doubles the bytes) loses its "↳" lines, then
its People & Places section, before it is checked. --if-changed re-translates every language when
the live English title or description changed, and otherwise only the languages not yet done.
"""
from __future__ import annotations

import argparse
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
_TIMESTAMP = re.compile(r"^\s*(\d{1,2}:\d{2}(?::\d{2})?)\b", re.M)


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", text or ""))


# A number however a language groups or points it: 60,000 / 60.000 / 60 000 are "60000", 2.5 and
# 2,5 are "25"; native digits (Devanagari) read as ASCII.
_GROUPED_NUMBER = re.compile(r"\d{1,3}(?:[,.\u00a0\u202f\u2009 ]\d{3})+(?!\d)|\d+(?:[.,]\d+)?")


def _ascii_digits(text: str) -> str:
    return "".join(str(unicodedata.decimal(ch)) if ch.isdecimal() and not ch.isascii() else ch
                   for ch in text or "")


def description_numbers(text: str) -> set[str]:
    return {re.sub(r"\D", "", m.group(0)) for m in _GROUPED_NUMBER.finditer(_ascii_digits(text))}


def _without_findings(text: str) -> str:
    return "\n".join(l for l in (text or "").split("\n") if not l.strip().startswith(FINDING_MARK))


def _without_people(text: str) -> str:
    blocks = re.split(r"\n[ \t]*\n", text or "")
    return "\n\n".join(b for b in blocks if not b.strip().startswith(PEOPLE_MARK))


def fit_translation(translated: dict, limit: int = MAX_DESCRIPTION_BYTES) -> dict:
    """A translated description cut to YouTube's byte limit: its "↳" findings go first, then its
    People & Places section. The citations, chapters, links and footer are never cut."""
    desc = translated.get("description", "")
    for shrink in (_without_findings, _without_people):
        if len(desc.encode("utf-8")) <= limit:
            break
        desc = re.sub(r"\n{3,}", "\n\n", shrink(desc)).strip()
    return {**translated, "description": desc}


def citation_lines(description: str) -> list[str]:
    """The line above each bare URL line of the template's research section: a source's citation,
    which stays in its own language. An older description's free-form labels are not held to it."""
    if RESEARCH_HEADER not in (description or ""):
        return []
    lines = [l.strip() for l in (description or "").split("\n")]
    out = []
    for index, line in enumerate(lines):
        if index and re.fullmatch(r"https?://\S+", line):
            above = lines[index - 1]
            if above and not _URL.search(above) and not above.startswith(FINDING_MARK) \
                    and not above.startswith(("📚", "📍", "⏱")):
                out.append(above)
    return out


def check_translation(source: dict, translated: dict) -> list[str]:
    """Reasons a translated title/description cannot be used; [] when it can."""
    problems = []
    title, desc = translated.get("title", ""), translated.get("description", "")
    if not title.strip() or len(title) > 100:
        problems.append(f"title empty or over 100 characters ({len(title)})")
    size = len(desc.encode("utf-8"))
    if size > MAX_DESCRIPTION_BYTES:
        problems.append(f"description over {MAX_DESCRIPTION_BYTES} bytes ({size})")
    missing = _numbers(source["title"]) - _numbers(title)
    if missing:
        problems.append(f"title lost numbers {sorted(missing)}")
    for url in _URL.findall(source["description"]):
        if url not in desc:
            problems.append(f"description lost URL {url}")
    lost = set(_TIMESTAMP.findall(source["description"])) - set(_TIMESTAMP.findall(desc))
    if lost:
        problems.append(f"description lost chapter timestamps {sorted(lost)}")
    # Numbers are compared against the English minus whatever fit_translation removed, so a
    # Hindi description that lost its findings to the byte limit is not failed for their numbers.
    english = source["description"]
    if FINDING_MARK not in desc:
        english = _without_findings(english)
    if PEOPLE_MARK not in desc:
        english = _without_people(english)
    lost_numbers = description_numbers(english) - description_numbers(desc)
    if lost_numbers:
        problems.append(f"description lost numbers {sorted(lost_numbers)}")
    kept = {l.strip() for l in desc.split("\n")}
    for line in citation_lines(source["description"]):
        if line not in kept:
            problems.append(f"description changed a source citation: {line[:80]}")
    return problems


def _client():
    import anthropic
    return anthropic.Anthropic()


def _ask(system: str, user: str, max_tokens: int = 4000) -> dict:
    response = _client().messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                                         messages=[{"role": "user", "content": user}])
    text = next(b.text for b in response.content if getattr(b, "type", "") == "text")
    match = re.search(r"\{.*\}", text, re.S)
    return json.loads(match.group(0) if match else text)


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
    return _ask(system, json.dumps({"title": title, "description": description}, ensure_ascii=False))


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
                     max_tokens=8000)
        texts = reply.get("cues") or []
        if len(texts) != len(batch):
            raise ValueError(f"{lang}: {len(texts)} caption cues back for {len(batch)} sent")
        out += [{**cue, "text": str(text).strip()} for cue, text in zip(batch, texts)]
    for source, translated in zip(cues, out):
        if _numbers(source["text"]) - _numbers(translated["text"]):
            raise ValueError(f"{lang}: cue {source['index']} lost a number")
    return out


def plan_languages(previous: dict, source: dict, wanted: list[str], video_id: str,
                   if_changed: bool) -> tuple[list[str], str, bool]:
    """(languages to translate now, a note, whether existing caption tracks need nothing).

    Without --if-changed, or with no record for this video: every requested language. With it: a
    changed live English title or description (a retitle, or a re-described film) re-translates
    every requested language's metadata; an unchanged one translates only the languages not yet
    done (de/fr/it added 2026-10-14), so adding languages does not re-buy the others."""
    if not (if_changed and previous.get("video_id") == video_id):
        return wanted, "", False
    languages = previous.get("languages") or {}
    done = {lang for lang, entry in languages.items()
            if isinstance(entry.get("metadata"), dict) and entry["metadata"].get("title")}
    if previous.get("source") == source:
        missing = [lang for lang in wanted if lang not in done]
        if not missing:
            return [], "unchanged: live title and description match the localized source; nothing to do", False
        return missing, f"live title and description unchanged; translating the missing {missing}", False
    # The narration and its subtitles have not changed, so existing caption tracks are kept.
    return (wanted, "live title or description changed since the last localization; re-translating",
            set(wanted) <= set(languages))


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
    # Runs for a subset of languages add to the record instead of replacing it.
    record = {"video_id": args.video_id, "source": source, "model": MODEL,
              "languages": dict(previous.get("languages") or {}) if previous.get("video_id") == args.video_id else {}}
    for lang in wanted:
        entry: dict = {}
        translated = fit_translation(translate_metadata(source["title"], source["description"], lang))
        problems = check_translation(source, translated)
        if problems:      # one retry, then skip the language rather than ship a broken one
            translated = fit_translation(
                translate_metadata(source["title"], source["description"], lang))
            problems = check_translation(source, translated)
        if problems:
            entry["metadata"] = {"skipped": problems}
        else:
            localizations[lang] = {"title": translated["title"],
                                   "description": translated["description"]}
            entry["metadata"] = localizations[lang]
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
