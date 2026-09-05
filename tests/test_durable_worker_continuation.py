"""Real worker-window boundaries, bounded lease handoff and reconnectable progress."""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import time

import anyio
import httpx
import pytest

import _durable_execution_legacy as engine
from durable_execution import BudgetExceeded, CooperativeYield, LeaseLost, PostgresStore
from test_durable_execution_phase6 import MemoryBlob, MemoryStore, runtime


def test_deadline_yields_before_reserving_or_calling_provider(tmp_path):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    worker = runtime(tmp_path, store, blob, "worker-a")
    worker.time_budget_seconds = 60
    worker._started_at = time.monotonic() - 61
    with pytest.raises(CooperativeYield, match="script:next"):
        worker.paid_value(stage_key="script:next", provider="anthropic", request={},
                          estimated_cost=0.2, operation=lambda _: pytest.fail("provider called"))
    assert not store.stages
    assert store.job["reserved_cost_usd"] == 0
    assert not issubclass(CooperativeYield, Exception)


def test_local_render_phase_yields_before_starting_after_deadline(tmp_path):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    worker = runtime(tmp_path, store, blob, "worker-a")
    worker.time_budget_seconds = 60
    worker._started_at = time.monotonic() - 61
    with pytest.raises(CooperativeYield, match="Rendering scenes"):
        worker.event("stage", "Rendering scenes")
    assert not store.events_seen


def test_completed_stage_is_not_failed_when_next_boundary_yields(tmp_path):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    worker = runtime(tmp_path, store, blob, "worker-a")
    worker.time_budget_seconds = 60
    def paid(_key):
        worker._started_at = time.monotonic() - 61
        return {"approved": True}, 0.05
    worker.paid_value(stage_key="script:one", provider="anthropic", request={},
                      estimated_cost=0.1, operation=paid)
    with pytest.raises(CooperativeYield):
        worker.paid_value(stage_key="script:two", provider="anthropic", request={},
                          estimated_cost=0.1, operation=lambda _: pytest.fail("provider called"))
    assert store.stages["script:one"]["status"] == "completed"
    assert "script:two" not in store.stages
    second = runtime(tmp_path, store, blob, "worker-b")
    result, cost, cached = second.paid_value(
        stage_key="script:one", provider="anthropic", request={}, estimated_cost=0.1,
        operation=lambda _: pytest.fail("repurchased completed stage"))
    assert result == {"approved": True} and cached
    assert store.job["spent_cost_usd"] == pytest.approx(cost)


class HandoffCursor:
    def __init__(self, row):
        self.row = row
        self.calls = []
    def execute(self, sql, params):
        self.calls.append((sql, params))
        if "UPDATE generation_jobs" in sql:
            status, error, checkpoint, result, _status, _job, _owner = params
            self.row.update(status=status, error=error, checkpoint=json.loads(checkpoint),
                            attempts=max(0, self.row["attempts"] - 1), lease_owner=None,
                            lease_expires_at=None)
            self.row["result"].update(json.loads(result))
    def fetchone(self):
        return copy.deepcopy(self.row)


def handoff_store(row):
    store = object.__new__(PostgresStore)
    cursor = HandoffCursor(row)
    @contextmanager
    def transaction():
        yield None, cursor
    store._tx = transaction
    store._row = lambda _cursor, raw: raw
    store.append_event = lambda *args: None
    return store, cursor


def test_handoff_preserves_approval_budget_stages_and_failure_attempts():
    row = {"id": "job-1", "status": "processing", "lease_owner": "worker-a",
           "request": {"immutable_hash": "abc"}, "result": {}, "attempts": 2,
           "max_attempts": 5, "spent_cost_usd": 0.7, "reserved_cost_usd": 0.2,
           "max_cost_usd": 2.0}
    store, cursor = handoff_store(row)
    checkpoint = {"sha256": "saved-control", "url": "blob"}
    result = store.yield_job("job-1", worker_id="worker-a", checkpoint=checkpoint)
    assert result["status"] == "queued"
    assert result["attempts"] == 1  # the next claim returns to 2, no error attempt consumed
    assert result["result"]["continuation_count"] == 1
    assert result["checkpoint"] == checkpoint
    assert result["lease_owner"] is None
    assert result["request"] == {"immutable_hash": "abc"}
    assert result["spent_cost_usd"] == 0.7
    assert result["reserved_cost_usd"] == 0.2
    assert result["max_cost_usd"] == 2.0
    assert all("generation_stages" not in sql for sql, _ in cursor.calls)


def test_handoff_is_bounded_and_wrong_owner_cannot_release_lease():
    row = {"id": "job-1", "status": "processing", "lease_owner": "worker-a",
           "result": {"continuation_count": 24}, "attempts": 1}
    store, _ = handoff_store(row)
    with pytest.raises(LeaseLost):
        store.yield_job("job-1", worker_id="worker-b", checkpoint={"sha256": "saved"})
    result = store.yield_job("job-1", worker_id="worker-a", checkpoint={"sha256": "saved"})
    assert result["status"] == "error"
    assert "continuations exhausted" in result["error"]


def test_anthropic_reservation_is_not_clipped_to_fit_spend_cap():
    request = {"max_tokens": 60000, "messages": [{"role": "user", "content": "hi"}]}
    assert engine._anthropic_reserved_cost(request) > 1.5
    with pytest.raises(BudgetExceeded, match="single-call"):
        engine.enforce_budget({"spent_cost_usd": 0, "reserved_cost_usd": 0,
                               "max_cost_usd": 5, "max_inflight_call_usd": 1},
                              engine._anthropic_reserved_cost(request), "large-script")


def test_search_reservation_and_actual_cache_usage_are_accounted():
    request = {"max_tokens": 1000, "messages": [],
               "tools": [{"type": "web_search_20260318", "max_uses": 5}]}
    assert engine._anthropic_reserved_cost(request) > 0.325
    del request["tools"][0]["max_uses"]
    with pytest.raises(BudgetExceeded, match="max_uses"):
        engine._anthropic_reserved_cost(request)
    assert engine._anthropic_usage_cost({
        "input_tokens": 1000, "output_tokens": 1000, "cache_read_input_tokens": 2000,
        "cache_creation_input_tokens": 3000,
        "cache_creation": {"ephemeral_5m_input_tokens": 1000,
                           "ephemeral_1h_input_tokens": 2000},
        "server_tool_use": {"web_search_requests": 3},
    }) == pytest.approx(0.08725)


def test_status_reconnect_uses_native_last_event_id(monkeypatch):
    import app as studio
    monkeypatch.setenv("DURABLE_EXECUTION", "1")
    seen = []
    class Store:
        def get_job(self, _job):
            return {"id": "job", "status": "done", "result": {}}
        def events(self, job_id, after, limit):
            seen.append(after)
            return [{"seq": 51, "event_type": "done", "data": "ready"}]
    monkeypatch.setattr(studio, "_durable_components", lambda: (Store(), object()))
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app),
                                     base_url="http://test") as client:
            response = await client.get("/api/explainer/status/job?after=12",
                                        headers={"Last-Event-ID": "50"})
            assert response.status_code == 200
            assert 'id: 51\n' in response.text
            assert '"seq": 51' in response.text
    anyio.run(check)
    assert seen == [50]
