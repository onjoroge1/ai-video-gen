"""No-provider-spend assembly for the salvaged Hippo full film.

Both inputs are immutable finished-video artifacts: a newly approved 0–45 second opening and the
already-paid 45–300 second remainder. The concat is stream-copy only and creates a separate library
record so neither source artifact is overwritten.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import db
import explainer_pipeline as ep
import spec_pilot


class HippoRecoveryError(RuntimeError):
    pass


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _video(record: dict | None) -> dict:
    return ((record or {}).get("artifacts") or {}).get("video") or {}


def assemble_if_ready(*, opening_job_id: str, remainder_job_id: str, target_id: str,
                      blob) -> dict:
    existing = db.finished_video_get(target_id)
    if existing:
        return {"status": "already_complete", "id": target_id}

    opening_record = db.finished_video_get(opening_job_id)
    remainder_record = db.finished_video_get(remainder_job_id)
    opening = _video(opening_record)
    remainder = _video(remainder_record)
    if not opening or not remainder:
        return {
            "status": "waiting",
            "opening_ready": bool(opening),
            "remainder_ready": bool(remainder),
        }

    root = Path(tempfile.mkdtemp(prefix="hippo_recovery_concat_"))
    output = root / "what_if_america_adopted_hippo_meat_full.mp4"
    manifest = root / "concat.txt"
    try:
        runtime = SimpleNamespace(blob=blob)
        with spec_pilot._blob_segment_inputs([opening, remainder], runtime) as urls:
            manifest.write_text(
                "".join(f"file '{url}'\n" for url in urls),
                encoding="utf-8",
            )
            ep._run_ffmpeg([
                ep._ffmpeg_bin(), "-nostdin", "-y",
                "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
                "-f", "concat", "-safe", "0", "-i", str(manifest),
                "-map", "0:v", "-map", "0:a", "-c", "copy",
                "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
                str(output),
            ], timeout=600.0)

        duration = ep._audio_dur(str(output))
        if not 297.0 <= duration <= 303.0:
            raise HippoRecoveryError(
                f"Recovered full-film runtime {duration:.2f}s is outside 300s tolerance")
        remote = blob.upload(
            str(output),
            f"finished/{target_id}/video-{_sha256(output)[:24]}.mp4",
        )
        artifact = {"kind": "video", **remote}
        record = {
            "id": target_id,
            "title": "What If America Had Adopted Hippo Meat? — Full Illustrated History",
            "format": "landscape",
            "status": "done",
            "video_url": artifact["url"],
            "download_url": artifact.get("download_url") or artifact["url"],
            "thumbnail_url": None,
            "size_bytes": artifact.get("size_bytes"),
            "artifacts": {"video": artifact},
            "metadata": {
                "technical_status": "completed",
                "automated_grade_status": "NOT_RUN_RECOVERY_CONCAT",
                "editorial_status": "pending",
                "promotion_status": "full_film_recovered",
                "duration_sec": round(duration, 2),
                "actual_cost": 0.0,
                "assembly_provider_spend_usd": 0.0,
                "opening_job_id": opening_job_id,
                "opening_video_sha256": opening.get("sha256"),
                "remainder_job_id": remainder_job_id,
                "remainder_video_sha256": remainder.get("sha256"),
                "video_sha256": artifact.get("sha256"),
                "pilot_reused": False,
                "recovery_note": "Deleted opening rebuilt under separate approval; remainder reused.",
            },
        }
        if not db.finished_video_upsert(record):
            try:
                blob.delete(str(artifact["url"]))
            finally:
                raise HippoRecoveryError("Recovered film upload could not be indexed")
        return {
            "status": "completed",
            "id": target_id,
            "duration_sec": round(duration, 2),
            "video_sha256": artifact.get("sha256"),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)
