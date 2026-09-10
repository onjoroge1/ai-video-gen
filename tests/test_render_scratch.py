"""Scratch ownership, old cache compatibility and a real nested worker handoff."""
import copy
import inspect
from pathlib import Path
import time

import pytest

import durable_execution as durable
import explainer_pipeline as ep
import render_cache
from test_durable_execution_phase6 import MemoryBlob, MemoryStore, runtime


@pytest.mark.parametrize('failure', [None, OSError('disk full'), durable.CooperativeYield('next')])
def test_scratch_is_reclaimed_without_deleting_inputs_or_prior_output(tmp_path, failure):
    source = tmp_path / 'paid.png'
    source.write_bytes(b'paid source')
    output = tmp_path / 'finished.mp4'
    output.write_bytes(b'prior output')
    @render_cache.durable_render
    def assemble(source, output_path, tmp_dir):
        work = Path(tmp_dir)
        assert work != tmp_path and Path(output_path).parent == work
        (work / 'concat.mp4').write_bytes(b'x' * 1_000_000)
        Path(output_path + '.caption.png').write_bytes(b'caption')
        Path(output_path).write_bytes(Path(source).read_bytes())
        if failure:
            raise failure
    if failure:
        with pytest.raises(type(failure)):
            assemble(str(source), str(output), str(tmp_path))
    else:
        assemble(str(source), str(output), str(tmp_path))
    assert set(tmp_path.iterdir()) == {source, output}
    assert source.read_bytes() == b'paid source'
    assert output.read_bytes() == (b'prior output' if failure else b'paid source')


def test_pr108_completed_render_reuses_its_original_key(tmp_path, monkeypatch):
    store, blob = MemoryStore(), MemoryBlob(tmp_path / 'blob')
    worker = runtime(tmp_path, store, blob, 'worker')
    worker.cache_local_renders = True
    source = tmp_path / 'source.png'
    source.write_bytes(b'unchanged image')
    output = Path(worker.output_dir) / 'scene.mp4'
    args = (str(source), 'unused', str(output), '', '')
    kwargs = {'duration_override': 2, 'captions': 'none'}
    bound = inspect.signature(ep._make_scene_segment).bind(*args, **kwargs)
    bound.apply_defaults()
    inputs = dict(bound.arguments)
    inputs.pop('output_path')
    # This is PR108's exact request, including its whole-file source digest.
    request = {'renderer': '_make_scene_segment',
               'version': '5db0f3871aabd7f27795d8151f0ecec55cb009a42e43902e841df5f560bb1201',
               'inputs': render_cache._content_identity(inputs)}
    key = 'render:' + durable.canonical_hash(request)[:32]
    def old_encode(_key):
        output.write_bytes(b'already encoded')
        return {}, 0
    worker.paid_file(stage_key=key, provider='ffmpeg', request=request, estimated_cost=0,
                     output_path=str(output), operation=old_encode)
    before = copy.deepcopy(store.stages)
    output.unlink()
    monkeypatch.setattr(ep, '_run_ffmpeg', lambda *a, **k: pytest.fail('re-encoded saved stage'))
    with durable.activate(worker):
        ep._make_scene_segment(*args, **kwargs)
    assert output.read_bytes() == b'already encoded'
    assert store.stages == before
    assert store.job['spent_cost_usd'] == 0


