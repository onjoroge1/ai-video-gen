"""The channels the pipeline may upload to, and the one it must never touch.

An upload lands on whichever channel the refresh TOKEN is bound to (the row picked on Google's
"Choose your account or a brand account" page), so each channel has its own token slot in .env
and every upload checks the bound channel against this table before sending a byte.
"""
from __future__ import annotations

CHANNELS = {
    "world": {"id": "UCnDdL_at-7BV9kBQnJ3GMtA", "title": "Bolt explains the world",
              "token_env": "YOUTUBE_OAUTH_REFRESH_TOKEN"},
    # Renamed from Bolt Explains Cancer on 2026-10-10 (2 videos, 18 views, no audience to lose).
    "history": {"id": "UCUXQrPJppPI97unCQsr9wRA", "title": "Bolt Explains History",
                "token_env": "YOUTUBE_OAUTH_REFRESH_TOKEN_HISTORY"},
}

# The operator's personal channel, and the one the base Google account binds to by default:
# the first teaser upload (2026-09-30) landed here by accident. Pipeline films never go here.
BLOCKED = {"UClUGfSF39lhWu2M7eDvxObg": "Bolt Explains Politics (personal)"}


def check_bound(channel: str, bound_id: str, bound_title: str = "") -> str | None:
    """None when a token bound to `bound_id` may upload for `channel`, else the reason it may not."""
    if bound_id in BLOCKED:
        return (f"token is bound to {BLOCKED[bound_id]} ({bound_id}), the operator's personal channel; "
                "pipeline uploads never go there")
    want = CHANNELS[channel]
    if bound_id != want["id"]:
        return (f"token is bound to {bound_title!r} ({bound_id}), not {want['title']} ({want['id']}); "
                f"re-run scripts/youtube_oauth_setup.py --channel {channel} --write --no-browser in ONE "
                "browser window and pick that channel on the brand-account screen")
    return None
