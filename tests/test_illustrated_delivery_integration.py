"""Provider-fake illustrated delivery with actual orchestrator, gates and FFmpeg.

The synthetic script/research are fixtures, not a Claude-quality measurement. The
database is an in-memory adapter and Blob is a hash-checked filesystem adapter;
this does not prove production credentials, SQL locking or remote persistence.
No generation, storyboard/evidence compiler, audio timing, renderer, durable
worker or Finished Videos route is replaced wholesale.
"""
from collections import Counter
import copy
from datetime import datetime, timezone
import base64
import hashlib
import io
import json
import math
import mimetypes
from pathlib import Path
import struct
from types import SimpleNamespace
import wave

import anyio
import httpx
from PIL import Image, ImageDraw
import pytest

import agent_actions
import app as studio
import db
import durable_execution as durable
import explainer_pipeline as pipeline
import finished_api
import illustrated_story
import private_access
from longform_evidence import compile_evidence_plan
from longform_research import validate_claim_joins, validate_research_dossier
from test_agent_actions import ACTION_ID, FakeActionRepository, _secure_environment
from test_durable_execution_phase6 import MemoryBlob, MemoryStore
from test_illustrated_story import _script


class DeliveryStore(MemoryStore):
    """Persistence boundary only; the actual runtime owns spend and checkpoints."""

    def __init__(self):
        super().__init__(cap=5)
        self.job = None
        self.finished = {}
        self.workers = []
        self.enqueues = 0

    def enqueue(self, **values):
        if self.job:
            assert self.job['id'] == values['job_id']
            return copy.deepcopy(self.job)
        self.enqueues += 1
        self.job = dict(values, id=values['job_id'], status='queued',
                        spent_cost_usd=0, reserved_cost_usd=0, checkpoint={},
                        attempts=0, max_attempts=3, result={})
        return copy.deepcopy(self.job)

    def get_job(self, job_id):
        return copy.deepcopy(self.job) if self.job and self.job['id'] == job_id else None

    def claim(self, *, job_id, worker_id):
        if not self.job or self.job['status'] not in {'queued', 'retry'}:
            return None
        assert self.job['id'] == job_id
        self.workers.append(worker_id)
        self.job.update(status='processing', worker_id=worker_id,
                        attempts=self.job['attempts'] + 1)
        return copy.deepcopy(self.job)

    def heartbeat(self, job_id, worker_id):
        assert self.job['id'] == job_id and self.job['worker_id'] == worker_id

    def set_status(self, job_id, status, *, worker_id, error=None, result=None):
        self.heartbeat(job_id, worker_id)
        self.job.update(status=status, error=error)
        if result:
            self.job['result'].update(result)

    def yield_job(self, job_id, *, worker_id, checkpoint):
        self.heartbeat(job_id, worker_id)
        self.job.update(status='queued', checkpoint=checkpoint,
                        attempts=self.job['attempts'] - 1, worker_id=None)
        self.job['result']['continuation_count'] = 1
        return copy.deepcopy(self.job)

    def finalize_finished(self, job_id, record, *, worker_id):
        self.heartbeat(job_id, worker_id)
        assert job_id not in self.finished
        self.finished[job_id] = copy.deepcopy(record)
        self.job.update(status=record['status'], result=record['metadata'])

    def finished_get(self, job_id):
        return copy.deepcopy(self.finished.get(job_id))

    def finished_list(self, **kwargs):
        return copy.deepcopy(list(self.finished.values()))

    def events(self, job_id, after=0, limit=200, **kwargs):
        return [{'seq': index + 1, 'event_type': kind, 'data': data, 'details': details}
                for index, (kind, data, details) in enumerate(self.events_seen)
                if index + 1 > after][:limit]


class DeliveryBlob(MemoryBlob):
    def upload(self, local_path, remote_path):
        artifact = super().upload(local_path, remote_path)
        artifact.update(access='private', content_type=(
            mimetypes.guess_type(remote_path)[0] or 'application/octet-stream'))
        return artifact


class DeliveryActions(FakeActionRepository):
    def claim(self, action_id, *, claim_token):
        action = super().claim(action_id, claim_token=claim_token)
        self.action['job_id'] = __import__('hashlib').sha256(action_id.encode()).hexdigest()[:24]
        return copy.deepcopy(self.action)


