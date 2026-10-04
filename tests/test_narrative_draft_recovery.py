"""Paid-provider fakes verify boundaries, not creativity or real-world facts."""
from copy import deepcopy
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

import durable_execution as durable
import explainer_pipeline as ep
import narrative_template as nt
from test_narrative_template import inputs, draft
from test_durable_execution_phase6 import MemoryStore, MemoryBlob, runtime
from test_durable_anthropic_response import Provider, payload


def response(value):
    return NS(content=[NS(type='tool_use', name=nt.DRAFT_TOOL, input=value)],
              stop_reason='tool_use', usage=NS(input_tokens=100, output_tokens=200))


def provider(monkeypatch, *values):
    create = Mock(side_effect=[response(v) for v in values])
    monkeypatch.setattr(ep, '_claude', lambda: NS(messages=NS(create=create)))
    return create


def run():
    return nt.generate(*inputs(), 'removed_keystone', 'q', 180, 450)


def bad_outline():
    value = draft(inputs()[1])
    value['outline'][2]['section'] = 'the_proposed_fix'
    value['outline'][4]['claim_ids'] = ['invented']
    value['outline'][6]['new_contribution'] = ''
    return value


def test_field_errors_identify_all_bad_fields_without_leaking_values():
    value = bad_outline()
    evidence = nt.brief(*inputs(), 'removed_keystone')
    with pytest.raises(nt.DraftValidationError) as caught:
        nt.validate_draft(value, evidence)
    assert {i['path'] for i in caught.value.issues} == {
        'outline[2].section', 'outline[4].claim_ids[0]', 'outline[6].new_contribution'}
    assert 'invented' not in str(caught.value)
    assert 'Expected proposed_fix' in str(caught.value)


@pytest.mark.parametrize('value', [None, [], {}, {'paragraphs':[None, {'narration':42}],
    'outline':[None, {'section':[], 'claim_ids':[{}]}], 'hook_candidates':[{}, None, []], 'selected_hook':[]}])
def test_malformed_field_types_produce_diagnostics_not_parser_crashes(value):
    assert nt.draft_issues(value, nt.brief(*inputs(), 'removed_keystone'))


def test_one_repair_uses_accepted_evidence_and_keeps_both_drafts(tmp_path, monkeypatch):
    worker = NS(output_dir=str(tmp_path), checkpoint=Mock())
    monkeypatch.setattr(durable, 'current', lambda: worker)
    initial, fixed = bad_outline(), draft(inputs()[1])
    create = provider(monkeypatch, initial, fixed)
    script = run()
    assert create.call_count == 2
    report = json.loads((tmp_path / nt.DRAFT_REPORT).read_text())
    assert report['status'] == 'accepted' and report['approval'] == 'not_evaluated'
    assert [a['candidate'] for a in report['attempts']] == [initial, fixed]
    assert report['attempts'][0]['issues'] and report['attempts'][1]['issues'] == []
    assert script['_script_cost_usd'] == pytest.approx(sum(a['cost_usd'] for a in report['attempts']))
    repair = create.call_args.kwargs
    assert 'ONE BOUNDED CONTRACT REPAIR' in repair['messages'][0]['content']
    assert 'locked_paragraphs' in repair['messages'][0]['content']
    assert repair['tool_choice']['name'] == nt.DRAFT_TOOL
    properties = repair['tools'][0]['input_schema']['properties']
    assert properties['outline']['items']['properties']['section']['enum'] == [s for s, _ in nt.SECTIONS]
    assert report['accepted_plan'] == inputs()[0]
    assert '_script_readiness' not in script
    assert run() == script and create.call_count == 2


def test_failed_repair_is_terminal_after_worker_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(durable, 'current', lambda: NS(output_dir=str(tmp_path), checkpoint=Mock()))
    create = provider(monkeypatch, bad_outline(), bad_outline())
    for _ in range(2):
        with pytest.raises(nt.DraftValidationError, match=r'outline\[2\].section'):
            run()
    assert create.call_count == 2
    report = json.loads((tmp_path / nt.DRAFT_REPORT).read_text())
    assert report['status'] == 'failed' and len(report['attempts']) == 2


def test_metadata_repair_cannot_rewrite_valid_narration(monkeypatch):
    fixed = draft(inputs()[1])
    fixed['paragraphs'][4]['narration'] = 'The hunters chased a different animal.'
    create = provider(monkeypatch, bad_outline(), fixed)
    with pytest.raises(nt.DraftValidationError, match=r'REPAIR_CHANGED at paragraphs\[4\].narration'):
        run()
    assert create.call_count == 2


