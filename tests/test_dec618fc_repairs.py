import json
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
import causal_story as cs
import explainer_pipeline as ep
import studio_jobs


@pytest.mark.parametrize('situation,expected', [
    ('Kiwi survive on offshore islands.', False),
    ('Island birds lost their habitat.', False),
    ('On Guam, snakes attacked birds.', True),
    ('Guamese is a different word.', False),
])
def test_parallel_case_requires_distinctive_whole_word(situation, expected):
    issues = []
    cs._check_parallel_cases({'parallel_cases': [{'domain':'Pacific island birds (Guam)',
        'problem':'predators','solution':'control','result':'survival'}]}, [
        {'role':cs.SETUP,'situation':'New Zealand farmers faced rabbits.','step_id':'1'},
        {'role':cs.ESCALATION,'situation':situation,'step_id':'2'},
        {'role':cs.GENERALIZATION,'situation':'Compare Guam.','step_id':'3'}], issues)
    assert any(i['code']=='PARALLEL_CASE_OUT_OF_PLACE' for i in issues) == expected


@pytest.mark.parametrize('chosen,accepted', [('c1',True),('c2',False)])
def test_mixed_failures_repair_only_event_evidence_without_mutating_report(monkeypatch,chosen,accepted):
    original = {'scenes':[{'beat_id':'event_1','narration':'Stoats ate unguarded eggs.',
        'event':{'text':'Stoats ate eggs.','claim_refs':['c1']},'claim_refs':[]}]}
    report = {'errors':[{'code':'NARRATION_EXCEEDS_EVENT','scene':'event_1'},
                        {'code':'OTHER_HARD_FAILURE','scene':'elsewhere'}]}
    before=deepcopy(report)
    response=NS(usage=NS(input_tokens=100,output_tokens=100),content=[NS(text=json.dumps({'scenes':[
        {'scene':1,'narration':'Stoats ate eggs.','evidence_id':'e1',
         'claim_refs':[{'claim_id':chosen,'narration_phrase':'Stoats ate eggs.'}]}]}))])
    create=Mock(return_value=response)
    monkeypatch.setattr(ep,'_claude',lambda:NS(messages=NS(create=create)))
    out,cost=ep.repair_claim_join_failures(original,{'claims':[
        {'claim_id':'c1','claim':'Stoats ate eggs.'},
        {'claim_id':'c2','claim':'Unrelated claim.'}]},report)
    assert cost>0 and report==before
    prompt=json.loads(create.call_args.kwargs['messages'][0]['content'])
    assert prompt['scenes'][0]['allowed_claim_ids']==['c1']
    assert 'Unrelated claim' not in json.dumps(prompt['claims'])
    assert (out['scenes'][0]['narration']=='Stoats ate eggs.') == accepted
    assert original['scenes'][0]['narration']=='Stoats ate unguarded eggs.'


def test_failed_diagnostic_surfaces_exact_script_and_keeps_failure(tmp_path,monkeypatch):
    class Reader:
        def __init__(self,**kw): self.root=__import__('pathlib').Path(kw['output_dir'])
        def restore_checkpoint(self,cp):
            (self.root/'_state.json').write_text(json.dumps({'script':{'title':'stale'}}))
            (self.root/'semantic_failure_claim-ledger.json').write_text(json.dumps({
                'stage':'claim-ledger','failed_at':'2026-10-03T15:15:00Z',
                'script':{'title':'failed draft','scenes':[{'narration':'Exact failed text.'}]},
                'report':{'passed':False,'errors':[{'code':'NARRATION_EXCEEDS_EVENT'}]}}))
    monkeypatch.setattr(studio_jobs.durable_execution,'DurableRuntime',Reader)
    store=Mock(get_job=Mock(return_value={'status':'error','checkpoint':{'sha256':'abc'}}))
    out=studio_jobs.artifacts('job-1',store,Mock())
    assert out['script']['title']=='failed draft'
    assert out['script_source']=='failed diagnostic: claim-ledger'
    assert not out['reports']['claim_failure']['report']['passed']


def test_claim_repair_batch_is_bounded(monkeypatch):
    create=Mock(return_value=NS(usage=NS(input_tokens=1,output_tokens=1),
        content=[NS(text='{"scenes": []}')]))
    monkeypatch.setattr(ep,'_claude',lambda:NS(messages=NS(create=create)))
    script={'scenes':[{'beat_id':f'e{i}','narration':'Stoats ate eggs.',
        'event':{'text':'Stoats ate eggs.','claim_refs':['c1']}} for i in range(6)]}
    ep.repair_claim_join_failures(script,{'claims':[{'claim_id':'c1','claim':'Stoats ate eggs.'}]},
        {'errors':[{'scene':f'e{i}','code':'NARRATION_EXCEEDS_EVENT'} for i in range(6)]})
    payload=json.loads(create.call_args.kwargs['messages'][0]['content'])
    assert [s['scene'] for s in payload['scenes']]==[1,2,3,4]
