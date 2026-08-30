from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
ACCESS = ROOT / "private_access.py"
TOKEN = "097569477bd3df50bb4cf43ed04d1d24"
PATH = f"/api/qa/cleanup-last-quiz-{TOKEN}"
MARKER = "# QA_ONLY_CLEANUP_LAST_QUIZ"
MOUNT = 'app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")'


def patch_private_access() -> None:
    text = ACCESS.read_text(encoding="utf-8")
    if PATH in text:
        return
    old = 'PUBLIC_PATHS = frozenset(("/login", "/api/auth/login", "/api/auth/session", "/healthz"))'
    new = (
        'PUBLIC_PATHS = frozenset(("/login", "/api/auth/login", "/api/auth/session", '
        f'"/healthz", "{PATH}"))'
    )
    if old not in text:
        raise RuntimeError("private access public-path declaration changed; refusing blind patch")
    ACCESS.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_app() -> None:
    text = APP.read_text(encoding="utf-8")
    if MARKER in text:
        start = text.index(MARKER)
        mount_at = text.index(MOUNT, start)
        text = text[:start].rstrip() + "\n\n" + text[mount_at:]
    if MOUNT not in text:
        raise RuntimeError("static mount changed; refusing to register an unreachable QA route")

    route = r'''
# QA_ONLY_CLEANUP_LAST_QUIZ
_QA_CLEANUP_LAST_QUIZ_PATH = "__PATH__"


def _qa_cleanup_last_quiz_candidates() -> list[dict]:
    store = durable_execution.PostgresStore()
    rows = store.finished_list(limit=200, offset=0, query="")
    candidates = []
    for row in rows:
        metadata = row.get("metadata") or {}
        format_name = str(row.get("format") or "")
        title = str(row.get("title") or "")
        searchable = " ".join((
            format_name,
            title,
            str(metadata.get("short_template") or ""),
            str(metadata.get("template") or ""),
            str(metadata.get("quiz_creative") or ""),
            json.dumps(metadata, sort_keys=True, default=str),
        )).lower()
        if not (
            metadata.get("short_template") == "quiz"
            or metadata.get("template") == "quiz"
            or metadata.get("quiz_creative")
            or "quiz" in format_name.lower()
            or "quiz" in title.lower()
            or "guess all 3" in searchable
            or "guess the animal" in searchable
            or "animal 1/3" in searchable
        ):
            continue
        candidates.append({
            "id": row.get("id"),
            "title": title,
            "format": format_name,
            "status": row.get("status"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "size_bytes": row.get("size_bytes"),
            "thumbnail_url": row.get("thumbnail_url"),
            "metadata": metadata,
            "artifact_kinds": sorted((row.get("artifacts") or {}).keys()),
        })
    return candidates


@app.get(_QA_CLEANUP_LAST_QUIZ_PATH)
async def qa_cleanup_last_quiz(action: str = "candidates", video_id: str = ""):
    """Preview-only read path used to retrieve one existing quiz for a local cleanup pass."""
    if (os.environ.get("VERCEL_ENV") != "preview"
            or os.environ.get("VERCEL_GIT_COMMIT_REF") != "qa/cleanup-last-quiz"):
        raise HTTPException(status_code=404, detail="Not found")

    try:
        candidates = await asyncio.to_thread(_qa_cleanup_last_quiz_candidates)
    except durable_execution.StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if action == "candidates":
        return {"count": len(candidates), "candidates": candidates}

    allowed_ids = {str(row.get("id") or "") for row in candidates}
    if not video_id or video_id not in allowed_ids:
        raise HTTPException(status_code=404, detail="Quiz video not found")

    try:
        store = durable_execution.PostgresStore()
        record = await asyncio.to_thread(store.finished_get, video_id)
    except durable_execution.StorageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not record:
        raise HTTPException(status_code=404, detail="Finished video not found")

    if action == "detail":
        return {
            "id": record.get("id"),
            "title": record.get("title"),
            "format": record.get("format"),
            "status": record.get("status"),
            "size_bytes": record.get("size_bytes"),
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
            "metadata": record.get("metadata") or {},
            "artifact_kinds": sorted((record.get("artifacts") or {}).keys()),
        }

    if action != "download":
        raise HTTPException(status_code=400, detail="action must be candidates, detail, or download")

    artifact = (record.get("artifacts") or {}).get("video") or {}
    if not artifact:
        raise HTTPException(status_code=404, detail="Video artifact not found")
    if artifact.get("access") == "private":
        root = tempfile.mkdtemp(prefix="qa_cleanup_last_quiz_")
        local_path = os.path.join(root, "source-quiz.mp4")
        try:
            await asyncio.to_thread(durable_execution.BlobStore().download, artifact, local_path)
        except durable_execution.StorageUnavailable as exc:
            shutil.rmtree(root, ignore_errors=True)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return FileResponse(
            local_path,
            media_type=artifact.get("content_type") or "video/mp4",
            filename="source-quiz.mp4",
            background=BackgroundTask(shutil.rmtree, root, ignore_errors=True),
        )

    remote = artifact.get("download_url") or artifact.get("url")
    if remote:
        return RedirectResponse(remote, status_code=307)
    raise HTTPException(status_code=404, detail="Video bytes are unavailable")
'''.replace("__PATH__", PATH)

    APP.write_text(text.replace(MOUNT, route.rstrip() + "\n\n" + MOUNT, 1), encoding="utf-8")


if __name__ == "__main__":
    patch_private_access()
    patch_app()
    print(f"Applied preview-only cleanup route: {PATH}")
