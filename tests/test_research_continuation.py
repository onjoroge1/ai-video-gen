"""Native research continuation keeps provider evidence and paid request identities intact."""
import copy
import json

import pytest

import explainer_pipeline as pipeline
from durable_execution import activate
from test_durable_anthropic_response import Provider, payload
from test_durable_execution_phase6 import MemoryBlob, MemoryStore, runtime
from test_longform_research_phase2 import SOURCE, QUOTE, _dossier


def _paused(number=1):
    data = payload(stop_reason="pause_turn", output_tokens=20)
    data["content"] = [
        {"type": "text", "text": "Searching for institutional evidence.", "citations": []},
        {"type": "server_tool_use", "id": f"search-{number}", "name": "web_search",
         "input": {"query": "regional gauge measurements"}},
        {"type": "web_search_tool_result", "tool_use_id": f"search-{number}",
         "content": [{"type": "web_search_result", "url": SOURCE, "cited_text": QUOTE,
                      "encrypted_content": "opaque-provider-token-must-survive"}]},
    ]
    data["usage"]["server_tool_use"]["web_search_requests"] = 1
    return data


def _completed(text=None):
    ledger = _dossier()
    ledger.pop("citation_records")
    ledger.pop("citation_urls")
    data = payload(text=json.dumps(ledger) if text is None else text, output_tokens=20)
    data["content"][0]["citations"] = []
    data["usage"]["server_tool_use"]["web_search_requests"] = 0
    return data


def _mock_sources(monkeypatch):
    monkeypatch.setattr(pipeline, "_verify_claims_against_sources", lambda dossier, **kw: dossier)
    monkeypatch.setattr(pipeline, "_claude", lambda: pytest.fail("research used script adapter"))
    monkeypatch.setattr(pipeline, "_parse_script_json",
                        lambda *a, **kw: pytest.fail("research purchased JSON evidence repair"))


def test_paused_research_survives_worker_restart_without_repurchase(tmp_path, monkeypatch):
    _mock_sources(monkeypatch)
    store, blob = MemoryStore(cap=20), MemoryBlob(tmp_path / "blob")
    paused = _paused()
    provider = Provider(paused, _completed())
    worker = runtime(tmp_path, store, blob, "worker-a")
    monkeypatch.setattr(pipeline, "_anthropic_native", lambda: worker.wrap_anthropic(provider))

    class WorkerStopped(BaseException):
        pass

    def stop_after_saved_pause(message):
        if "paused; continuing" in message:
            raise WorkerStopped()

    with pytest.raises(WorkerStopped):
        pipeline.generate_research_dossier("Why did the gauge move?", log=stop_after_saved_pause)
    assert len(provider.calls) == 1
    assert next(iter(store.stages.values()))["status"] == "incomplete"

    results = []
    for name in ("worker-b", "worker-c"):
        worker = runtime(tmp_path, store, blob, name)
        costs = []
        result = pipeline.generate_research_dossier("Why did the gauge move?", cost_sink=costs)
        assert result["validation"]["passed"] is True
        assert result["citation_urls"] == [SOURCE]
        assert result["citation_records"] == [{"url": SOURCE, "cited_text": QUOTE}]
        assert result["research_pause_continuations"] == 1
        assert result["research_response_count"] == 2
        assert result["web_search_requests"] == 1
        assert sum(costs) > 0.1
        results.append(result)

    assert results[0] == results[1]
    assert len(provider.calls) == 2
    first, second = provider.calls
    assert len(first["messages"]) == 1  # A paid request was not mutated after submission.
    assert second["messages"] == [*first["messages"], {"role": "assistant", "content": paused["content"]}]
    assert second["tools"] == first["tools"]
    assert first["tools"][0]["allowed_callers"] == ["direct"]
    assert first["extra_headers"]["Idempotency-Key"] != second["extra_headers"]["Idempotency-Key"]
    assert store.job["reserved_cost_usd"] == pytest.approx(0)


