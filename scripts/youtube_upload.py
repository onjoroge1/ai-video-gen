"""Upload one finished film (or short) to YouTube as a PRIVATE video, with its thumbnail.

Private on purpose: uploads from a Cloud project that has not passed YouTube's API compliance
audit are locked to private by YouTube anyway, and the operator makes each video public from
Studio after reviewing it. This script never changes an existing video.

    python3 scripts/youtube_upload.py --video jobs/wolves01/explainer.mp4 \\
        --title "..." --description-file jobs/wolves01/description.txt \\
        --thumbnail jobs/wolves01/thumbnail.jpg --tags "cane toads,invasive species" \\
        [--short] [--publish-at 2026-10-02T14:00:00Z] [--dry-run]

Prints the video id and Studio URL. --dry-run prints the request body and uploads nothing.

Refuses a duplicate (2026-10-14): a file already uploaded (by sha256, from the local ledger
jobs/yt/upload_ledger.json) or a title already on the channel in any privacy state (hashtags
ignored; a film and its #Shorts teaser are different kinds). The World channel had 27 uploads
in 12 days -- review builds, and one cane toad Short uploaded seven times -- while its reach
collapsed. A deliberate repeat (a hook test) passes with --allow-duplicate "reason", which the
ledger records.

Every upload declares altered or synthetic content (status.containsSyntheticMedia, 2026-10-14):
the films' pictures and narration are generated, and YouTube asks for the label on realistic
generated media. The description's own AI line was the only disclosure before.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATEGORY_EDUCATION = "27"
LEDGER = os.path.join(ROOT, "jobs", "yt", "upload_ledger.json")


def title_key(title: str) -> tuple[str, bool]:
    """(the title without hashtags or punctuation, is it a Short)."""
    short = "#shorts" in (title or "").lower()
    words = re.findall(r"[a-z0-9]+", re.sub(r"#\w+", " ", (title or "").lower()))
    return " ".join(words), short


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_ledger(path: str = LEDGER) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle).get("uploads") or []
    except (OSError, ValueError):
        return []


def duplicate_reasons(sha: str, title: str, channel_id: str, ledger: list[dict],
                      existing: list[dict]) -> list[str]:
    """Why this upload would duplicate one already made; [] when it would not.

    `existing` holds the channel's uploads as {"id", "title", "privacy"}; `ledger` the local
    record of earlier uploads with their file hashes."""
    reasons = []
    for entry in ledger:
        if entry.get("sha256") == sha and entry.get("channel_id") in (None, channel_id):
            reasons.append(f"this file was already uploaded as {entry.get('video_id')} "
                           f"({entry.get('uploaded_at', '?')[:10]}, \"{entry.get('title', '')}\")")
    key = title_key(title)
    for video in existing:
        if key[0] and title_key(video.get("title", "")) == key:
            reasons.append(f"the channel already has {video.get('id')} ({video.get('privacy', '?')}) "
                           f"titled \"{video.get('title', '')}\"")
    return reasons


def channel_uploads(yt, channel_id: str) -> list[dict]:
    """Every upload on the channel, any privacy (the owner's token sees private ones)."""
    playlist = yt.channels().list(part="contentDetails", id=channel_id).execute()["items"][0][
        "contentDetails"]["relatedPlaylists"]["uploads"]
    out, token = [], None
    while True:
        page = yt.playlistItems().list(part="snippet,status", playlistId=playlist, maxResults=50,
                                       pageToken=token).execute()
        out += [{"id": item["snippet"]["resourceId"]["videoId"], "title": item["snippet"]["title"],
                 "privacy": (item.get("status") or {}).get("privacyStatus", "?")}
                for item in page.get("items") or []]
        token = page.get("nextPageToken")
        if not token:
            return out


def request_body(title: str, description: str, tags: list[str], publish_at: str = "") -> dict:
    """The videos.insert body: private, Education, and declared as synthetic media."""
    body = {
        "snippet": {"title": title, "description": description[:5000], "tags": tags[:30],
                    "categoryId": CATEGORY_EDUCATION, "defaultLanguage": "en"},
        "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                   "license": "youtube", "embeddable": True, "containsSyntheticMedia": True},
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at
    return body


def record_upload(entry: dict, path: str = LEDGER) -> None:
    data = {"uploads": load_ledger(path)}
    data["uploads"].append(entry)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, ensure_ascii=False)


def _creds(channel: str = "world"):
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    from google.oauth2.credentials import Credentials
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from youtube_channels import CHANNELS
    token_env = CHANNELS[channel]["token_env"]
    missing = [k for k in ("YOUTUBE_OAUTH_CLIENT_ID", "YOUTUBE_OAUTH_CLIENT_SECRET",
                           token_env) if not os.environ.get(k)]
    if missing:
        sys.exit(f"missing in .env: {', '.join(missing)}")
    return Credentials(
        None, refresh_token=os.environ[token_env],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_OAUTH_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_OAUTH_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube.force-ssl",
                "https://www.googleapis.com/auth/youtube.readonly"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--description", default="")
    ap.add_argument("--description-file", default="")
    ap.add_argument("--thumbnail", default="")
    ap.add_argument("--tags", default="", help="comma-separated")
    ap.add_argument("--short", action="store_true", help="append #Shorts to the title")
    ap.add_argument("--publish-at", default="", help="RFC3339 UTC; sets privacy private + schedule")
    ap.add_argument("--channel", default="world", choices=["world", "history"],
                    help="which channel's token to use; the bound channel must match")
    ap.add_argument("--allow-duplicate", default="", metavar="REASON",
                    help="upload even if this file or title is already on the channel; the reason "
                         "is recorded in jobs/yt/upload_ledger.json (e.g. a deliberate hook test)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.video):
        sys.exit(f"no such video: {args.video}")
    description = args.description
    if args.description_file:
        with open(args.description_file, encoding="utf-8") as handle:
            description = handle.read()
    title = args.title.strip()
    if args.short and "#shorts" not in title.lower():
        title = f"{title} #Shorts"
    if len(title) > 100:
        sys.exit(f"title is {len(title)} chars; YouTube allows 100")
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    if not tags:
        # The description's own "Tags:" line is the pipeline's tag architecture; without --tags
        # the upload used to go out with none.
        for line in description.splitlines():
            if line.strip().lower().startswith("tags:"):
                tags = [t.strip() for t in line.split(":", 1)[1].split(",") if t.strip()]
                break
    # YouTube rejects the whole upload ("invalidTags") for one tag over 30 characters or one
    # holding < > or quotes; the description's Tags line is written for readers, not the API.
    # Measured on the cane toad re-cut (2026-10-02): five of its 17 tags were 34-44 characters.
    cleaned: list[str] = []
    total = 0
    for tag in tags:
        tag = tag.replace("<", "").replace(">", "").replace('"', "").strip()
        if not tag or len(tag) > 30 or tag.lower() in {t.lower() for t in cleaned}:
            continue
        if total + len(tag) + 2 > 480:
            break
        cleaned.append(tag)
        total += len(tag) + 2
    tags = cleaned
    body = request_body(title, description, tags, args.publish_at)
    sha = file_sha256(args.video)
    if args.dry_run:
        for reason in duplicate_reasons(sha, title, "", load_ledger(), []):
            print(f"DUPLICATE (ledger): {reason}")
        print(json.dumps(body, indent=1, ensure_ascii=False))
        print(f"video: {args.video} ({os.path.getsize(args.video) / 1e6:.1f} MB)"
              + (f"\nthumbnail: {args.thumbnail}" if args.thumbnail else ""))
        return 0

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    yt = build("youtube", "v3", credentials=_creds(args.channel), cache_discovery=False)
    # An upload lands on the channel the TOKEN is bound to (the one picked at Google's account
    # chooser), not on YOUTUBE_CHANNEL_ID. The first teaser upload (2026-09-30) landed on the
    # wrong channel this way. Refuse rather than misfile.
    mine = yt.channels().list(part="id,snippet", mine=True).execute().get("items") or []
    bound = mine[0]["id"] if mine else ""
    from youtube_channels import check_bound
    refusal = check_bound(args.channel, bound, mine[0]["snippet"]["title"] if mine else "")
    if refusal:
        sys.exit(refusal)
    reasons = duplicate_reasons(sha, title, bound, load_ledger(), channel_uploads(yt, bound))
    if reasons and not args.allow_duplicate.strip():
        sys.exit("refused, duplicate upload:\n  " + "\n  ".join(reasons)
                 + "\nReview builds stay local; a deliberate repeat needs --allow-duplicate \"reason\".")
    media = MediaFileUpload(args.video, mimetype="video/mp4", chunksize=8 * 1024 * 1024,
                            resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  upload {int(status.progress() * 100)}%")
    video_id = response["id"]
    print(f"uploaded (private): https://studio.youtube.com/video/{video_id}/edit")
    record_upload({"video_id": video_id, "title": title, "channel": args.channel, "channel_id": bound,
                   "sha256": sha, "file": os.path.relpath(os.path.abspath(args.video), ROOT),
                   "uploaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                   **({"allowed_duplicate": args.allow_duplicate.strip(), "duplicates": reasons}
                      if reasons else {})})
    if args.thumbnail:
        try:
            yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(
                args.thumbnail, mimetype="image/jpeg")).execute()
            print("thumbnail set")
        except Exception as exc:  # custom thumbnails need a phone-verified channel
            print(f"thumbnail NOT set ({type(exc).__name__}: {str(exc)[:160]}); "
                  "set it in Studio")
    print(json.dumps({"video_id": video_id, "title": title,
                      "watch": f"https://youtu.be/{video_id}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
