from pathlib import Path
import pytest
from PIL import Image

from bolt_video.kids.models import Episode
from bolt_video.kids import media
from bolt_video.kids.gates import timing_checks
from test_bolt_kids_contract import resolved_template


def measured_cues(episode):
    measured={}
    for beat in episode.beats:
        for cue in beat.audio:
            if cue.kind=='speech':
                measured[cue.id]={'hook':8,'question':7,'reveal':6,'recap':13,'goodbye':7}[beat.role]
            elif cue.kind=='song': measured[cue.id]=27 if cue.song_id=='parade' else 9
    return measured


def test_measured_timeline_preserves_response_pauses():
    ep=Episode.model_validate(resolved_template())
    timeline=media.compile_timeline(ep,measured_cues(ep))
    assert timeline['duration_sec']==119.5
    assert all(timing_checks(ep,timeline).values())
    pauses=[c for c in timeline['cues'] if c['kind']=='pause']
    assert len(pauses)==3 and all(c['end_sec']-c['start_sec']==2.5 for c in pauses)
    assert all(a['end_sec']==b['start_sec'] for a,b in zip(timeline['cues'],timeline['cues'][1:]))


def test_long_speech_fails_before_motion():
    ep=Episode.model_validate(resolved_template());measured=measured_cues(ep)
    measured['chick_answer_vo']=30
    checks=timing_checks(ep,media.compile_timeline(ep,measured))
    assert not checks['chick_answer_shot:action_fits']
    assert not checks['approximately_two_minutes']


def test_real_ffmpeg_encode_decode_and_natural_audio(tmp_path):
    source=tmp_path/'source.png';Image.new('RGB',(640,360),'teal').save(source)
    audio=tmp_path/'source.wav'
    media.encode(['-f','lavfi','-i','sine=frequency=440:duration=2','-ar','48000','-ac','2',audio])
    mixed=tmp_path/'mix.wav';media.normalized_audio(audio,mixed)
    shot=tmp_path/'shot.mp4';media.render_shot(source,shot,2,motion=False)
    output=tmp_path/'video.mp4';media.assemble([shot],mixed,output)
    report=media.technical_report(output,{'duration_sec':2})
    assert all(report['checks'].values()),report
    assert len(media.samples(output,2,tmp_path/'frames',count=3))==3


def test_one_time_action_cannot_freeze_or_loop_implicitly(tmp_path):
    source=tmp_path/'source.png';Image.new('RGB',(640,360),'teal').save(source)
    clip=tmp_path/'short.mp4';media.render_shot(source,clip,1,motion=False)
    with pytest.raises(ValueError):media.render_shot(clip,tmp_path/'long.mp4',3,motion=True)
    media.render_shot(clip,tmp_path/'loop.mp4',3,motion=True,loopable=True)
    assert abs(media.probe(tmp_path/'loop.mp4')['duration_sec']-3)<.05


def test_asset_content_type_and_size_inspection(tmp_path):
    image=tmp_path/'file.jpg';Image.new('RGB',(64,64),'teal').save(image)
    assert media.inspect_asset(image,'image/jpeg')['mime_type']=='image/jpeg'
    with pytest.raises(ValueError):media.inspect_asset(image,'image/png')
    tiny=tmp_path/'tiny.png';Image.new('RGB',(4,4)).save(tiny)
    with pytest.raises(ValueError):media.inspect_asset(tiny,'image/png')
