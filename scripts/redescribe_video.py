#!/usr/bin/env python3
"""Re-lay a LIVE film's description in the film template, keeping the operator's own lines.

    python3 scripts/redescribe_video.py IN1DERNZ2zA --job jobs/history-aral-sea-v2 \\
        [--channel world|history] [--dry-run | --apply] [--out FILE] [--log FILE] [--no-people]

Reads the live description (videos.list) and keeps everything outside the managed sections as
found: the summary paragraphs, chapters, Short links, the CTA, hashtags, the AI line and any
custom lines, in their order. Replaces only the managed sections (description_template): adds the
sourcing promise when the job's claim ledger earns it, rebuilds RESEARCH & SOURCES from the claims
the film's narration cites (the operator's existing source labels are reused as citations; sources
the film did not use are dropped and listed), adds PEOPLE & PLACES (one cheap model call, every
number and name checked against the transcript and cited claims; an existing section is re-checked
instead), and removes IN THIS VIDEO, QUESTIONS ANSWERED and any Tags: line.

--dry-run (the default) prints the proposed description, a diff against the live one and a
report, and changes nothing on YouTube. --out FILE writes the same to a file.

--apply updates ONLY snippet.description. videos.update replaces the whole snippet, so every
other writable snippet field (title, tags, categoryId, defaultLanguage, defaultAudioLanguage, and
anything else the API returned) is sent back exactly as read, and compared after the update. When
the video has a localization in its default language it mirrors the new text (a stale one kept an
old title after a retitle, 2026-10-11); other languages are re-synced by
`scripts/localize_video.py <id> --job <job> --if-changed`. Each apply appends a record with the
before/after SHA-256 to jobs/yt/metadata_change_log.json (the main checkout's when run from a
worktree; --log overrides) and saves both texts in jobs/yt/redescribe/. A video with a title A/B
test recorded in that log as running is refused unless --during-title-test.
"""
from __future__ import annotations

import argparse
import datetime
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import description_template as dt  # noqa: E402

# Fields videos.list returns that videos.update does not take; everything else is sent back.
READ_ONLY_SNIPPET = {"publishedAt", "channelId", "thumbnails", "channelTitle",
                     "liveBroadcastContent", "localized"}
PRESERVED = ("title", "tags", "categoryId", "defaultLanguage", "defaultAudioLanguage")


def sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def main_checkout_root() -> str:
    """The repository's main checkout (jobs/ lives there), also when run from a worktree."""
    try:
        common = subprocess.run(["git", "-C", ROOT, "rev-parse", "--path-format=absolute",
                                 "--git-common-dir"], capture_output=True, text=True,
                                timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        common = ""
    return os.path.dirname(common) if common.endswith(".git") else ROOT


def default_log_path() -> str:
    return os.path.join(main_checkout_root(), "jobs", "yt", "metadata_change_log.json")


def job_channel(job: str) -> str:
    try:
        return json.load(open(os.path.join(job, "youtube.json"))).get("channel") or "world"
    except (OSError, ValueError):
        return "world"


def title_test_running(log_path: str, video_id: str) -> str:
    """The label of a title A/B test the change log records as started and not ended, or ""."""
    try:
        entries = json.load(open(log_path, encoding="utf-8")).get("entries") or []
    except (OSError, ValueError):
        return ""
    state = ""
    for entry in entries:
        label = str(entry.get("label") or "")
        if entry.get("video_id") != video_id or not re.search(r"title\b.*\btest", label, re.I):
            continue
        state = "" if re.search(r"\b(ended|stopped|concluded|finished|winner)\b", label, re.I) else label
    return state


def propose(live_description: str, facts: dict, people: bool = True, complete=None,
            refresh_people: bool = False) -> tuple[str, dict]:
    """The new description and its report. One People & Places call at most, only when needed."""
    parsed = dt.parse(live_description)
    lines = None
    spend: list[float] = []
    report_people = None
    if people and (refresh_people or not parsed["people"]):
        complete = complete or dt.anthropic_complete(spend)
        lines, report_people = dt.people_and_places(
            facts["transcript"], dt.cited_claims(facts["script"]), complete)
    elif not people:
        lines = []
    new, report = dt.rebuild(live_description, facts, lines)
    report["people_generated"] = report_people
    report["people_spend_usd"] = round(sum(spend), 6)
    return new, report


def render_preview(video_id: str, title: str, live: str, new: str, report: dict) -> str:
    diff = "\n".join(difflib.unified_diff(live.splitlines(), new.splitlines(), "live", "proposed",
                                          lineterm=""))
    people = report.get("people_generated") or {}
    lines = [
        f"VIDEO {video_id}  {title}",
        f"bytes {report['bytes']}/{dt.MAX_BYTES} (live {dt.utf8_len(live)}); "
        f"sources listed {report['sources_listed']}/{report['sources_used']}; "
        f"people & places lines {report['people_listed']}; "
        f"promise: {report['promise_kind'] or 'omitted'}; "
        f"model spend ${report.get('people_spend_usd', 0):.4f}",
    ]
    if report.get("recut"):
        lines.append("re-cut opening: its narration was never judged by the claim ledger, so the "
                     "promise line is withheld; its claims are counted as used")
    if report["sources_trimmed"]:
        lines.append("trimmed for length (least used): " + ", ".join(report["sources_trimmed"]))
    if report["live_sources_dropped"]:
        lines.append("live sources the film's claims do not use (dropped): "
                     + ", ".join(report["live_sources_dropped"]))
    for row in people.get("dropped") or []:
        lines.append(f"people & places line dropped by the fact check: {row['line']} -- "
                     + "; ".join(row["problems"]))
    for row in report.get("people_dropped") or []:
        lines.append(f"existing people & places line no longer passes: {row['line']} -- "
                     + "; ".join(row["problems"]))
    if people.get("omitted"):
        lines.append(f"people & places omitted: {people['omitted']}")
    if people.get("error"):
        lines.append(f"people & places call failed: {people['error']}")
    if report["removed"]:
        lines.append(f"removed: {len(report['removed'])} retired block(s)/line(s) "
                     "(IN THIS VIDEO, QUESTIONS ANSWERED, Tags:, old promise)")
    return ("\n".join(lines) + "\n\n===== PROPOSED DESCRIPTION =====\n" + new
            + "\n\n===== DIFF (live -> proposed) =====\n" + diff + "\n")


def update_request(video: dict, description: str) -> tuple[str, dict]:
    """(parts, body) for videos.update changing only the description."""
    snippet = video["snippet"]
    body_snippet = {key: value for key, value in snippet.items() if key not in READ_ONLY_SNIPPET}
    body_snippet["description"] = description
    body = {"id": video["id"], "snippet": body_snippet}
    parts = "snippet"
    localizations = dict(video.get("localizations") or {})
    default = snippet.get("defaultLanguage")
    if default and default in localizations:
        localizations[default] = {**localizations[default], "title": snippet["title"],
                                  "description": description}
        body["localizations"] = localizations
        parts = "snippet,localizations"
    return parts, body


def append_log(log_path: str, record: dict) -> None:
    try:
        data = json.load(open(log_path, encoding="utf-8"))
    except FileNotFoundError:
        data = {"entries": []}
    data.setdefault("entries", []).append(record)
    tmp = log_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, ensure_ascii=False)
    os.replace(tmp, log_path)


