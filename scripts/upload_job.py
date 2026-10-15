#!/usr/bin/env python3
"""Upload a finished job to YouTube as PRIVATE and record the video id in the job directory.

    python3 scripts/upload_job.py jobs/bees_v15 [--title "..."] [--dry-run]

Takes the title from run_result.json (or --title), the description from description.txt and the
thumbnail from thumbnail.jpg, runs the preflight YouTube check first (the token must be bound to
the World channel), and calls scripts/youtube_upload.py, which uploads private and refuses a
token bound to any other channel. Writes <job>/youtube.json with the video id and Studio link.
Refuses a job that already has one, so a routine re-run cannot upload a film twice.

    python3 scripts/upload_job.py jobs/bees_v15 --teaser

uploads the companion Short instead: <job>/teaser.mp4 (scripts/make_teaser_short.py), private,
titled from teaser_package.json, with a description whose first line links to the full film
recorded in youtube.json, then adds a "Short version:" line to the film's own description.
Writes <job>/youtube_teaser.json and refuses if it exists.
Publishing stays a human decision in Studio.

The description follows the channel template (audit, 2026-10-13): no "Tags:" list, the
channel's own subscribe line, at most three hashtags, and the audience tags that tell YouTube
who the film is for. Its body follows the film template (description_template, 2026-10-14):
summary, sourcing promise, chapters, RESEARCH & SOURCES rebuilt from the job's own claims,
PEOPLE & PLACES (one cheap fact-checked call when description.txt has none; --no-people skips
it), then the Short link, CTA, hashtags and AI line. The layout report goes to
<job>/description_template.json.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _search_phrase(job: str, title: str, pipeline_tags: list[str] | None = None) -> str:
    """The topic's market search phrase from topics/research.json, else the film's first topic
    tag, else the title's first clause ("The 26-Queen Mistake" found no competitors at all)."""
    slug = os.path.basename(job.rstrip("/"))
    try:
        research = json.load(open(os.path.join(ROOT, "topics", "research.json")))
        for row in research.get("ranked") or []:
            if row.get("slug") == slug and row.get("search"):
                return row["search"]
    except (OSError, ValueError):
        pass
    if pipeline_tags:
        return pipeline_tags[0]
    return re.split(r"\.\s|\s\(|\s+That\s", title)[0]


def _description_without_tag_line(path: str) -> str:
    text = open(path, encoding="utf-8").read()
    return "\n".join(line for line in text.splitlines()
                     if not line.strip().lower().startswith("tags:")).strip() + "\n"


# The pipeline's generic line said nothing about what the channel is; the audit rewrote every
# film to this one (2026-10-13). A channel without its own line keeps whatever the film had.
CTAS = {"world": "Subscribe to Bolt Explains the World for illustrated true stories of fixes "
                 "that backfired.",
        # Matches the History channel description (2026-10-14).
        "history": "Subscribe to Bolt Explains History for true stories of what governments "
                   "imposed, and what it cost."}
_OLD_CTA = re.compile(r"^Subscribe (for clear, no-spin explainers|to Bolt Explains the World for "
                      r"illustrated (stories|documentaries) about human decisions)", re.I)
_HASHTAG_LINE = re.compile(r"^\s*(#\w+\s*)+$")
MAX_HASHTAGS = 3
SHORT_LINE_ROOM = 80          # bytes left free for "Short version: https://youtube.com/shorts/..."


