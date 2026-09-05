"""Paid-response completeness, restart safety, and lossless Anthropic replay."""
from contextlib import contextmanager
import copy
import json
import re
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from durable_execution import BudgetExceeded, PostgresStore, canonical_hash
from test_durable_execution_phase6 import MemoryBlob, MemoryStore, runtime


def payload(*, stop_reason="end_turn", text='{"scenes": []}', output_tokens=400):
    return {
        "id": "msg-observed-id", "model": "claude-observed-model", "type": "message",
        "role": "assistant", "stop_reason": stop_reason, "stop_sequence": None,
        "content": [{"type": "text", "text": text, "citations": [{
            "type": "web_search_result_location", "url": "https://example.org/source",
            "cited_text": "Evidence from the source.",
        }]}],
        "usage": {"input_tokens": 100, "output_tokens": output_tokens,
                  "cache_read_input_tokens": 80, "cache_creation_input_tokens": 20,
                  "server_tool_use": {"web_search_requests": 2}},
    }


def request(**patch):
    return {"model": "claude-requested-model", "max_tokens": 4000,
            "messages": [{"role": "user", "content": "Expand scenes 1-10."}], **patch}


class Provider:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        assert self.responses, "An already-paid request was purchased again"
        data = self.responses.pop(0)
        return SimpleNamespace(model_dump=lambda: copy.deepcopy(data))


def test_sdk_metadata_and_nested_usage_survive_worker_restart(tmp_path):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    raw = payload()
    provider = Provider(raw)
    first = runtime(tmp_path, store, blob, "worker-a")
    second = runtime(tmp_path, store, blob, "worker-b")
    for worker in (first, second):
        response = worker.wrap_anthropic(provider).messages.create(**request())
        assert response.stop_reason == "end_turn"
        assert response.model == raw["model"]
        assert response.id == raw["id"]
        assert response.stop_sequence is None
        assert response.usage.server_tool_use.web_search_requests == 2
        assert response.usage.cache_read_input_tokens == 80
        assert response.content[0].citations[0].url == "https://example.org/source"
        assert response.content[0].model_dump() == raw["content"][0]
        assert response.model_dump() == raw
    assert len(provider.calls) == 1
    assert list(store.stages.values())[0]["status"] == "completed"
    assert store.job["spent_cost_usd"] == pytest.approx(0.0105)


@pytest.mark.parametrize("stop_reason", ["max_tokens", "pause_turn"])
def test_incomplete_output_is_billed_once_and_smaller_request_can_resume(tmp_path, stop_reason):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    raw = payload(stop_reason=stop_reason, text='{"scenes": [', output_tokens=4000)
    provider = Provider(raw, payload())
    first = runtime(tmp_path, store, blob, "worker-a")
    second = runtime(tmp_path, store, blob, "worker-b")

    # Both the initial caller and a replacement worker can diagnose the actual stop reason.
    # An identical request never repurchases known truncated output or labels it complete.
    for worker in (first, second):
        response = worker.wrap_anthropic(provider).messages.create(**request())
        assert response.stop_reason == stop_reason
        assert response.content[0].text == '{"scenes": ['
        assert response.usage.output_tokens == 4000
    assert len(provider.calls) == 1
    assert list(store.stages.values())[0]["status"] == "incomplete"
    assert store.job["spent_cost_usd"] == pytest.approx(0.1005)
    assert store.job["reserved_cost_usd"] == pytest.approx(0)

    # The caller deliberately changes the batch; a new identity reserves against the same cap.
    response = second.wrap_anthropic(provider).messages.create(**request(
        max_tokens=2000,
        messages=[{"role": "user", "content": "Expand scenes 1-5."}]))
    assert response.stop_reason == "end_turn"
    assert json.loads(response.content[0].text) == {"scenes": []}
    assert len(provider.calls) == 2
    assert provider.calls[0]["extra_headers"]["Idempotency-Key"] != (
        provider.calls[1]["extra_headers"]["Idempotency-Key"])
    assert sorted(stage["status"] for stage in store.stages.values()) == ["completed", "incomplete"]
    assert store.job["spent_cost_usd"] == pytest.approx(0.111)
    assert store.job["reserved_cost_usd"] == pytest.approx(0)


def test_revised_request_still_respects_cap_after_truncation(tmp_path):
    store, blob = MemoryStore(cap=0.13), MemoryBlob(tmp_path / "blob")
    provider = Provider(payload(stop_reason="max_tokens", output_tokens=4000))
    worker = runtime(tmp_path, store, blob, "worker-a")
    client = worker.wrap_anthropic(provider)
    client.messages.create(**request())
    with pytest.raises(BudgetExceeded):
        client.messages.create(**request(max_tokens=2000))
    assert len(provider.calls) == 1
    assert store.job["spent_cost_usd"] == pytest.approx(0.1005)
    assert store.job["reserved_cost_usd"] == pytest.approx(0)


