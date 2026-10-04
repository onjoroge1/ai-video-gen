"""Real PR164 regression; no provider calls or claims of editorial approval."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import explainer_pipeline as ep
import narrative_template as nt
import story_compiler as compiler
import story_fact_model as facts
from test_narrative_template import inputs


def test_live_plan_devices_keep_case_identity_and_context():
    fixture = json.loads((Path(__file__).parent / 'fixtures/pr164_stoat_accepted_beats.json').read_text())
    original = deepcopy(fixture['beats'])
    beats = compiler.presentation_beats(fixture['beats'], fixture['engine'])
    assert fixture['beats'] == original
    assert facts.validate_structure(beats) == []
    for ident in ('event_04:hinge', 'event_09:tool'):
        device = next(b for b in beats if b['beat_id'] == ident)
        assert device['parallel_case_id'] == ''
        assert {'event_01', 'event_02', 'event_04'} <= set(device['context_refs'])
        assert set(device['context_refs']) == {e['beat_id'] for e in facts.context_events(device, beats)}
    # Reevaluating already saved words must work without recompiling or rewriting.
    for b in beats:
        if b.get('presentation_device'):
            b.pop('parallel_case_id')
    assert facts.validate_structure(beats) == []


@pytest.mark.parametrize('case', [None, '', '  '])
def test_legacy_blank_primary_case_is_equivalent(case):
    parent = {'beat_id': 'fact', 'role': 'setup', 'scope': 'primary_story',
              'parallel_case_id': '', 'event': {'text': 'Supported fact.', 'claim_refs': ['c1']}}
    device = {'beat_id': 'hinge', 'role': 'hinge', 'scope': 'primary_story',
              'parallel_case_id': case, 'context_refs': ['fact']}
    assert facts.validate_structure([parent, device]) == []
    assert facts.context_events(device, [parent, device]) == [{'beat_id': 'fact', 'event': facts.event_of(parent)}]


@pytest.mark.parametrize('scope,case', [('parallel_case', 'other'), ('primary_story', 'other'),
                                      ('parallel_case', '')])
def test_cross_case_refs_still_rejected_and_not_exposed(scope, case):
    parent = {'beat_id': 'fact', 'role': 'generalization', 'scope': scope,
              'parallel_case_id': case, 'event': {'text': 'Other case.', 'claim_refs': ['c1']}}
    device = {'beat_id': 'hinge', 'role': 'hinge', 'scope': 'primary_story',
              'context_refs': ['fact']}
    assert any(i['code'] == 'INVALID_CONTEXT_REF' for i in facts.validate_structure([parent, device]))
    assert facts.context_events(device, [parent, device]) == []


@pytest.mark.parametrize('ref', ['missing', 'event_03', 'event_07'])
def test_invalid_presentation_fails_before_narration_spending(monkeypatch, ref):
    plan, beats, dossier = inputs()
    beats[2]['context_refs'] = [ref]  # missing, self, or nonfactual callback
    provider = Mock(side_effect=AssertionError('must not spend'))
    monkeypatch.setattr(ep, '_claude', provider)
    with pytest.raises(ValueError, match='SEVEN_SECTION_PRESENTATION_STRUCTURE.*INVALID_CONTEXT_REF.*event_03'):
        nt.generate(plan, beats, dossier, 'removed_keystone', 'q', 180, 450)
    provider.assert_not_called()
