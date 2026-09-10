"""Account rejections pause any topic without becoming unsupported evidence."""
from contextlib import contextmanager
import copy
import json
from unittest.mock import Mock

import anthropic
import httpx
import pytest

import claim_entailment
import explainer_pipeline
import provider_blocks
from durable_execution import DurableExecutionError, PostgresStore
from test_durable_anthropic_response import Provider, payload, request
from test_durable_execution_phase6 import MemoryBlob, MemoryStore, runtime


def credit_error():
    return anthropic.BadRequestError(
        "Your credit balance is too low to access the Anthropic API.",
        response=httpx.Response(400, request=httpx.Request('POST', 'https://api.anthropic.com/v1/messages')),
        body={"error": {"type": "invalid_request_error",
                        "message": "Your credit balance is too low to access the Anthropic API."}})


@pytest.mark.parametrize('status,message,code', [
    (400, 'Your credit balance is too low', 'insufficient_credit'),
    (401, 'secret credential must never be exposed', 'authentication'),
    (403, 'private account detail', 'permission'),
    (400, 'invalid message format', None), (429, 'rate limited', None),
    (500, 'server error', None), (529, 'overloaded', None),
])
def test_only_explicit_account_rejections_are_manually_resumable(status, message, code):
    exc = Mock(status_code=status, body={'error': {'message': message}})
    result = provider_blocks.from_exception(exc)
    assert result.get('code') == code
    assert 'secret credential' not in str(result) and 'private account' not in str(result)
    assert provider_blocks.from_exception(TimeoutError('credit balance is too low')) == {}


@pytest.mark.parametrize('topic', ['cane toad introduction', 'river irrigation', 'rat bounty'])
def test_credit_block_bypasses_evidence_repair_then_reuses_paid_work(tmp_path, monkeypatch, topic):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / 'blob')
    first = runtime(tmp_path, store, blob, 'first')
    first.paid_value(stage_key='research', provider='anthropic', request={'topic': topic},
                     estimated_cost=.2, operation=lambda _: ({'facts': topic}, .1))
    provider = Provider(payload(text=json.dumps({'verdict': 'entailed'})))
    funded_create = provider.create
    attempted = []
    def blocked_create(**kwargs):
        attempted.append(kwargs)
        raise credit_error()
    provider.create = blocked_create
    client = first.wrap_anthropic(provider)
    monkeypatch.setattr(explainer_pipeline, '_claude', lambda: client)
    cache = {}
    with pytest.raises(provider_blocks.ProviderBlocked) as stopped:
        claim_entailment.evidence_entailment([{'claim': topic}], topic, cache=cache)
    assert stopped.value.block['code'] == 'insufficient_credit'
    assert not cache  # neither an unsupported verdict nor a cached pass
    reserved = store.job['reserved_cost_usd']
    assert reserved > 0 and store.job['spent_cost_usd'] == .1
    assert store.stages[stopped.value.stage_key]['result']['provider_block']['code'] == 'insufficient_credit'
    provider.create = funded_create
    second = runtime(tmp_path, store, blob, 'resumed')
    second.paid_value(stage_key='research', provider='anthropic', request={'topic': topic},
                     estimated_cost=.2, operation=lambda _: pytest.fail('Research repurchased'))
    client = second.wrap_anthropic(provider)
    assert claim_entailment.evidence_entailment([{'claim': topic}], topic, cache=cache)['passed']
    assert len(provider.calls) == 1
    assert attempted[0]['extra_headers'] == provider.calls[0]['extra_headers']
    assert store.job['reserved_cost_usd'] == pytest.approx(0)


CHECKPOINT = 'a' * 64


def blocked_records(legacy=False):
    block = provider_blocks.from_exception(credit_error())
    error = "Error code: 400 - Your credit balance is too low to access the Anthropic API."
    job = {'id': 'any-job', 'status': 'error' if legacy else 'provider_blocked',
           'error': error if legacy else block['message'],
           'result': {} if legacy else {'provider_block': block},
           'checkpoint': {'sha256': CHECKPOINT}, 'attempts': 7, 'max_attempts': 7,
           'max_cost_usd': 5, 'spent_cost_usd': 2.2109,
           'reserved_cost_usd': .0173, 'max_inflight_call_usd': 1,
           'request': {'immutable': 'same spec'}}
    stage = {'stage_key': 'anthropic:request', 'provider': 'anthropic', 'status': 'retry',
             'reserved_cost_usd': .0173, 'error': error,
             'result': {} if legacy else {'provider_block': block}}
    return job, stage


def transaction_store(job, stages):
    cursor = Mock()
    cursor.fetchone.side_effect = [copy.deepcopy(job), {**job, 'status': 'queued'}]
    cursor.fetchall.return_value = stages
    store = object.__new__(PostgresStore)
    @contextmanager
    def tx():
        yield None, cursor
    store._tx = tx
    store._row = lambda _, value: value
    store.append_event = Mock()
    return store, cursor


@pytest.mark.parametrize('legacy', [False, True])
def test_postgres_resume_accepts_new_and_saved_account_rejections(legacy):
    job, stage = blocked_records(legacy)
    store, cursor = transaction_store(job, [stage])
    assert store.resume_provider_block('any-job', expected_checkpoint_sha256=CHECKPOINT)['status'] == 'queued'
    mutations = [(sql, params) for sql, params in (c.args for c in cursor.execute.call_args_list)
                 if sql.lstrip().startswith('UPDATE')]
    assert len(mutations) == 1
    sql, params = mutations[0]
    assert 'generation_stages' not in sql and 'cost_usd=' not in sql and 'request=' not in sql
    assert json.loads(params[0])['provider_resume_count'] == 1
    assert 'attempts+1' in sql  # a single explicit retry, never an automatic rearm loop


@pytest.mark.parametrize('change', ['timeout', 'different_error', 'two_stages', 'running',
                                    'reservation', 'budget', 'checkpoint', 'provider'])
def test_postgres_rejects_ambiguous_content_or_budget_failures(change):
    job, stage = blocked_records(True)
    stages = [stage]
    if change == 'timeout': stage['error'] = 'connection timed out'
    elif change == 'different_error': job['error'] = 'STORY_SPINE_UNSUPPORTED'
    elif change == 'two_stages': stages.append(copy.deepcopy(stage))
    elif change == 'running': stage['status'] = 'running'
    elif change == 'reservation': stage['reserved_cost_usd'] = .9
    elif change == 'budget': job['max_cost_usd'] = 2.22
    elif change == 'checkpoint': job['checkpoint']['sha256'] = 'b' * 64
    elif change == 'provider': stage['provider'] = 'openai'
    store, cursor = transaction_store(job, stages)
    with pytest.raises(DurableExecutionError):
        store.resume_provider_block('any-job', expected_checkpoint_sha256=CHECKPOINT)
    assert not any(c.args[0].lstrip().startswith('UPDATE') for c in cursor.execute.call_args_list)


def test_duplicate_resume_does_not_extend_attempts_again():
    job, stage = blocked_records()
    job['status'] = 'processing'
    store, cursor = transaction_store(job, [stage])
    assert store.resume_provider_block('any-job', expected_checkpoint_sha256=CHECKPOINT)['status'] == 'processing'
    assert not any(c.args[0].lstrip().startswith('UPDATE') for c in cursor.execute.call_args_list)
