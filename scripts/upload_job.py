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
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "youtube_upload.py"),
           "--video", video, "--title", title, "--channel", args.channel]
    if os.path.isfile(os.path.join(job, "description.txt")):
        cmd += ["--description-file", os.path.join(job, "description.txt")]
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
           "--tags", ",".join(package.get("tags") or [])]
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
