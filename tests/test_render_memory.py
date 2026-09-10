"""Bound real 1080p encoding and recover only interrupted, unbilled local work."""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest
from PIL import Image, ImageDraw

import durable_execution as durable
import explainer_pipeline as ep
from test_durable_execution_phase6 import MemoryBlob, MemoryStore, runtime


def test_crop_preserves_every_visible_pixel_and_origin(tmp_path):
    path = tmp_path / 'overlay.png'
    original = Image.new('RGBA', (1920, 1080))
    ImageDraw.Draw(original).rounded_rectangle((513, 731, 1407, 851), radius=20,
                                               fill=(220, 110, 30, 170))
    original.save(path)
    x, y = ep._crop_overlay(str(path))
    restored = Image.new('RGBA', original.size)
    with Image.open(path) as cropped:
        assert cropped.width * cropped.height < original.width * original.height / 10
        restored.paste(cropped, (x, y))
    assert restored.tobytes() == original.tobytes()
    Image.new('RGBA', (1920, 1080)).save(path)
    assert ep._crop_overlay(str(path)) == (0, 0)
    with Image.open(path) as empty:
        assert empty.size == (1, 1) and empty.getpixel((0, 0))[3] == 0


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux reports child peak RSS in KiB')
def test_full_resolution_caption_render_stays_below_memory_budget(tmp_path, monkeypatch):
    # Separate process gives this encode its own measured peak. Real caption PNGs,
    # Ken Burns, headline fade and H.264 run through the production renderer.
    import media_binaries
    monkeypatch.setenv('FFMPEG_BIN', media_binaries.bundled_ffmpeg())
    code = '''
import json, resource, sys
from pathlib import Path
from PIL import Image, ImageDraw
import explainer_pipeline as ep
import media_binaries
root=Path(sys.argv[1])
image=root/'source.png'
picture=Image.new('RGB',(1536,1024),(40,60,80))
ImageDraw.Draw(picture).rectangle((300,200,1000,800),fill=(200,140,70))
picture.save(image)
video=root/'scene.mp4'
ep._make_scene_segment(str(image),'unused',str(video),'A changed ecosystem','A supported story',
    duration_override=3,captions='headline_karaoke',
    word_times=[(f'Caption phrase {i}',i/4,(i+1)/4) for i in range(12)])
print(json.dumps({'peak_kib':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
                  'duration':ep._audio_dur(str(video)), 'bytes':video.stat().st_size}))
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)],
                            capture_output=True, text=True, check=True, timeout=180)
    measured = json.loads(result.stdout.splitlines()[-1])
    assert 0 < measured['peak_kib'] < 800 * 1024, measured
    assert measured['duration'] == pytest.approx(3, abs=.05)
    assert measured['bytes'] > 30_000


def test_xfade_batches_keep_every_scene_and_transition(tmp_path):
    videos = []
    seconds = .5
    for index in range(5):
        path = str(tmp_path / f'{index}.mp4')
        ep._run_ffmpeg([ep._ffmpeg_bin(), '-y', '-f', 'lavfi', '-i',
                       f'color=c=0x{index * 40:02x}8050:s=320x180:r=30:d={seconds + ep.FADE_DUR}',
                       '-c:v', 'libx264', '-pix_fmt', 'yuv420p', path])
        videos.append(path)
    final = str(tmp_path / 'joined.mp4')
    ep._xfade_concat(videos, [seconds] * 5, final, str(tmp_path))
    assert ep._audio_dur(final) == pytest.approx(5 * seconds + ep.FADE_DUR, abs=.1)
    # The final scene must survive the recursive join, including its hold.
    frame = subprocess.run([ep._ffmpeg_bin(), '-nostdin', '-sseof', '-0.1', '-i', final,
                            '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                           capture_output=True, check=True, timeout=30).stdout
    assert frame and frame[0] > 130


def test_script_is_durable_before_media_and_storage_failure_stops_handoff(tmp_path, monkeypatch):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / 'blob')
    worker = runtime(tmp_path, store, blob, 'worker-a')
    state = Path(worker.output_dir) / '_state.json'
    state.parent.mkdir(parents=True, exist_ok=True)
    script = {'scenes': [{'narration': 'Saved before media.', 'claim_refs': ['c1']}]}
    with durable.activate(worker):
        ep._save_script_checkpoint(str(state), script, 'illustrated', None, 'landscape',
                                   label='script-ready')
    checkpoint = copy.deepcopy(store.job['checkpoint'])
    state.unlink()
    second = runtime(tmp_path, store, blob, 'worker-b')
    second.restore_checkpoint(checkpoint)
    assert json.loads((Path(second.output_dir) / '_state.json').read_text())['script'] == script
    assert not store.stages
    monkeypatch.setattr(blob, 'upload', Mock(side_effect=durable.StorageUnavailable('offline')))
    with durable.activate(worker), pytest.raises(durable.StorageUnavailable):
        ep._save_script_checkpoint(str(state), script, 'illustrated', None, 'landscape',
                                   label='narration-ready')
    assert store.job['checkpoint'] == checkpoint


SHA = 'a' * 64
KEY = 'render:' + 'b' * 32


@pytest.mark.parametrize('change', [
    'none', 'processing', 'lease', 'used', 'stale', 'cap', 'reserved', 'content_error',
    'no_stage', 'paid_stage', 'stage_reservation', 'stage_charge', 'wrong_key', 'failed_stage',
])
def test_recovery_is_atomic_and_never_reopens_paid_work(change):
    job = {'id': 'same-job', 'status': 'error', 'error': 'Maximum worker attempts exhausted',
           'checkpoint': {'sha256': SHA}, 'result': {}, 'spent_cost_usd': 2.9473,
           'reserved_cost_usd': 0, 'max_cost_usd': 5}
    stages = [{'stage_key': KEY, 'provider': 'ffmpeg', 'status': 'running',
               'reserved_cost_usd': 0, 'actual_cost_usd': 0}]
    if change == 'processing': job['status'] = 'processing'
    if change == 'lease': job['lease_owner'] = 'live-worker'
    if change == 'used': job['result']['render_memory_recovery_v1'] = {'done': True}
    if change == 'stale': job['checkpoint']['sha256'] = 'c' * 64
    if change == 'cap': job['spent_cost_usd'] = 5
    if change == 'reserved': job['reserved_cost_usd'] = .1
    if change == 'content_error': job['error'] = 'STORY_SPINE_UNSUPPORTED'
    if change == 'no_stage': stages = []
    if change == 'paid_stage': stages.append(dict(stages[0], provider='anthropic'))
    if change == 'stage_reservation': stages[0]['reserved_cost_usd'] = .1
    if change == 'stage_charge': stages[0]['actual_cost_usd'] = .1
    if change == 'wrong_key': stages[0]['stage_key'] = 'image:abc'
    if change == 'failed_stage': stages[0]['status'] = 'failed'
    before = copy.deepcopy((job, stages))
    cursor = Mock()
    cursor.fetchone.side_effect = [job, {**job, 'status': 'queued'}]
    cursor.fetchall.return_value = stages
    store = object.__new__(durable.PostgresStore)
    @contextmanager
    def transaction(): yield None, cursor
    store._tx = transaction
    store._row = lambda _cursor, row: row
    store.append_event = Mock()
    if change != 'none':
        with pytest.raises(durable.DurableExecutionError):
            store.rearm_local_render_failure('same-job', expected_checkpoint_sha256=SHA)
        assert not any(call.args[0].lstrip().startswith('UPDATE ')
                       for call in cursor.execute.call_args_list)
    else:
        assert store.rearm_local_render_failure('same-job', expected_checkpoint_sha256=SHA)['status'] == 'queued'
        updates = [call.args for call in cursor.execute.call_args_list
                   if call.args[0].lstrip().startswith('UPDATE ')]
        assert len(updates) == 2
        assert updates[0][1] == ('same-job', [KEY])
        assert 'attempts+1' in updates[1][0]
        assert json.loads(updates[1][1][0])['render_memory_recovery_v1']['checkpoint_sha256'] == SHA
        assert all(field not in updates[0][0] + updates[1][0]
                   for field in ('spent_cost_usd=', 'max_cost_usd=', 'request=', 'actual_cost_usd='))
    assert (job, stages) == before


@pytest.mark.parametrize('authorized,used,eligible', [(True, False, True), (False, False, True),
                                                     (True, True, True), (True, False, False)])
def test_dispatch_reuses_exact_action_and_requires_local_stage_reconciliation(monkeypatch,
                                                                            authorized, used, eligible):
    import anyio
    import httpx
    import agent_actions
    import app as studio
    from test_agent_actions import ACTION_ID, FakeActionRepository, _secure_environment
    _secure_environment(monkeypatch)
    repository = FakeActionRepository()
    repository.action = {'action_id': ACTION_ID, 'operation': 'generic_illustrated',
        'status': 'queued', 'job_id': 'same-job',
        'claim_token_sha256': agent_actions.token_digest(ACTION_ID)}
    job = {'id': 'same-job', 'status': 'error', 'error': 'Maximum worker attempts exhausted',
           'checkpoint': {'sha256': SHA},
           'result': {'render_memory_recovery_v1': {'done': True}} if used else {}}
    store = Mock()
    store.get_job.return_value = job
    if not eligible:
        store.rearm_local_render_failure.side_effect = durable.DurableExecutionError('Ambiguous paid stage')
    monkeypatch.setattr(agent_actions, 'repository', lambda: repository)
    monkeypatch.setattr(studio, '_durable_components', lambda: (store, object()))
    dispatched = []
    async def worker(job_id):
        dispatched.append(job_id)
        return {'claimed': not used}
    monkeypatch.setattr(studio, '_run_durable_explainer_worker', worker)
    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app),
                                     base_url='http://test') as client:
            response = await client.post(f'/api/agent/actions/{ACTION_ID}/dispatch',
                headers={'Authorization': f'Bearer {ACTION_ID if authorized else "wrong"}'})
            assert response.status_code == (403 if not authorized else 409 if not eligible else 200)
    anyio.run(request)
    if authorized and not used:
        store.rearm_local_render_failure.assert_called_once_with('same-job', expected_checkpoint_sha256=SHA)
    else:
        store.rearm_local_render_failure.assert_not_called()
    assert dispatched == (['same-job'] if authorized and eligible else [])


def test_static_caption_inputs_remain_visible_only_in_their_time_window(tmp_path, monkeypatch):
    source = tmp_path / 'background.png'
    Image.new('RGB', (320, 180), (0, 0, 0)).save(source)
    def caption(text, width, height, output, **_kwargs):
        image = Image.new('RGBA', (width, height))
        ImageDraw.Draw(image).rectangle((20, 110, 120, 150), fill=text)
        image.save(output)
    monkeypatch.setattr(ep, '_make_caption_png', caption)
    video = str(tmp_path / 'captions.mp4')
    ep._make_scene_segment(str(source), 'unused', video, '', '', vw=320, vh=180,
                           captions='karaoke', duration_override=2, motion='locked',
                           word_times=[('#ff0000', .2, .7), ('#00ff00', 1.2, 1.7)])
    for second, expected in [(.4, (255, 0, 0)), (.9, (0, 0, 0)), (1.4, (0, 255, 0))]:
        data = ep._run_ffmpeg([ep._ffmpeg_bin(), '-ss', str(second), '-i', video,
                               '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']).stdout
        offset = (130 * 320 + 60) * 3
        assert tuple(data[offset:offset + 3]) == pytest.approx(expected, abs=5)
