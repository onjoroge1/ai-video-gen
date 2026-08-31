"""No-provider-spend assembly for the salvaged Hippo full film.

Both inputs are immutable finished-video artifacts: a newly approved 0–45 second opening and the
already-paid 45–300 second remainder. The concat is stream-copy only and creates a separate library
record so neither source artifact is overwritten.
"""
from __future__ import annotations

import hashlib
import shutil
import struct
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


def _mp4_top_level_boxes(path: str | Path) -> list[str]:
    """Parse top-level ISO-BMFF boxes so a fragmented MP4 cannot pass as browser-safe."""
    total = Path(path).stat().st_size
    offset = 0
    boxes: list[str] = []
    with open(path, "rb") as handle:
        while offset + 8 <= total:
            handle.seek(offset)
            header = handle.read(8)
            size, raw_type = struct.unpack(">I4s", header)
            header_size = 8
            if size == 1:
                extended = handle.read(8)
                if len(extended) != 8:
                    raise HippoRecoveryError("MP4 has a truncated extended box header")
                size = struct.unpack(">Q", extended)[0]
                header_size = 16
            elif size == 0:
                size = total - offset
            if size < header_size or offset + size > total:
                raise HippoRecoveryError("MP4 has an invalid top-level box size")
            boxes.append(raw_type.decode("latin-1"))
            offset += size
    if offset != total:
        raise HippoRecoveryError("MP4 has trailing bytes outside a top-level box")
    return boxes


def assemble_if_ready(*, opening_job_id: str, remainder_job_id: str, target_id: str,
                      blob) -> dict:
    existing = db.finished_video_get(target_id)
    existing_metadata = (existing or {}).get("metadata") or {}
    if (existing and existing_metadata.get("container_profile") == "standard_mp4"
            and existing_metadata.get("browser_safe_container") is True):
        print(f"[hippo-recovery] browser-safe target already complete: {target_id}")
        return {"status": "already_complete", "id": target_id}
    if existing:
        print(f"[hippo-recovery] rebuilding unsafe fragmented target: {target_id}")

    opening_record = db.finished_video_get(opening_job_id)
    remainder_record = db.finished_video_get(remainder_job_id)
    opening = _video(opening_record)
    remainder = _video(remainder_record)
    if not opening or not remainder:
        print("[hippo-recovery] waiting for immutable opening and remainder artifacts")
        return {
            "status": "waiting",
            "opening_ready": bool(opening),
            "remainder_ready": bool(remainder),
        }

    root = Path(tempfile.mkdtemp(prefix="hippo_recovery_concat_"))
    output = root / "what_if_america_adopted_hippo_meat_full.mp4"
    manifest = root / "concat.txt"
    try:
        print("[hippo-recovery] starting zero-spend standard-MP4 stream concat")
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
                str(output),
            ], timeout=600.0)

        boxes = _mp4_top_level_boxes(output)
        if "moov" not in boxes or "moof" in boxes:
            raise HippoRecoveryError(
                f"Recovered film is not browser-safe standard MP4; boxes={boxes}")
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
                "container_profile": "standard_mp4",
                "browser_safe_container": True,
                "top_level_boxes": boxes,
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
        print(
            f"[hippo-recovery] validated standard MP4 duration={duration:.2f}s "
            f"size={artifact.get('size_bytes')} boxes={boxes}")
        if not db.finished_video_upsert(record):
            try:
                blob.delete(str(artifact["url"]))
            finally:
                raise HippoRecoveryError("Recovered film upload could not be indexed")
        print(f"[hippo-recovery] indexed browser-safe recovered film: {target_id}")
        return {
            "status": "completed",
            "id": target_id,
            "duration_sec": round(duration, 2),
            "video_sha256": artifact.get("sha256"),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)
