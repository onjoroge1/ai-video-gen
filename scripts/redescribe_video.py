#!/usr/bin/env python3
"""Re-lay a LIVE film's description in the film template, keeping the operator's own lines.

    python3 scripts/redescribe_video.py IN1DERNZ2zA --job jobs/history-aral-sea-v2 \\
        [--channel world|history] [--dry-run | --apply] [--out FILE] [--proposal FILE]
        [--cut recut|original] [--job-unbound REASON] [--log FILE] [--no-people]

Reads the live description (videos.list) and keeps everything outside the managed sections as
found: the summary paragraphs, chapters, Short links, the CTA, hashtags, the AI line and any
custom lines, in their order. Replaces only the managed sections (description_template): adds the
sourcing promise when the job's claim ledger earns it, rebuilds RESEARCH & SOURCES from the claims
the film's narration cites (the operator's existing source labels are reused as citations; sources
the film did not use are dropped and listed), adds PEOPLE & PLACES (one cheap model call, every
number, name and content word checked against the transcript and cited claims; an existing
section is re-checked instead), and removes IN THIS VIDEO, QUESTIONS ANSWERED and any Tags: line.

The video must be the job's film. Its id must be one the job's artifacts record (youtube.json, the
upload ledger's entry for the job's explainer*.mp4, teaser_package.json's film_video_id, or the
teaser/Short description's full-film link), and videos.list must place it on the channel's own
id; --job-unbound REASON overrides only the first. A job with a re-cut opening needs to know which
cut is live: the ledger's file says so, otherwise --cut recut|original is required.

--dry-run (the default) prints the proposed description, a diff against the live one and a
report, changes nothing on YouTube, and saves the proposal (the text, the SHA-256 of the live
description it was built from, and the report) to <job>/redescribe_proposal_<video_id>.json or
--proposal FILE. --out FILE writes the preview to a file too.

--apply publishes exactly that reviewed proposal and makes no model call: it refuses when there
is no proposal for this video and job, or when the live description changed since the dry run.
It updates ONLY snippet.description. videos.update replaces the whole snippet, so every other
writable snippet field (title, tags, categoryId, defaultLanguage, defaultAudioLanguage, and
anything else the API returned) is sent back exactly as read, and compared after the update. When
the video has a localization in its default language it mirrors the new text (a stale one kept an
old title after a retitle, 2026-10-11); other languages are re-synced by
`scripts/localize_video.py <id> --job <job> --if-changed`. Each apply appends a record with the
before/after SHA-256 to jobs/yt/metadata_change_log.json (the main checkout's when run from a
worktree; --log overrides) as soon as YouTube accepts the update, then completes it with the
read-back, and saves both texts in jobs/yt/redescribe/. A video with a title A/B test recorded in
that log as running is refused unless --during-title-test.
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


def _ledger_path(job: str) -> str:
    """jobs/yt/upload_ledger.json beside the job, else the main checkout's."""
    beside = os.path.join(os.path.dirname(os.path.abspath(job)), "yt", "upload_ledger.json")
    if os.path.isfile(beside):
        return beside
    return os.path.join(main_checkout_root(), "jobs", "yt", "upload_ledger.json")


_FULL_FILM_LINK = re.compile(r"full (?:film|story|video)\W*\s*https?://(?:youtu\.be/|(?:www\.)?"
                             r"youtube\.com/watch\?v=)([\w-]{11})", re.I)


def job_binding(job: str, ledger_path: str = "") -> dict[str, dict]:
    """{video_id: {"source": where the job records it, "cut": "original" | "recut" | ""}}.

    youtube.json is written by upload_job, which uploads explainer.mp4 (the original cut); the
    upload ledger names the exact file; teaser_package.json's film_video_id and the teaser/Short
    description's full-film link name the film but not its cut."""
    out: dict[str, dict] = {}

    def add(video_id, source, cut=""):
        if isinstance(video_id, str) and re.fullmatch(r"[\w-]{11}", video_id):
            out.setdefault(video_id, {"source": source, "cut": cut})

    try:
        add(json.load(open(os.path.join(job, "youtube.json"))).get("video_id"), "youtube.json",
            "original")
    except (OSError, ValueError, AttributeError):
        pass
    name = os.path.basename(os.path.abspath(job))
    try:
        uploads = json.load(open(ledger_path or _ledger_path(job))).get("uploads") or []
    except (OSError, ValueError, AttributeError):
        uploads = []
    for entry in uploads:
        if not isinstance(entry, dict):
            continue
        file = str(entry.get("file") or "")
        parts = file.replace("\\", "/").split("/")
        if len(parts) >= 2 and parts[-2] == name and re.fullmatch(r"explainer[\w.-]*\.mp4", parts[-1]):
            cut = {"explainer.mp4": "original", "explainer.recut.mp4": "recut"}.get(parts[-1], "")
            add(entry.get("video_id"), f"upload ledger ({file})", cut)
    try:
        add(json.load(open(os.path.join(job, "teaser_package.json"))).get("film_video_id"),
            "teaser_package.json film_video_id")
    except (OSError, ValueError, AttributeError):
        pass
    for file in ("teaser_description.txt", "short_description.txt"):
        try:
            text = open(os.path.join(job, file), encoding="utf-8").read()
        except OSError:
            continue
        for match in _FULL_FILM_LINK.finditer(text):
            add(match.group(1), f"{file} full-film link")
    return out


