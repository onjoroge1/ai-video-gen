"""Offline request/security/cache tests; optional installations tested separately in CI."""
from copy import deepcopy
from pathlib import Path
import json
import uuid
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from bolt_video.engines import jobs, runner, api
from private_access import PrivateAccessMiddleware, create_session, COOKIE_NAME


def source_record(video_id='source'):
    return {'id':video_id,'title':'Original','status':'done','artifacts':{
        'video':{'url':'https://test.public.blob.vercel-storage.com/source.mp4',
                 'sha256':'a'*64,'size_bytes':1000}}}


class Store:
    def __init__(self):
        self.jobs={};self.records={'source':source_record()};self.enqueues=0
    def get_job(self,job_id):return deepcopy(self.jobs.get(job_id))
    def finished_get(self,video_id):return deepcopy(self.records.get(video_id))
    def enqueue(self,**kwargs):
        self.enqueues+=1
        return deepcopy(self.jobs.setdefault(kwargs['job_id'],{**kwargs,'id':kwargs['job_id'],'status':'queued'}))


def request(**kwargs):
    return jobs.EngineRequest(request_id=uuid.uuid4(),engine='openshorts',title='Child',
        source_video_id='source',start_sec=1,end_sec=3,source_rights_confirmed=True,**kwargs)


def test_queue_reuses_immutable_id_and_never_changes_parent():
    store=Store();req=request();original=deepcopy(store.records)
    first=jobs.queue(req,store);second=jobs.queue(req,store)
    assert first==second and store.enqueues==1 and store.records==original
    assert first['max_cost_usd']==0 and first['kind']=='video_engine'
    changed=req.model_copy(update={'title':'Different'})
    with pytest.raises(ValueError,match='different immutable'):jobs.queue(changed,store)


@pytest.mark.parametrize('mutation',['hash','url','size','not_done','missing'])
def test_cannot_queue_untrusted_or_missing_sources(mutation):
    store=Store();rec=store.records['source'];a=rec['artifacts']['video']
    if mutation=='hash':a.pop('sha256')
    if mutation=='url':a['url']='http://169.254.169.254/latest/meta-data'
    if mutation=='size':a['size_bytes']=jobs.MAX_FILE_BYTES+1
    if mutation=='not_done':rec['status']='error'
    if mutation=='missing':store.records={}
    with pytest.raises(ValueError):jobs.queue(request(),store)
    assert store.enqueues==0


def test_validation_rejects_payload_or_budget_tampering():
    row=jobs.queue(request(),Store());jobs.validate_payload(row)
    row['max_cost_usd']=10
    with pytest.raises(ValueError):jobs.validate_payload(row)
    row['max_cost_usd']=0;row['request']['publish']=True
    with pytest.raises(ValueError):jobs.validate_payload(row)


def test_recomputed_hash_does_not_allow_path_injection():
    row=jobs.queue(request(),Store());body=row['request'];body['inputs']['../../escape']=body['inputs'].pop('source')
    clean={k:v for k,v in body.items() if k!='sha256'};body['sha256']=jobs.digest(clean)
    with pytest.raises(ValueError,match='role'):jobs.validate_payload(row)


@pytest.mark.parametrize('patch',[{'start_sec':float('nan')},{'end_sec':float('inf')},
 {'end_sec':1000},{'end_sec':0},{'source_rights_confirmed':False},{'api_key':'secret'},
 {'engine':'evil'},{'silent':True},{'source_video_id':'../../etc/passwd'}])
def test_bad_request_shapes_fail(patch):
    raw=request().model_dump();raw.update(patch)
    with pytest.raises((ValueError,ValidationError)):jobs.EngineRequest.model_validate(raw)


def test_caption_rebasing_and_clipping(tmp_path):
    source=tmp_path/'original.srt';out=tmp_path/'clip.srt'
    source.write_text('1\n00:00:00,500 --> 00:00:01,500\nA\n\n2\n00:00:02,000 --> 00:00:04,000\nB\n')
    runner.copy_captions(str(source),out,request(),2)
    assert out.read_text()=='1\n00:00:00,000 --> 00:00:00,500\nA\n\n2\n00:00:01,000 --> 00:00:02,000\nB\n'


def test_subprocess_receives_no_provider_or_storage_credentials(monkeypatch,tmp_path):
    for key in ['DATABASE_URL','BLOB_READ_WRITE_TOKEN','OPENAI_API_KEY','FAL_KEY','AWS_SECRET_ACCESS_KEY']:
        monkeypatch.setenv(key,'secret')
    env=runner.clean_environment(tmp_path)
    assert not any('KEY' in k or 'TOKEN' in k or k=='DATABASE_URL' for k in env)


def test_authenticated_queue_status_and_worker_absence(monkeypatch):
    monkeypatch.setenv('APP_PASSWORD','test-only-long-password')
    store=Store();monkeypatch.setattr(api,'components',lambda:(store,object()))
    monkeypatch.setattr(api,'readiness',lambda e:{'ready_on_this_host':False})
    app=FastAPI();app.add_middleware(PrivateAccessMiddleware);api.mount(app)
    with TestClient(app) as client:
        req=request().model_dump(mode='json')
        assert client.post('/api/video-engines/jobs',json=req).status_code==401
        client.cookies.set(COOKIE_NAME,create_session())
        assert client.post('/api/video-engines/jobs',json=req,headers={'Origin':'https://evil.example'}).status_code==403
        result=client.post('/api/video-engines/jobs',json=req)
        assert result.status_code==202
        job=result.json();assert 'blob.vercel' not in json.dumps(job)
        assert client.get(job['status_path']).json()['id']==job['id']
        response=client.post(job['dispatch_path']).json()
        assert response['worker_required'] is True and response['job']['status']=='queued'
        assert store.enqueues==1


def test_video_probe_actual_bounds(monkeypatch):
    monkeypatch.setattr(runner,'probe',lambda p:{'duration_sec':2,'audio':{'codec_name':'aac'},'video':{'width':720,'height':1280}})
    with pytest.raises(ValueError,match='actual'):runner.inspect_inputs(request(),{'source':'local.mp4'})


def test_default_worker_claim_is_kind_isolated():
    import inspect
    import _durable_execution_legacy as durable
    signature=inspect.signature(durable.PostgresStore.claim)
    assert signature.parameters['kind'].default=='explainer'
    assert 'AND kind=%s' in inspect.getsource(durable.PostgresStore.claim)
