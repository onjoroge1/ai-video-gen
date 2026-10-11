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
titled from teaser_package.json, with a description that links to the full film recorded in
youtube.json. Writes <job>/youtube_teaser.json and refuses if it exists.
Publishing stays a human decision in Studio.
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


def build_tags(job: str, title: str) -> list[str]:
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
    pipeline_tags = []
    if os.path.isfile(os.path.join(job, "description.txt")):
        for line in open(os.path.join(job, "description.txt"), encoding="utf-8"):
            if line.strip().lower().startswith("tags:"):
                pipeline_tags = [t.strip() for t in line.split(":", 1)[1].split(",") if t.strip()]
    search = _search_phrase(job, title, pipeline_tags)
    videos, error = [], ""
    try:
        videos = tag_strategy.harvest(search, os.environ["YOUTUBE_API_KEY"])
    except Exception as exc:  # noqa: BLE001 - a failed harvest falls back to the pipeline's tags
        error = f"{type(exc).__name__}: {str(exc)[:160]}"
    result = tag_strategy.select_tags(videos, transcript, title, pipeline_tags)
    result.update(search=search, harvest_error=error)
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
    tags = build_tags(job, title)
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "youtube_upload.py"),
           "--video", video, "--title", title, "--channel", args.channel,
           "--tags", ",".join(tags)]
    if os.path.isfile(os.path.join(job, "description.txt")):
        # The tags travel in the tags field; the description's own "Tags:" line is removed.
        clean = os.path.join(job, "upload_description.txt")
        with open(clean, "w", encoding="utf-8") as handle:
            handle.write(_description_without_tag_line(os.path.join(job, "description.txt")))
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
    description = (f"Watch the full story: https://youtu.be/{film_id}\n\n{body}").strip()
    desc_path = os.path.join(job, "teaser_upload_description.txt")
    with open(desc_path, "w", encoding="utf-8") as handle:
        handle.write(description + "\n")
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "youtube_upload.py"), "--video", video,
           "--title", title, "--short", "--description-file", desc_path, "--channel", channel,
           "--tags", ",".join((["shorts"] + build_tags(job, json.load(open(film)).get("title", title)))
                              if os.path.isfile(film) else (package.get("tags") or []))]
    if dry_run:
        cmd.append("--dry-run")
    run = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    print(run.stdout[-2000:], run.stderr[-1000:], sep="\n")
    match = re.search(r"studio\.youtube\.com/video/([A-Za-z0-9_-]{6,})/edit", run.stdout)
    if run.returncode != 0 or not match:
        return run.returncode or 1
    if not dry_run:
        with open(record_path, "w", encoding="utf-8") as handle:
            json.dump({"video_id": match.group(1), "title": title, "privacy": "private",
                       "channel": channel, "full_film": film_id,
                       "studio": f"https://studio.youtube.com/video/{match.group(1)}/edit"},
                      handle, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
