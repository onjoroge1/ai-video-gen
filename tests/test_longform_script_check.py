"""The sampler observes the production stop boundary rather than duplicating it."""
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "longform_script_check", Path(__file__).parents[1] / "scripts" / "longform_script_check.py")
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def test_sampler_uses_the_production_entrypoint_and_its_final_report(monkeypatch):
    calls = []
    def run(question, directory, **kwargs):
        calls.append((question, kwargs))
        kwargs['text_cost_sink'].append(.42)
        Path(directory, '_state.json').write_text(json.dumps({'script': {
            'scenes': [{'narration': 'The final words.'}],
            '_script_readiness': {'passed': True, 'warnings': ['runtime advisory']}}}))
        raise harness.ep.ScriptApprovalRequired('review')
    monkeypatch.setattr(harness.ep, 'run_explainer_pipeline', run)
    report = harness.run_sample(harness.parse_args(['--visual-style', 'illustrated_story', 'Topic']), 1)
    assert report['passed'] and report['clean_script_checks']
    assert report['script']['scenes'][0]['narration'] == 'The final words.'
    assert report['recorded_cost_usd'] == .42
    assert calls[0][1]['stop_after_script'] and calls[0][1]['fresh_script']
    assert calls[0][1]['story_format'] == 'standard_explainer'


def test_sampler_does_not_treat_a_return_or_missing_readiness_as_pass(monkeypatch):
    monkeypatch.setattr(harness.ep, 'run_explainer_pipeline', lambda *a, **k: {})
    args = harness.parse_args(['Topic'])
    assert not harness.run_sample(args, 1)['passed']
    def stopped(*a, **k): raise harness.ep.ScriptApprovalRequired('legacy stop')
    monkeypatch.setattr(harness.ep, 'run_explainer_pipeline', stopped)
    report = harness.run_sample(args, 1)
    assert report['passed'] and not report['clean_script_checks']


def test_failed_sample_reads_latest_failure_not_earlier_state(monkeypatch, tmp_path):
    calls = []
    def run(question, directory, **kwargs):
        calls.append(directory)
        kwargs['text_cost_sink'].append(.25)
        Path(directory, '_state.json').write_text(json.dumps({'script': {'title': 'old'}}))
        Path(directory, 'semantic_failure_script-readiness.json').write_text(json.dumps({
            'stage': 'script-readiness', 'failed_at': '2026-10-03',
            'script': {'title': 'rejected current draft'}, 'report': {'passed': False}}))
        raise ValueError('SCRIPT_NOT_READY')
    monkeypatch.setattr(harness.ep, 'run_explainer_pipeline', run)
    output = tmp_path / 'report.json'
    assert harness.main(['--visual-style', 'illustrated_story', '--samples', '2', '--output', str(output), 'Topic']) == 1
    result = json.loads(output.read_text())
    assert len(set(calls)) == 2 and result['recorded_cost_usd'] == .5
    assert all(s['script']['title'] == 'rejected current draft' for s in result['samples'])
    assert all(s['stage'] == 'script-readiness' for s in result['samples'])


@pytest.mark.parametrize('extra', [
    ['--visual-style', 'illustrated_story', '--format', 'evidence_led_mystery'],
    ['--video-format', 'portrait'], ['--video-format', 'social'],
    ['--samples', '0'], ['--duration', '0'],
])
def test_invalid_combinations_fail_before_any_provider_call(extra):
    with pytest.raises(SystemExit) as exc:
        harness.parse_args(extra + ['Topic'])
    assert exc.value.code == 2