def upload_description(text: str, channel: str) -> str:
    """The film's description as uploaded: the template's footer rules applied to the pipeline's."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("tags:"):
            continue
        if channel in CTAS and _OLD_CTA.match(stripped):
            line = CTAS[channel]
        elif _HASHTAG_LINE.match(stripped):
            line = " ".join(stripped.split()[:MAX_HASHTAGS])
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def add_short_line(description: str, short_id: str, channel: str = "world") -> str:
    """"Short version: <url>" directly above the subscribe line (else above the AI line, else last)."""
    url = f"https://youtube.com/shorts/{short_id}"
    if url in description:
        return description
    lines = description.rstrip("\n").split("\n")
    anchors = [CTAS.get(channel, "\0"), "Subscribe ", "🤖"]
    for anchor in anchors:
        for index, line in enumerate(lines):
            if line.strip().startswith(anchor):
                return "\n".join(lines[:index] + [f"Short version: {url}"] + lines[index:]) + "\n"
    return "\n".join(lines + ["", f"Short version: {url}"]) + "\n"


def audience_tags(job: str, transcript: str, channel: str = "world") -> list[str]:
    """The fixed audience layer: who the film is for, independent of its topic.

    "nature documentary" when the direction is about an animal or a species, else "history
    documentary"; "invasive species documentary" only for an introduction story, which the
    narration says in that word (carp, toads, hippos -- not the Yellowstone wolves or sparrows).
    """
    if channel == "history":
        # The History channel's own layer: who the film is for, not what it is about.
        return ["history documentary", "dark history"]
    if channel != "world":
        return []
    slug = os.path.basename(job.rstrip("/"))
    direction = ""
    for path in (os.path.join(job, "direction.txt"),
                 os.path.join(ROOT, "topics", "directions", f"{slug}.txt")):
        if os.path.isfile(path):
            direction = open(path, encoding="utf-8").read()
            break
    first = (direction.strip().splitlines() or [""])[0].lower()
    nature = bool(re.search(r"\banimal|\bspecies|\bwildlife|\becolog", first))
    tags = ["unintended consequences", "nature documentary" if nature else "history documentary"]
    if re.search(r"\binvasive\b", transcript or "", re.I):
        tags.append("invasive species documentary")
    return tags


def pipeline_tags_of(job: str) -> list[str]:
    """The pipeline's architecture tags: pipeline_tags.json (2026-10-14 on), else an older job's
    description "Tags:" line."""
    path = os.path.join(job, "pipeline_tags.json")
    if os.path.isfile(path):
        try:
            tags = json.load(open(path, encoding="utf-8")).get("tags") or []
            if tags:
                return [str(t) for t in tags]
        except ValueError:
            pass
    if os.path.isfile(os.path.join(job, "description.txt")):
        for line in open(os.path.join(job, "description.txt"), encoding="utf-8"):
            if line.strip().lower().startswith("tags:"):
                return [t.strip() for t in line.split(":", 1)[1].split(",") if t.strip()]
    return []


def template_description(job: str, text: str, people: bool = True, complete=None,
                         log=print) -> str:
    """`text` laid out in the film template from the job's own artifacts.

    A job with no research artifacts keeps its text, minus the retired sections. People & Places
    lines already in the text are re-checked; when there are none, one cheap model call writes
    them (people=False skips it). Never raises: an upload must not fail on its description.
    """
    import description_template as dt
    try:
        facts = dt.load_job(job, recut=False)          # the uploader sends explainer.mp4
        if not dt.cited_claims(facts["script"]):
            log("description: no research artifacts in the job; retired sections removed only")
            return dt.strip_retired(text) + "\n"
        existing = dt.parse(text)["people"]
        lines = None
        spend: list[float] = []
        if not existing and people:
            if complete is None:
                from dotenv import load_dotenv
                load_dotenv(os.path.join(ROOT, ".env"))
                complete = dt.anthropic_complete(spend)
            lines, people_report = dt.people_and_places(
                facts["transcript"], dt.cited_claims(facts["script"]), complete)
        # Room for the "Short version:" line add_short_line puts in once the teaser is up.
        new, report = dt.rebuild(text, facts, lines, limit=dt.MAX_BYTES - SHORT_LINE_ROOM)
        if lines is not None:
            report["people_generated"] = people_report
        report["people_spend_usd"] = round(sum(spend), 6)
        with open(os.path.join(job, "description_template.json"), "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=1, ensure_ascii=False)
        log(f"description: template applied ({report['bytes']} bytes, {report['sources_listed']}/"
            f"{report['sources_used']} sources, {report['people_listed']} people & places lines, "
            f"promise {report['promise_kind'] or 'omitted'})")
        return new + "\n"
    except Exception as exc:  # noqa: BLE001 - the pipeline's own description still uploads
        log(f"description: template not applied ({type(exc).__name__}: {str(exc)[:160]})")
        return dt.strip_retired(text) + "\n"


def build_tags(job: str, title: str, channel: str = "world") -> list[str]:
    """Researched tags for the job (tag_strategy), written to <job>/tags.json once and reused.

    Tags are treated as seriously as the title (operator, 2026-10-11): harvested from the
    topic's winning videos, kept only when the film can claim them, recorded with provenance.
    """
    path = os.path.join(job, "tags.json")
    if os.path.isfile(path):
        return json.load(open(path))["tags"]
    import tag_strategy
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    transcript = ""
    if os.path.isfile(os.path.join(job, "transcript.txt")):
        transcript = open(os.path.join(job, "transcript.txt"), encoding="utf-8").read()
    pipeline_tags = pipeline_tags_of(job)
    search = _search_phrase(job, title, pipeline_tags)
    videos, error = [], ""
    try:
        videos = tag_strategy.harvest(search, os.environ["YOUTUBE_API_KEY"])
    except Exception as exc:  # noqa: BLE001 - a failed harvest falls back to the pipeline's tags
        error = f"{type(exc).__name__}: {str(exc)[:160]}"
    audience = audience_tags(job, transcript, channel)
    result = tag_strategy.select_tags(videos, transcript, title, pipeline_tags, audience=audience,
                                      brand=tag_strategy.CHANNEL_TAGS.get(channel,
                                                                         tag_strategy.CHANNEL_TAG))
    result.update(search=search, harvest_error=error, audience=audience)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1)
    print(f"tags: {len(result['tags'])} ({sum(1 for s in result['sources'].values() if s['source'] == 'competitor')} "
          f"from {len(videos)} competitor videos for {search!r}){' -- harvest failed: ' + error if error else ''}")
    return result["tags"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("job")
    parser.add_argument("--title", default="")
    parser.add_argument("--channel", default="world", choices=["world", "history"])
    parser.add_argument("--teaser", action="store_true",
                        help="upload the companion Short (teaser.mp4) after the full film")
    parser.add_argument("--no-people", action="store_true",
                        help="skip the People & Places call when description.txt has none")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    job = os.path.abspath(args.job)
    if args.teaser:
        return upload_teaser(job, args.channel, args.dry_run)
    record_path = os.path.join(job, "youtube.json")
    if os.path.exists(record_path):
        print(f"already uploaded: {open(record_path).read().strip()}")
        return 1
    video = os.path.join(job, "explainer.mp4")
    if not os.path.isfile(video):
        sys.exit(f"no film at {video}")
    result = json.load(open(os.path.join(job, "run_result.json"))) if os.path.exists(
        os.path.join(job, "run_result.json")) else {}
    title = (args.title or result.get("title") or "").strip()
    if not title:
        sys.exit("no title: pass --title or finish the run so run_result.json has one")
    preflight = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "preflight.py"),
                                "--need-upload", "--min-free-gb", "0", "--channel", args.channel],
                               capture_output=True, text=True)
    youtube_line = [line for line in preflight.stdout.splitlines() if "youtube" in line]
    if not youtube_line or not youtube_line[0].startswith("PASS"):
        print("\n".join(youtube_line) or preflight.stdout)
        return 1
    tags = build_tags(job, title, args.channel)
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "youtube_upload.py"),
           "--video", video, "--title", title, "--channel", args.channel,
           "--tags", ",".join(tags)]
    if os.path.isfile(os.path.join(job, "description.txt")):
        # The tags travel in the tags field; the description's own "Tags:" line is removed.
        clean = os.path.join(job, "upload_description.txt")
        # Footer rules first, then the template, whose byte budget is the last word on length.
        body = template_description(
            job, upload_description(open(os.path.join(job, "description.txt"),
                                         encoding="utf-8").read(), args.channel),
            people=not args.no_people)
        with open(clean, "w", encoding="utf-8") as handle:
            handle.write(body)
        cmd += ["--description-file", clean]
    if os.path.isfile(os.path.join(job, "thumbnail.jpg")):
        cmd += ["--thumbnail", os.path.join(job, "thumbnail.jpg")]
    if args.dry_run:
        cmd.append("--dry-run")
    run = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    print(run.stdout[-2000:], run.stderr[-1000:], sep="\n")
    match = re.search(r"studio\.youtube\.com/video/([A-Za-z0-9_-]{6,})/edit", run.stdout)
    if run.returncode != 0 or not match:
        return run.returncode or 1
    if not args.dry_run:
        with open(record_path, "w", encoding="utf-8") as handle:
            json.dump({"video_id": match.group(1), "title": title, "privacy": "private",
                       "channel": args.channel,
                       "studio": f"https://studio.youtube.com/video/{match.group(1)}/edit"}, handle, indent=1)
    return 0


def upload_teaser(job: str, channel: str, dry_run: bool) -> int:
    record_path = os.path.join(job, "youtube_teaser.json")
    if os.path.exists(record_path):
        print(f"teaser already uploaded: {open(record_path).read().strip()}")
        return 1
    film = os.path.join(job, "youtube.json")
    video = os.path.join(job, "teaser.mp4")
    package_path = os.path.join(job, "teaser_package.json")
    if not os.path.isfile(film):
        sys.exit("upload the full film first: the Short's description links to it")
    if not (os.path.isfile(video) and os.path.isfile(package_path)):
        sys.exit(f"no teaser in {job}: run scripts/make_teaser_short.py {job} first")
    film_id = json.load(open(film))["video_id"]
    package = json.load(open(package_path))
    title = re.sub(r"\s*#shorts\s*$", "", (package.get("title") or "").strip(), flags=re.I)
    body = (package.get("description") or "").replace("Full story on the channel.", "").strip()
    body = re.sub(r"(?m)^\s*#shorts\s*$", "", body, flags=re.I).strip()
    # A CC BY music bed must be credited wherever it plays (the wolf Short's credit was missing).
    music = []
    if os.path.isfile(os.path.join(job, "description.txt")):
        music = [line.strip() for line in open(os.path.join(job, "description.txt"), encoding="utf-8")
                 if line.strip().lower().startswith("music:")]
    description = "\n\n".join(part for part in (
        f"Full film: https://youtu.be/{film_id}", body, "\n".join(music), "#Shorts") if part)
    desc_path = os.path.join(job, "teaser_upload_description.txt")
    with open(desc_path, "w", encoding="utf-8") as handle:
        handle.write(description + "\n")
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "youtube_upload.py"), "--video", video,
           "--title", title, "--short", "--description-file", desc_path, "--channel", channel,
           "--tags", ",".join((["shorts"] + build_tags(job, json.load(open(film)).get("title", title),
                                                       channel))
                              if os.path.isfile(film) else (package.get("tags") or []))]
    if dry_run:
        cmd.append("--dry-run")
    run = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    print(run.stdout[-2000:], run.stderr[-1000:], sep="\n")
    match = re.search(r"studio\.youtube\.com/video/([A-Za-z0-9_-]{6,})/edit", run.stdout)
    if run.returncode != 0 or not match:
        return run.returncode or 1
    if not dry_run:
        linked = link_short_in_film(film_id, match.group(1), channel)
        with open(record_path, "w", encoding="utf-8") as handle:
            json.dump({"video_id": match.group(1), "title": title, "privacy": "private",
                       "channel": channel, "full_film": film_id, "film_links_short": linked,
                       "studio": f"https://studio.youtube.com/video/{match.group(1)}/edit"},
                      handle, indent=1)
    return 0


def link_short_in_film(film_id: str, short_id: str, channel: str):
    """Add "Short version: <url>" to the film's live description; True, or the error as text.

    A failure here never undoes the Short's upload. The film's default-language localization
    mirrors the new text (a stale one kept an old title after a retitle, 2026-10-11).
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import youtube_upload
        from googleapiclient.discovery import build
        yt = build("youtube", "v3", credentials=youtube_upload._creds(channel), cache_discovery=False)
        video = yt.videos().list(part="snippet,localizations", id=film_id).execute()["items"][0]
        snippet = video["snippet"]
        description = add_short_line(snippet.get("description", ""), short_id, channel)
        if description == snippet.get("description", ""):
            return True
        body_snippet = {key: snippet[key] for key in ("title", "categoryId", "tags", "defaultLanguage",
                                                      "defaultAudioLanguage") if key in snippet}
        body_snippet["description"] = description
        body = {"id": film_id, "snippet": body_snippet}
        parts = "snippet"
        localizations = dict(video.get("localizations") or {})
        default = snippet.get("defaultLanguage")
        if default in localizations:
            localizations[default] = {"title": snippet["title"], "description": description}
            body["localizations"] = localizations
            parts = "snippet,localizations"
        yt.videos().update(part=parts, body=body).execute()
        print(f"film {film_id}: added Short version link")
        return True
    except Exception as exc:  # noqa: BLE001 - the Short is uploaded either way
        print(f"film {film_id}: Short link not added ({type(exc).__name__}: {str(exc)[:160]})")
        return f"{type(exc).__name__}: {str(exc)[:160]}"


if __name__ == "__main__":
    sys.exit(main())
