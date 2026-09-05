"""Topic approvals must remain non-spending and bind their exact scope."""
import copy
import anyio
import httpx
import pytest
import agent_actions
import app as studio
import private_access
from test_agent_actions import ACTION_ID, FakeActionRepository, _secure_environment


def test_recipe_rejects_provider_or_scope_drift():
    providers = {'script': {'provider': 'anthropic', 'model': 'fixture'}}
    payload = agent_actions.build_illustrated_payload(topic='Workshop', duration_sec=90,
        creative_direction='Clear illustrated story', cost_ceiling_usd=5, providers=providers)
    sha = agent_actions.illustrated_payload_hash(payload)
    changed = copy.deepcopy(payload)
    changed['request']['duration_sec'] = 600
    with pytest.raises(agent_actions.AgentActionConflict):
        agent_actions.validate_illustrated_payload(changed, expected_sha256=sha,
            providers=providers, cost_ceiling_usd=5)
    with pytest.raises(agent_actions.AgentActionConflict):
        agent_actions.validate_illustrated_payload(payload, expected_sha256=sha,
            providers={'script': {'provider': 'openai', 'model': 'other'}}, cost_ceiling_usd=5)


def test_topic_entry_requires_approval_and_missing_keys_preserve_it(monkeypatch):
    _secure_environment(monkeypatch)
    monkeypatch.setenv('DURABLE_EXECUTION', '1')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fixture')
    monkeypatch.setenv('OPENAI_API_KEY', 'fixture')
    repo = FakeActionRepository()
    monkeypatch.setattr(agent_actions, 'repository', lambda: repo)
    async def must_not_enqueue(*args, **kwargs):
        pytest.fail('Unapproved/unconfigured request reached queue')
    monkeypatch.setattr(studio, '_enqueue_explainer_request', must_not_enqueue)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=studio.app),
                                     base_url='http://test') as client:
            created = await client.post('/api/agent/actions', json={
                'operation': 'generic_illustrated', 'topic': 'Workshop',
                'duration_sec': 90, 'cost_ceiling_usd': 5})
            assert created.status_code == 200, created.text
            proposal = created.json()
            assert proposal['scope'] == 'single-illustrated-video'
            assert proposal['duration_sec'] == 90
            headers = {'Authorization': 'Bearer ' + proposal['claim_token']}
            execute = f'/api/agent/actions/{ACTION_ID}/execute'
            assert (await client.post(execute, headers=headers)).status_code == 409
            assert repo.action['status'] == 'pending'
            approve = f'/api/agent/actions/{ACTION_ID}/approve'
            body = {'spec_sha256': proposal['spec_sha256'], 'cost_ceiling_usd': 5}
            assert (await client.post(approve, json=body)).status_code == 401
            client.cookies.set(private_access.COOKIE_NAME, private_access.create_session('owner'))
            assert (await client.post(approve, json={**body, 'cost_ceiling_usd': 4})).status_code == 409
            assert (await client.post(approve, json=body)).status_code == 200
            monkeypatch.delenv('ANTHROPIC_API_KEY')
            missing = await client.post(execute, headers=headers)
            assert missing.status_code == 503, missing.text
            assert repo.action['status'] == 'approved'
            assert 'ANTHROPIC_API_KEY' in missing.json()['detail']['missing_configuration']
    anyio.run(run)
