import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import directed_longform as dl
import nature_short_presentation as nsp
import nature_story_flow as ns
import spec_pilot

ROOT = Path(__file__).resolve().parents[1]

def payload():
    return json.loads((ROOT/'spec/harp_seal_nature_short_v2.json').read_text())


def test_existing_approved_harp_spec_hash_is_unchanged():
    old = json.loads((ROOT/'spec/harp_seal_nature_short_v1.json').read_text())
    assert dl.validate_directed_spec(old)['spec_sha256'] == '4d4f1c7370786862a625fd686f9b58b4251dcbc1cce48fb2a5411b6ad36032d6'


def test_canonical_episode_compiles_exact_production_bundle():
    episode = json.loads((ROOT/'spec/harp_seal_nature_story_v2.json').read_text())
    assert ns.compile_directed_short(episode) == payload()
    assert ns.narration_text(episode) == ' '.join(s['narration'] for s in payload()['narration'])
    assert dl.validate_directed_spec(payload())['valid']


def test_measured_scene_timing_does_not_drift_when_beats_change_speed():
    scenes = [(0, SimpleNamespace(scene_id='a')), (1, SimpleNamespace(scene_id='b'))]
    shots = [dict(shot_id='1',scene_id='a',start_sec=0,end_sec=2),
             dict(shot_id='2',scene_id='a',start_sec=2,end_sec=4),
             dict(shot_id='3',scene_id='b',start_sec=4,end_sec=6),
             dict(shot_id='4',scene_id='b',start_sec=6,end_sec=8)]
    durations = {'a.mp3':6,'b.mp3':2}
    ep=SimpleNamespace(_audio_dur=lambda p:durations[p])
    holds=nsp.measured_holds(shots,scenes,list(durations),ep,3.4,.75)
    assert holds == [3,3,1,1]  # A global rescale would incorrectly give [2,2,2,2].
    durations['a.mp3']=8
    with pytest.raises(ValueError,match='repartition this beat'):
        nsp.measured_holds(shots,scenes,list(durations),ep,3.4,.75)


def test_voice_and_acting_direction_are_part_of_reuse_identity():
    spec=dl.DirectedLongformSpec.model_validate(payload())
    a=nsp.narration_identity('Dinner service: closed.', 'coral', spec.nature_short)
    b=nsp.narration_identity('Dinner service: closed.', 'onyx', spec.nature_short)
    spec.nature_short.voice_instructions='A slow and solemn science reader.'
    c=nsp.narration_identity('Dinner service: closed.', 'coral', spec.nature_short)
    assert a != b and a != c


def test_nature_motion_uses_portrait_and_evidence_action_lane(tmp_path,monkeypatch):
    source=tmp_path/'source.jpg';Image.new('RGB',(64,96),'blue').save(source)
    shot=payload()['shots'][0]
    captured={}
    def animate(path,prompt,out,w,h,**kwargs):
        captured.update(prompt=prompt,size=(w,h))
        Path(out).write_bytes(b'mock-provider-output')
        kwargs['err_sink'].append('ok:fal')
        return out
    monkeypatch.setattr(spec_pilot.ep,'animate_scene',animate)
    monkeypatch.setattr(spec_pilot.ep,'_run_ffmpeg',lambda args,**kw:None)
    assert spec_pilot._render_motion_shot(str(source),shot,2,str(tmp_path/'out.mp4'),[],lambda x:None,
                                          frame=spec_pilot.FRAME['portrait'],nature_directed=True)
    assert captured['size']==(1080,1920)
    assert captured['prompt'].startswith('narration-aligned evidence change:')
    assert shot['transformation'] in captured['prompt']


def test_caption_words_are_authored_and_override_safe(tmp_path):
    cues,quality=nsp.caption_cues('Dinner service: closed.', [('Dinner',0,.3),('service',.3,.6),('closed',.65,1)],1.2)
    assert quality==1 and cues[0]['text']=='Dinner service: closed.'
    output=tmp_path/'captions.ass'
    nsp.write_ass(output,[dict(start=0,end=1,text=r'{\pos(0,0)}hello')],[],1080,1920)
    text=output.read_text()
    assert r'{\pos(0,0)}' not in text
    assert 'MarginL, MarginR, MarginV' in text


def test_optin_cannot_modify_landscape_or_partial_longform():
    data=payload();data['target']['format']='landscape'
    assert not dl.validate_directed_spec(data)['valid']
    data=payload();data['target']['duration_sec']=300
    assert not dl.validate_directed_spec(data)['valid']
