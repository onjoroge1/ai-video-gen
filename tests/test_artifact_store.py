from pathlib import Path

import artifact_store


class _Response:
    text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "url": "https://blob.example/video-random.mp4",
            "downloadUrl": "https://blob.example/video-random.mp4?download=1",
            "pathname": "finished/job/video-random.mp4",
            "contentType": "video/mp4",
        }


def test_persist_finished_uploads_bytes_then_indexes_metadata(tmp_path, monkeypatch):
    video = tmp_path / "quiz.mp4"
    captions = tmp_path / "captions.srt"
    video.write_bytes(b"video-bytes")
    captions.write_text("1\n00:00:00,000 --> 00:00:01,000\nQuestion\n")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_store_token")
    monkeypatch.setenv("DATABASE_URL", "postgres://configured")
    uploads = []
    records = []

    def fake_put(url, **kwargs):
        uploads.append((url, kwargs["params"]["pathname"], kwargs["headers"]["x-content-type"]))
        return _Response()

    monkeypatch.setattr(artifact_store.requests, "put", fake_put)
    monkeypatch.setattr(artifact_store.db, "db_enabled", lambda: True)
    monkeypatch.setattr(artifact_store.db, "finished_video_upsert",
                        lambda record: records.append(record) or True)

    record = artifact_store.persist_finished(
        "job123", str(video), {"title": "Quiz", "format": "short-quiz", "status": "done"},
        {"srt": str(captions)},
    )
    assert [item[1] for item in uploads] == ["finished/job123/video.mp4", "finished/job123/srt.srt"]
    assert record["title"] == "Quiz"
    assert set(record["artifacts"]) == {"video", "srt"}
    assert records[0]["video_url"].startswith("https://blob.example/")


def test_vercel_storage_readiness_fails_before_render(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("VERCEL_BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    try:
        artifact_store.assert_ready()
    except artifact_store.ArtifactPersistenceError as exc:
        assert "BLOB_READ_WRITE_TOKEN" in str(exc)
        assert "DATABASE_URL" in str(exc)
    else:
        raise AssertionError("production must fail closed without durable storage")


def test_read_only_local_archive_does_not_skip_blob_upload(tmp_path, monkeypatch):
    import app

    video = tmp_path / "render.mp4"
    video.write_bytes(b"render")
    calls = []
    monkeypatch.setattr(app.shutil, "copy",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("read-only")))
    monkeypatch.setattr(app.artifact_store, "persist_finished",
                        lambda job_id, path, meta, extras: calls.append((job_id, path)) or {"id": job_id})

    result = app._persist_finished("job-ro", str(video), {"title": "Stored"})

    assert result == str(video)
    assert calls == [("job-ro", str(video))]
