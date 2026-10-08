#!/usr/bin/env python3
"""Can a paid run start, and can its film be uploaded? Checked before anything is spent.

    python3 scripts/preflight.py [--need-upload] [--min-free-gb 3]

Checks, in order: the code carries the fixes a routine run relies on; Anthropic accepts a
request (a one-token call, refused unbilled when credit is out); OpenAI accepts a request (free
models.list); free disk; and, with --need-upload, that the YouTube token refreshes and is bound
to the World channel. Prints one line per check and exits 1 if any fails. Spends at most one
Anthropic token.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORLD = "UCnDdL_at-7BV9kBQnJ3GMtA"
# The Sonnet image checker and spend ledger; a routine must not run on code without them.
REQUIRED_COMMIT = "f5fe538"


def check_code() -> tuple[bool, str]:
    result = subprocess.run(["git", "-C", ROOT, "merge-base", "--is-ancestor", REQUIRED_COMMIT, "HEAD"],
                            capture_output=True, text=True)
    branch = subprocess.run(["git", "-C", ROOT, "branch", "--show-current"],
                            capture_output=True, text=True).stdout.strip()
    return result.returncode == 0, f"code on {branch or 'detached'} {'includes' if result.returncode == 0 else 'LACKS'} {REQUIRED_COMMIT}"


def check_anthropic() -> tuple[bool, str]:
    try:
        import anthropic
        reply = anthropic.Anthropic().messages.create(
            model="claude-haiku-5-5", max_tokens=1, messages=[{"role": "user", "content": "ok"}])
        return True, f"anthropic OK ({reply.usage.input_tokens} tokens)"
    except Exception as exc:  # noqa: BLE001
        return False, f"anthropic FAILED: {type(exc).__name__}: {str(exc)[:160]}"


def check_openai() -> tuple[bool, str]:
    try:
        import openai
        count = len(openai.OpenAI().models.list().data)
        return True, f"openai OK ({count} models listed)"
    except Exception as exc:  # noqa: BLE001
        return False, f"openai FAILED: {type(exc).__name__}: {str(exc)[:160]}"


def check_disk(min_free_gb: float) -> tuple[bool, str]:
    free = shutil.disk_usage(ROOT).free / 1e9
    return free >= min_free_gb, f"disk {free:.1f} GB free (need {min_free_gb:.0f})"


def check_youtube() -> tuple[bool, str]:
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import youtube_upload
        from googleapiclient.discovery import build
        yt = build("youtube", "v3", credentials=youtube_upload._creds(), cache_discovery=False)
        mine = yt.channels().list(part="id,snippet", mine=True).execute().get("items") or []
        bound = mine[0]["id"] if mine else ""
        title = mine[0]["snippet"]["title"] if mine else ""
        ok = bound == WORLD
        return ok, (f"youtube token bound to {title!r}" + ("" if ok else
                    f" ({bound}), not Bolt explains the world ({WORLD}); re-run "
                    "scripts/youtube_oauth_setup.py --write --no-browser in ONE browser window and "
                    "pick the brand channel on the second screen"))
    except SystemExit as exc:
        return False, f"youtube FAILED: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"youtube FAILED: {type(exc).__name__}: {str(exc)[:160]}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--need-upload", action="store_true")
    parser.add_argument("--min-free-gb", type=float, default=3.0)
    args = parser.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"), override=True)
    checks = [check_code(), check_anthropic(), check_openai(), check_disk(args.min_free_gb)]
    if args.need_upload:
        checks.append(check_youtube())
    for ok, line in checks:
        print(("PASS " if ok else "FAIL ") + line)
    return 0 if all(ok for ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
