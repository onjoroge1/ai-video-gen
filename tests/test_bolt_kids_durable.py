"""Use the actual shared DurableRuntime with local storage/test provider responses."""
from pathlib import Path
from types import SimpleNamespace
import pytest

from durable_execution import activate
from test_durable_execution_phase6 import MemoryStore, MemoryBlob, runtime
from bolt_video.kids.models import Episode
from bolt_video.kids.providers import Providers
from test_bolt_kids_contract import resolved_template


def test_speech_restores_on_another_worker_without_provider_purchase(tmp_path,monkeypatch):
    store=MemoryStore(cap=10);blob=MemoryBlob(tmp_path/'blob')
    first=runtime(tmp_path,store,blob,'first');second=runtime(tmp_path,store,blob,'second')
    episode=Episode.model_validate(resolved_template());cue=episode.beats[0].audio[0];character=episode.characters[0]
    manifest={'speech':'gpt-4o-mini-tts-2025-12-15'};p=Providers(first,manifest);calls=[]
    def create(**kwargs):
        calls.append(kwargs);return SimpleNamespace(iter_bytes=lambda:iter([b'fixture-audio-bytes']))
    monkeypatch.setattr(p,'_openai',lambda:SimpleNamespace(audio=SimpleNamespace(speech=SimpleNamespace(create=create))))
    first_path=Path(first.output_dir)/'speech.mp3'
    with activate(first):p.speech(cue,character,first_path)
    q=Providers(second,manifest)
    monkeypatch.setattr(q,'_openai',lambda:(_ for _ in ()).throw(AssertionError('repurchase')))
    second_path=Path(second.output_dir)/'speech.mp3'
    with activate(second):q.speech(cue,character,second_path)
    assert first_path.read_bytes()==second_path.read_bytes() and len(calls)==1
    assert calls[0]['instructions']==character.voice_instructions
    assert calls[0]['voice']==character.voice
    assert store.job['reserved_cost_usd']==0


def test_voice_change_cannot_reuse_wrong_recording(tmp_path,monkeypatch):
    store=MemoryStore(cap=10);blob=MemoryBlob(tmp_path/'blob');rt=runtime(tmp_path,store,blob,'worker')
    episode=Episode.model_validate(resolved_template());cue=episode.beats[0].audio[0];character=episode.characters[0]
    p=Providers(rt,{'speech':'gpt-4o-mini-tts-2025-12-15'});calls=[]
    def create(**kwargs):
        calls.append(kwargs);return SimpleNamespace(iter_bytes=lambda:iter([kwargs['voice'].encode()]))
    monkeypatch.setattr(p,'_openai',lambda:SimpleNamespace(audio=SimpleNamespace(speech=SimpleNamespace(create=create))))
    with activate(rt):
        p.speech(cue,character,Path(rt.output_dir)/'a.mp3')
        p.speech(cue,character.model_copy(update={'voice':'coral'}),Path(rt.output_dir)/'b.mp3')
    assert len(calls)==2
