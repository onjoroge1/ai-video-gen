#!/usr/bin/env python3
"""Publish a rendered MP4 and its companion text files as one database release bundle."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--captions", required=True)
    parser.add_argument("--transcript")
    parser.add_argument("--format", default="quiz")
    parser.add_argument("--duration", type=float)
    parser.add_argument("--metadata-json", default="{}")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env", override=False)
    try:
        metadata = json.loads(args.metadata_json)
    except json.JSONDecodeError as exc:
        parser.error(f"invalid --metadata-json: {exc}")

    ok = db.publish_video_bundle(
        slug=args.slug,
        title=args.title,
        video_path=args.video,
        description_path=args.description,
        captions_path=args.captions,
        transcript_path=args.transcript,
        video_format=args.format,
        duration_sec=args.duration,
        metadata=metadata,
    )
    if not ok:
        print("Publication failed; no verified database record was returned.", file=sys.stderr)
        return 1

    manifest = db.published_video_manifest(args.slug)
    if not manifest:
        print("Publication could not be verified by read-back.", file=sys.stderr)
        return 1
    manifest["video_sha256"] = manifest["video_sha256"][:12] + "…"
    manifest["created_at"] = str(manifest["created_at"])
    manifest["updated_at"] = str(manifest["updated_at"])
    manifest["duration_sec"] = float(manifest["duration_sec"]) if manifest["duration_sec"] else None
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
