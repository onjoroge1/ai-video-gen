from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock
import json

import explainer_pipeline as ep
import hook_callback as hc
import retention_polish as rp
import script_integrity as si
import story_planner as sp

PAIR = {'viewer_question':'How did protecting farms put kiwi chicks on the menu?',
        'supported_answer':'Introduced stoats also preyed on native birds.',
        'contrast':'Protecting farms harmed native birds.',
        'callback_image':'a kiwi chick', 'closing_question':'What else are you putting on the menu?'}


def test_pair_reaches_planner_expansion_editor_and_review_without_becoming_evidence():
    plan = {'hook_contract':PAIR}
    prompt = sp.planner_prompt('stoats',180,'removed_keystone',{'claims':[]})
    assert hc.BRIEF in prompt and '"hook_contract"' in prompt
    assert 'not additional evidence' in hc.expansion_direction(plan)
    assert hc.contract(plan) == PAIR
    script = {'hook':PAIR['viewer_question'], '_hook_contract':PAIR,
        'scenes':[{'scene_id':'s1','narration':PAIR['viewer_question'],
                   'event':{'text':'Stoats were introduced.','claim_refs':['c1']}},
                  {'scene_id':'s2','narration':'What else are you putting on the menu?','event':{'text':'','claim_refs':[]}}]}
    editor = rp.prompt(script,{'overall':70},78,70)
    assert hc.BRIEF in editor and PAIR['supported_answer'] in editor
    seen=[]
    def judge(payload):
        seen.append(payload)
        return {'issues':[{'code':'HOOK_PROMISE_UNPAID','scene':2,
            'quote':'What else are you putting on the menu?',
            'reason':'No spoken explanation connects stoats to kiwi predation.',
            'repair':'Explain the supported cause before applying it.'}]}
    result = si.review(script, {'claims':[{'claim_id':'c1','claim':'Stoats were introduced.'}]},judge=judge)
    assert not result['passed'] and result['errors'][0]['scene'] == 2
    assert seen[0]['hook_plan_not_evidence'] == PAIR
    assert seen[0]['scenes'][0]['evidence'][0]['claim'] == 'Stoats were introduced.'
    assert seen[0]['scenes'][1]['evidence'] == []


def test_missing_or_malformed_pair_is_legacy_compatible_and_fields_are_allowlisted():
    assert hc.contract({}) == {} and hc.expansion_direction({}) == ''
    assert hc.contract({'hook_contract':'bad'}) == {}
    assert hc.contract({'hook_contract':{'viewer_question':' Q? ','unknown':'x','contrast':3}}) == {'viewer_question':'Q?'}


def test_changed_hook_or_pair_invalidates_review_cache():
    script={'hook':'First question?', '_hook_contract':PAIR,'scenes':[{'narration':'An answer.'}]}
    judge=Mock(return_value={'issues':[]}); cache={}
    si.review(script,{},judge=judge,cache=cache)
    si.review(script,{},judge=judge,cache=cache)
    changed=deepcopy(script); changed['hook']='Another question?'
    si.review(changed,{},judge=judge,cache=cache)
    changed['_hook_contract']['supported_answer']='Another intended answer.'
    si.review(changed,{},judge=judge,cache=cache)
    assert judge.call_count == 3


def test_grader_receives_pair_rubric_and_actual_narration(monkeypatch):
    create=Mock(return_value=NS(usage=NS(input_tokens=100,output_tokens=100),content=[NS(text=json.dumps(
        {'hook':80,'story':80,'ending':80,'repetition':80,'cadence':80,'weakest':'hook','notes':'Earn the answer.'}))]))
    monkeypatch.setattr(ep,'_claude',lambda:NS(messages=NS(create=create)))
    ep.grade_script({'hook':'How did this happen?','scenes':[{'narration':f'Spoken scene {i}.'} for i in range(4)]})
    assert hc.GRADE_GUIDANCE in create.call_args.kwargs['system']
    assert 'Spoken scene 3.' in create.call_args.kwargs['messages'][0]['content']


def test_new_unpaid_promise_cannot_be_accepted_as_an_improving_repair():
    before={'errors':[{'code':'NARRATION_EXCEEDS_EVENT','scene':1},{'code':'NARRATION_EXCEEDS_EVENT','scene':2}]}
    after={'errors':[{'code':'HOOK_PROMISE_UNPAID','scene':2}]}
    assert not si.improves(before,after)


def test_pair_survives_actual_planning_to_scene_expansion(monkeypatch):
    import test_causal_lane_integration as fixture
    original = fixture._sheet
    monkeypatch.setattr(fixture,'_sheet',lambda n: {**original(n),'hook_contract':PAIR})
    prompts=[]
    def create(**call):
        prompt=call['messages'][0]['content']; prompts.append(prompt)
        return fixture._reply(fixture._route(prompt,10))
    monkeypatch.setattr(ep,'_claude',lambda:NS(messages=NS(create=create)))
    script=ep._generate_script_chunked('Why did the plan fail?',200,'engaging','',10,causal_lane=True)
    assert script['_hook_contract'] == PAIR
    assert any('NOW WRITE scenes' in p and PAIR['supported_answer'] in p for p in prompts)


def test_promptfoo_requires_a_pair_but_does_not_claim_it_proves_quality():
    from evals.promptfoo.asserts import plan_has_hook_pair
    assert not plan_has_hook_pair('{}',{})['pass']
    result=plan_has_hook_pair(json.dumps({'hook_contract':PAIR}),{})
    assert result['pass'] and 'separately judged' in result['reason']
