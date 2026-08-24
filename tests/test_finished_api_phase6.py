import json
from pathlib import Path

import anyio
import httpx
from fastapi import FastAPI

import finished_api
from durable_execution import StorageUnavailable


def test_finished_library_reports_database_outage_instead_of_empty(monkeypatch, tmp_path):
    app = FastAPI()
    finished_api.mount(app, str(tmp_path), Path("static"))
    monkeypatch.setattr(finished_api.db, "db_enabled", lambda: True)

    class BrokenStore:
        def finished_list(self, **_kwargs):
            raise StorageUnavailable("database connection refused")

    monkeypatch.setattr(finished_api, "PostgresStore", BrokenStore)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/finished")
            assert response.status_code == 503
            detail = response.json()["detail"]
            assert detail["code"] == "FINISHED_STORAGE_UNAVAILABLE"
            assert detail["retryable"] is True

    anyio.run(run)


class _EmptyStore:
    def finished_list(self, **_kwargs):
        return []

    def finished_get(self, _video_id):
        return None


def _seed_local_render(tmp_path) -> str:
    """One indexed local render, exactly as _persist_finished leaves it on disk."""
    video = tmp_path / "abc123.mp4"
    video.write_bytes(b"\x00" * 2048)
    captions = tmp_path / "abc123.srt"
    captions.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps({
        "abc123": {"title": "Local render", "path": str(video), "srt_path": str(captions)},
    }), encoding="utf-8")
    return "abc123"


def test_finished_library_does_not_fall_back_locally_when_durable_storage_is_required(
        monkeypatch, tmp_path):
    """Production stays fail-closed: Postgres is authoritative and local bytes cannot stand in.

    Seeds a real local render first — the previous version of this test pointed at an empty
    directory, so the local fallback had nothing to return and it passed without ever
    exercising the rule in its own name.
    """
    _seed_local_render(tmp_path)
    app = FastAPI()
    finished_api.mount(app, str(tmp_path), Path("static"))
    monkeypatch.setattr(finished_api.db, "db_enabled", lambda: True)
    monkeypatch.setattr(finished_api, "PostgresStore", _EmptyStore)
    monkeypatch.setattr(finished_api.artifact_store, "durable_storage_required", lambda: True)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            listing = await client.get("/api/finished")
            assert listing.status_code == 200
            assert listing.json()["videos"] == []
            assert (await client.get("/api/finished/abc123")).status_code == 404

    anyio.run(run)


def test_finished_library_serves_local_renders_when_the_database_has_no_row(
        monkeypatch, tmp_path):
    """DATABASE_URL set with no Blob token is the ordinary local setup.

    Renders still write finished_videos/<id>.{mp4,srt,...} and index them, but no Postgres row
    is created, so querying only the database reported an empty library while the files sat on
    disk — every local render was undownloadable through /finished.
    """
    video_id = _seed_local_render(tmp_path)
    app = FastAPI()
    finished_api.mount(app, str(tmp_path), Path("static"))
    monkeypatch.setattr(finished_api.db, "db_enabled", lambda: True)
    monkeypatch.setattr(finished_api, "PostgresStore", _EmptyStore)
    monkeypatch.setattr(finished_api.artifact_store, "durable_storage_required", lambda: False)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            listing = await client.get("/api/finished")
            assert listing.status_code == 200
            rows = listing.json()["videos"]
            assert [row["id"] for row in rows] == [video_id]
            assert sorted(rows[0]["artifacts"]) == ["srt", "video"]

            detail = await client.get(f"/api/finished/{video_id}")
            assert detail.status_code == 200

            for kind, expected in (("video", 2048), ("srt", None)):
                artifact = await client.get(
                    f"/api/finished/{video_id}/artifact/{kind}?download=true")
                assert artifact.status_code == 200, kind
                if expected:
                    assert len(artifact.content) == expected

    anyio.run(run)