def resolve_cut(job: str, video_id: str, binding: dict, requested: str) -> tuple[bool, str]:
    """(recut?, why) for a job, or raises ValueError when a re-cut job's live cut is unknown.

    Never guessed: a job with a re-cut opening has two films, and each has its own narration."""
    if requested in ("recut", "original"):
        return requested == "recut", f"--cut {requested}"
    if not dt.has_recut(job):
        return False, "the job has no re-cut opening"
    cut = (binding.get(video_id) or {}).get("cut")
    if cut:
        return cut == "recut", f"{binding[video_id]['source']} records the {cut} cut"
    raise ValueError(f"{job} has a re-cut opening (explainer.recut.mp4) and nothing records which "
                     f"cut {video_id} is; pass --cut recut or --cut original")


def default_proposal_path(job: str, video_id: str) -> str:
    return os.path.join(job, f"redescribe_proposal_{video_id}.json")


def save_proposal(path: str, *, video_id: str, job: str, channel: str, cut: str, live: str,
                  proposed: str, report: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    data = {"video_id": video_id, "job": job, "channel": channel, "cut": cut,
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "live_sha256": sha256(live), "proposed_sha256": sha256(proposed),
            "proposed": proposed, "report": report}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, ensure_ascii=False)


def load_proposal(path: str, *, video_id: str, job: str, live: str, facts: dict) -> dict:
    """The reviewed proposal for --apply, or raises ValueError saying why it cannot be used.

    The text that goes live is the text the operator saw: no new model call, built from this
    exact live description, and its People & Places lines still pass the deterministic check."""
    try:
        data = json.load(open(path, encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"no reviewed proposal at {path}: run --dry-run first and review it")
    except ValueError as exc:
        raise ValueError(f"the proposal at {path} is not readable JSON ({exc})")
    if data.get("video_id") != video_id or os.path.abspath(data.get("job") or "") != job:
        raise ValueError(f"the proposal at {path} is for {data.get('video_id')} / {data.get('job')}, "
                         f"not {video_id} / {job}")
    proposed = data.get("proposed")
    if not isinstance(proposed, str) or sha256(proposed) != data.get("proposed_sha256"):
        raise ValueError(f"the proposal at {path} was altered after the dry run")
    if sha256(live) != data.get("live_sha256"):
        raise ValueError("the live description changed since the dry run; dry-run again and review")
    people = dt.parse(proposed)["people"]
    if people:
        _, failing = dt.recheck_people(people, facts["transcript"], dt.cited_claims(facts["script"]))
        if failing:
            raise ValueError("People & Places lines in the proposal no longer pass the fact check: "
                             + "; ".join(row["line"] for row in failing))
    return data


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
        lines.append("re-cut film: the new opening replaces the original scenes before the "
                     "splice; its narration was never judged by the claim ledger, so the promise "
                     "line is withheld; the opening's claims count as used, the cut scenes' do not")
    if report["sources_trimmed"]:
        lines.append("trimmed for length (least used): " + ", ".join(report["sources_trimmed"]))
    if report["live_sources_dropped"]:
        lines.append("live sources the film's claims do not use (dropped): "
                     + ", ".join(report["live_sources_dropped"]))
    for block in report.get("kept_custom_blocks") or []:
        lines.append("kept custom lines (not research URLs): " + block.replace("\n", " / "))
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


def log_readable(log_path: str) -> str:
    """"" when the change log can take a record (missing is fine), else why not."""
    try:
        data = json.load(open(log_path, encoding="utf-8"))
    except FileNotFoundError:
        return ""
    except (OSError, ValueError) as exc:
        return f"{type(exc).__name__}: {exc}"
    return "" if isinstance(data, dict) else "not a JSON object"


def _write_log(log_path: str, change) -> str:
    """Apply `change(entries)` to the log atomically; never raises. Returns where it went: the
    log, or a <log>.unlogged-<stamp>.json beside it when the log cannot be written, because by then
    the live description has already changed and the record must exist somewhere."""
    try:
        try:
            data = json.load(open(log_path, encoding="utf-8"))
        except FileNotFoundError:
            data = {"entries": []}
        change(data.setdefault("entries", []))
        tmp = log_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1, ensure_ascii=False)
        os.replace(tmp, log_path)
        return log_path
    except Exception as exc:  # noqa: BLE001 - see above
        entries: list = []
        change(entries)
        fallback = f"{log_path}.unlogged-{datetime.datetime.now().strftime('%Y%m%dT%H%M%S%f')}.json"
        try:
            with open(fallback, "w", encoding="utf-8") as handle:
                json.dump({"log_error": f"{type(exc).__name__}: {exc}", "entries": entries},
                          handle, indent=1, ensure_ascii=False)
        except OSError:
            print("UNLOGGED live change:", json.dumps(entries, ensure_ascii=False))
            return ""
        return fallback