@pytest.mark.parametrize("legacy_reason", ["max_tokens", None])
def test_legacy_response_reuses_existing_charge_without_silent_repurchase(tmp_path, legacy_reason):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    kwargs = request()
    digest = canonical_hash(kwargs)
    stage_key = f"anthropic:{digest[:32]}"
    raw = payload(stop_reason=legacy_reason)
    if legacy_reason is None:
        raw.pop("stop_reason")
    store.prepare_stage("job-1", stage_key, "anthropic", digest, 0.1)
    store.complete_stage("job-1", stage_key, actual_cost=0.05, result=raw, artifact={})
    provider = Provider()
    worker = runtime(tmp_path, store, blob, "worker-a")
    for _ in range(2):
        response = worker.wrap_anthropic(provider).messages.create(**kwargs)
        assert getattr(response, "stop_reason", None) == legacy_reason
        assert response.model_dump() == raw
    assert provider.calls == []
    assert store.job["spent_cost_usd"] == pytest.approx(0.05)
    assert store.job["reserved_cost_usd"] == pytest.approx(0)
    assert store.stages[stage_key]["status"] == (
        "incomplete" if legacy_reason == "max_tokens" else "completed")


def test_telemetry_failure_cannot_reopen_a_settled_incomplete_response(tmp_path):
    class EventFailureStore(MemoryStore):
        def append_event(self, job_id, event_type, data, details=None):
            if event_type == "stage_incomplete":
                raise ConnectionError("event write interrupted")
            return super().append_event(job_id, event_type, data, details)

    store, blob = EventFailureStore(), MemoryBlob(tmp_path / "blob")
    provider = Provider(payload(stop_reason="max_tokens"))
    first = runtime(tmp_path, store, blob, "worker-a")
    with pytest.raises(ConnectionError, match="event write interrupted"):
        first.wrap_anthropic(provider).messages.create(**request())
    second = runtime(tmp_path, store, blob, "worker-b")
    response = second.wrap_anthropic(provider).messages.create(**request())
    assert response.stop_reason == "max_tokens"
    assert len(provider.calls) == 1
    assert store.job["spent_cost_usd"] == pytest.approx(0.0105)
    assert store.job["reserved_cost_usd"] == pytest.approx(0)


def test_postgres_reclassifies_legacy_truncation_without_mutating_job_spend():
    """Exercise the actual store method's already-settled transaction branch."""
    completed = {"status": "completed", "actual_cost_usd": 0.05, "result": payload()}
    cursor = Mock()
    cursor.fetchone.side_effect = [completed, {**completed, "status": "incomplete"}]

    class TransactionStore(PostgresStore):
        def __init__(self):
            pass

        @contextmanager
        def _tx(self):
            yield None, cursor

        @staticmethod
        def _row(cur, row):
            return row

    result = TransactionStore().incomplete_stage(
        "job-1", "anthropic:legacy", actual_cost=0.05,
        result=payload(stop_reason="max_tokens"))
    assert result["status"] == "incomplete"
    assert result["actual_cost_usd"] == 0.05
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert any("UPDATE generation_stages" in statement for statement in statements)
    assert not any("UPDATE generation_jobs" in statement for statement in statements)


def test_real_expander_splits_truncated_durable_batch_and_replays_without_spend(tmp_path, monkeypatch):
    import explainer_pipeline as pipeline
    from test_causal_lane_integration import _route

    class ExpansionProvider:
        def __init__(self):
            self.messages = self
            self.calls = []
            self.expansions = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            prompt = kwargs["messages"][0]["content"]
            matched = re.search(r"NOW WRITE scenes (\d+)-(\d+) ONLY", prompt)
            if matched:
                lo, hi = map(int, matched.groups())
                self.expansions.append((lo, hi))
                if (lo, hi) == (1, 10):
                    raw = payload(stop_reason="max_tokens", text='{"scenes": [')
                else:
                    raw = payload(text=json.dumps({"scenes": [
                        {"narration": f"Unique beat number {i}.", "environment_type": "city"}
                        for i in range(lo, hi + 1)]}))
            else:
                raw = payload(text=json.dumps(_route(prompt, 10)))
            return SimpleNamespace(model_dump=lambda: raw)

    store, blob = MemoryStore(cap=10), MemoryBlob(tmp_path / "blob")
    provider = ExpansionProvider()
    worker = runtime(tmp_path, store, blob, "worker-a")
    monkeypatch.setattr(pipeline, "_claude", lambda: worker.wrap_anthropic(provider))
    monkeypatch.setattr(pipeline, "_dedupe_narration", lambda scenes, *a: (scenes, 0))

    first_script = pipeline._generate_script_chunked(
        "Why?", 200, "s", "", 10, causal_lane=True, pinned_engine="backfiring_solution")
    assert provider.expansions == [(1, 10), (1, 5), (6, 10)]
    assert [scene["story_beat_n"] for scene in first_script["scenes"]] == list(range(1, 11))
    assert len([s for s in store.stages.values() if s["status"] == "incomplete"]) == 1
    first_call_count = len(provider.calls)
    first_spend = store.job["spent_cost_usd"]

    worker = runtime(tmp_path, store, blob, "worker-b")
    replayed_script = pipeline._generate_script_chunked(
        "Why?", 200, "s", "", 10, causal_lane=True, pinned_engine="backfiring_solution")
    assert [scene["story_beat_n"] for scene in replayed_script["scenes"]] == list(range(1, 11))
    assert replayed_script["_script_cost_usd"] == first_script["_script_cost_usd"]
    assert len(provider.calls) == first_call_count
    assert store.job["spent_cost_usd"] == first_spend > 0
    assert store.job["reserved_cost_usd"] == pytest.approx(0)
