"""Channel routing and cache migration, with no paid provider or external storage calls."""
import json
from types import SimpleNamespace

import anyio
import httpx
import pytest

import app
import db
import explainer_pipeline as ep
import reference_corpus as corpus
import topic_fit as tf


def response(value):
    return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(value))],
                           usage=SimpleNamespace(input_tokens=10, output_tokens=10))


def test_catalogue_and_request_validation_are_free(monkeypatch):
    monkeypatch.delenv('APP_PASSWORD', raising=False)
    monkeypatch.delenv('APP_SHARED_SECRET', raising=False)
    monkeypatch.delenv('VERCEL', raising=False)
    monkeypatch.setattr(ep, '_claude', lambda: pytest.fail('read-only catalogue bought a call'))
    async def queue(request, background_tasks):
        return {'request': request.model_dump()}
    monkeypatch.setattr(app, '_enqueue_explainer_request', queue)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url='http://test') as client:
            catalogue = await client.get('/api/explainer/channels')
            assert catalogue.status_code == 200
            assert [c['id'] for c in catalogue.json()['channels']] == ['world', 'history']
            for style, fmt in [('cinematic', 'landscape'), ('illustrated_story', 'social')]:
                result = await client.post('/api/explainer/generate', json={
                    'question': 'Hanoi rat bounty', 'topic_channel': 'world',
                    'visual_style': style, 'video_format': fmt})
                assert result.status_code == 400
                assert 'landscape' in result.json()['detail']
            result = await client.post('/api/explainer/generate', json={
                'question': 'Hanoi rat bounty', 'topic_channel': 'world',
                'visual_style': 'illustrated_story', 'video_format': 'landscape',
                'duration_sec': 90, 'motion_mode': 'stills'})
            assert result.status_code == 200
            assert result.json()['request']['topic_channel'] == 'world'
            assert result.json()['request']['visual_style'] == 'illustrated_story'
    anyio.run(run)


def test_old_science_cache_cannot_reappear_after_deploy(monkeypatch, tmp_path):
    path = tmp_path / 'topics.json'
    monkeypatch.setattr(app, '_TRENDING_FILE', str(path))
    monkeypatch.setattr(db, 'db_enabled', lambda: True)
    old = {'roi_version': 2, 'channels': [{'label': 'Bolt Explains — Earth'}],
           'questions': [{'question': 'What is gravity?'}]}
    path.write_text(json.dumps(old))
    monkeypatch.setattr(db, 'cache_get', lambda _key: old)
    assert app._load_trending()['questions'] == []
    current = {'roi_version': 2, 'editorial_version': tf.EDITORIAL_VERSION,
               'channels': [{'label': 'Bolt Explains History'}], 'questions': []}
    path.write_text(json.dumps(current))
    assert app._load_trending() == current


def test_refresh_keeps_supported_format_and_channel_metadata(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(db, 'db_enabled', lambda: False)
    monkeypatch.setattr(app, 'FINISHED_DIR', str(tmp_path))
    monkeypatch.setattr(app, '_TRENDING_FILE', str(tmp_path / 'topics.json'))
    monkeypatch.setattr(app, '_metrics_json_load', lambda: [])
    def generate(channel, **kwargs):
        calls.append(channel)
        return [dict(tf.TOPIC_CANDIDATES[channel][0])]
    monkeypatch.setattr(ep, 'generate_causal_topics', generate)
    monkeypatch.setattr(ep, 'validate_topics_youtube', lambda topics, **kwargs: topics)
    monkeypatch.setattr(ep, 'suggest_titles', lambda topics: topics)
    monkeypatch.setattr(ep, 'youtube_validation_active', lambda: False)
    data = app._refresh_trending()
    assert calls == ['world', 'history']
    assert len(data['questions']) == 2
    assert {t['topic_channel'] for t in data['questions']} == {'world', 'history'}
    assert all(t['visual_style'] == 'illustrated_story' and t['content_format'] == 'long'
               for t in data['questions'])
    assert app._load_trending() == data


def test_animal_priority_is_checked_against_selected_channel(monkeypatch):
    monkeypatch.setenv('TOPIC_FIT', 'on')
    seen = []
    def create(**call):
        seen.append(call['messages'][0]['content'])
        return response({'verdict': 'fits', 'channel': 'world', 'episode': 'sparrow campaign',
                         'aftermath': 'ecological harm', 'reason': 'animal intervention'})
    monkeypatch.setattr(ep, '_claude', lambda: SimpleNamespace(messages=SimpleNamespace(create=create)))
    with pytest.raises(ValueError, match='Bolt Explains the World'):
        ep.screen_topic_fit('Sparrow campaign', channel='history', log=lambda _: None)
    assert 'HISTORY channel' in seen[0]
    assert ep.screen_topic_fit('Sparrow campaign', channel='world', log=lambda _: None)['verdict'] == 'fits'


def test_rejection_does_not_reintroduce_the_inversion_rule(monkeypatch):
    monkeypatch.setenv('TOPIC_FIT', 'on')
    monkeypatch.setattr(ep, '_claude', lambda: SimpleNamespace(messages=SimpleNamespace(
        create=lambda **_: response({'verdict': 'no_story', 'channel': 'neither',
                                    'reason': 'unrealized proposal'}))))
    with pytest.raises(ValueError, match='Harm does not have to reverse'):
        ep.screen_topic_fit('American hippo-import proposal', log=lambda _: None)


def test_ecosystem_path_has_its_own_contract_and_no_borrowed_blueprint(monkeypatch):
    import story_engines as engines
    import story_compiler as compiler
    from test_story_compiler import MACQUARIE
    assert corpus.coverage()['removed_keystone'] == 0
    monkeypatch.setenv('BLUEPRINT_ADHERENCE', 'strong')
    assert ep._retrieve_blueprint('removed_keystone', '', 90) == ''
    compiled = compiler.compile_roles(MACQUARIE, 'removed_keystone')
    assert compiled['passed']
    assert compiled['derived'] == []  # no invented reward or bounty mechanism
    assert engines.minimum_beats(engines.get('removed_keystone')) == 6
    assert ep._engine_runtime_fit('removed_keystone', 60)['fits']


def test_structure_selection_reads_the_researched_events(monkeypatch):
    seen = []
    def create(**call):
        seen.append(call['messages'][0]['content'])
        return response({'engine': 'removed_keystone', 'why': 'ecological consequences'})
    monkeypatch.setattr(ep, '_claude', lambda: SimpleNamespace(messages=SimpleNamespace(create=create)))
    dossier = {'claims': [{'claim_id': 'c1', 'claim': 'The agency removed cats; it paid no bounty.',
                           'support_quote': 'The agency removed cats; it paid no bounty.'}]}
    assert ep._select_story_engine('Pest-control program', 90, research_dossier=dossier) == 'removed_keystone'
    assert 'paid no bounty' in seen[0]
    assert 'SOURCED CLAIMS FOR THIS EPISODE' in seen[0]
