"""One-time YouTube OAuth setup for READ-ONLY channel analytics.

Run this yourself; it opens your browser for Google's consent screen and must be approved by
the account that owns the channel. It never uploads, edits or publishes anything: the scopes
requested are youtube.readonly and yt-analytics.readonly only.

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

Then:
    YOUTUBE_OAUTH_CLIENT_ID=... YOUTUBE_OAUTH_CLIENT_SECRET=... \\
        python3 scripts/youtube_oauth_setup.py

It prints the four lines to paste into .env. Nothing is written anywhere by this script.
"""
from __future__ import annotations

import os
import sys

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def main() -> int:
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
    # access_type=offline + prompt=consent is what makes Google return a refresh token.
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
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
    print("\nAdd these four lines to .env (keep them out of git):\n")
    print(f"YOUTUBE_OAUTH_CLIENT_ID={client_id}")
    print(f"YOUTUBE_OAUTH_CLIENT_SECRET={client_secret}")
    print(f"YOUTUBE_OAUTH_REFRESH_TOKEN={creds.refresh_token}")
    print(f"YOUTUBE_CHANNEL_ID={channel['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
