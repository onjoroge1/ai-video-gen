"""Final-word timing/callback repair and exact-checkpoint recovery, without paid calls."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import anyio
import httpx
import pytest

import agent_actions
import app as studio
import db
import durable_execution as durable
import explainer_pipeline as pipeline
import illustrated_story as lane
import storyboard_repair as repair
from test_agent_actions import ACTION_ID, FakeActionRepository, _secure_environment
from test_illustrated_story import _script
from test_longform_research_phase2 import _dossier
from test_research_budget_restart import CHECKPOINT, transaction_store
from test_durable_execution_phase6 import MemoryBlob, MemoryStore, runtime
from test_durable_anthropic_response import Provider, payload

OPENING = "a cane toad sitting in a Queensland sugarcane furrow"
LIVE_ERROR = ("Illustrated storyboard failed: LATE_MECHANISM: the mechanism lands at 49s, "
              "past the 44s mark (20% of runtime); state the principle early and spend the rest "
              "of the video earning it; NO_CALLBACK: the closing step never returns to "
              f"'{OPENING}'; both reference closes come back to the thing the story opened on")


def words(text, count):
    return " ".join((text.split() * (count + 1))[:count])


def failed_script():
    script = _script()
    script['_story_contract']['opening_object'] = OPENING
    script['_research_dossier'] = _dossier()
    for scene, count in zip(script['scenes'], [50, 48, 43, 6, 50, 130, 130, 130, 45, 28]):
        scene['narration'] = words(scene['narration'], count)
    script['scenes'][-1]['narration'] = words('The lesson is to consider the consequences of every proposed solution.', 28)
    return script


def board(script):
    return lane.build_storyboard(copy.deepcopy(script), 'Why did this happen?')


def response_for(script):
    edit = repair.plan(script, board(script))
    by_id = {s['scene_id']: s for s in script['scenes']}
    updated = []
    for scene_id in edit['scene_ids']:
        index = next(i for i, s in enumerate(script['scenes']) if s['scene_id'] == scene_id)
        text = (words(by_id[scene_id]['narration'], [44, 40, 36, 6][index]) if index < 4
                else 'Return to ' + OPENING + '. ' + words('This image brings the lesson back to where this story began.', 27))
        updated.append({'scene_id': scene_id, 'narration': text})
    return {'scenes': updated}


def writer(monkeypatch, response):
    create = Mock(return_value=SimpleNamespace(
        content=[SimpleNamespace(text=json.dumps(response))],
        usage=SimpleNamespace(input_tokens=100, output_tokens=300)))
    monkeypatch.setattr(pipeline, '_claude', lambda: SimpleNamespace(messages=SimpleNamespace(create=create)))
    claims = Mock(return_value={'passed': True, 'errors': []})
    monkeypatch.setattr(pipeline, '_validate_claims', claims)
    return create, claims


def write_failure(root, script=None):
    script = script or failed_script()
    failure = {'schema_version': 1, 'stage': 'illustrated-storyboard', 'script': script,
               'research_dossier': script['_research_dossier'], 'operator_direction': '',
               'report': board(script)['validation']}
    (root / repair.FAILURE_FILE).write_text(json.dumps(failure))
    (root / '_state.json').write_text(json.dumps({'script': script, 'style_mode': 'educational'}))
    return failure


def write_budget_rejection(root, script=None):
    script = script or failed_script()
    failure = write_failure(root, script)
    prior = {
        'version': repair.VERSION,
        'status': 'rejected',
        'input_sha256': repair.digest(script),
        'input_script': script,
        'original_validation': failure['report'],
        'reason': repair.BUDGET_REJECTION_REASON,
        'rejection_code': 'EDIT_CONSTRAINT',
    }
    (root / repair.FILENAME).write_text(json.dumps(prior))
    return failure, prior


def budget_response_for(script):
    edit = repair.budget_plan(script, board(script))
    rows = []
    for scene_id in edit['scene_ids']:
        index = next(i for i, scene in enumerate(script['scenes'])
                     if scene['scene_id'] == scene_id)
        if index < edit['mechanism_index']:
            limit = edit['scene_word_limits'][scene_id]
            if index == 0:
                hook = script['hook']
                text = hook + ' ' + words('Roots were being eaten beneath the cane.', limit - len(hook.split()))
            else:
                text = words(script['scenes'][index]['narration'], limit)
        else:
            text = 'Return to ' + OPENING + '. ' + words(
                'The ending brings the lesson back to where the story began.', 30)
            original = len(script['scenes'][index]['narration'].split())
            text = words(text, original)
        rows.append({'scene_id': scene_id, 'narration': text})
    return {'scenes': rows}


def failed_job():
    return {'id': 'job-1', 'status': 'error', 'error': LIVE_ERROR, 'result': {},
            'checkpoint': {'sha256': CHECKPOINT}, 'attempts': 2, 'max_attempts': 5,
            'max_cost_usd': 10, 'spent_cost_usd': 3.1509, 'reserved_cost_usd': 0,
            'request': {'operator_direction': '', 'immutable': 'approved spec'}}


def test_live_error_is_reproduced_and_deadline_accounts_for_compression():
    script = failed_script()
    assert repair.PREFIX + '; '.join(board(script)['validation']['errors']) == LIVE_ERROR
    assert repair.repairable_failure(LIVE_ERROR)
    edit = repair.plan(script, board(script))
    assert edit['opening_word_limit'] == 127  # not 132 = 20% of the old 660-word draft
    out = repair.apply_response(script, edit, response_for(script))
    assert board(out)['validation']['passed']
    assert script['scenes'][0]['narration'] != out['scenes'][0]['narration']
    for original, revised in zip(script['scenes'][4:-1], out['scenes'][4:-1]):
        assert original == revised  # mechanism and body were not moved, padded or relabelled
    assert OPENING in out['scenes'][-1]['narration']


@pytest.mark.parametrize('change', ['unknown_scene', 'duplicate', 'extra_field', 'blank', 'still_late', 'no_callback', 'pad_close'])
def test_bad_edits_are_rejected(change):
    script = failed_script()
    response = response_for(script)
    if change == 'unknown_scene': response['scenes'][0]['scene_id'] = 'nope'
    if change == 'duplicate': response['scenes'].append(response['scenes'][0])
    if change == 'extra_field': response['scenes'][0]['causal_role'] = 'mechanism'
    if change == 'blank': response['scenes'][0]['narration'] = ''
    if change == 'still_late': response['scenes'][0]['narration'] += ' extra' * 20
    if change == 'no_callback': response['scenes'][-1]['narration'] = words('A generic lesson.', 40)
    if change == 'pad_close': response['scenes'][-1]['narration'] += ' padding' * 30
    with pytest.raises(ValueError):
        repair.apply_response(script, repair.plan(script, board(script)), response)


def test_repair_revalidates_sources_and_reuses_accepted_result(tmp_path, monkeypatch):
    script = failed_script()
    before = copy.deepcopy(script)
    create, claims = writer(monkeypatch, response_for(script))
    costs = []
    out, report = pipeline._repair_illustrated_storyboard(script, 'q', script['_research_dossier'], tmp_path, costs, lambda _: None)
    assert report['validation']['passed'] and script == before
    assert claims.call_count == 1 and len(costs) == 1
    checked = claims.call_args.args[0]
    assert OPENING in checked['scenes'][-1]['narration']
    again, report = pipeline._repair_illustrated_storyboard(script, 'q', script['_research_dossier'], tmp_path, costs, lambda _: None)
    assert again == out and create.call_count == 1 and claims.call_count == 1
    assert json.loads((tmp_path / repair.FILENAME).read_text())['status'] == 'accepted'


@pytest.mark.parametrize('kind', ['sources', 'late', 'invalid_json'])
def test_rejected_repair_retains_failure_and_is_not_repurchased(tmp_path, monkeypatch, kind):
    script = failed_script()
    response = response_for(script)
    if kind == 'late': response['scenes'][0]['narration'] += ' extra' * 30
    create, claims = writer(monkeypatch, response)
    if kind == 'sources': claims.return_value = {'passed': False, 'errors': [{'code': 'UNSUPPORTED'}]}
    if kind == 'invalid_json': create.return_value.content[0].text = 'broken JSON'
    for _ in range(2):
        out, report = pipeline._repair_illustrated_storyboard(copy.deepcopy(script), 'q', script['_research_dossier'], tmp_path, [], lambda _: None)
        assert out == script and not report['validation']['passed']
    assert create.call_count == 1
    saved = json.loads((tmp_path / repair.FILENAME).read_text())
    assert saved['status'] == 'rejected'
    assert saved['rejection_code'] == {'sources': 'SOURCE_VALIDATION', 'late': 'EDIT_CONSTRAINT',
                                       'invalid_json': 'JSON_PARSE'}[kind]
    assert saved['provider_response_text'] == create.return_value.content[0].text
    assert ('candidate_script' in saved) == (kind == 'sources')
    assert repair.rejection_summary(tmp_path)


def test_public_rejection_summary_never_exposes_private_response_or_exception(tmp_path):
    for code in [*repair.REJECTION_SUMMARIES, 'token=secret-private-value']:
        (tmp_path / repair.FILENAME).write_text(json.dumps({
            'status': 'rejected', 'rejection_code': code, 'reason': 'password=secret-private-value',
            'provider_response_text': 'secret-private-value'}))
        summary = repair.rejection_summary(tmp_path)
        assert summary and 'secret-private-value' not in summary
    for content in ['not json', '[]', '{"status":"accepted"}']:
        (tmp_path / repair.FILENAME).write_text(content)
        assert not repair.rejection_summary(tmp_path)


def test_other_gates_and_passed_scripts_do_not_buy_an_edit(tmp_path, monkeypatch):
    create, _ = writer(monkeypatch, {})
    for script in (_script(), failed_script()):
        if script['_story_contract']['opening_object'] == OPENING:
            script['scenes'][2]['caused_by'] = 'missing'
        pipeline._repair_illustrated_storyboard(script, 'q', {}, tmp_path, [], lambda _: None)
    assert not create.called and not (tmp_path / repair.FILENAME).exists()


def test_interruption_after_paid_response_replays_that_stage(tmp_path, monkeypatch):
    script = failed_script()
    _, claims = writer(monkeypatch, {})
    provider = Provider(payload(text=json.dumps(response_for(script))))
    store, blob = MemoryStore(cap=10), MemoryBlob(tmp_path / 'blob')
    first = runtime(tmp_path, store, blob, 'first')
    (Path(first.output_dir) / '_state.json').write_text(json.dumps({'script': script}))
    monkeypatch.setattr(pipeline, '_claude', lambda: first.wrap_anthropic(provider))
    claims.side_effect = durable.CooperativeYield('source validation')
    with durable.activate(first), pytest.raises(durable.CooperativeYield):
        pipeline._repair_illustrated_storyboard(script, 'q', script['_research_dossier'], first.output_dir, [], lambda _: None)
    assert len(provider.calls) == 1
    checkpoint = first.checkpoint('yield')
    replacement = runtime(tmp_path, store, blob, 'replacement')
    replacement.restore_checkpoint(checkpoint)
    monkeypatch.setattr(pipeline, '_claude', lambda: replacement.wrap_anthropic(provider))
    claims.side_effect = None
    with durable.activate(replacement):
        out, report = pipeline._repair_illustrated_storyboard(script, 'q', script['_research_dossier'], replacement.output_dir, [], lambda _: None)
    assert report['validation']['passed'] and len(provider.calls) == 1
    assert store.job['reserved_cost_usd'] == 0


def test_saved_failure_is_reproduced_before_recovery(tmp_path):
    write_failure(tmp_path)
    saved = repair.inspect_saved_failure(tmp_path, LIVE_ERROR, '')
    assert saved and saved['script'] == failed_script()


def test_budget_retry_has_hard_scene_caps_that_sum_to_the_deadline():
    script = failed_script()
    edit = repair.budget_plan(script, board(script))
    assert sum(edit['scene_word_limits'].values()) == edit['opening_word_limit']
    candidate = repair.apply_response(script, edit, budget_response_for(script))
    assert board(candidate)['validation']['passed']
    for scene in candidate['scenes'][:edit['mechanism_index']]:
        assert len(scene['narration'].split()) <= edit['scene_word_limits'][scene['scene_id']]


def test_saved_budget_rejection_is_reproduced_before_second_recovery(tmp_path):
    failure, prior = write_budget_rejection(tmp_path)
    saved = repair.inspect_saved_budget_rejection(tmp_path, LIVE_ERROR, '')
    assert saved and saved['script'] == failed_script()
    assert saved['failure_sha256'] == repair.digest(failure)
    assert saved['prior_repair_sha256'] == repair.digest(prior)
    (tmp_path / repair.BUDGET_FILENAME).write_text('{}')
    assert repair.inspect_saved_budget_rejection(tmp_path, LIVE_ERROR, '') is None


def test_budget_retry_requires_exact_rearm_marker_and_replays_once(tmp_path, monkeypatch):
    script = failed_script()
    failure, prior = write_budget_rejection(tmp_path, script)
    create, claims = writer(monkeypatch, budget_response_for(script))
    store, blob = MemoryStore(cap=10), MemoryBlob(tmp_path / 'blob')
    store.get_job = lambda _: store.job
    worker = runtime(tmp_path, store, blob, 'budget-worker')
    # Put the saved archive in the worker directory used by the active runtime.
    write_budget_rejection(Path(worker.output_dir), script)
    marker = {
        'failure_sha256': repair.digest(failure),
        'prior_repair_sha256': repair.digest(prior),
    }
    store.job['result'] = {durable.STORYBOARD_BUDGET_RECOVERY: marker}
    with durable.activate(worker):
        out, report = pipeline._repair_illustrated_storyboard(
            script, 'q', script['_research_dossier'], worker.output_dir, [], lambda _: None)
        again, _ = pipeline._repair_illustrated_storyboard(
            script, 'q', script['_research_dossier'], worker.output_dir, [], lambda _: None)
    assert report['validation']['passed'] and again == out
    assert repair.BUDGET_VERSION in out and repair.VERSION not in out
    assert create.call_count == 1 and claims.call_count == 1
    assert json.loads((Path(worker.output_dir) / repair.BUDGET_FILENAME).read_text())['status'] == 'accepted'


def test_budget_retry_without_exact_marker_never_calls_provider(tmp_path, monkeypatch):
    script = failed_script()
    write_budget_rejection(tmp_path, script)
    create, _ = writer(monkeypatch, budget_response_for(script))
    out, report = pipeline._repair_illustrated_storyboard(
        script, 'q', script['_research_dossier'], tmp_path, [], lambda _: None)
    assert out == script and not report['validation']['passed'] and not create.called


def test_server_inspects_the_actual_durable_archive_before_rearming(tmp_path):
    store, blob = MemoryStore(cap=10), MemoryBlob(tmp_path / 'blob')
    worker = runtime(tmp_path, store, blob, 'saved')
    write_failure(Path(worker.output_dir))
    checkpoint = worker.checkpoint('semantic-failure-illustrated-storyboard')
    job = {**failed_job(), 'checkpoint': checkpoint}
    result = studio._storyboard_checkpoint_repairable(job, store, blob)
    assert result and len(result['failure_sha256']) == 64
    job['error'] += '; NO_RUNTIME: missing'
    assert studio._storyboard_checkpoint_repairable(job, store, blob) is None
    assert store.job['spent_cost_usd'] == 0 and not store.stages


def test_server_inspects_saved_v1_budget_rejection_before_rearming(tmp_path):
    store, blob = MemoryStore(cap=10), MemoryBlob(tmp_path / 'blob')
    worker = runtime(tmp_path, store, blob, 'saved-budget-rejection')
    failure, prior = write_budget_rejection(Path(worker.output_dir))
    checkpoint = worker.checkpoint('storyboard-repair-rejected')
    job = {**failed_job(), 'checkpoint': checkpoint}
    job['result'][durable.STORYBOARD_RECOVERY] = {
        'failure_sha256': repair.digest(failure)}
    result = studio._storyboard_budget_checkpoint_repairable(job, store, blob)
    assert result == {'failure_sha256': repair.digest(failure),
                      'prior_repair_sha256': repair.digest(prior)}
    assert store.job['spent_cost_usd'] == 0 and not store.stages


def test_paid_edit_still_obeys_the_job_budget(tmp_path, monkeypatch):
    script = failed_script()
    provider = Provider(payload(text=json.dumps(response_for(script))))
    store, blob = MemoryStore(cap=.001), MemoryBlob(tmp_path / 'blob')
    worker = runtime(tmp_path, store, blob, 'over_budget')
    monkeypatch.setattr(pipeline, '_claude', lambda: worker.wrap_anthropic(provider))
    with durable.activate(worker), pytest.raises(durable.BudgetExceeded):
        pipeline._repair_illustrated_storyboard(script, 'q', script['_research_dossier'], worker.output_dir, [], lambda _: None)
    assert not provider.calls and not store.stages


def test_concurrent_dispatch_cannot_grant_a_second_retry():
    job = {**failed_job(), 'status': 'processing'}
    store, cursor = transaction_store(job)
    assert store.resume_storyboard_failure('job-1', expected_checkpoint_sha256=CHECKPOINT,
                                          expected_error=LIVE_ERROR, failure_sha256='b' * 64) == job
    assert not any(c.args[0].lstrip().startswith('UPDATE') for c in cursor.execute.call_args_list)


def test_resume_pipeline_repairs_saved_draft_without_research_or_regeneration(tmp_path, monkeypatch):
    script = failed_script()
    write_failure(tmp_path, script)
    create, _ = writer(monkeypatch, response_for(script))
    monkeypatch.setattr(pipeline, 'generate_research_dossier', Mock(side_effect=AssertionError('research repurchased')))
    monkeypatch.setattr(pipeline, 'generate_graded_script', Mock(side_effect=AssertionError('script regenerated')))
    class ReachedNextGate(Exception):
        pass
    def next_gate(candidate, question):
        assert board(candidate)['validation']['passed']
        assert OPENING in candidate['scenes'][-1]['narration']
        raise ReachedNextGate
    monkeypatch.setattr(pipeline, 'validate_longform_story', next_gate)
    monkeypatch.setenv('RUNTIME_HARD', '0')
    with pytest.raises(ReachedNextGate):
        pipeline.run_explainer_pipeline('Why did this happen?', str(tmp_path), duration_sec=300,
                                       visual_style='illustrated_story', resume=True, max_cost_usd=10)
    saved = json.loads((tmp_path / '_state.json').read_text())['script']
    assert repair.VERSION in saved and board(saved)['validation']['passed']
    assert create.call_count == 1


def test_failed_resume_reports_repair_rejection_and_keeps_original_gate(tmp_path, monkeypatch):
    script = failed_script()
    write_failure(tmp_path, script)
    create, _ = writer(monkeypatch, response_for(script))
    create.return_value.content[0].text = 'not JSON: private provider response'
    monkeypatch.setenv('RUNTIME_HARD', '0')
    monkeypatch.setenv('ILLUSTRATED_STORYBOARD_HARD', '1')
    for _ in range(2):
        with pytest.raises(ValueError) as exc:
            pipeline.run_explainer_pipeline('Why did this happen?', str(tmp_path), duration_sec=300,
                                           visual_style='illustrated_story', resume=True, max_cost_usd=10)
        message = str(exc.value)
        assert message.startswith('Illustrated storyboard failed: The repair response could not be parsed as JSON.')
        assert 'LATE_MECHANISM' in message and 'NO_CALLBACK' in message
        assert 'private provider response' not in message
    assert create.call_count == 1


def test_existing_media_blocks_a_narration_repair(tmp_path, monkeypatch):
    script = failed_script()
    create, _ = writer(monkeypatch, response_for(script))
    (tmp_path / 'audio').mkdir()
    (tmp_path / 'audio' / 'scene.mp3').write_bytes(b'paid audio')
    out, report = pipeline._repair_illustrated_storyboard(script, 'q', {}, tmp_path, [], lambda _: None)
    assert not create.called and out == script and not report['validation']['passed']


@pytest.mark.parametrize('change', ['error', 'direction', 'dossier', 'report', 'state', 'media', 'used'])
def test_changed_or_already_attempted_checkpoint_cannot_rearm(tmp_path, change):
    failure = write_failure(tmp_path)
    error, direction = LIVE_ERROR, ''
    if change == 'error': error += '; ANOTHER_FAILURE: no'
    if change == 'direction': direction = 'changed'
    if change == 'dossier': failure['research_dossier'] = {'claims': []}
    if change == 'report': failure['report']['errors'] = ['NO_CALLBACK: invented']
    if change == 'state': (tmp_path / '_state.json').write_text('{}')
    if change == 'media': (tmp_path / 'audio').mkdir(); (tmp_path / 'audio' / 'scene.mp3').write_bytes(b'media')
    if change == 'used': (tmp_path / repair.FILENAME).write_text('{}')
    (tmp_path / repair.FAILURE_FILE).write_text(json.dumps(failure))
    assert repair.inspect_saved_failure(tmp_path, error, direction) is None


def test_transaction_preserves_all_spend_limits_and_paid_stages():
    job = failed_job()
    store, cursor = transaction_store(job)
    store.resume_storyboard_failure('job-1', expected_checkpoint_sha256=CHECKPOINT,
                                   expected_error=LIVE_ERROR, failure_sha256='b' * 64)
    updates = [c.args for c in cursor.execute.call_args_list if c.args[0].lstrip().startswith('UPDATE')]
    assert len(updates) == 1
    sql, params = updates[0]
    assert 'cost_usd=' not in sql and 'request=' not in sql and 'generation_stages' not in sql
    assert json.loads(params[0])[durable.STORYBOARD_RECOVERY]['prior_error'] == LIVE_ERROR


def test_budget_recovery_transaction_binds_both_saved_hashes():
    job = failed_job()
    job['result'][durable.STORYBOARD_RECOVERY] = {
        # The final failure record gets a new failed_at timestamp after v1 rejects; the
        # current checkpoint hash/report, not this earlier diagnostic hash, is authoritative.
        'failure_sha256': 'd' * 64, 'checkpoint_sha256': CHECKPOINT}
    store, cursor = transaction_store(job)
    store.resume_storyboard_budget_failure(
        'job-1', expected_checkpoint_sha256=CHECKPOINT, expected_error=LIVE_ERROR,
        failure_sha256='b' * 64, prior_repair_sha256='c' * 64)
    updates = [c.args for c in cursor.execute.call_args_list
               if c.args[0].lstrip().startswith('UPDATE')]
    assert len(updates) == 1
    sql, params = updates[0]
    marker = json.loads(params[0])[durable.STORYBOARD_BUDGET_RECOVERY]
    assert marker['failure_sha256'] == 'b' * 64
    assert marker['prior_repair_sha256'] == 'c' * 64
    assert 'cost_usd=' not in sql and 'request=' not in sql


@pytest.mark.parametrize('change', ['lease', 'reservation', 'budget', 'checkpoint', 'used', 'other_error', 'paid_unknown', 'changed_error'])
def test_unsafe_recovery_never_writes(change):
    job, stages, expected = failed_job(), [], LIVE_ERROR
    if change == 'lease': job['lease_owner'] = 'worker'
    if change == 'reservation': job['reserved_cost_usd'] = .1
    if change == 'budget': job['spent_cost_usd'] = 10
    if change == 'checkpoint': job['checkpoint']['sha256'] = 'c' * 64
    if change == 'used': job['result'][durable.STORYBOARD_RECOVERY] = {'used': True}
    if change == 'other_error': job['error'] += '; SOFT_HINGE: wrong'
    if change == 'paid_unknown': stages = [{'status': 'running'}]
    if change == 'changed_error': expected = 'Illustrated storyboard failed: NO_CALLBACK: different'
    store, cursor = transaction_store(job, stages)
    with pytest.raises(durable.DurableExecutionError):
        store.resume_storyboard_failure('job-1', expected_checkpoint_sha256=CHECKPOINT,
                                       expected_error=expected, failure_sha256='b' * 64)
    assert not any(c.args[0].lstrip().startswith('UPDATE') for c in cursor.execute.call_args_list)


@pytest.mark.parametrize('saved_ok', [True, False])
def test_dispatch_checks_private_checkpoint_and_uses_same_approval(monkeypatch, saved_ok):
    _secure_environment(monkeypatch)
    repository = FakeActionRepository()
    repository.action = {'action_id': ACTION_ID, 'operation': 'generic_illustrated',
                         'status': 'queued', 'job_id': 'job-1', 'cost_ceiling_usd': 10,
                         'claim_token_sha256': agent_actions.token_digest(ACTION_ID),
                         'spec_sha256': 'd' * 64}
    job = failed_job()
    store = Mock()
    store.get_job.return_value = job
    store.events.return_value = []
    monkeypatch.setattr(agent_actions, 'repository', lambda: repository)
    monkeypatch.setattr(studio, '_durable_execution_required', lambda: True)
    monkeypatch.setattr(studio, '_durable_components', lambda: (store, Mock()))
    monkeypatch.setattr(db, 'finished_video_get', lambda _: None)
    inspect = Mock(return_value={'failure_sha256': 'b' * 64} if saved_ok else None)
    monkeypatch.setattr(studio, '_storyboard_checkpoint_repairable', inspect)
    dispatched = []
    async def worker(job_id):
        dispatched.append(job_id)
        return {'claimed': True}
    monkeypatch.setattr(studio, '_run_durable_explainer_worker', worker)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app), base_url='https://test') as client:
            status = (await client.get(f'/api/agent/actions/{ACTION_ID}/public-status')).json()
            assert status['job']['restart']['kind'] == 'storyboard_repair'
            assert CHECKPOINT not in json.dumps(status)
            denied = await client.post(f'/api/agent/actions/{ACTION_ID}/dispatch')
            assert denied.status_code == 403 and not inspect.called
            result = await client.post(f'/api/agent/actions/{ACTION_ID}/dispatch', headers={'Authorization': f'Bearer {ACTION_ID}'})
            assert result.status_code == (200 if saved_ok else 409), result.text
    anyio.run(run)
    assert store.resume_storyboard_failure.call_count == int(saved_ok)
    assert dispatched == (['job-1'] if saved_ok else [])


def test_dispatch_checks_private_budget_rejection_and_uses_same_approval(monkeypatch):
    _secure_environment(monkeypatch)
    repository = FakeActionRepository()
    repository.action = {'action_id': ACTION_ID, 'operation': 'generic_illustrated',
                         'status': 'queued', 'job_id': 'job-1', 'cost_ceiling_usd': 10,
                         'claim_token_sha256': agent_actions.token_digest(ACTION_ID),
                         'spec_sha256': 'd' * 64}
    job = failed_job()
    job['result'][durable.STORYBOARD_RECOVERY] = {
        'failure_sha256': 'b' * 64, 'checkpoint_sha256': CHECKPOINT}
    store = Mock()
    store.get_job.return_value = job
    store.events.return_value = []
    monkeypatch.setattr(agent_actions, 'repository', lambda: repository)
    monkeypatch.setattr(studio, '_durable_execution_required', lambda: True)
    monkeypatch.setattr(studio, '_durable_components', lambda: (store, Mock()))
    monkeypatch.setattr(db, 'finished_video_get', lambda _: None)
    monkeypatch.setattr(studio, '_storyboard_budget_checkpoint_repairable', lambda *_: {
        'failure_sha256': 'b' * 64, 'prior_repair_sha256': 'c' * 64})
    dispatched = []
    async def worker(job_id):
        dispatched.append(job_id)
        return {'claimed': True}
    monkeypatch.setattr(studio, '_run_durable_explainer_worker', worker)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app),
                                     base_url='https://test') as client:
            status = (await client.get(
                f'/api/agent/actions/{ACTION_ID}/public-status')).json()
            assert status['job']['restart']['kind'] == 'storyboard_opening_budget'
            response = await client.post(
                f'/api/agent/actions/{ACTION_ID}/dispatch',
                headers={'Authorization': f'Bearer {ACTION_ID}'})
            assert response.status_code == 200, response.text
    anyio.run(run)
    store.resume_storyboard_budget_failure.assert_called_once_with(
        'job-1', expected_checkpoint_sha256=CHECKPOINT, expected_error=LIVE_ERROR,
        failure_sha256='b' * 64, prior_repair_sha256='c' * 64)
    assert dispatched == ['job-1']