def append_log(log_path: str, record: dict) -> str:
    return _write_log(log_path, lambda entries: entries.append(record))


def update_log_record(log_path: str, record: dict) -> str:
    """Replace the entry with the same record_id (appended at send time) by `record`."""
    def change(entries):
        for index, entry in enumerate(entries):
            if isinstance(entry, dict) and entry.get("record_id") == record["record_id"]:
                entries[index] = record
                return
        entries.append(record)
    return _write_log(log_path, change)


def apply(yt, video: dict, description: str, *, job: str, channel: str, log_path: str,
          report: dict, binding: str = "") -> dict:
    """Send the update, record it at once, read the video back, compare, and complete the record.

    The record is written as soon as YouTube accepts the update (status "sent"), so a failed
    read-back or log write cannot leave a live change unrecorded; a rerun would otherwise find
    the description already in the template and log nothing."""
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
    record = {
        "record_id": f"{video_id}-{stamp}",
        "date": datetime.date.today().isoformat(),
        "label": "description re-laid in the film template (scripts/redescribe_video.py)",
        "video_id": video_id, "channel": channel, "job": job, "job_binding": binding,
        "before_sha256": sha256(before), "after_sha256": sha256(description),
        "before_file": before_file, "after_file": after_file,
        "parts": parts, "status": "sent", "verified": None,
        "preserved": [key for key in PRESERVED if key in video["snippet"]],
        "sources_listed": report.get("sources_listed"), "sources_used": report.get("sources_used"),
        "people_listed": report.get("people_listed"), "promise": report.get("promise_kind"),
        "people_spend_usd": report.get("people_spend_usd", 0),
    }
    record["logged_to"] = append_log(log_path, record)
    try:
        after = yt.videos().list(part="snippet,localizations", id=video_id).execute()["items"][0]
        changed = sorted(key for key in set(video["snippet"]) | set(after["snippet"])
                         if key not in READ_ONLY_SNIPPET and key != "description"
                         and video["snippet"].get(key) != after["snippet"].get(key))
        verified = after["snippet"].get("description", "") == description and not changed
        record.update({"status": "verified" if verified else "read back with differences",
                       "verified": verified, "fields_changed_unexpectedly": changed})
    except Exception as exc:  # noqa: BLE001 - the update went through; say the check did not
        record.update({"status": "sent, read-back failed", "verified": False,
                       "read_back_error": f"{type(exc).__name__}: {str(exc)[:200]}"})
    record["logged_to"] = update_log_record(log_path, record)
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("video_id")
    parser.add_argument("--job", required=True)
    parser.add_argument("--channel", choices=["world", "history"], default="")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print and save the proposal (default)")
    mode.add_argument("--apply", action="store_true",
                      help="publish the proposal the dry run saved (no model call)")
    parser.add_argument("--out", default="", help="also write the preview to this file")
    parser.add_argument("--proposal", default="", help="the proposal file the dry run writes and "
                        "--apply reads (default: <job>/redescribe_proposal_<video_id>.json)")
    parser.add_argument("--log", default="", help="metadata change log (default: the main "
                                                  "checkout's jobs/yt/metadata_change_log.json)")
    parser.add_argument("--cut", choices=["auto", "recut", "original"], default="auto",
                        help="which cut the video is, for a job with a re-cut opening (auto: only "
                             "when the upload ledger records it; otherwise required)")
    parser.add_argument("--job-unbound", default="", metavar="REASON",
                        help="the job's artifacts do not record this video id; say why it is the "
                             "job's film anyway")
    parser.add_argument("--no-people", action="store_true", help="no People & Places section")
    parser.add_argument("--refresh-people", action="store_true",
                        help="regenerate People & Places even when the live description has it")
    parser.add_argument("--during-title-test", action="store_true",
                        help="apply although the log records a title A/B test as running")
    args = parser.parse_args(argv)
    job = os.path.abspath(args.job)
    channel = args.channel or job_channel(job)
    log_path = os.path.abspath(args.log) if args.log else default_log_path()
    proposal_path = os.path.abspath(args.proposal or default_proposal_path(job, args.video_id))

    # The video must be this job's film, checked before any model call or write.
    binding = job_binding(job)
    if args.video_id in binding:
        bound = binding[args.video_id]["source"]
    elif args.job_unbound.strip():
        bound = f"unbound, operator: {args.job_unbound.strip()}"
        print(f"note: {job} does not record {args.video_id} ({args.job_unbound.strip()})")
    else:
        recorded = ", ".join(f"{v} ({b['source']})" for v, b in binding.items()) or "none"
        print(f"refused: {args.video_id} is not the film of {job}; the job records: {recorded}. "
              "Pass --job-unbound REASON if it is.")
        return 2
    try:
        recut, cut_why = resolve_cut(job, args.video_id, binding, args.cut)
        facts = dt.load_job(job, recut=recut)
    except ValueError as exc:
        print(f"refused: {exc}")
        return 2
    cut = "recut" if recut else "original"
    if not dt.cited_claims(facts["script"]):
        print(f"refused: {job} has no research artifacts the film's scenes cite "
              "(_state.json script with dossier claims); the sources cannot be rebuilt")
        return 2

    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    load_dotenv(os.path.join(main_checkout_root(), ".env"))
    import youtube_upload
    from googleapiclient.discovery import build
    from youtube_channels import CHANNELS, check_bound
    yt = build("youtube", "v3", credentials=youtube_upload._creds(channel), cache_discovery=False)
    items = yt.videos().list(part="snippet,localizations", id=args.video_id).execute().get("items")
    if not items:
        print(f"refused: {args.video_id} not found")
        return 2
    video = items[0]
    owner = video["snippet"].get("channelId")
    if owner != CHANNELS[channel]["id"]:
        print(f"refused: {args.video_id} belongs to channel {owner}, not {CHANNELS[channel]['title']} "
              f"({CHANNELS[channel]['id']})")
        return 2
    live = video["snippet"].get("description", "")
    title = video["snippet"].get("title", "")
    if not args.apply:
        new, report = propose(live, facts, people=not args.no_people,
                              refresh_people=args.refresh_people)
        # The saved preview carries what the terminal shows: binding, cut, a running title test.
        notes = [f"job: {job}; binding: {bound}; cut: {cut} ({cut_why}); channel: {channel}"]
        running = title_test_running(log_path, args.video_id)
        if running:
            notes.append("note: the change log records a title test on this video (--apply "
                         f"refuses without --during-title-test): {running}")
        preview = "\n".join(notes) + "\n" + render_preview(args.video_id, title, live, new, report)
        print(preview)
        if args.out:
            os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(preview)
        save_proposal(proposal_path, video_id=args.video_id, job=job, channel=channel, cut=cut,
                      live=live, proposed=new, report=report)
        print(f"dry run: nothing sent; proposal saved to {proposal_path} (--apply publishes it)")
        return 0

    print(f"job binding: {bound}; cut: {cut} ({cut_why})")
    if args.no_people or args.refresh_people:
        print("note: --no-people/--refresh-people shape the dry run; --apply publishes its proposal")
    try:
        saved = load_proposal(proposal_path, video_id=args.video_id, job=job, live=live, facts=facts)
    except ValueError as exc:
        print(f"refused: {exc}")
        return 1
    new, report = saved["proposed"], saved.get("report") or {}
    print(render_preview(args.video_id, title, live, new, {**report, "people_generated": None}))
    if dt.utf8_len(new) > dt.MAX_BYTES:
        print(f"refused: {dt.utf8_len(new)} bytes is over YouTube's {dt.MAX_BYTES}-byte limit")
        return 1
    if new == live:
        print("unchanged: the live description already matches the proposal")
        return 0
    running = title_test_running(log_path, args.video_id)
    if running and not args.during_title_test:
        print(f"refused: a title A/B test is recorded as running ({running}); pass "
              "--during-title-test to update the description anyway (the title is sent back "
              "unchanged)")
        return 1
    if not os.path.isdir(os.path.dirname(log_path)):
        print(f"refused: no change-log directory at {os.path.dirname(log_path)} (pass --log)")
        return 1
    problem = log_readable(log_path)
    if problem:
        print(f"refused: the change log {log_path} cannot take a record ({problem}); fix it first")
        return 1
    mine = yt.channels().list(part="id,snippet", mine=True).execute().get("items") or []
    refusal = check_bound(channel, mine[0]["id"] if mine else "",
                          mine[0]["snippet"]["title"] if mine else "")
    if refusal:
        print(f"refused: {refusal}")
        return 1
    record = apply(yt, video, new, job=job, channel=channel, log_path=log_path, report=report,
                   binding=bound)
    print(f"applied: {args.video_id} description updated ({record['parts']}); {record['status']}; "
          f"logged to {record.get('logged_to') or 'NOWHERE (see above)'}")
    return 0 if record["verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
