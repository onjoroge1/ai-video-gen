import copy
import json
import pytest

from bolt_video.kids.models import Episode, validate_episode, canonical_hash
from bolt_video.kids.template import starter
from bolt_video.kids.gates import GateBook, KidsGateFailure, judge_checks, release_check
from bolt_video.kids.config import build_payload, authorize
from bolt_video.kids.providers import transcript_match


def resolved_template():
    value=starter()
    for ref in value['references']:
        ref.update(sha256='a'*64,license='Owned original artwork')
    return value


def test_unresolved_starter_cannot_spend():
    assert validate_episode(starter())['valid'] is False


def test_valid_contract_hash_and_fixed_host():
    a=validate_episode(resolved_template());b=validate_episode(resolved_template())
    assert a['valid'] and a['spec_sha256']==b['spec_sha256']
    assert a['normalized_spec']['bolt_design']=='white_teal_robot'
    assert a['status']=='validated_not_authorized'


@pytest.mark.parametrize('uri',['https://example.com/x.png','file:///etc/passwd','asset://../secret.png',
                                'asset:///tmp/x.png','asset://x/../../a','library://abc','asset://x?secret=1'])
def test_reference_schemes_fail_closed(uri):
    value=resolved_template();value['references'][0]['uri']=uri
    assert not validate_episode(value)['valid']


@pytest.mark.parametrize('mutation',[
    lambda s:s.update(bolt_design='puppy'),
    lambda s:s.update(acceptance={'skip_gates':True}),
    lambda s:s.update(target_duration_sec=180),
    lambda s:s['beats'][0]['audio'][0].update(character_id='unknown'),
    lambda s:s['beats'][2]['audio'][-1].update(duration_sec=0),
    lambda s:s['beats'][2]['audio'][-1].update(duration_sec=1.5),
    lambda s:s['beats'][2]['audio'][-1].update(duration_sec=float('nan')),
    lambda s:s['assets'][2].update(mode='still'),
    lambda s:s['references'][0].update(sha256='0'*64),
    lambda s:s['references'][0].update(license='unresolved'),
    lambda s:s['beats'][-1].update(role='question'),
    lambda s:s['beats'][3].update(answer='penguin'),
    lambda s:s['beats'][3]['shots'][0].update(asset_id='listen'),
    lambda s:s['assets'][6].update(loopable=True),
    lambda s:s['assets'].append({**s['assets'][0],'id':'unused'}),
    lambda s:s['beats'][2]['audio'][0].update(id='opening_vo'),
])
def test_invalid_story_cannot_reach_providers(mutation):
    value=resolved_template();mutation(value)
    assert not validate_episode(value)['valid']


def test_payload_binds_policy_voice_refs_and_budget(monkeypatch):
    monkeypatch.setenv('FAL_MODEL','kling-2.1-standard')
    monkeypatch.setenv('DURABLE_JOB_MAX_COST_USD','10')
    payload=build_payload(resolved_template(),10)
    digest=canonical_hash(payload)
    assert authorize(payload,digest,10).target_duration_sec==120
    for path,value in [('policy_version','other'),('cost_ceiling_usd',12)]:
        changed=copy.deepcopy(payload);changed[path]=value
        with pytest.raises(ValueError):authorize(changed,digest,10)
    monkeypatch.setenv('FAL_MODEL','kling-3-pro')
    with pytest.raises(ValueError):authorize(payload,digest,10)


def test_cap_and_estimate_cannot_be_bypassed(monkeypatch):
    monkeypatch.setenv('DURABLE_JOB_MAX_COST_USD','5')
    with pytest.raises(ValueError):build_payload(resolved_template(),10)
    with pytest.raises(ValueError):build_payload(resolved_template(),float('inf'))
    with pytest.raises(ValueError):build_payload(resolved_template(),.01)


@pytest.mark.parametrize('checks',[{}, {'foo':None},{'foo':'true'},{'foo':False},{'foo':1}])
def test_empty_or_nonboolean_checks_never_pass(tmp_path,checks):
    gate=GateBook(tmp_path,'a'*64)
    with pytest.raises(KidsGateFailure):gate.record('test',checks)
    assert json.loads(gate.path.read_text())['publishable'] is False


def test_unavailable_judge_is_not_a_numeric_reject(tmp_path):
    checks,missing=judge_checks({'checks':{'safe':True}},['safe'])
    assert missing
    gate=GateBook(tmp_path,'a'*64)
    with pytest.raises(KidsGateFailure):gate.record('judge',checks,unavailable=missing)
    row=json.loads(gate.path.read_text())['gates'][0]
    assert row['status']=='unscored_unavailable' and 'score' not in row


def test_judge_requires_exact_checklist():
    result={'checks':{'safe':True},'evidence':'Observed a friendly robot.'}
    assert judge_checks(result,['safe'])==({'safe':True},False)
    assert judge_checks(result,['safe','action'])[1]


def test_transcript_checks_missing_and_extra_words():
    assert transcript_match('Hello, little bunny!', 'Hello little bunny')['expected_coverage']==1
    assert transcript_match('One two three', 'One two')['expected_coverage']<.95
    assert transcript_match('One two three', 'One two three four')['observed_precision']<.95


def test_release_requires_exact_video_and_whole_checklist():
    checklist={k:True for k in ['watched_entire_video','voices_and_lyrics_intelligible',
        'learning_content_correct','actions_and_answers_match','age_appropriate','rights_and_disclosure_reviewed']}
    quality={'status':'passed','video_sha256':'a'*64}
    assert release_check(quality,'a'*64,'approve',checklist)
    assert not release_check(quality,'b'*64,'approve',checklist)
    assert not release_check(quality,'a'*64,'approve',{})
    assert not release_check({'status':'needs_repair','video_sha256':'a'*64},'a'*64,'approve',checklist)
    assert not release_check(quality,'a'*64,'reject',checklist)
