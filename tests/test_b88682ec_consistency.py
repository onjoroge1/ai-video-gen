"""Saved PR158 production regression; no provider access or regenerated evidence."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
import explainer_pipeline as ep
import claim_entailment as ce
import script_integrity as si
import durable_execution as durable
from test_durable_execution_phase6 import MemoryStore, MemoryBlob, runtime
from test_durable_anthropic_response import Provider, payload


def fixture():
    return json.loads(Path('tests/fixtures/b88682ec_script_failure.json').read_text())


def client(data):
    create = Mock(return_value=NS(content=[NS(text=json.dumps(data))], usage=NS(input_tokens=100,output_tokens=100)))
    return NS(messages=NS(create=create)), create


def test_live_draft_noop_factcheck_is_not_reported_complete(monkeypatch):
    f=fixture(); script=f['script']; original=deepcopy(script)
    # Reproduce the actual production response: unchanged prose, "no corrections".
    provider,create=client({'title':script['title'],'narration':[s['narration'] for s in script['scenes']],
                            'notes':['No corrections required.']})
    monkeypatch.setattr(ep,'_claude',lambda:provider)
    monkeypatch.setattr(ep,'_validate_claims',lambda *a:deepcopy(f['report']))
    result,notes,cost=ep.factcheck_script(script,'Why stoats?',f['dossier'])
    assert notes[0].startswith('Fact-check repair rejected') and cost>0
    assert result['scenes']==original['scenes']
    findings=json.loads(create.call_args.kwargs['messages'][0]['content'])['validation_findings']
    assert any('And it worked' in str(e) for e in findings)
    assert len(findings)==14
    audit=result['_edit_audit'][-1]
    assert not audit['accepted'] and audit['before_report']==audit['candidate_report']


def test_failed_candidate_is_transactional_and_retained_for_inspection(monkeypatch):
    f=fixture(); script=f['script']; original=deepcopy(script)
    lines=[s['narration'] for s in script['scenes']]
    lines[2]='The plan was intended to control rabbits.'
    provider,_=client({'title':'An invented title','narration':lines,'notes':[]})
    monkeypatch.setattr(ep,'_claude',lambda:provider)
    before=f['report']; after={'passed':False,'errors':[{'code':'HOOK_PROMISE_UNPAID','scene':1}]}
    monkeypatch.setattr(ep,'_validate_claims',Mock(side_effect=[before,after]))
    result,notes,_=ep.factcheck_script(script,'Why stoats?',f['dossier'])
    assert result['title']==original['title'] and result['scenes']==original['scenes']
    assert result['_edit_audit'][-1]['candidate']['scenes'][2]['narration']==lines[2]
    assert result['_edit_audit'][-1]['candidate_report']==after


def test_validated_partial_correction_is_incomplete_not_approval(monkeypatch):
    f=fixture();script=f['script'];lines=[s['narration'] for s in script['scenes']]
    lines[2]='The plan was intended to control rabbits.'
    provider,_=client({'title':script['title'],'narration':lines,'notes':[]})
    monkeypatch.setattr(ep,'_claude',lambda:provider)
    monkeypatch.setattr(ep,'_validate_claims',Mock(side_effect=[f['report'],{'passed':False,'errors':f['report']['errors'][1:]}]))
    result,notes,_=ep.factcheck_script(script,'Why stoats?',f['dossier'])
    assert result['scenes'][2]['narration']==lines[2]
    assert notes[0].startswith('Fact-check incomplete') and result['_edit_audit'][-1]['accepted']


def test_operational_review_failure_never_triggers_prose_repair(monkeypatch):
    f=fixture(); provider,create=client({})
    monkeypatch.setattr(ep,'_claude',lambda:provider)
    monkeypatch.setattr(ep,'_validate_claims',lambda *a:{'retryable':True,'errors':[]})
    result,notes,_=ep.factcheck_script(f['script'],'Why stoats?',f['dossier'])
    create.assert_not_called()
    assert notes[0].startswith('Fact-check unavailable')


def test_self_contradictory_guam_finding_is_not_a_content_failure():
    verdict={'verdict':'partially_entailed','supported_core':'On Guam, a predator arrived by accident and devastated birds.',
             'unsupported_details':["that the predator 'arrived by accident'"]}
    assert ce._normalise(verdict,'')['verdict']=='invalid_response'
    verdict['supported_core']='On Guam, a predator devastated birds.'
    assert ce._normalise(verdict,'')['verdict']=='partially_entailed'


def test_invalid_judge_retry_is_new_paid_request_but_replays_on_restart(tmp_path,monkeypatch):
    bad=payload(text=json.dumps({'verdict':'partially_entailed','supported_core':'It arrived by accident.',
                'unsupported_details':["'arrived by accident'"]}))
    good=payload(text=json.dumps({'verdict':'entailed'}))
    provider=Provider(bad)
    calls=[]
    def response_create(**kwargs):
        calls.append(kwargs)
        return Provider(bad if len(calls)==1 else good).create(**kwargs)
    provider.create=response_create
    store,blob=MemoryStore(cap=10),MemoryBlob(tmp_path/'blob')
    for worker_name in ('first','resumed'):
        worker=runtime(tmp_path,store,blob,worker_name)
        monkeypatch.setattr(ep,'_claude',lambda:worker.wrap_anthropic(provider))
        result=ce.narration_fidelity('It arrived by accident.','It arrived by accident.',cache={})
        assert result['passed']
    assert len(calls)==2
    assert calls[0]['messages']!=calls[1]['messages']


def test_integrity_retry_has_distinct_request(monkeypatch):
    requests=[]
    def judge(value):
        requests.append(value)
        return {} if len(requests)==1 else {'issues':[]}
    assert si.review({'scenes':[{'narration':'Stoats arrived.'}]},{},judge=judge)['passed']
    assert requests[1]['review_attempt']==2 and 'review_attempt' not in requests[0]


def test_negated_supported_core_does_not_invalidate_real_contradiction():
    result=ce._normalise({'verdict':'contradicted','supported_core':'It did not arrive by accident.',
        'unsupported_details':["'arrive by accident'"]},'')
    assert result['verdict']=='contradicted'


def test_compiled_title_is_validated_against_events(monkeypatch):
    import longform_research as lr
    f=fixture()
    monkeypatch.setattr(lr,'validate_story_fact_model',lambda *a,**kw:{'passed':True,'errors':[]})
    monkeypatch.setattr(si,'review',lambda *a,**kw:{'passed':True,'errors':[],'retryable':False})
    calls=[]
    def title_review(story,title,**kwargs):
        calls.append((story,title))
        return {'passed':False,'verdict':'partially_entailed','reason':'wrong intended target',
                'unsupported_details':['set stoats loose on kiwi']}
    monkeypatch.setattr(ce,'narration_fidelity',title_review)
    report=ep._validate_claims(f['script'],f['dossier'])
    assert not report['passed'] and report['errors'][0]['code']=='TITLE_EXCEEDS_STORY'
    assert calls[0][1]==f['script']['title']
    assert 'intended' in calls[0][0] or 'meant for' in calls[0][0]


def test_first_scene_repair_receives_cold_open_claims(monkeypatch):
    f=fixture(); script=f['script']
    provider,create=client({'scenes':[]})
    monkeypatch.setattr(ep,'_claude',lambda:provider)
    ep.repair_claim_join_failures(script,f['dossier'],f['report'])
    body=json.loads(create.call_args.kwargs['messages'][0]['content'])
    assert set(script['_cold_open_claim_refs'])<=set(body['scenes'][0]['allowed_claim_ids'])
    assert body['read_only_lead']['cold_open']==script['_cold_open']
