import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
import studio_jobs
from test_durable_execution_phase6 import MemoryStore, MemoryBlob, runtime


def test_snapshot_status_does_not_equate_saved_script_with_pass():
    for status in ('error', 'provider_blocked', 'awaiting_script_approval', 'storage_error'):
        result = studio_jobs.snapshot({'id':'job-1', 'status':status,
            'request':{'question':'topic', 'secret':'private'},
            'checkpoint':{'sha256':'abc', 'url':'private-blob'},
            'result':{'script':{'title':'ungraded'}}},
            [{'seq':1,'event_type':'error','data':'failed'}])
        assert result['status'] == status and not result['active']
        assert result['events'][0]['seq'] == 1
        assert 'private' not in json.dumps(result)
    assert studio_jobs.snapshot({'id':'job-1','status':'queued'}, [])['active']


def test_artifacts_restore_latest_checkpoint_without_provider_calls(tmp_path, monkeypatch):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / 'blob')
    worker = runtime(tmp_path, store, blob, 'writer')
    root = Path(worker.output_dir)
    monkeypatch.setattr(studio_jobs.durable_execution.DurableRuntime, 'paid_value',
                        Mock(side_effect=AssertionError('read must never spend')))
    monkeypatch.setattr(store, 'get_job', lambda job_id: store.job, raising=False)
    for title in ('first draft', 'repaired draft'):
        (root / '_state.json').write_text(json.dumps({'script': {'title': title}}))
        (root / 'claim_ledger_report.json').write_text('{"passed":false}')
        checkpoint = worker.checkpoint(title)
        store.job['checkpoint'] = checkpoint
        saved = studio_jobs.artifacts('job-1', store, blob)
        assert saved['script']['title'] == title
        assert saved['checkpoint_sha256'] == checkpoint['sha256']
        assert saved['reports']['claims']['passed'] is False


def test_artifact_reader_handles_missing_and_corrupt_saved_files(tmp_path, monkeypatch):
    directories = []
    class Reader:
        def __init__(self, **kwargs):
            self.directory = Path(kwargs['output_dir']); directories.append(self.directory)
        def restore_checkpoint(self, checkpoint):
            (self.directory / '_state.json').write_text('{broken')
    monkeypatch.setattr(studio_jobs.durable_execution, 'DurableRuntime', Reader)
    store = Mock(get_job=Mock(return_value={'checkpoint': {'sha256':'abc'}}))
    result = studio_jobs.artifacts('job-1', store, Mock())
    assert result['script'] is None and result['unavailable'] == ['script']
    assert all(not d.exists() for d in directories)
    store.get_job.return_value = None
    with pytest.raises(HTTPException) as error:
        studio_jobs.artifacts('missing', store, Mock())
    assert error.value.status_code == 404


def test_rejected_narration_is_private_diagnostic_not_an_approved_script(tmp_path, monkeypatch):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / 'blob')
    worker = runtime(tmp_path, store, blob, 'writer')
    report = {'status': 'failed', 'attempts': [
        {'candidate': {'paragraphs': [{'narration': 'Rejected prose.'}]},
         'issues': [{'path': 'outline[2].section', 'code': 'SEVEN_SECTION_OUTLINE'}]}]}
    (Path(worker.output_dir) / 'seven_section_draft.json').write_text(json.dumps(report))
    store.job['checkpoint'] = worker.checkpoint('draft-failed')
    store.job['status'] = 'error'
    monkeypatch.setattr(store, 'get_job', lambda _: store.job, raising=False)
    monkeypatch.setattr(studio_jobs.durable_execution.DurableRuntime, 'paid_value',
                        Mock(side_effect=AssertionError('read must never spend')))
    saved = studio_jobs.artifacts('job-1', store, blob)
    assert saved['reports']['narrative_draft'] == report
    assert saved['script'] is None
    assert not saved.get('approval_current') and 'content_sha256' not in saved


def test_routes_are_private_and_snapshot_does_not_restore_or_dispatch(monkeypatch):
    import asyncio
    import httpx
    import app as web
    import private_access
    # Exercise route/auth contracts without this runner's stalled thread wakeups.
    async def inline_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr(web.asyncio, 'to_thread', inline_thread)
    monkeypatch.setenv('APP_USERNAME', 'owner')
    monkeypatch.setenv('APP_PASSWORD', 'test-password')
    monkeypatch.setenv('APP_SESSION_SECRET', 'test-session-secret')
    store = Mock()
    store.get_job.return_value = {'id':'job-1','status':'error','error':'gate failed'}
    store.events.return_value = [{'seq':8,'event_type':'error','data':'gate failed'}]
    monkeypatch.setattr(web, '_durable_execution_required', lambda: True)
    monkeypatch.setattr(web, '_durable_components', lambda: (store, Mock()))
    monkeypatch.setattr(web, '_run_durable_explainer_worker', Mock(side_effect=AssertionError('no dispatch')))
    from fastapi import FastAPI
    test_app = FastAPI()
    test_app.add_middleware(private_access.PrivateAccessMiddleware)
    test_app.add_api_route('/api/studio/jobs/{job_id}', web.studio_job_snapshot)
    test_app.add_api_route('/api/studio/jobs/{job_id}/artifacts', web.studio_job_artifacts)
    test_app.add_api_route('/studio/jobs/{job_id}', web.studio_job_page)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url='http://test') as client:
            assert (await client.get('/api/studio/jobs/job-1')).status_code == 401
            assert (await client.get('/api/studio/jobs/job-1/artifacts')).status_code == 401
            assert (await client.get('/studio/jobs/job-1', headers={'accept':'text/html'})).status_code == 303
            client.cookies.set(private_access.COOKIE_NAME, private_access.create_session('owner'))
            response = await client.get('/api/studio/jobs/job-1?after=7')
            assert response.status_code == 200
            assert response.json()['error'] == 'gate failed'
            assert response.headers['cache-control'] == 'no-store'
            store.events.assert_called_once_with('job-1', 7, 500)
            page = await web.studio_job_page('job-1')
            assert Path(page.path).name == 'studio-job.html'
            store.get_job.return_value = None
            assert (await client.get('/api/studio/jobs/missing')).status_code == 404
    asyncio.run(run())


def test_input_repairs_are_visible_without_conferring_approval(tmp_path, monkeypatch):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / 'blob')
    worker = runtime(tmp_path, store, blob, 'writer')
    script = {'title': 'Unapproved repaired input', 'scenes': [],
        '_context_migration': {'version': 'test', 'changes': []},
        '_numerical_resolution': {'version': 'test', 'changes': []}}
    (Path(worker.output_dir) / '_state.json').write_text(json.dumps({'script': script}))
    store.job['checkpoint'] = worker.checkpoint('repaired-input')
    store.job['status'] = 'error'
    monkeypatch.setattr(store, 'get_job', lambda _: store.job, raising=False)
    monkeypatch.setattr(studio_jobs.durable_execution.DurableRuntime, 'paid_value',
                        Mock(side_effect=AssertionError('read must never spend')))
    saved = studio_jobs.artifacts('job-1', store, blob)
    assert saved['reports']['input_repairs'] == {
        k: script[k] for k in ('_context_migration', '_numerical_resolution')}
    assert saved['approval_current'] is False
    assert store.job['status'] == 'error'