def fixture_story():
    """Clearly synthetic narrative with every factual join and state made explicit."""
    script = _script(environments=['workshop'])
    script['_story_engine'] = 'backfiring_solution'
    script['_story_contract']['final_callback_object'] = 'the workshop table'
    claims, citations = [], []
    for index, scene in enumerate(script['scenes']):
        # Unique words prevent an artificial repeated anchor from matching twice.
        if scene['causal_role'] not in {'hinge', 'tool'}:
            count = max(10, len(scene['narration'].split()))
            scene['narration'] = ' '.join(f'workshop{index}word{n}' for n in range(count)) + '.'
        text = scene['narration']
        scene['image_prompt'] = 'A red workshop table with a visibly changing counter.'
        scene['mascot_present'] = index == 0
        scene['evidence_id'] = f'e{index}'
        scene['claim_refs'] = [{'claim_id': f'c{index}', 'narration_phrase': text,
                                'evidence_id': f'e{index}'}]
        url = f'https://fixture.example.edu/workshop/{index}'
        citations.append({'url': url, 'cited_text': text})
        claims.append(dict(claim_id=f'c{index}', claim=text, source_url=url,
                           support_quote=text, source_type='primary', confidence='high',
                           geographic_scope='local', timescale='one demonstration',
                           assumptions=[], allowed_exaggeration=False, material=True))
        words = text.split()
        scene['visual_beats'] = []
        starts = [0, len(words) // 2] if index < 3 else [0]
        for state_index, start in enumerate(starts):
            beat = dict(anchor_phrase=' '.join(words[start:start + 3]), purpose='evidence',
                        visual=f'Table counter at state {index}-{state_index}',
                        source='master' if state_index == 0 else 'distinct',
                        state_before='A workshop table with an empty counter',
                        state_after=f'Table counter at state {index}-{state_index}',
                        required_objects=['workshop table', 'counter'], forbidden_objects=[])
            if index == 0 and state_index == 0:
                beat.update(purpose='action', pure_evidence=False, bolt_visible=True,
                            bolt_action='measures the workshop table')
            scene['visual_beats'].append(beat)
    dossier = dict(version=1, topic=script['title'], claims=claims,
                   citation_urls=[c['url'] for c in citations], citation_records=citations)
    script['_research_dossier'] = dossier
    assert validate_research_dossier(dossier)['passed']
    assert validate_claim_joins(script, dossier)['passed']
    assert illustrated_story.build_storyboard(script, script['title'])['validation']['passed']
    assert compile_evidence_plan(script)['validation']['passed'], compile_evidence_plan(script)['validation']
    return script, dossier


class FakeMediaSDK:
    """Replace SDK responses while retaining real paid-stage adapters and codecs."""

    def __init__(self, script):
        self.calls = Counter()
        self.words_by_hash = {}
        self.seconds_per_word = 90 / sum(len(s['narration'].split()) for s in script['scenes'])
        self.audio = SimpleNamespace(speech=SimpleNamespace(create=self.speech),
                                     transcriptions=SimpleNamespace(create=self.transcribe))
        self.images = SimpleNamespace(generate=self.image, edit=self.image)

    def speech(self, **request):
        key = request['extra_headers']['Idempotency-Key']
        self.calls[('tts', key)] += 1
        text = request['input']
        duration = len(text.split()) * self.seconds_per_word
        frequency = 220 + int(hashlib.sha256(text.encode()).hexdigest()[:4], 16) % 500
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as audio:
            audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            audio.writeframes(b''.join(struct.pack('<h', int(1000 * math.sin(
                2 * math.pi * frequency * i / 8000))) for i in range(int(duration * 8000))))
        data = stream.getvalue()
        self.words_by_hash[hashlib.sha256(data).hexdigest()] = text.split()
        return SimpleNamespace(iter_bytes=lambda: iter([data]))

    def transcribe(self, **request):
        data = request['file'].read()
        words = self.words_by_hash[hashlib.sha256(data).hexdigest()]
        return SimpleNamespace(words=[SimpleNamespace(word=word,
            start=index * self.seconds_per_word,
            end=(index + 1) * self.seconds_per_word) for index, word in enumerate(words)])

    def image(self, **request):
        key = request['extra_headers']['Idempotency-Key']
        self.calls[('image', key)] += 1
        # Real nonuniform pixels so FFmpeg's controlled movement remains observable.
        img = Image.new('RGB', (320, 180), '#e8d6b0')
        draw = ImageDraw.Draw(img)
        draw.rectangle((40, 60, 250, 140), fill='#934141')
        draw.ellipse((90, 20, 150, 90), fill='#315c75')
        stream = io.BytesIO()
        img.save(stream, format='PNG')
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(
            stream.getvalue()).decode())], usage=SimpleNamespace(
                input_tokens=0, output_tokens=100, input_tokens_details=None))


