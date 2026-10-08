"""OpenAI script fallback uses the same spending and replay boundary."""
import pytest
from durable_execution import activate, BudgetExceeded
from script_provider import _OpenAIMessages
from test_script_provider import _FakeClient, _Raw, _Usage
from test_durable_execution_phase6 import MemoryStore, MemoryBlob, runtime


@pytest.mark.parametrize('finish,status', [('stop', 'completed'), ('length', 'incomplete')])
def test_openai_response_replays_without_duplicate_call(monkeypatch, tmp_path, finish, status):
    monkeypatch.setenv('OPENAI_SCRIPT_REASONING_HEADROOM', '100')
    store, blob = MemoryStore(), MemoryBlob(tmp_path / 'blob')
    client = _FakeClient(_Raw('{"story": "fixture"}', finish, _Usage(100, 80)))
    adapter = _OpenAIMessages(client)
    calls = []
    original = client.chat.completions.create
    def create(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)
    monkeypatch.setattr(client.chat.completions, 'create', create)
    for worker in ('worker-a', 'worker-b'):
        with activate(runtime(tmp_path, store, blob, worker)):
            response = adapter.create(model='gpt-test', max_tokens=100,
                                      messages=[{'role': 'user', 'content': 'A story'}])
            assert response.content[0].text == '{"story": "fixture"}'
    assert len(calls) == 1
    assert calls[0]['extra_headers']['Idempotency-Key']
    assert next(iter(store.stages.values()))['status'] == status
    assert store.job['spent_cost_usd'] > 0
    assert store.job['reserved_cost_usd'] == pytest.approx(0)


def test_openai_budget_blocks_before_sdk_call(tmp_path):
    store, blob = MemoryStore(cap=.000001), MemoryBlob(tmp_path / 'blob')
    client = _FakeClient(_Raw('unused'))
    with activate(runtime(tmp_path, store, blob, 'worker-a')):
        with pytest.raises(BudgetExceeded):
            _OpenAIMessages(client).create(model='gpt-test', max_tokens=100)
    assert client.chat.completions.seen is None