def test_pause_continuations_are_bounded_and_all_search_usage_is_recorded(tmp_path, monkeypatch):
    _mock_sources(monkeypatch)
    store, blob = MemoryStore(cap=20), MemoryBlob(tmp_path / "blob")
    provider = Provider(*[_paused(number) for number in range(4)])
    for name in ("worker-a", "worker-b"):
        worker = runtime(tmp_path, store, blob, name)
        monkeypatch.setattr(pipeline, "_anthropic_native", lambda: worker.wrap_anthropic(provider))
        costs = []
        with pytest.raises(ValueError, match="remained paused after 3 continuations"):
            pipeline.generate_research_dossier("Question", cost_sink=costs)
        assert sum(costs) > 0.4
    assert len(provider.calls) == 4
    assert {stage["status"] for stage in store.stages.values()} == {"incomplete"}
    assert len({call["extra_headers"]["Idempotency-Key"] for call in provider.calls}) == 4


@pytest.mark.parametrize("reason,text,error", [
    ("max_tokens", '{"claims":[', "token ceiling"),
    ("max_tokens", json.dumps(_dossier()), "token ceiling"),
    ("end_turn", '{"claims":[', "malformed dossier JSON"),
    ("end_turn", '{"claims":"unstructured"}', "structured claims list"),
    ("refusal", json.dumps(_dossier()), "did not finish"),
])
def test_incomplete_or_malformed_evidence_is_not_repaired_or_repurchased(
        tmp_path, monkeypatch, reason, text, error):
    _mock_sources(monkeypatch)
    monkeypatch.setattr(pipeline, "_store_research_dossier",
                        lambda *a, **kw: pytest.fail("invalid evidence was cached as a dossier"))
    store, blob = MemoryStore(cap=20), MemoryBlob(tmp_path / "blob")
    data = _completed(text)
    data["stop_reason"] = reason
    provider = Provider(data)
    for name in ("worker-a", "worker-b"):
        worker = runtime(tmp_path, store, blob, name)
        monkeypatch.setattr(pipeline, "_anthropic_native", lambda: worker.wrap_anthropic(provider))
        costs = []
        with pytest.raises(ValueError, match=error):
            pipeline.generate_research_dossier("Question", cost_sink=costs)
        assert sum(costs) > 0
    assert len(provider.calls) == 1


def test_continuation_does_not_license_model_only_sources(tmp_path, monkeypatch):
    _mock_sources(monkeypatch)
    store, blob = MemoryStore(cap=20), MemoryBlob(tmp_path / "blob")
    ledger = _dossier(source_url="https://invented.example.edu/fake")
    provider = Provider(_paused(), _completed(json.dumps(ledger)))
    worker = runtime(tmp_path, store, blob, "worker")
    monkeypatch.setattr(pipeline, "_anthropic_native", lambda: worker.wrap_anthropic(provider))
    with pytest.raises(ValueError, match="unverified_source"):
        pipeline.generate_research_dossier("Question")


@pytest.mark.parametrize("configured,expected", [("600", 240.0), ("100", 100.0)])
def test_research_timeout_leaves_time_to_checkpoint(tmp_path, monkeypatch, configured, expected):
    _mock_sources(monkeypatch)
    monkeypatch.setenv("RESEARCH_TIMEOUT_SEC", configured)
    store, blob = MemoryStore(cap=20), MemoryBlob(tmp_path / "blob")
    provider = Provider(_paused(), _completed())
    worker = runtime(tmp_path, store, blob, "worker")
    monkeypatch.setattr(pipeline, "_anthropic_native", lambda: worker.wrap_anthropic(provider))
    pipeline.generate_research_dossier("Question")
    assert all(call["timeout"] == expected for call in provider.calls)


def test_durable_native_client_disables_sdk_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-live-key")
    monkeypatch.setenv("CLAUDE_MAX_RETRIES", "6")
    calls = []
    provider = Provider()

    def construct(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        return provider

    monkeypatch.setattr(pipeline.anthropic, "Anthropic", construct)
    store, blob = MemoryStore(), MemoryBlob(tmp_path / "blob")
    worker = runtime(tmp_path, store, blob, "worker")
    with activate(worker):
        assert pipeline._anthropic_native().messages is not provider.messages
    assert calls[0]["max_retries"] == 0
    assert pipeline._anthropic_native() is provider
    assert calls[1]["max_retries"] == 6
