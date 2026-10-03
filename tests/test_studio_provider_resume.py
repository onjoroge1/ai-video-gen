import asyncio
from copy import deepcopy
from unittest.mock import Mock

import httpx
from fastapi import FastAPI

import app as web
import private_access
import studio_jobs
from test_provider_blocks import blocked_records, CHECKPOINT


def test_processing_keeps_polling_and_only_eligible_jobs_offer_resume():
    assert studio_jobs.snapshot({'id':'j','status':'processing'}, [])['active']
    job, _ = blocked_records()
    job['kind'] = 'explainer'
    assert studio_jobs.snapshot(job, [])['provider_resumable']
    for field, value in [('kind','explainer_pilot'), ('status','done'), ('checkpoint',{})]:
        assert not studio_jobs.snapshot({**job, field:value}, [])['provider_resumable']


def test_authenticated_checkpoint_bound_resume_preserves_recipe_and_cap(monkeypatch):
    async def inline(fn, *args, **kwargs): return fn(*args, **kwargs)
    monkeypatch.setattr(web.asyncio, 'to_thread', inline)
    monkeypatch.setenv('APP_USERNAME', 'owner')
    monkeypatch.setenv('APP_PASSWORD', 'test-password')
    monkeypatch.setenv('APP_SESSION_SECRET', 'test-session-secret')
    job, _ = blocked_records()
    job.update(kind='explainer', request={'stop_after_script':True,'question':'stoats'})
    original = deepcopy(job)
    store = Mock(get_job=Mock(return_value=job))
    monkeypatch.setattr(web, '_durable_execution_required', lambda: True)
    monkeypatch.setattr(web, '_durable_components', lambda: (store, Mock()))
    app = FastAPI()
    app.add_middleware(private_access.PrivateAccessMiddleware)
    app.add_api_route('/api/studio/jobs/{job_id}/resume-provider', web.studio_resume_provider, methods=['POST'])
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as c:
            url = '/api/studio/jobs/any-job/resume-provider'
            body = {'checkpoint_sha256':CHECKPOINT}
            assert (await c.post(url,json=body)).status_code == 401
            store.resume_provider_block.assert_not_called()
            c.cookies.set(private_access.COOKIE_NAME, private_access.create_session('owner'))
            assert (await c.post(url,json={})).status_code == 422
            assert (await c.post(url,json={'checkpoint_sha256':'b'*64})).status_code == 409
            store.resume_provider_block.assert_not_called()
            response = await c.post(url,json=body)
            assert response.status_code == 200
            assert response.json()['dispatch_url'] == '/api/explainer/dispatch/any-job'
            store.resume_provider_block.assert_called_once_with('any-job',expected_checkpoint_sha256=CHECKPOINT)
            assert job == original
            store.resume_provider_block.reset_mock()
            job['kind'] = 'explainer_pilot'
            assert (await c.post(url,json=body)).status_code == 409
            store.resume_provider_block.assert_not_called()
            job['kind'] = 'explainer'
            store.resume_provider_block.side_effect = web.durable_execution.DurableExecutionError('Not eligible')
            assert (await c.post(url,json=body)).status_code == 409
            store.get_job.return_value = None
            assert (await c.post(url,json=body)).status_code == 404
    asyncio.run(run())
