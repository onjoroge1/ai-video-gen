#!/usr/bin/env python3
"""Translated titles, descriptions and subtitles for a live video (operator, 2026-10-11).

    python3 scripts/localize_video.py eWJr_iwUNx4 --job jobs/asian-carp [--langs es,pt,id,hi]
                                      [--channel world] [--no-captions] [--dry-run]

YouTube shows a localized title and description to viewers whose YouTube language matches, in
search, suggestions and the home feed. The narration stays English, so each language also gets a
subtitle track translated from <job>/captions.srt: a viewer who clicks a Spanish title can follow
an English film. Translates the video's LIVE title and description (the operator edits them in
Studio after upload), checks every translation keeps each number, URL and chapter timestamp, and
writes <job>/localizations.json. Needs the youtube.force-ssl scope (scripts/youtube_oauth_setup.py).
Existing localizations in other languages and existing caption tracks are left as they are.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

LANG_NAMES = {"es": "Spanish (Latin American)", "pt": "Portuguese (Brazilian)",
              "id": "Indonesian", "hi": "Hindi", "de": "German", "fr": "French",
              "tr": "Turkish", "ko": "Korean", "ja": "Japanese", "ar": "Arabic"}
MODEL = os.environ.get("LOCALIZE_MODEL", "claude-sonnet-5-5")
_URL = re.compile(r"https?://\S+")
_TIMESTAMP = re.compile(r"^\s*(\d{1,2}:\d{2}(?::\d{2})?)\b", re.M)


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", text or ""))


def check_translation(source: dict, translated: dict) -> list[str]:
    """Reasons a translated title/description cannot be used; [] when it can."""
    problems = []
    title, desc = translated.get("title", ""), translated.get("description", "")
    if not title.strip() or len(title) > 100:
        problems.append(f"title empty or over 100 characters ({len(title)})")
    if len(desc) > 5000:
        problems.append(f"description over 5000 characters ({len(desc)})")
    missing = _numbers(source["title"]) - _numbers(title)
    if missing:
        problems.append(f"title lost numbers {sorted(missing)}")
    for url in _URL.findall(source["description"]):
        if url not in desc:
            problems.append(f"description lost URL {url}")
    lost = set(_TIMESTAMP.findall(source["description"])) - set(_TIMESTAMP.findall(desc))
    if lost:
        problems.append(f"description lost chapter timestamps {sorted(lost)}")
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
        "100 characters. Translate the description faithfully: keep every number exactly, every "
        "URL unchanged, every chapter line's timestamp unchanged (translate only its label), "
        "hashtags unchanged, line breaks kept. Add no claim the English does not make. "
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("video_id")
    parser.add_argument("--job", required=True)
    parser.add_argument("--langs", default="es,pt,id,hi")
    parser.add_argument("--channel", default="world", choices=["world", "history"])
    parser.add_argument("--no-captions", action="store_true")
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
    localizations.setdefault(default_lang, source)
    cues = []
    srt_path = os.path.join(args.job, "captions.srt")
    if not args.no_captions and os.path.isfile(srt_path):
        cues = parse_srt(open(srt_path, encoding="utf-8").read())
    existing_tracks = {c["snippet"]["language"] for c in yt.captions().list(
        part="snippet", videoId=args.video_id).execute().get("items", [])
        if c["snippet"].get("trackKind") != "asr"}
    record = {"video_id": args.video_id, "source": source, "model": MODEL, "languages": {}}
    for lang in [l.strip() for l in args.langs.split(",") if l.strip()]:
        entry: dict = {}
        translated = translate_metadata(source["title"], source["description"], lang)
        problems = check_translation(source, translated)
        if problems:      # one retry, then skip the language rather than ship a broken one
            translated = translate_metadata(source["title"], source["description"], lang)
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
        record["languages"][lang] = entry
        print(f"{lang}: {entry.get('metadata', {}).get('title') or entry['metadata']}"
              f" | captions: {entry.get('caption_track') or entry.get('captions') or entry.get('captions_error')}")
    if not args.dry_run:
        body = {"id": args.video_id,
                "snippet": {key: snippet[key] for key in ("title", "description", "categoryId", "tags",
                                                          "defaultAudioLanguage") if key in snippet},
                "localizations": localizations}
        body["snippet"]["defaultLanguage"] = default_lang
        yt.videos().update(part="snippet,localizations", body=body).execute()
    with open(os.path.join(args.job, "localizations.json"), "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=1)
    print("written:", os.path.join(args.job, "localizations.json"),
          "(dry run, nothing sent)" if args.dry_run else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
