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


def test_finished_library_does_not_fall_back_locally_when_database_is_empty(
        monkeypatch, tmp_path):
    app = FastAPI()
    finished_api.mount(app, str(tmp_path), Path("static"))
    monkeypatch.setattr(finished_api.db, "db_enabled", lambda: True)

    class EmptyStore:
        def finished_list(self, **_kwargs):
            return []

    monkeypatch.setattr(finished_api, "PostgresStore", EmptyStore)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/finished")
            assert response.status_code == 200
            assert response.json()["videos"] == []

    anyio.run(run)