@pytest.mark.parametrize("restart_boundary", ["image", "render"])
def test_illustrated_request_survives_restart_and_delivers_mp4(monkeypatch, tmp_path, restart_boundary):
    _secure_environment(monkeypatch)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-provider-key')
    monkeypatch.setenv('OPENAI_API_KEY', 'fake-provider-key')
    monkeypatch.setenv('SCRIPT_PROVIDER', 'anthropic')
    monkeypatch.setenv('DURABLE_EXECUTION', '1')
    # Explicitly retain the deployed sourcing and illustrated gate defaults.
    for name in ('ILLUSTRATED_STORYBOARD_HARD', 'CLAIM_LEDGER_HARD', 'LONGFORM_RESEARCH_MODE',
                 'DIAGNOSTIC_RENDER', 'RUNTIME_HARD'):
        monkeypatch.delenv(name, raising=False)
    script, dossier = fixture_story()
    sdk = FakeMediaSDK(script)
    store, blob = DeliveryStore(), DeliveryBlob(tmp_path / 'blob')
    actions = DeliveryActions()
    monkeypatch.setattr(agent_actions, 'repository', lambda: actions)
    monkeypatch.setattr(studio, '_durable_components', lambda: (store, blob))
    monkeypatch.setattr(studio, '_require_render_storage', lambda: None)
    monkeypatch.setattr(studio, '_sweep_old_temp', lambda *_a, **_k: None)
    monkeypatch.setattr(db, 'db_enabled', lambda: True)
    monkeypatch.setattr(db, 'finished_video_get', store.finished_get)
    monkeypatch.setattr(finished_api, 'PostgresStore', lambda: store)
    monkeypatch.setattr(finished_api, 'BlobStore', lambda: blob)
    monkeypatch.setattr(pipeline, '_openai', lambda: sdk)

    def unexpected_provider():
        raise AssertionError('Unexpected live language-provider boundary')

    monkeypatch.setattr(pipeline, '_claude', unexpected_provider)
    monkeypatch.setattr(pipeline, '_anthropic_native', unexpected_provider)

    def fixture_provider(kind, value, request):
        rt = durable.current()
        result, _, _ = rt.paid_value(stage_key=f'fixture:{kind}', provider='fixture-claude',
            request=request, estimated_cost=.01,
            operation=lambda _key: (copy.deepcopy(value), .01))
        return copy.deepcopy(result)

    monkeypatch.setattr(pipeline, 'generate_research_dossier',
        lambda question, **kwargs: fixture_provider('research', dossier, {'topic': question}))
    monkeypatch.setattr(pipeline, 'generate_script',
        lambda question, *args, **kwargs: fixture_provider('script', script, {'topic': question}))
    monkeypatch.setattr(pipeline, 'grade_script', lambda *_a, **_k: None)
    monkeypatch.setattr(pipeline, 'factcheck_script',
                        lambda value, *_a, **_k: (value, [], 0))
    monkeypatch.setattr(pipeline, 'generate_description', lambda *_a, **_k: None)
    monkeypatch.setattr(pipeline, 'generate_thumbnail', lambda *_a, **_k: None)
    monkeypatch.setattr(pipeline, 'FORMATS', {
        **pipeline.FORMATS, 'landscape': {
            **pipeline.FORMATS['landscape'], 'w': 320, 'h': 180, 'captions': 'none'}})
    # The real animatic renderer is bounded to test resolution; no FFmpeg stage is stubbed.
    original_animatic = pipeline.render_low_cost_animatic
    monkeypatch.setattr(pipeline, 'render_low_cost_animatic', lambda *args, **kwargs:
        original_animatic(*args, **dict(kwargs, width=320, height=180)))
    interrupted = []

    def verify_image(*args, **kwargs):
        if restart_boundary == "image" and not interrupted:
            assert any(s['provider'] == 'openai-images' and s['status'] == 'completed'
                       for s in store.stages.values())
            interrupted.append(True)
            raise durable.CooperativeYield('after-first-committed-image')
        return {'passed': True, 'visible_information': True, 'reasons': []}

    monkeypatch.setattr(pipeline, 'verify_evidence_asset', verify_image)
    original_segment = pipeline._make_scene_segment
    def encode_then_interrupt(*args, **kwargs):
        original_segment(*args, **kwargs)
        if restart_boundary == "render" and not interrupted:
            assert any(s['provider'] == 'ffmpeg' and s['status'] == 'completed'
                       for s in store.stages.values())
            interrupted.append(True)
            raise durable.CooperativeYield('after-first-committed-render')
    monkeypatch.setattr(pipeline, '_make_scene_segment', encode_then_interrupt)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app),
                                     base_url='http://test') as client:
            created = await client.post('/api/agent/actions', json={
                'operation': 'generic_illustrated', 'topic': script['title'],
                'duration_sec': 90, 'cost_ceiling_usd': 5})
            assert created.status_code == 200, created.text
            proposal = created.json()
            assert not sdk.calls and not store.stages and store.job is None
            token = proposal['claim_token']
            client.cookies.set(private_access.COOKIE_NAME, private_access.create_session('owner'))
            approved = await client.post(f'/api/agent/actions/{ACTION_ID}/approve', json={
                'spec_sha256': proposal['spec_sha256'], 'cost_ceiling_usd': 5})
            assert approved.status_code == 200, approved.text
            executed = await client.post(f'/api/agent/actions/{ACTION_ID}/execute',
                                        headers={'Authorization': f'Bearer {token}'})
            assert executed.status_code == 200, executed.text
            job_id = store.job['id']
            first = await studio._run_durable_explainer_worker(job_id)
            assert first.get('continued'), first
            assert store.job['status'] == 'queued' and not store.finished
            assert store.job['checkpoint']['sha256']
            first_calls = copy.deepcopy(sdk.calls)
            image_calls = sum(n for (kind, _), n in first_calls.items() if kind == 'image')
            assert image_calls == 1 if restart_boundary == 'image' else image_calls > 1
            assert sum(n for (kind, _), n in first_calls.items() if kind == 'tts') == 10
            # A fresh worker gets a new temporary directory and restores the real checkpoint.
            second = await studio._run_durable_explainer_worker(job_id)
            assert store.job['status'] in {'done', 'degraded'}, second
            if restart_boundary == 'render':
                assert any(kind == 'stage_reused' and details.get('provider') == 'ffmpeg'
                           for kind, _, details in store.events_seen)
            assert len(set(store.workers)) == 2 and store.enqueues == 1
            assert all(sdk.calls[key] == count for key, count in first_calls.items())
            assert max(sdk.calls.values()) == 1
            assert store.job['spent_cost_usd'] < store.job['max_cost_usd'] == 5
            assert store.job['reserved_cost_usd'] == pytest.approx(0)
            listing = await client.get('/api/finished')
            assert listing.status_code == 200, listing.text
            assert [video['id'] for video in listing.json()['videos']] == [job_id]
            record = (await client.get(f'/api/finished/{job_id}')).json()
            assert record['metadata']['actual_cost'] == pytest.approx(store.job['spent_cost_usd'])
            assert record['metadata']['scene_count'] == 10
            assert record['metadata']['visual_style'] == 'illustrated_story'
            assert {'video', 'storyboard', 'claims', 'research', 'timing',
                    'generation-manifest'} <= record['artifacts'].keys()
            delivered = await client.get(f'/api/finished/{job_id}/artifact/video?download=true')
            assert delivered.status_code == 200, delivered.text[:300]
            assert delivered.headers['content-type'] == 'video/mp4'
            assert hashlib.sha256(delivered.content).hexdigest() == record['artifacts']['video']['sha256']
            video_path = tmp_path / 'delivered.mp4'
            video_path.write_bytes(delivered.content)
            assert 85 <= pipeline._audio_dur(str(video_path)) <= 100
            board_path = Path(record['artifacts']['storyboard']['url'])
            assert json.loads(board_path.read_text())['validation']['passed']
            claim_path = Path(record['artifacts']['claims']['url'])
            assert json.loads(claim_path.read_text())['passed']
    anyio.run(run)