def apply(yt, video: dict, description: str, *, job: str, channel: str, log_path: str,
          report: dict) -> dict:
    """Send the update, read the video back, compare, and record it. Returns the log record."""
    video_id = video["id"]
    before = video["snippet"].get("description", "")
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    saved = os.path.join(os.path.dirname(log_path), "redescribe")
    os.makedirs(saved, exist_ok=True)
    before_file = os.path.join(saved, f"{video_id}_{stamp}_before.txt")
    after_file = os.path.join(saved, f"{video_id}_{stamp}_after.txt")
    with open(before_file, "w", encoding="utf-8") as handle:
        handle.write(before)
    with open(after_file, "w", encoding="utf-8") as handle:
        handle.write(description)
    parts, body = update_request(video, description)
    yt.videos().update(part=parts, body=body).execute()
    after = yt.videos().list(part="snippet,localizations", id=video_id).execute()["items"][0]
    changed = sorted(key for key in set(video["snippet"]) | set(after["snippet"])
                     if key not in READ_ONLY_SNIPPET and key != "description"
                     and video["snippet"].get(key) != after["snippet"].get(key))
    verified = after["snippet"].get("description", "") == description and not changed
    record = {
        "date": datetime.date.today().isoformat(),
        "label": "description re-laid in the film template (scripts/redescribe_video.py)",
        "video_id": video_id, "channel": channel, "job": job,
        "before_sha256": sha256(before), "after_sha256": sha256(description),
        "before_file": before_file, "after_file": after_file,
        "parts": parts, "verified": verified, "fields_changed_unexpectedly": changed,
        "preserved": [key for key in PRESERVED if key in video["snippet"]],
        "sources_listed": report.get("sources_listed"), "sources_used": report.get("sources_used"),
        "people_listed": report.get("people_listed"), "promise": report.get("promise_kind"),
        "people_spend_usd": report.get("people_spend_usd", 0),
    }
    append_log(log_path, record)
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("video_id")
    parser.add_argument("--job", required=True)
    parser.add_argument("--channel", choices=["world", "history"], default="")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the proposal (default)")
    mode.add_argument("--apply", action="store_true", help="update the live description")
    parser.add_argument("--out", default="", help="also write the preview to this file")
    parser.add_argument("--log", default="", help="metadata change log (default: the main "
                                                  "checkout's jobs/yt/metadata_change_log.json)")
    parser.add_argument("--cut", choices=["auto", "recut", "original"], default="auto",
                        help="which cut is live when the job has a re-cut opening (default: the "
                             "recut when explainer.recut.mp4 exists)")
    parser.add_argument("--no-people", action="store_true", help="no People & Places section")
    parser.add_argument("--refresh-people", action="store_true",
                        help="regenerate People & Places even when the live description has it")
    parser.add_argument("--during-title-test", action="store_true",
                        help="apply although the log records a title A/B test as running")
    args = parser.parse_args(argv)
    job = os.path.abspath(args.job)
    channel = args.channel or job_channel(job)
    log_path = os.path.abspath(args.log) if args.log else default_log_path()

    facts = dt.load_job(job, recut={"auto": None, "recut": True, "original": False}[args.cut])
    if not dt.cited_claims(facts["script"]):
        print(f"refused: {job} has no research artifacts the film's scenes cite "
              "(_state.json script with dossier claims); the sources cannot be rebuilt")
        return 2

    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    load_dotenv(os.path.join(main_checkout_root(), ".env"))
    import youtube_upload
    from googleapiclient.discovery import build
    yt = build("youtube", "v3", credentials=youtube_upload._creds(channel), cache_discovery=False)
    items = yt.videos().list(part="snippet,localizations", id=args.video_id).execute().get("items")
    if not items:
        print(f"refused: {args.video_id} not found on the {channel} channel")
        return 2
    video = items[0]
    live = video["snippet"].get("description", "")
    new, report = propose(live, facts, people=not args.no_people,
                          refresh_people=args.refresh_people)
    preview = render_preview(args.video_id, video["snippet"].get("title", ""), live, new, report)
    print(preview)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(preview)
    running = title_test_running(log_path, args.video_id)
    if running:
        print(f"note: the change log records a title test on this video: {running}")
    if not args.apply:
        print("dry run: nothing sent")
        return 0
    if report["over_limit"]:
        print(f"refused: {report['bytes']} bytes is over YouTube's {dt.MAX_BYTES}-byte limit")
        return 1
    if new == live:
        print("unchanged: the live description already matches the template")
        return 0
    if running and not args.during_title_test:
        print("refused: a title A/B test is recorded as running; pass --during-title-test to "
              "update the description anyway (the title is sent back unchanged)")
        return 1
    if not os.path.isdir(os.path.dirname(log_path)):
        print(f"refused: no change-log directory at {os.path.dirname(log_path)} (pass --log)")
        return 1
    record = apply(yt, video, new, job=job, channel=channel, log_path=log_path, report=report)
    print(f"applied: {args.video_id} description updated ({record['parts']}); verified "
          f"{record['verified']}; logged to {log_path}")
    return 0 if record["verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
