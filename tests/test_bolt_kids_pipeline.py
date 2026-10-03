"""Synthetic orchestration/media tests. These do not establish creative quality."""
from pathlib import Path
import copy
import json
import shutil

from PIL import Image,ImageDraw
import pytest

from bolt_video.kids import media
from bolt_video.kids.config import build_payload
from bolt_video.kids.models import Episode,canonical_hash
from bolt_video.kids.pipeline import render_episode
from bolt_video.kids.gates import KidsGateFailure
from test_bolt_kids_contract import resolved_template
from test_bolt_kids_media import measured_cues


class Runtime:
    """In-memory stage store for local tests, not a replacement production scheduler."""
    def __init__(self,cache=None):
        self.cache=cache if cache is not None else {};self.store=self;self.blob=object()
        self.job_id='synthetic-kids';self.saved=[];self.executions=[]
    def get_job(self,_):return {'max_cost_usd':10,'spent_cost_usd':0}
    def checkpoint(self,label):self.saved.append(label)
    def paid_file(self,*,stage_key,provider,request,estimated_cost,output_path,operation):
        if stage_key in self.cache:
            metadata,data=self.cache[stage_key];Path(output_path).write_bytes(data)
            return metadata,0,True
        self.executions.append(stage_key);metadata,cost=operation(stage_key)
        self.cache[stage_key]=(metadata,Path(output_path).read_bytes())
        return metadata,cost,False
    def paid_value(self,*,stage_key,provider,request,estimated_cost,operation):
        if stage_key in self.cache:return self.cache[stage_key],0,True
        self.executions.append(stage_key);result,cost=operation(stage_key)
        self.cache[stage_key]=result;return result,cost,False


class Synthetic:
    def __init__(self,episode,runtime,fail=None):
        self.episode=episode;self.runtime=runtime;self.times=measured_cues(episode)
        self.text={};self.generated=[];self.fail=fail
    def tone(self,id,text,duration,path):
        self.text[str(path)]=text
        def call(_):
            self.generated.append(id)
            media.encode(['-f','lavfi','-i',f'sine=frequency=440:duration={duration}',
                          '-ar','48000','-ac','2','-f','wav',path])
            return {},0
        self.runtime.paid_file(stage_key='fixture-'+id,provider='fixture',request={},estimated_cost=0,
                               output_path=str(path),operation=call)
    def speech(self,cue,character,path):self.tone(cue.id,cue.text,self.times[cue.id],path)
    def song(self,song,path):self.tone(song.id,song.lyrics,song.duration_sec,path)
    def transcribe(self,path):
        text=self.text[str(path)]
        return {'text':'missing lyrics' if self.fail=='lyrics' else text,'words':[]}
    def review(self,label,payload,required,images=()):
        self.generated.append('review:'+label)
        if self.fail=='script-unavailable' and label=='script':return {}
        checks={k:True for k in required}
        if self.fail=='image' and label.startswith('source-'):checks[required[0]]=False
        if self.fail=='encoded-action' and label.startswith('encoded-action-'):checks[required[1]]=False
        return {'checks':checks,'evidence':'SYNTHETIC TEST DOUBLE. This is not a creative assessment.'}
    def image(self,asset,world,cast,refs,path):
        self.generated.append('image:'+asset.id)
        image=Image.new('RGB',(640,360),(30+len(asset.id)*5,140,155));draw=ImageDraw.Draw(image)
        draw.text((30,40),'SYNTHETIC TEST - NOT A BOLT EPISODE',fill='white')
        draw.text((30,80),asset.id,fill='white');image.save(path)
    def motion(self,asset,image,path):
        self.generated.append('motion:'+asset.id)
        # Actual moving test pattern, not a fabricated MP4 header or still-image pass claim.
        media.encode(['-f','lavfi','-i',f'testsrc2=size=640x360:rate=24:duration={asset.motion_seconds}',
                      '-an','-c:v','libx264','-preset','ultrafast','-threads','1',path])


