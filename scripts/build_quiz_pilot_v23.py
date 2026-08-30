from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "static" / "quiz-pilot-v23"
WORK_DIR = Path(tempfile.mkdtemp(prefix="quiz_v23_build_"))
JOB_ID = "quiz-v23-three-animal-pacing-20260830"
BRANCH = os.environ.get("VERCEL_GIT_COMMIT_REF", "")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _require_provider_keys() -> None:
    missing = [
        name for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        raise RuntimeError(
            "Preview build is missing required quiz provider key(s): " + ", ".join(missing)
        )


def _configure_media_binaries() -> dict:
    # The quiz renderer imports its binary paths at module import time, so establish the
    # bundled ffmpeg and an ffprobe-compatible duration wrapper before importing it.
    import media_binaries

    ffmpeg = media_binaries.ffmpeg()
    os.environ["FFMPEG_BIN"] = ffmpeg
    ffprobe = media_binaries.resolve("ffprobe", use_cache=False)
    source = "system"
    if not ffprobe:
        wrapper = WORK_DIR / "ffprobe-duration"
        wrapper.write_text(
            f"#!{sys.executable}\n"
            "import sys\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            "import media_binaries\n"
            "print(media_binaries.probe_duration(sys.argv[-1]))\n",
            encoding="utf-8",
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        ffprobe = str(wrapper)
        source = "ffmpeg-duration-wrapper"
    os.environ["FFPROBE_BIN"] = ffprobe
    return {"ffmpeg": ffmpeg, "ffprobe": ffprobe, "ffprobe_source": source}


def _existing_record() -> dict | None:
    try:
        import db

        if db.db_enabled():
            record = db.finished_video_get(JOB_ID)
            if record and (record.get("video_url") or record.get("download_url")):
                return record
    except Exception as exc:
        print(f"[quiz-build-pilot] existing-record lookup skipped: {exc}", flush=True)
    return None


def main() -> None:
    if BRANCH and BRANCH != "fix/quiz-three-round-pacing":
        print(f"[quiz-build-pilot] skipped on branch {BRANCH!r}", flush=True)
        return

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    existing = _existing_record()
    if existing:
        summary = {
            "status": "already_persisted",
            "job_id": JOB_ID,
            "title": existing.get("title"),
            "video_url": existing.get("video_url"),
            "download_url": existing.get("download_url"),
            "metadata": existing.get("metadata") or {},
        }
        _write_json(STATIC_DIR / "summary.json", summary)
        print("QUIZ_PILOT_RECORD=" + json.dumps(summary, default=str), flush=True)
        return

    _require_provider_keys()
    media = _configure_media_binaries()

    # These are deliberately set again in-process so the test remains bounded even if the
    # project-level Preview configuration is looser than the pilot contract.
    os.environ["QUIZ_HABITAT"] = "1"
    os.environ["QUIZ_FAL_OPENER"] = "0"
    os.environ["REQUIRE_DURABLE_ARTIFACTS"] = "0"
    os.environ["DURABLE_EXECUTION"] = "0"
    os.environ["MAX_VIDEO_COST_USD"] = "2.00"

    import media_binaries
    import quiz_pipeline as qp

    result = qp.run_quiz_pipeline(
        category="wild animals",
        output_dir=str(WORK_DIR),
        n_items=3,
        voice="echo",
        operator_direction=(
            "Controlled retention test for the restored three-round flow. Preserve the current "
            "Luckiest Guy display typography, habitat clues, difficulty badges, Bolt reveal "
            "performances, and seamless loop. Use exactly three broadly recognizable wild "
            "animals ordered MEDIUM, HARD, EXPERT. Difficulty must come from genuine visual "
            "confusability and pose, never an obscure species. Make round one attainable but not "
            "instant, round two clearly harder, and round three the final boss. Keep each spoken "
            "prompt comfortably inside its 2.4-second search window."
        ),
        progress_cb=lambda message: print(f"[quiz-build-pilot] {message}", flush=True),
    )

    primary = Path(result["output_path"])
    if not primary.is_file() or primary.stat().st_size <= 0:
        raise RuntimeError(f"Quiz renderer returned a missing or empty video: {primary}")

    deployed_video = STATIC_DIR / "three-animal-pacing-pilot.mp4"
    shutil.copy2(primary, deployed_video)
    probe = media_binaries.probe_media(str(deployed_video))
    items = list((result.get("script") or {}).get("items") or [])
    summary = {
        "status": "rendered",
        "job_id": JOB_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "branch": BRANCH,
        "commit_sha": os.environ.get("VERCEL_GIT_COMMIT_SHA", ""),
        "title": result.get("title"),
        "duration_sec": result.get("duration_sec") or probe.get("duration"),
        "actual_cost_usd": result.get("actual_cost"),
        "scene_count": result.get("scene_count"),
        "item_count": len(items),
        "items": [
            {
                "answer": item.get("answer"),
                "difficulty": item.get("difficulty"),
                "reaction": item.get("reaction"),
            }
            for item in items
        ],
        "primary_variant": result.get("primary_variant"),
        "probe": probe,
        "media": media,
        "retained_features": {
            "display_font": "LuckiestGuy-Regular.ttf",
            "difficulty_order": ["medium", "hard", "expert"],
            "viewer_labels": ["WARM-UP", "NO HINTS", "FINAL BOSS"],
            "habitat_mode": True,
            "bolt_reveal_performance": True,
            "seamless_loop": True,
            "search_window_sec": 2.4,
        },
        "static_video_path": "/quiz-pilot-v23/three-animal-pacing-pilot.mp4",
        "blob": None,
    }

    # Prefer durable Blob/Postgres persistence. The deployed static copy remains a fallback if
    # build-time OIDC is unavailable; upload failure never hides a successful render.
    try:
        import artifact_store

        extras = {}
        for key, kind in (
            ("srt_path", "captions"),
            ("description_path", "description"),
            ("thumbnail_path", "thumbnail"),
            ("generation_manifest_path", "generation_manifest"),
        ):
            path = result.get(key)
            if path and Path(path).is_file():
                extras[kind] = str(path)
        record = artifact_store.persist_finished(
            JOB_ID,
            str(deployed_video),
            {
                "title": result.get("title") or "Three-Animal Quiz V2.3 Pilot",
                "format": "quiz_short",
                "template": "rapid_reveal_v2_3",
                "status": "test_render",
                "duration_sec": summary["duration_sec"],
                "actual_cost_usd": summary["actual_cost_usd"],
                "item_count": summary["item_count"],
                "items": summary["items"],
                "source_commit": summary["commit_sha"],
                "retained_features": summary["retained_features"],
            },
            extras=extras,
        )
        if record:
            summary["blob"] = {
                "video_url": record.get("video_url"),
                "download_url": record.get("download_url"),
                "size_bytes": record.get("size_bytes"),
            }
    except Exception as exc:
        summary["blob_error"] = str(exc)
        print(f"[quiz-build-pilot] durable upload skipped: {exc}", flush=True)

    _write_json(STATIC_DIR / "summary.json", summary)
    _write_json(STATIC_DIR / "script.json", result.get("script") or {})
    print("QUIZ_PILOT_SUMMARY=" + json.dumps(summary, default=str), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("QUIZ_PILOT_BUILD_FAILED", flush=True)
        traceback.print_exc()
        raise
