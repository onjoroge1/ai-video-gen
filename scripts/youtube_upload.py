"""Upload one finished film (or short) to YouTube as a PRIVATE video, with its thumbnail.

Private on purpose: uploads from a Cloud project that has not passed YouTube's API compliance
audit are locked to private by YouTube anyway, and the operator makes each video public from
Studio after reviewing it. This script never changes an existing video.

    python3 scripts/youtube_upload.py --video jobs/wolves01/explainer.mp4 \\
        --title "..." --description-file jobs/wolves01/description.txt \\
        --thumbnail jobs/wolves01/thumbnail.jpg --tags "cane toads,invasive species" \\
        [--short] [--publish-at 2026-10-02T14:00:00Z] [--dry-run]

Prints the video id and Studio URL. --dry-run prints the request body and uploads nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATEGORY_EDUCATION = "27"


def _creds():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    from google.oauth2.credentials import Credentials
    missing = [k for k in ("YOUTUBE_OAUTH_CLIENT_ID", "YOUTUBE_OAUTH_CLIENT_SECRET",
                           "YOUTUBE_OAUTH_REFRESH_TOKEN") if not os.environ.get(k)]
    if missing:
        sys.exit(f"missing in .env: {', '.join(missing)}")
    return Credentials(
        None, refresh_token=os.environ["YOUTUBE_OAUTH_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_OAUTH_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_OAUTH_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/youtube.upload",
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
    body = {
        "snippet": {"title": title, "description": description[:5000], "tags": tags[:30],
                    "categoryId": CATEGORY_EDUCATION, "defaultLanguage": "en"},
        "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                   "license": "youtube", "embeddable": True},
    }
    if args.publish_at:
        body["status"]["publishAt"] = args.publish_at
    if args.dry_run:
        print(json.dumps(body, indent=1, ensure_ascii=False))
        print(f"video: {args.video} ({os.path.getsize(args.video) / 1e6:.1f} MB)"
              + (f"\nthumbnail: {args.thumbnail}" if args.thumbnail else ""))
        return 0

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    yt = build("youtube", "v3", credentials=_creds(), cache_discovery=False)
    # An upload lands on the channel the TOKEN is bound to (the one picked at Google's account
    # chooser), not on YOUTUBE_CHANNEL_ID. The first teaser upload (2026-09-30) landed on the
    # wrong channel this way. Refuse rather than misfile.
    mine = yt.channels().list(part="id,snippet", mine=True).execute().get("items") or []
    bound = mine[0]["id"] if mine else ""
    wanted = os.environ.get("YOUTUBE_CHANNEL_ID", "").strip()
    if wanted and bound != wanted:
        sys.exit(f"token is bound to channel {bound} ({mine[0]['snippet']['title']!r}) but "
                 f"YOUTUBE_CHANNEL_ID is {wanted}; re-run scripts/youtube_oauth_setup.py "
                 "--write and pick the right channel at Google's account chooser")
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
