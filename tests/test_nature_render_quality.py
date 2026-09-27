"""Regression evidence for the b67a6448 audit. No live providers are used."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageFont

import directed_longform as dl
import nature_render_quality as nrq
import nature_short_presentation as nsp
import nature_story_flow as ns
from media_binaries import ffmpeg
from longform_rendered_gate import build_contact_sheet

ROOT = Path(__file__).resolve().parents[1]


def payload():
    return json.loads((ROOT / 'spec/giant_pacific_octopus_nature_short_v3.json').read_text())


def media_ep():
    import explainer_pipeline as ep
    return SimpleNamespace(_ffmpeg_bin=ffmpeg, _run_ffmpeg=ep._run_ffmpeg)


def test_new_bundle_is_reproducible_bounded_and_old_approval_stays_immutable():
    episode = json.loads((ROOT / 'spec/giant_pacific_octopus_nature_story_v3.json').read_text())
    assert ns.compile_directed_short(episode) == payload()
    report = dl.validate_directed_spec(payload())
    assert report['valid'], report['issues']
    assert report['cost_estimate']['estimated_total_usd'] < 5
    assert report['cost_estimate']['quality_review_usd'] == .97
    old = json.loads((ROOT / 'spec/giant_pacific_octopus_nature_short_v2.json').read_text())
    assert dl.validate_directed_spec(old)['spec_sha256'] == '5b6b9dc2b3a24b3c101858d7bf77583024f50a86134eb3fee09a2f01b2e78024'
    assert report['spec_sha256'] != dl.validate_directed_spec(old)['spec_sha256']
    assert report['nature_retention_storyboard']['assessment_type'] == 'structural_compliance_not_editorial_quality'


def test_hyphens_and_em_dash_match_spoken_subwords_without_faking_missing_words():
    speech = 'Then—pop. Rice-grain-sized eggs release tiny eight-armed octopuses.'
    words = 'Then pop Rice grain sized eggs release tiny eight armed octopuses'.split()
    timed = [(w, i*.3, (i+1)*.3) for i,w in enumerate(words)]
    cues, ratio = nsp.caption_cues(speech, timed, 3.5)
    assert ratio == 1
    assert ' '.join(c['text'] for c in cues) == speech
    assert nsp.caption_cues(speech, timed[:5], 3.5)[1] < .9


def test_measured_hold_repair_preserves_each_scene_and_breaks_static_stretch():
    shots = [dict(shot_id=f's{i}',scene_id=sid,mode=mode) for i,(sid,mode) in enumerate([
        ('a','Full Motion'),('a','Still'),('b','Still'),('b','Full Motion')])]
    holds, report = nrq.repair_holds(shots, [2.617,2.617,3.78,3.78], 3.4,.75,5)
    assert report['passed']
    assert sum(holds[:2]) == pytest.approx(5.234)
    assert sum(holds[2:]) == pytest.approx(7.56)
    assert holds[1]+holds[2] <= 5.001
    assert max(holds[1:3]) <= 3.4
    _, report = nrq.repair_holds([dict(shot_id=str(i),scene_id='a',mode='Still') for i in range(3)], [2.7]*3,3.4,.75,5)
    assert not report['passed']
    assert report['issues'][0]['code'] == 'still_sequence'


@pytest.mark.parametrize('observation,passed', [
    (dict(action_complete=True,anatomy_consistent=True,action_start_sec=2.2,action_complete_sec=4.1,safe_end_sec=4.6),True),
    (dict(action_complete=True,anatomy_consistent=True,action_start_sec=.1,action_complete_sec=1.6,safe_end_sec=4),True),
    (dict(action_complete=False,anatomy_consistent=True),False),
    (dict(action_complete=True,anatomy_consistent=False),False),
    (dict(action_complete=True,anatomy_consistent=True,action_start_sec=0,action_complete_sec=4.4,safe_end_sec=4.8),False),
    (dict(action_complete=True,anatomy_consistent=True,action_start_sec=0,action_complete_sec=float('nan'),safe_end_sec=4.8),False),
])
def test_action_selection_includes_both_start_and_completed_result(observation,passed):
    selected = nrq.select_action_window(observation, 5, 2.617)
    assert selected['passed'] is passed
    if passed:
        assert selected['start_sec'] <= observation['action_start_sec']
        end = selected['start_sec']+selected['duration_sec']
        assert observation['action_complete_sec'] <= end <= observation['safe_end_sec']+.0001
        assert selected['speed'] <= 1.15


def test_slow_narration_uses_bounded_reusable_derivative(tmp_path):
    source = tmp_path / 'paid.mp3'; source.write_bytes(b'immutable source')
    calls=[]
    def run(args):
        calls.append(args);Path(args[-1]).write_bytes(b'pitched preserved derivative')
    ep = SimpleNamespace(_audio_dur=lambda p: 8 if p == str(source) else 7,
                         _run_ffmpeg=run,_ffmpeg_bin=lambda:'ffmpeg')
    scene=SimpleNamespace(scene_id='b6',narration='one two three four five six seven eight nine ten eleven twelve')
    direction=SimpleNamespace(min_narration_wpm=140,max_narration_speedup=1.15)
    first,notes=nrq.pace_narration([(0,scene)],[str(source)],direction,tmp_path,ep)
    second,_=nrq.pace_narration([(0,scene)],[str(source)],direction,tmp_path,ep)
    assert first==second and len(calls)==1
    assert source.read_bytes()==b'immutable source'
    assert notes[0]['speed_factor']==1.15
    assert 'atempo=1.15000000' in calls[0]


def test_semantic_review_requires_exact_narration_evidence(tmp_path,monkeypatch):
    spec=dl.DirectedLongformSpec.model_validate(payload())
    response={key:True for key in ('coherent','progresses','supported','render_modes_feasible','ending_earned')}
    response['beat_evidence']=[dict(scene_id=s.scene_id,narration_span=s.narration,new_information='A new causal beat') for s in spec.narration]
    monkeypatch.setattr(nrq,'_review_json',lambda *a,**k:json.loads(json.dumps(response)))
    assert nrq.review_story(spec,tmp_path,None,[])['passed']
    response['beat_evidence'][0]['narration_span']='unspoken marketing claim'
    with pytest.raises(ValueError,match='semantic story'):
        nrq.review_story(spec,tmp_path,None,[])
    assert not json.loads((tmp_path/'nature_semantic_review.json').read_text())['passed']


def test_source_review_does_not_treat_file_presence_as_visible_evidence(tmp_path,monkeypatch):
    source=tmp_path/'image.jpg';Image.new('RGB',(30,50)).save(source)
    shot=dict(shot_id='hatch',mode='Full Motion',visual='a fully closed egg',transformation='hatchling clears egg')
    monkeypatch.setattr(nrq,'_review_json',lambda *a,**k:{'shots':[dict(shot_id='hatch',passed=False,evidence='Egg is already open')]})
    with pytest.raises(ValueError,match='source-image'):
        nrq.review_visuals([shot],[source],source,tmp_path,None,[])
    report = json.loads((tmp_path/'nature_visual_review.json').read_text())
    assert not report['passed']
    assert report['status'] == 'images_rejected'
    assert report['failed_shot_ids'] == ['hatch']


@pytest.mark.parametrize('response', [
    {'available': False, 'error': 'invalid_review_json'},
    {'shots': 'not a list'},
    {'shots': [{'shot_id': []}]},
    {'shots': []},
    {'shots': [{'shot_id': 'other', 'passed': True, 'evidence': 'visible'}]},
    {'shots': [{'shot_id': 'hatch', 'passed': True, 'evidence': 'visible'}] * 2},
    {'shots': [{'shot_id': 'hatch', 'passed': 'true', 'evidence': 'visible'}]},
    {'shots': [{'shot_id': 'hatch', 'passed': True, 'evidence': ''}]},
    {'available': False, 'shots': [{'shot_id': 'hatch', 'passed': True, 'evidence': 'visible'}]},
])
def test_incomplete_source_assessment_is_saved_and_never_becomes_an_image_pass(tmp_path, monkeypatch, response):
    source = tmp_path/'image.jpg'; Image.new('RGB', (30, 50)).save(source)
    shot = dict(shot_id='hatch', mode='Full Motion', visual='closed egg', transformation='exit')
    monkeypatch.setattr(nrq, '_review_json', lambda *a, **k: response)
    with pytest.raises(ValueError, match='could not assess every shot'):
        nrq.review_visuals([shot], [source], source, tmp_path, None, [])
    report = json.loads((tmp_path/'nature_visual_review.json').read_text())
    assert report['status'] == 'review_unavailable' and not report['passed']
    assert report['review_errors']
    assert report['image_sha256']['hatch'] == nrq._sha(source)


@pytest.mark.parametrize('text,reason', [('{"shots": [', 'max_tokens'), ('[]', 'end_turn'),
                                         ('{"shots": []}', 'max_tokens')])
def test_review_response_metadata_survives_unusable_output_without_raw_text(text, reason):
    calls = []
    usage = SimpleNamespace(output_tokens=1600)
    response = SimpleNamespace(content=[SimpleNamespace(type='text', text=text)],
                               usage=usage, stop_reason=reason)
    def create(**kwargs):
        calls.append(kwargs)
        return response
    ep = SimpleNamespace(_claude=lambda: SimpleNamespace(messages=SimpleNamespace(create=create)),
                         ANTHROPIC_MODEL='test', _msg_cost=lambda u: .01)
    costs = []
    report = nrq._review_json(ep, 'fixture', costs)
    assert report['available'] is False
    assert report['response'] == {'stop_reason': reason, 'output_tokens': 1600}
    assert len(calls) == 1 and costs == [.01]
    assert text not in json.dumps(report)


def test_portrait_contact_sheet_preserves_aspect_ratio(tmp_path):
    source=tmp_path/'portrait.png';Image.new('RGB',(540,960),'red').save(source)
    sheet=tmp_path/'sheet.jpg'
    build_contact_sheet({'frames':[{'frame_path':str(source),'state_id':'a','midpoint_sec':1}]},str(sheet))
    with Image.open(sheet) as im:
        assert im.size==(810,522)
        assert im.getpixel((10,450))[0] > 200


def test_portable_font_and_real_encoded_caption_pixels(tmp_path,monkeypatch):
    # Simulate a fontless serverless host using Pillow's embedded scalable font.
    import font_utils
    monkeypatch.setattr(font_utils,'load_font',lambda *a,**kw:ImageFont.load_default(size=72))
    fonts,family=nrq.prepare_font(tmp_path)
    assert (fonts/'NatureCaption.ttf').stat().st_size>1000
    ep=media_ep();base=tmp_path/'base.mp4';after=tmp_path/'after.mp4'
    ep._run_ffmpeg([ffmpeg(),'-y','-f','lavfi','-i','color=c=0x124050:s=270x480:r=30:d=2',
                    '-c:v','libx264','-pix_fmt','yuv420p',str(base)])
    cues=[dict(start=.1,end=.9,text='EGGS NEED OXYGEN'),dict(start=1.1,end=1.9,text='EIGHT TINY ARMS')]
    tags=[dict(start=0,end=2,text='MONTHS OF CARE')]
    ass=tmp_path/'captions.ass'
    nsp.write_ass(ass,cues,tags,270,480,font_name=family)
    ep._run_ffmpeg([ffmpeg(),'-y','-i',str(base),'-vf',nrq.ass_filter(ass,fonts),'-c:v','libx264',str(after)])
    assert nrq.verify_captions(base,after,ass,fonts,cues,[0,1],ep,tmp_path)['passed']
    assert not nrq.verify_captions(base,base,ass,fonts,cues,[0,1],ep,tmp_path)['passed']
    tag_only=tmp_path/'tag-only.ass';nsp.write_ass(tag_only,[],tags,270,480,font_name=family)
    ep._run_ffmpeg([ffmpeg(),'-y','-i',str(base),'-vf',nrq.ass_filter(tag_only,fonts),'-c:v','libx264',str(after)])
    assert not nrq.verify_captions(base,after,ass,fonts,cues,[0,1],ep,tmp_path)['passed']
    assert not nrq.verify_captions(base,after,ass,fonts,cues[1:],[0,1],ep,tmp_path)['passed']


def test_poor_alignment_stops_v4_before_images(tmp_path):
    spec=dl.DirectedLongformSpec.model_validate(payload())
    ep=SimpleNamespace(_audio_dur=lambda _:3,transcribe_words=lambda *a,**kw:[('Missing',.1,.3)])
    with pytest.raises(ValueError,match='caption alignment'):
        nsp.prepare_captions([(0,spec.narration[0])],['audio'],ep,tmp_path,spec.nature_short)
    assert json.loads((tmp_path/'nature_captions.json').read_text())['human_timing_review_required']


def test_new_bundle_is_typed_and_loadable_through_mcp_api():
    import app
    spec_id='giant_pacific_octopus_nature_short_v3'
    request=app.AgentActionCreateRequest(operation='directed_pilot',bundled_spec_id=spec_id,cost_ceiling_usd=5)
    assert request.bundled_spec_id==spec_id
    assert app._bundled_directed_spec(spec_id)==payload()
    assert spec_id in (ROOT/'reelforge_mcp.py').read_text()


def test_motion_encoder_keeps_observed_completed_tail(tmp_path,monkeypatch):
    import spec_pilot
    import numpy as np
    ep=media_ep();source=tmp_path/'source.mp4';out=tmp_path/'trimmed.mp4'
    image=tmp_path/'image.jpg'; Image.new('RGB',(108,192),'red').save(image)
    ep._run_ffmpeg([ffmpeg(),'-y','-f','lavfi','-i','color=c=red:s=108x192:r=30:d=3',
                   '-f','lavfi','-i','color=c=lime:s=108x192:r=30:d=2',
                   '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]',
                   '-map','[v]','-c:v','libx264','-pix_fmt','yuv420p',str(source)])
    selected=nrq.select_action_window(dict(action_complete=True,anatomy_consistent=True,
                   action_start_sec=2.2,action_complete_sec=4.1,safe_end_sec=4.6),5,2.617)
    monkeypatch.setattr(spec_pilot,'_motion_cache_path',lambda *a,**kw:source)
    monkeypatch.setattr(nrq,'review_motion',lambda *a,**kw:{'passed':True,'selection':selected})
    monkeypatch.setattr(spec_pilot.ep,'_run_ffmpeg',ep._run_ffmpeg)
    events=[]
    assert spec_pilot._render_motion_shot(str(image),dict(shot_id='hatch',visual='egg',transformation='exit'),
                   2.617,str(out),[],lambda _:None,events,frame=dict(w=108,h=192),review_action=True)
    first=np.asarray(nrq._frame(ep,out,.05));last=np.asarray(nrq._frame(ep,out,2.5))
    assert first[:,:,0].mean()>200 and first[:,:,1].mean()<30
    assert last[:,:,1].mean()>200 and last[:,:,0].mean()<30
    assert events[0]['action_review']['passed']