def setup(tmp_path,monkeypatch):
    monkeypatch.setenv('FAL_MODEL','kling-2.1-standard')
    monkeypatch.setenv('FAL_I2V_RESOLUTION','720p')
    monkeypatch.setenv('DURABLE_JOB_MAX_COST_USD','10')
    monkeypatch.setenv('DURABLE_MAX_INFLIGHT_CALL_USD','1')
    value=resolved_template();source=tmp_path/'reference.png';Image.new('RGB',(64,64),'teal').save(source)
    for ref in value['references']:ref['sha256']=media.sha256(source)
    payload=build_payload(value,10);episode=Episode.model_validate(value)
    def resolve(episode,destination,blob):
        destination.mkdir(parents=True,exist_ok=True)
        return {ref.id:str(source) for ref in episode.references}
    return episode,payload,resolve


def test_no_generation_after_script_unavailable(tmp_path,monkeypatch):
    episode,payload,resolver=setup(tmp_path,monkeypatch);runtime=Runtime();services=Synthetic(episode,runtime,'script-unavailable')
    with pytest.raises(KidsGateFailure,match='unscored_unavailable'):
        render_episode(payload,canonical_hash(payload),10,tmp_path/'out',runtime,
                       services=services,resolver=resolver,check_configuration=False,log=lambda _:None)
    assert services.generated==['review:script']


def test_missing_song_words_stop_all_visual_spending(tmp_path,monkeypatch):
    episode,payload,resolver=setup(tmp_path,monkeypatch);runtime=Runtime();services=Synthetic(episode,runtime,'lyrics')
    with pytest.raises(KidsGateFailure,match='song-'):
        render_episode(payload,canonical_hash(payload),10,tmp_path/'out',runtime,
                       services=services,resolver=resolver,check_configuration=False,log=lambda _:None)
    assert not any(x.startswith(('image:','motion:')) for x in services.generated)


def test_bad_reference_stops_even_script_review(tmp_path,monkeypatch):
    episode,payload,resolver=setup(tmp_path,monkeypatch);runtime=Runtime();services=Synthetic(episode,runtime)
    for ref in payload['spec']['references']:ref['sha256']='b'*64
    with pytest.raises(KidsGateFailure,match='references'):
        render_episode(payload,canonical_hash(payload),10,tmp_path/'out',runtime,
                       services=services,resolver=resolver,check_configuration=False,log=lambda _:None)
    assert not services.generated


def test_full_synthetic_episode_and_cached_local_replay(tmp_path,monkeypatch):
    # Full duration with a small diagnostic canvas; 720p encoding has a separate real-media test.
    monkeypatch.setattr(media,'WIDTH',320);monkeypatch.setattr(media,'HEIGHT',180)
    episode,payload,resolver=setup(tmp_path,monkeypatch);runtime=Runtime();services=Synthetic(episode,runtime)
    result=render_episode(payload,canonical_hash(payload),10,tmp_path/'out',runtime,
        services=services,resolver=resolver,check_configuration=False,log=lambda _:None)
    assert result['duration_sec']==119.5 and result['publishable'] is False
    assert result['editorial_status']=='pending_full_viewing'
    quality=json.loads(Path(result['grade_path']).read_text())
    assert quality['audience_engagement']=='unmeasured' and quality['score'] is None
    assert all(quality['technical']['checks'].values())
    assert len([x for x in services.generated if x=='mystery'])==1
    assert len([x for x in services.generated if x.startswith('motion:')])==5
    rows=json.loads(Path(result['kids_gate_path']).read_text())['gates']
    assert any(row['gate'].startswith('encoded-action-') for row in rows)
    # Simulate another worker with the completed local-render and paid-audio cache.
    second=Runtime(runtime.cache);services2=Synthetic(episode,second)
    second_result=render_episode(payload,canonical_hash(payload),10,tmp_path/'worker-b',second,
        services=services2,resolver=resolver,check_configuration=False,log=lambda _:None)
    assert not any(x.startswith('fixture-') or x.startswith('kids-render:') for x in second.executions)
    assert media.sha256(result['output_path'])==media.sha256(second_result['output_path'])
    target=__import__('os').environ.get('KIDS_TEST_ARTIFACT_DIR')
    if target:
        root=Path(target);root.mkdir(parents=True,exist_ok=True)
        for key in ('output_path','grade_path','kids_gate_path','audio_timing_report_path'):
            shutil.copyfile(result[key],root/Path(result[key]).name)
