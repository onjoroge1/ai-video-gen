from copy import deepcopy
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
import durable_execution
import explainer_pipeline as ep
import script_comparison as comparison
import script_stages
from test_script_replay import saved


def test_same_evidence_model_settings_and_accepted_plan():
    exp = comparison.experiment(saved(164), 'Why did introducing stoats backfire?', 180)
    evidence = exp['shared']['evidence']
    serialized = json.dumps(evidence, ensure_ascii=False)
    assert all(serialized in arm['prompt'] for arm in exp['arms'].values())
    assert next(c for c in evidence['claims'] if c['claim_id'] == 'c22')['claim'].endswith('cause could be identified.')
    assert exp['shared']['accepted_plan']['_spine']['compiled']['passed']
    assert 'writer and common review only' in exp['scope']
    assert comparison.experiment(saved(164), 'changed', 180)['shared_sha256'] != exp['shared_sha256']


def test_paid_comparison_refuses_without_durable_budget(tmp_path):
    with pytest.raises(ValueError, match='DURABLE_STUDIO_BUDGET'):
        comparison.run(saved(164), 'q', 180, '', tmp_path, [], print)


def test_four_calls_preserved_drafts_and_zero_rebuys_on_resume(monkeypatch, tmp_path):
    records = {}
    monkeypatch.setattr(durable_execution, 'current', lambda: NS())
    monkeypatch.setattr(script_stages, 'load', lambda name, inputs: deepcopy(records.get(name)))
    monkeypatch.setattr(script_stages, 'save', lambda name, inputs, output: records.update({name: deepcopy(output)}))
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        name = kwargs['tools'][0]['name']
        value = ({'narration': 'A factual draft.', 'evidence_gaps': [], 'editorial_weaknesses': []}
                 if name == 'submit_document' else {'paragraphs': [{'narration': 'Another draft.'}]} if name == 'submit_seven_section_draft'
                 else {'issues': [], 'hook': 'Review opinion', 'causal_story': '', 'cadence': '', 'payoff': '', 'repetition': ''})
        return NS(content=[NS(type='tool_use', name=name, input=value)], usage=NS())
    monkeypatch.setattr(ep, '_claude', lambda: NS(messages=NS(create=create)))
    monkeypatch.setattr(ep, '_msg_cost', lambda usage: .01)
    monkeypatch.setattr(ep, '_charge', lambda *args: .01)
    result = comparison.run(saved(164), 'q', 180, '', tmp_path, [], lambda _: None)
    assert len(requests) == 4
    assert len({(r['model'], r['max_tokens'], r['system']) for r in requests}) == 1
    assert result['cost_usd'] == .04
    assert result['approved'] is False
    assert result['results']['current']['contract_issues'] # Bad shape retained, never silently repaired.
    assert set(result['blind_drafts']) == {'A', 'B'}
    assert comparison.run(saved(164), 'q', 180, '', tmp_path, [], lambda _: None) == result
    assert len(requests) == 4
    assert json.loads((tmp_path / comparison.REPORT).read_text()) == result


def test_comparison_pipeline_stops_at_human_review_before_media(monkeypatch, tmp_path):
    import script_revisions
    from test_script_contract_revisions import source
    from longform_rendered_gate import HumanReviewRequired
    row, artifact, args = source(saved(164))
    _, request = script_revisions.prepare(row, artifact, mode='compare', **args)
    run = Mock(return_value={'approved': False})
    monkeypatch.setattr(comparison, 'run', run)
    media = Mock(side_effect=AssertionError('comparison reached media'))
    monkeypatch.setattr(ep, '_preflight_verifier_credit', media)
    monkeypatch.setattr(ep, 'compile_motion_plan', media)
    with pytest.raises(HumanReviewRequired, match='unapproved'):
        ep.run_explainer_pipeline('q', str(tmp_path), duration_sec=180,
            visual_style='illustrated_story', max_cost_usd=5, stop_after_script=True,
            script_revision=request['script_revision'])
    assert run.call_count == 1
    assert not media.called
    assert not (tmp_path / '_state.json').exists()
    report = json.loads((tmp_path / 'script_revision.json').read_text())
    assert report['input_repairs']['_context_migration']['changes']
