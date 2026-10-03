"""Final editorial review: bounded, evidence checked, replayable, never a stale grade."""
from copy import deepcopy
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
import explainer_pipeline as ep
import illustrated_story as lane
import retention_polish as polish
import storyboard_repair as repair
from test_illustrated_story import _script


def grade(value=80, **axes):
    return {'overall': value, 'scores': dict(dict.fromkeys(polish.AXES, value), **axes),
            'weakest': 'repetition', 'notes': 'Repeat less.'}


def setup(monkeypatch, grades, *, claims=True, structure=True):
    script = _script()
    script['_grade'] = grade(99)  # stale score must never decide the final pass
    for s in script['scenes']:
        s['event'] = {'text': 'A sourced event.', 'claim_refs': ['c1']}
    edit = {'scenes': [{'scene_id': script['scenes'][5]['scene_id'],
                       'narration': 'The next consequence follows. ' * 10}]}
    response = NS(content=[NS(type='tool_use', name=repair.EDIT_TOOL, input=edit)],
                  usage=NS(input_tokens=100, output_tokens=50), stop_reason='tool_use')
    create = Mock(return_value=response)
    grader = Mock(side_effect=grades)
    monkeypatch.setattr(ep, '_claude', lambda: NS(messages=NS(create=create)))
    monkeypatch.setattr(ep, 'grade_script', grader)
    monkeypatch.setattr(ep, 'rederive_narration_bindings', Mock())
    monkeypatch.setattr(ep, 'validate_longform_story', Mock(return_value={'passed': structure}))
    monkeypatch.setattr(lane, 'build_storyboard', Mock(return_value={'validation': {'passed': True}}))
    monkeypatch.setattr(ep, 'duplicate_narration', Mock(return_value=[]))
    validator = Mock(return_value={'passed': claims})
    monkeypatch.setattr(ep, '_validate_claims', validator)
    return script, create, grader, validator


@pytest.mark.parametrize('g,passed', [(grade(), True), (grade(73), False),
    (grade(80, hook=77), False), (grade(80, story=77), False),
    (grade(80, repetition=69), False), (grade(78, cadence=70), True),
    (None, False), ({'overall': 99, 'scores': {}}, False), (grade(float('nan')), False)])
def test_targets(g, passed):
    assert (not polish.target_errors(g)) == passed


def test_improvement_is_rechecked_and_replay_does_not_repurchase(tmp_path, monkeypatch):
    script, create, grader, validator = setup(monkeypatch, [grade(73), grade(80)])
    original = deepcopy(script)
    result, report = polish.run(script, 'q', {'claims': []}, tmp_path, [], lambda _: None)
    assert report['passed'] and report['attempts'] == 1
    assert result['_grade']['overall'] == 80 and script == original
    assert validator.call_count == 1
    for old, new in zip(script['scenes'], result['scenes']):
        assert old['event'] == new['event']
    again, again_report = polish.run(script, 'q', {'claims': []}, tmp_path, [], lambda _: None)
    assert again == result and again_report == report
    assert create.call_count == 1 and grader.call_count == 2
    with pytest.raises(ValueError, match='different evidence'):
        polish.run(script, 'q', {'claims': ['changed']}, tmp_path, [], lambda _: None)


@pytest.mark.parametrize('kind', ['evidence', 'structure', 'degraded_axis', 'unscored', 'no_improvement'])
def test_bad_candidate_keeps_original_and_failed_final_grade(tmp_path, monkeypatch, kind):
    new_grade = (None if kind == 'unscored' else grade(73) if kind == 'no_improvement'
                 else grade(80, cadence=72) if kind == 'degraded_axis' else grade(80))
    script, create, grader, validator = setup(monkeypatch, [grade(73), new_grade],
                                            claims=kind != 'evidence', structure=kind != 'structure')
    result, report = polish.run(script, 'q', {}, tmp_path, [], lambda _: None)
    assert not report['passed'] and report['attempts'] == 1
    assert result['scenes'] == script['scenes'] and result['_grade']['overall'] == 73
    polish.run(result, 'q', {}, tmp_path, [], lambda _: None)
    assert create.call_count == 1


def test_unavailable_grader_does_not_use_old_score_or_buy_an_edit(tmp_path, monkeypatch):
    script, create, grader, _ = setup(monkeypatch, [None])
    result, report = polish.run(script, 'q', {}, tmp_path, [], lambda _: None)
    assert not report['passed'] and report['errors'][0].startswith('UNSCORED')
    assert result['_grade'] == {'status': 'UNSCORED'} and not create.called


def test_two_pass_ceiling(tmp_path, monkeypatch):
    script, create, grader, _ = setup(monkeypatch, [grade(71), grade(73), grade(75)])
    _, report = polish.run(script, 'q', {}, tmp_path, [], lambda _: None)
    assert not report['passed'] and report['attempts'] == 2 and create.call_count == 2


@pytest.mark.parametrize('kind', ['event', 'duplicate', 'fragment', 'unknown', 'padded', 'cold_open'])
def test_edit_scope_and_integrity(kind):
    script = _script()
    row = {'scene_id': script['scenes'][0]['scene_id'], 'narration': 'A clear and complete new hook.'}
    data = {'scenes': [row]}
    if kind == 'event': row['event'] = {'text': 'invented'}
    if kind == 'duplicate': data['scenes'].append(dict(row))
    if kind == 'fragment': row['narration'] = 'The stoats hunted instead of the.'
    if kind == 'unknown': row['scene_id'] = 'unknown'
    if kind == 'padded': row['narration'] = 'Unnecessary filler. ' * 40
    if kind == 'cold_open': script['_cold_open'] = 'A stoat beside a broken kiwi egg.'
    with pytest.raises(ValueError): polish.apply_edits(script, data)


def test_rejected_checkpoint_does_not_buy_another_attempt(tmp_path, monkeypatch):
    script, create, _, _ = setup(monkeypatch, [grade(73), grade(70)])
    polish.run(script, 'q', {}, tmp_path, [], lambda _: None)
    path = tmp_path / polish.FILENAME
    record = json.loads(path.read_text())
    record['status'] = 'started'
    path.write_text(json.dumps(record))
    _, report = polish.run(script, 'q', {}, tmp_path, [], lambda _: None)
    assert not report['passed'] and create.call_count == 1


def test_existing_media_prevents_editorial_rewrites(tmp_path, monkeypatch):
    script, create, _, _ = setup(monkeypatch, [grade(73)])
    (tmp_path / 'audio').mkdir()
    (tmp_path / 'audio' / 'voice.mp3').write_bytes(b'paid')
    result, report = polish.run(script, 'q', {}, tmp_path, [], lambda _: None)
    assert not create.called and result['scenes'] == script['scenes'] and not report['passed']