@pytest.mark.parametrize('authorized,eligible', [(True, True), (False, True), (True, False)])
def test_disk_dispatch_cannot_fall_through_to_unbounded_storage_retry(monkeypatch, authorized, eligible):
    import anyio
    import httpx
    from unittest.mock import Mock
    import agent_actions
    import app as studio
    from test_agent_actions import ACTION_ID, FakeActionRepository, _secure_environment
    _secure_environment(monkeypatch)
    repository = FakeActionRepository()
    repository.action = {'action_id': ACTION_ID, 'operation': 'generic_illustrated',
        'status': 'queued', 'job_id': 'same-job',
        'claim_token_sha256': agent_actions.token_digest(ACTION_ID)}
    store = Mock()
    store.get_job.return_value = {'id': 'same-job', 'status': 'storage_error',
        'error': '[Errno 28] No space left on device', 'checkpoint': {'sha256': 'a' * 64}}
    if not eligible:
        store.rearm_local_render_failure.side_effect = durable.DurableExecutionError('Recovery already used')
    monkeypatch.setattr(agent_actions, 'repository', lambda: repository)
    monkeypatch.setattr(studio, '_durable_components', lambda: (store, object()))
    dispatched = []
    async def worker(job_id):
        dispatched.append(job_id)
        return {'claimed': True}
    monkeypatch.setattr(studio, '_run_durable_explainer_worker', worker)
    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app),
                                     base_url='http://test') as client:
            response = await client.post(f'/api/agent/actions/{ACTION_ID}/dispatch',
                headers={'Authorization': f'Bearer {ACTION_ID if authorized else "wrong"}'})
            assert response.status_code == (403 if not authorized else 200 if eligible else 409)
    anyio.run(request)
    if authorized:
        store.rearm_local_render_failure.assert_called_once_with('same-job',
            expected_checkpoint_sha256='a' * 64, failure_kind='disk')
    else:
        store.rearm_local_render_failure.assert_not_called()
    store.requeue.assert_not_called()
    assert dispatched == (['same-job'] if authorized and eligible else [])


def test_nested_join_resumes_after_yield_and_cleans_all_intermediates(tmp_path, monkeypatch):
    videos = []
    for index in range(5):
        clip = str(tmp_path / f'input{index}.mp4')
        ep._run_ffmpeg([ep._ffmpeg_bin(), '-y', '-f', 'lavfi', '-i',
                       f'color=c=0x{index * 40:02x}8050:s=320x180:r=30:d={.5 + ep.FADE_DUR}',
                       '-c:v', 'libx264', '-pix_fmt', 'yuv420p', clip])
        videos.append(clip)
    source_hashes = [durable.file_sha256(path) for path in videos]
    store, blob = MemoryStore(), MemoryBlob(tmp_path / 'blob')
    first = runtime(tmp_path, store, blob, 'first')
    first.cache_local_renders = True
    first.time_budget_seconds = 60
    complete = store.complete_stage
    def interrupt_after_child(*args, **kwargs):
        result = complete(*args, **kwargs)
        first._started_at = time.monotonic() - 61
        return result
    monkeypatch.setattr(store, 'complete_stage', interrupt_after_child)
    with durable.activate(first), pytest.raises(durable.CooperativeYield):
        ep._xfade_concat(videos, [.5] * 5, str(Path(first.output_dir) / 'joined.mp4'), first.output_dir)
    assert list(Path(first.output_dir).iterdir()) == []
    assert sorted(s['status'] for s in store.stages.values()) == ['completed', 'retry']
    committed = next(key for key, stage in store.stages.items() if stage['status'] == 'completed')
    artifact = copy.deepcopy(store.stages[committed]['artifact'])
    monkeypatch.setattr(store, 'complete_stage', complete)
    second = runtime(tmp_path, store, blob, 'second')
    second.cache_local_renders = True
    joined = Path(second.output_dir) / 'joined.mp4'
    with durable.activate(second):
        ep._xfade_concat(videos, [.5] * 5, str(joined), second.output_dir)
    assert list(Path(second.output_dir).iterdir()) == [joined]
    assert ep._audio_dur(str(joined)) == pytest.approx(2.5 + ep.FADE_DUR, abs=.1)
    assert store.stages[committed]['artifact'] == artifact
    assert any(kind == 'stage_reused' and data == committed for kind, data, _ in store.events_seen)
    assert all(stage['status'] == 'completed' for stage in store.stages.values())
    assert [durable.file_sha256(path) for path in videos] == source_hashes
    assert store.job['spent_cost_usd'] == 0
