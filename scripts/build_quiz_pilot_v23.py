from __future__ import annotations

import copy
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
# Running a file from scripts/ puts that directory first on sys.path. Pin the repository root
# ahead of site-packages so an unrelated PyPI module named quiz_pipeline cannot shadow ours.
sys.path.insert(0, str(ROOT))
STATIC_DIR = ROOT / "static" / "quiz-pilot-v23"
WORK_DIR = Path(tempfile.mkdtemp(prefix="quiz_v23_build_"))
JOB_ID = "quiz-v23-three-animal-pacing-20260830"
BRANCH = os.environ.get("VERCEL_GIT_COMMIT_REF", "")

_SHARED_HABITAT = (
    "a broad grassy woodland edge at dawn, pale mist between scattered oak trees, "
    "soft golden light across the middle distance, low shrubs framing an open clearing"
)
_FIXED_QUIZ = {
    "title": "Can You Name All 3 From the Shadow?",
    "category": "wild animals",
    "hook": "Guess all three shadows",
    "outro": "",
    "items": [
        {
            "subject": "red fox",
            "difficulty": "medium",
            "clue_visual": (
                "a clean bold black silhouette of a red fox standing side-on, bushy tail held "
                "low, ears upright, all four legs clearly separated"
            ),
            "reveal_visual": (
                "a realistic friendly red fox in the identical side-on pose and scale, bushy "
                "tail held low, ears upright"
            ),
            "habitat": _SHARED_HABITAT,
            "confusables": ["coyote", "golden jackal", "small wild dog"],
            "pose": "standing side-on in the middle distance with its tail held low",
            "answer": "RED FOX",
            "reaction": "Nice start!",
            "fact": "Red foxes can hear small animals moving underground.",
            "color": "gold",
        },
        {
            "subject": "tapir",
            "difficulty": "hard",
            "clue_visual": (
                "a clean bold black silhouette of a tapir angled three-quarters away, head "
                "lowered, short flexible snout partly hidden by the angle, whole body visible"
            ),
            "reveal_visual": (
                "a realistic friendly tapir in the identical three-quarters-away pose and "
                "scale, head lowered, whole body visible"
            ),
            "habitat": (
                "a humid rainforest clearing after rain, giant glossy leaves in the foreground, "
                "mossy trunks and soft green light, an open muddy path through the middle distance"
            ),
            "confusables": ["wild boar", "giant anteater", "capybara", "peccary"],
            "pose": "walking three-quarters away with its head lowered beside the muddy path",
            "answer": "TAPIR",
            "reaction": "Tricky one!",
            "fact": "Young tapirs are born with pale spots and stripes.",
            "color": "teal",
        },
        {
            "subject": "coyote",
            "difficulty": "expert",
            "clue_visual": (
                "a clean bold black silhouette of a coyote angled toward the camera, head "
                "lowered and turned slightly, body foreshortened, tail down, whole animal visible"
            ),
            "reveal_visual": (
                "a realistic friendly coyote in the identical angled pose and scale, head "
                "lowered and turned slightly, tail down"
            ),
            "habitat": _SHARED_HABITAT,
            "confusables": ["gray wolf", "German shepherd", "golden jackal", "red fox"],
            "pose": (
                "walking toward the camera at a slight angle with its head lowered and tail down"
            ),
            "answer": "COYOTE",
            "reaction": "Final boss!",
            "fact": "Coyotes communicate with yips, howls, and barks.",
            "color": "coral",
        },
    ],
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _require_provider_keys() -> None:
    # The pilot deliberately bypasses the unavailable Anthropic script/QA calls and uses a fixed,
    # reviewed quiz contract. OpenAI still generates the real visual and narration assets.
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise RuntimeError("Preview build is missing OPENAI_API_KEY")


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


def _install_fixed_quiz_contract() -> None:
    """Replace only the unavailable Anthropic authoring/QA calls for this one build pilot.

    The production image generation, TTS, timing, overlays, typography, habitat compositor,
    Bolt reveal performance, variants, audio mix, captions, loop, and final encode stay unchanged.
    """
    import numpy as np
    from PIL import Image
    import _quiz_pipeline_legacy as legacy

    def fixed_generate(category, n_items=3, cost_sink=None, operator_direction=""):
        quiz = copy.deepcopy(_FIXED_QUIZ)
        quiz["items"] = quiz["items"][:n_items]
        print("[quiz-build-pilot] using fixed reviewed script; Anthropic authoring bypassed", flush=True)
        return quiz

    def fixed_factcheck(quiz, cost_sink=None):
        return quiz, []

    def local_readability_grade(first_crop, full_clue, reveal, answer, difficulty, cost_sink=None):
        # This is deliberately a local readability measurement, not a claim of semantic visual QA.
        # It keeps the existing occupancy/contrast shipping gate meaningful while Anthropic is capped.
        im = Image.open(full_clue).convert("RGB")
        arr = np.asarray(im, dtype=np.float32)
        lum = arr[..., 0] * 0.299 + arr[..., 1] * 0.587 + arr[..., 2] * 0.114
        dark_cut = min(72.0, float(np.percentile(lum, 18)))
        mask = lum <= dark_cut
        min_pixels = max(8, int(im.height * 0.012))
        cols = np.where(mask.sum(axis=0) >= min_pixels)[0]
        width_pct = (100.0 * (int(cols[-1]) - int(cols[0]) + 1) / im.width) if len(cols) else 0.0
        dark_level = float(np.percentile(lum, 12))
        background_level = float(np.percentile(lum, 62))
        contrast = max(0.0, min(100.0, (background_level - dark_level) / 255.0 * 150.0))
        return {
            "qa_mode": "local_readability_only",
            "qa_unavailable_reason": "Anthropic API usage limit until 2026-09-01T00:00:00Z",
            "first_crop_confidence": None,
            "first_guess": "",
            "full_clue_fair": None,
            "reveal_matches_answer": None,
            "anatomy_ok": None,
            "pose_continuity": None,
            "subject_width_pct": round(width_pct, 2),
            "clue_contrast_score": round(contrast, 2),
            "biggest_fix": "semantic QA deferred; inspect the rendered pilot editorially",
        }

    def fixed_description(category, title, items, hook, out_dir, cost_sink=None):
        path = Path(out_dir) / "youtube_description.txt"
        answers = ", ".join(str(item.get("answer") or "").title() for item in items)
        path.write_text(
            f"Three wild animals are hiding in their real habitats. The rounds climb from "
            f"warm-up to hard to final boss: {answers}. Lock in each guess before the reveal.\n\n"
            "How many did you get—0, 1, 2, or all 3?\n\n"
            "#shorts #quiz #animals #wildlife #guesstheanimal\n",
            encoding="utf-8",
        )
        return str(path)

    legacy.generate_quiz = fixed_generate
    legacy.factcheck_quiz = fixed_factcheck
    legacy.grade_quiz_visuals = local_readability_grade
    legacy.generate_quiz_description = fixed_description


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

    _install_fixed_quiz_contract()
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
            "animals ordered MEDIUM, HARD, EXPERT."
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
        "authoring_mode": "fixed_reviewed_script",
        "semantic_visual_qa": "deferred_due_to_anthropic_usage_limit",
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
                "authoring_mode": summary["authoring_mode"],
                "semantic_visual_qa": summary["semantic_visual_qa"],
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