def test_reported_evidence_gap_does_not_buy_a_cosmetic_repair(tmp_path, monkeypatch):
    monkeypatch.setattr(durable, 'current', lambda: NS(output_dir=str(tmp_path), checkpoint=Mock()))
    value = draft(inputs()[1]); value['evidence_gaps'] = ['Missing outcome evidence']
    create = provider(monkeypatch, value)
    with pytest.raises(nt.DraftValidationError, match='EVIDENCE_GAP'):
        run()
    assert create.call_count == 1
    report = json.loads((tmp_path / nt.DRAFT_REPORT).read_text())
    assert report['attempts'][0]['candidate']['evidence_gaps'] == ['Missing outcome evidence']


def test_missing_gap_field_is_repairable_but_does_not_change_prose(monkeypatch):
    value = draft(inputs()[1]); value.pop('evidence_gaps')
    create = provider(monkeypatch, value, draft(inputs()[1]))
    run()
    assert create.call_count == 2


def test_unparseable_output_is_preserved_before_repair(tmp_path, monkeypatch):
    monkeypatch.setattr(durable, 'current', lambda: NS(output_dir=str(tmp_path), checkpoint=Mock()))
    raw = NS(content=[NS(type='text', text='{"outline": [')], stop_reason='max_tokens',
             usage=NS(input_tokens=100, output_tokens=200))
    create = Mock(side_effect=[raw, response(draft(inputs()[1]))])
    monkeypatch.setattr(ep, '_claude', lambda: NS(messages=NS(create=create)))
    run()
    attempt = json.loads((tmp_path / nt.DRAFT_REPORT).read_text())['attempts'][0]
    assert attempt['candidate'] is None and attempt['stop_reason'] == 'max_tokens'
    assert attempt['response'] == [{'type':'text', 'text':'{"outline": ['}]
    assert attempt['issues'][0]['path'] == '$'


@pytest.mark.parametrize('failure', [durable.BudgetExceeded, durable.LeaseLost, durable.StorageUnavailable])
def test_operational_failure_keeps_rejected_draft_and_does_not_consume_new_attempt(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(durable, 'current', lambda: NS(output_dir=str(tmp_path), checkpoint=Mock()))
    create = Mock(side_effect=[response(bad_outline()), failure('stop')])
    monkeypatch.setattr(ep, '_claude', lambda: NS(messages=NS(create=create)))
    with pytest.raises(failure): run()
    report = json.loads((tmp_path / nt.DRAFT_REPORT).read_text())
    assert report['status'] == 'repair_pending' and len(report['attempts']) == 1
    assert report['attempts'][0]['candidate'] == bad_outline()


@pytest.mark.parametrize('yield_after_attempt', [0, 1, 2, 'before_record'])
def test_real_checkpoint_and_provider_replay_never_rebuy_attempts(tmp_path, monkeypatch, yield_after_attempt):
    class Yield(BaseException): pass
    store, blob = MemoryStore(cap=10), MemoryBlob(tmp_path / 'blob')
    first, second = runtime(tmp_path, store, blob, 'first'), runtime(tmp_path, store, blob, 'second')
    raws = []
    for value in [bad_outline(), draft(inputs()[1])]:
        raw = payload(); raw['stop_reason'] = 'tool_use'
        raw['content'] = [{'type':'tool_use', 'id':'fixture', 'name':nt.DRAFT_TOOL, 'input':value}]
        raws.append(raw)
    paid = Provider(*raws)
    saved = first.checkpoint
    def checkpoint(label):
        saved(label)
        if label == 'script-stage-seven-section-draft-progress':
            report = json.loads((__import__('pathlib').Path(first.output_dir) / nt.DRAFT_REPORT).read_text())
            if len(report['attempts']) == yield_after_attempt: raise Yield()
    monkeypatch.setattr(first, 'checkpoint', checkpoint)
    save_progress = nt._save_draft_state
    def save_state(inputs, state, plan, evidence):
        if (yield_after_attempt == 'before_record' and durable.current() is first
                and len(state['attempts']) == 1):
            raise Yield()
        return save_progress(inputs, state, plan, evidence)
    monkeypatch.setattr(nt, '_save_draft_state', save_state)
    def generate(worker):
        monkeypatch.setattr(ep, '_claude', lambda: worker.wrap_anthropic(paid))
        with durable.activate(worker): return run()
    with pytest.raises(Yield): generate(first)
    second.restore_checkpoint(store.job['checkpoint'])
    script = generate(second)
    assert generate(second) == script and len(paid.calls) == 2
    assert store.job['spent_cost_usd'] > 0 and store.job['reserved_cost_usd'] == 0
