"""Real app routing and approval boundary; no providers or live storage."""
import copy
import hashlib
import json

import anyio
import httpx
import pytest

import app as studio
import agent_actions
import private_access
from bolt_video.kids.config import build_payload
from bolt_video.kids.models import canonical_hash
from test_agent_actions import FakeActionRepository, _secure_environment, ACTION_ID
from test_bolt_kids_contract import resolved_template


class KidsRepository(FakeActionRepository):
    def claim(self,action_id,*,claim_token):
        result=super().claim(action_id,claim_token=claim_token)
        self.action['job_id']=hashlib.sha256(action_id.encode()).hexdigest()[:24]
        return copy.deepcopy(self.action)


def test_routes_are_reachable_private_and_nonspending(monkeypatch):
    _secure_environment(monkeypatch)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app),base_url='http://test') as client:
            for path in ['/bolt-kids','/api/kids/schema','/api/kids/template','/api/kids/assets']:
                assert (await client.get(path)).status_code==401
            client.cookies.set(private_access.COOKIE_NAME,private_access.create_session('owner'))
            assert (await client.get('/bolt-kids')).status_code==200
            assert (await client.get('/api/kids/schema')).status_code==200
            draft=(await client.get('/api/kids/template')).json()
            report=(await client.post('/api/kids/validate',json={'spec':draft})).json()
            assert not report['valid']
            assert (await client.post('/api/kids/validate',json={'spec':resolved_template()})).json()['valid']
    anyio.run(run)


def test_kids_approval_is_exact_idempotent_and_not_a_directed_pilot(monkeypatch):
    _secure_environment(monkeypatch)
    monkeypatch.setenv('DURABLE_JOB_MAX_COST_USD','10')
    monkeypatch.setenv('FAL_MODEL','kling-2.1-standard')
    monkeypatch.setenv('DURABLE_MAX_INFLIGHT_CALL_USD','1')
    repo=KidsRepository();queued=[]
    monkeypatch.setattr(agent_actions,'repository',lambda:repo)
    monkeypatch.setattr(studio,'_durable_execution_required',lambda:True)
    import bolt_video.kids.config as config
    monkeypatch.setattr(config,'readiness',lambda *args:{'configured':True})
    async def enqueue(request,background_tasks,**kwargs):
        queued.append((request,kwargs));return {'job_id':kwargs['job_id'],'durable':True}
    monkeypatch.setattr(studio,'_enqueue_explainer_request',enqueue)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app),base_url='http://test') as client:
            body={'operation':'bolt_kids_episode','spec':resolved_template(),'cost_ceiling_usd':10}
            created=await client.post('/api/agent/actions',json=body)
            assert created.status_code==200,created.text
            result=created.json();assert result['scope']=='single-120-second-kids-episode'
            assert result['publishable'] is False and not queued
            token=result['claim_token'];headers={'Authorization':'Bearer '+token}
            dup=(await client.post('/api/agent/actions',json=body)).json()
            assert dup['action_id']==result['action_id'] and dup['reused'] and 'claim_token' not in dup
            execute=f'/api/agent/actions/{ACTION_ID}/execute'
            assert (await client.post(execute,headers=headers)).status_code==409
            assert not queued
            client.cookies.set(private_access.COOKIE_NAME,private_access.create_session('owner'))
            approve=f'/api/agent/actions/{ACTION_ID}/approve'
            assert (await client.post(approve,json={'spec_sha256':'0'*64,'cost_ceiling_usd':10})).status_code==409
            assert (await client.post(approve,json={'spec_sha256':result['spec_sha256'],'cost_ceiling_usd':10})).status_code==200
            client.cookies.clear()
            response=await client.post(execute,headers=headers)
            assert response.status_code==200,response.text
            assert len(queued)==1 and queued[0][0].kids_authorization
            assert queued[0][0].directed_spec is None and not queued[0][0].illustrated_authorization
            assert queued[0][1]['max_cost_usd']==10
            assert (await client.post(execute,headers=headers)).status_code==200
            assert len(queued)==1
    anyio.run(run)


def test_internal_kids_request_and_budget_cannot_be_mutated(monkeypatch):
    monkeypatch.setenv('FAL_MODEL','kling-2.1-standard')
    monkeypatch.setenv('DURABLE_JOB_MAX_COST_USD','10')
    payload=build_payload(resolved_template(),10)
    request=studio._kids_request(payload,canonical_hash(payload),10)
    studio._validate_kids_request_authorization(request)
    for field,value in [('duration_sec',45),('voice','onyx'),('fact_check',False),('directed_paid_authorized',True)]:
        changed=request.model_copy(deep=True);setattr(changed,field,value)
        with pytest.raises(ValueError):studio._validate_kids_request_authorization(changed)


def test_generic_generate_cannot_inject_kids_authorization(monkeypatch):
    _secure_environment(monkeypatch)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app),base_url='http://test') as client:
            client.cookies.set(private_access.COOKIE_NAME,private_access.create_session('owner'))
            result=await client.post('/api/explainer/generate',json={'question':'x','kids_authorization':{'fake':True}})
            assert result.status_code==403
    anyio.run(run)


def test_kids_format_is_not_mislabeled_as_pilot():
    assert studio.finished_library_format(visual_style='bolt_kids',video_format='landscape',
        short_template='auto',directed_spec=False,directed_full_film=False)=='bolt_kids'
