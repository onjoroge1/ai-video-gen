"""One-time YouTube OAuth setup for READ-ONLY channel analytics.

Run this yourself; it opens your browser for Google's consent screen and must be approved by
the account that owns the channel. The scopes requested are
youtube.readonly, yt-analytics.readonly and youtube.upload (private uploads via
scripts/youtube_upload.py; it cannot edit or delete existing videos).

Before running, in Google Cloud Console (https://console.cloud.google.com):
  1. APIs & Services -> Library: enable "YouTube Data API v3" and "YouTube Analytics API".
  2. APIs & Services -> OAuth consent screen: External, add your own Google account as a
     test user (the app can stay in Testing; refresh tokens for test users do not expire as
     long as the app stays in Testing with fewer than 100 users -- but note Google expires
     test-user refresh tokens after 7 days ONLY when the consent screen is in Testing AND
     the app is marked as unverified for sensitive scopes; publishing the consent screen to
     "In production" avoids that; readonly YouTube scopes are not "restricted", so no
     verification review is needed).
  3. APIs & Services -> Credentials -> Create credentials -> OAuth client ID -> type
     "Desktop app". Copy the Client ID and Client secret.

Then, with the two values in .env (the script loads .env itself; do not `source` it, the
file holds unquoted URLs that the shell cannot parse):
    python3 scripts/youtube_oauth_setup.py

It prints the four lines to paste into .env. With --write it also appends the refresh token
and channel id to .env itself (replacing any earlier YOUTUBE_OAUTH_REFRESH_TOKEN /
YOUTUBE_CHANNEL_ID lines), so the token never has to be copied by hand.

If the Google account owns several YouTube channels (brand accounts), the consent page shows
a chooser; the token is bound to the channel picked there, and the script prints which one.
"""
from __future__ import annotations

import os
import sys

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    # Upload only; no edit/delete of existing videos. Until the Cloud project passes YouTube's
    # API compliance audit, every API upload is locked to private, which is the intended
    # workflow here: the operator reviews in Studio and makes it public by hand.
    "https://www.googleapis.com/auth/youtube.upload",
]


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    client_id = os.environ.get("YOUTUBE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YOUTUBE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print("Set YOUTUBE_OAUTH_CLIENT_ID and YOUTUBE_OAUTH_CLIENT_SECRET first "
              "(Google Cloud Console -> Credentials -> OAuth client ID, type Desktop app).")
        return 2
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    flow = InstalledAppFlow.from_client_config(
        {"installed": {
            "client_id": client_id, "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }},
        scopes=SCOPES,
    )
    # access_type=offline + prompt=consent is what makes Google return a refresh token, and it
    # is the prompt under which Google shows "Choose your account or a brand account" (worked
    # 2026-10-01). Do NOT add select_account: on 2026-10-08 it showed only the Google-account
    # chooser and every run bound to the base account's channel.
    # --no-browser: print the URL only. When the flow is driven from another browser window,
    # the auto-opened tab is a second copy of the same consent; whichever finishes first wins
    # the one-time code and the other lands on an error page. Measured 2026-10-01: the brand
    # channel was picked in one window while the auto-opened one completed as the base account.
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent",
                                  open_browser="--no-browser" not in sys.argv)
    if not creds.refresh_token:
        print("Google returned no refresh token. Revoke the app at "
              "https://myaccount.google.com/permissions and run this again.")
        return 1
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    mine = youtube.channels().list(part="id,snippet,statistics", mine=True).execute()
    items = mine.get("items") or []
    if not items:
        print("The signed-in account owns no channel; sign in with the channel's account.")
        return 1
    channel = items[0]
    print("\nChannel:", channel["snippet"]["title"],
          "| subscribers:", channel["statistics"].get("subscriberCount"),
          "| videos:", channel["statistics"].get("videoCount"))
    print("Channel id:", channel["id"])
    # The secret and the refresh token are printed only when they are NOT being written to .env:
    # on screen they end up in terminal scrollback, screenshots and session transcripts.
    if "--write" not in sys.argv:
        print("\nAdd these four lines to .env (keep them out of git):\n")
        print(f"YOUTUBE_OAUTH_CLIENT_ID={client_id}")
        print(f"YOUTUBE_OAUTH_CLIENT_SECRET={client_secret}")
        print(f"YOUTUBE_OAUTH_REFRESH_TOKEN={creds.refresh_token}")
        print(f"YOUTUBE_CHANNEL_ID={channel['id']}")
    if "--write" in sys.argv:
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        try:
            with open(env_path, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except FileNotFoundError:
            lines = []
        # The refresh token is replaced; the channel id is written only if .env has none, so a
        # consent that lands on the wrong channel (it binds to whatever was picked at Google's
        # chooser) does not also silently repoint the analytics report at that channel.
        keep = [line for line in lines if not line.startswith("YOUTUBE_OAUTH_REFRESH_TOKEN=")]
        keep.append(f"YOUTUBE_OAUTH_REFRESH_TOKEN={creds.refresh_token}")
        if not any(line.startswith("YOUTUBE_CHANNEL_ID=") for line in keep):
            keep.append(f"YOUTUBE_CHANNEL_ID={channel['id']}")
        wanted = os.environ.get("YOUTUBE_CHANNEL_ID", "").strip()
        if wanted and wanted != channel["id"]:
            print(f"\nWARNING: this token is bound to {channel['snippet']['title']!r} "
                  f"({channel['id']}), not the channel in .env ({wanted}). Uploads would land "
                  "on the wrong channel. Run again and pick the other channel on Google's "
                  "'Choose an account' page (brand channels are listed under the account).")
        with open(env_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(keep) + "\n")
        print(f"\nWrote the refresh token and channel id to {env_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
