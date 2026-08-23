import anyio
import httpx

import app as studio


def test_generate_only_enqueues_and_returns_detached_dispatch(monkeypatch):
    monkeypatch.setenv("DURABLE_EXECUTION", "1")
    monkeypatch.setattr(studio, "_require_render_storage", lambda: None)
    monkeypatch.setattr(studio, "_sweep_old_temp", lambda *_args, **_kwargs: None)
    calls = []

    class Store:
        def enqueue(self, **kwargs):
            calls.append(kwargs)
            return {"id": kwargs["job_id"], "status": "queued", "result": {},
                    "spent_cost_usd": 0, "max_cost_usd": kwargs["max_cost_usd"],
                    "attempts": 0, "checkpoint": {}}

    monkeypatch.setattr(studio, "_durable_components", lambda: (Store(), object()))

    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/explainer/generate", json={"question": "Why?"})
            assert response.status_code == 200
            payload = response.json()
            assert payload["durable"] is True
            assert payload["dispatch_url"] == f"/api/explainer/dispatch/{payload['job_id']}"

    anyio.run(run)
    assert len(calls) == 1


def test_status_stream_reads_persisted_events_without_process_memory(monkeypatch):
    monkeypatch.setenv("DURABLE_EXECUTION", "1")
    studio.explainer_jobs.clear()

    class Store:
        def get_job(self, job_id):
            return {"id": job_id, "status": "done", "result": {}}

        def events(self, job_id, after, limit):
            if after:
                return []
            return [{"seq": 7, "event_type": "done", "data": "remote complete"}]

    store = Store()
    monkeypatch.setattr(studio, "_durable_components", lambda: (store, object()))

    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/explainer/status/cross-instance")
            assert response.status_code == 200
            assert '"type": "done"' in response.text
            assert "remote complete" in response.text

    anyio.run(run)


def test_resumed_status_stream_starts_after_the_acknowledgement_event(monkeypatch):
    monkeypatch.setenv("DURABLE_EXECUTION", "1")
    seen_after = []

    class Store:
        def get_job(self, job_id):
            return {"id": job_id, "status": "done", "result": {}}

        def events(self, job_id, after, limit):
            seen_after.append(after)
            return [{"seq": 42, "event_type": "done", "data": "resumed complete"}]

    monkeypatch.setattr(studio, "_durable_components", lambda: (Store(), object()))

    async def run():
        transport = httpx.ASGITransport(app=studio.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/explainer/status/resumed?after=41")
            assert response.status_code == 200
            assert "resumed complete" in response.text

    anyio.run(run)
    assert seen_after == [41]
