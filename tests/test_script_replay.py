"""Saved production inputs; these are deterministic regressions, not paid quality tests."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
import script_replay as replay
import script_revisions
import script_stages
import story_fact_model as facts
from test_script_contract_revisions import source


def saved(pr):
    return json.loads((Path(__file__).parent / f'fixtures/pr{pr}_saved_script.json').read_text())


@pytest.mark.parametrize('pr', [164, 165])
def test_actual_restore_adds_context_and_narrows_numeric_claim(pr):
    original = saved(pr)
    snapshot = deepcopy(original)
    migrated = replay.migrate_context(original)
    assert [s['narration'] for s in migrated['scenes']] == [s['narration'] for s in original['scenes']]
    assert [facts.event_of(s) for s in migrated['scenes']] == [facts.event_of(s) for s in original['scenes']]
    row, artifact, args = source(original)
    _, request = script_revisions.prepare(row, artifact, mode='evaluate', **args)
    restored = script_revisions.restore(request['script_revision'], stop_after_script=True)
    for ident in ('event_04:hinge', 'event_09:tool'):
        scene = next(s for s in restored['scenes'] if s['beat_id'] == ident)
        contexts = facts.context_events(scene, restored['scenes'])
        assert {'event_01', 'event_02', 'event_04'} <= {e['beat_id'] for e in contexts}
        assert scene['parallel_case_id'] == ''
    assert restored['scenes'][0]['context_refs'] == original['scenes'][0]['context_refs']
    claim = next(c for c in restored['_research_dossier']['claims'] if c['claim_id'] == 'c22')
    assert claim['support_quote'] == replay.QUOTE
    assert claim['claim'] == replay.COUNT_CLAIM
    assert '63' not in restored['scenes'][4]['narration']
    assert 'stoats were responsible for 19 of 31 identified-cause chick deaths' in restored['scenes'][4]['narration']
    assert restored['_numerical_resolution']['original_claim']['claim'] == replay.OLD_CLAIM
    assert '_entailment_cache' not in restored
    assert replay.prepare_input(restored) == restored
    assert original == snapshot


@pytest.mark.parametrize('mutation', ['order', 'event', 'case', 'ref', 'accepted', 'paragraph'])
def test_context_migration_fails_closed(mutation):
    script = saved(164)
    if mutation == 'order': script['scenes'].reverse()
    if mutation == 'event': script['scenes'][0]['event']['text'] = 'Invented fact.'
    if mutation == 'case': script['scenes'][2]['parallel_case_id'] = 'other'
    if mutation == 'ref': script['scenes'][2]['context_refs'].append('missing')
    if mutation == 'accepted': script['_spine']['compiled']['passed'] = False
    if mutation == 'paragraph': script['scenes'][0]['paragraph_id'] = 'other'
    with pytest.raises(ValueError, match='CONTEXT_MIGRATION'):
        replay.prepare_input(script)


def test_numeric_resolution_does_not_generalize_to_other_sources_or_unknown_wording():
    script = saved(164)
    claim = next(c for c in script['_research_dossier']['claims'] if c['claim_id'] == 'c22')
    claim['source_url'] = 'https://example.com/different'
    assert replay.reconcile_numbers(script) == script
    script = saved(164)
    script['scenes'][4]['narration'] = 'Stoats killed 63 percent of all kiwi.'
    with pytest.raises(ValueError, match='UNHANDLED_WORDING'):
        replay.reconcile_numbers(script)


def test_numeric_resolution_reaches_judge_and_changes_its_cache():
    import claim_entailment as ce
    restored = replay.prepare_input(saved(164))
    claim = next(c for c in restored['_research_dossier']['claims'] if c['claim_id'] == 'c22')
    assert 'omit_percentage_preserve_count' in ce._claim_block(claim)
    changed = deepcopy(claim)
    changed['numerical_resolution']['policy'] = 'different policy'
    assert ce.cache_key([claim], 'event') != ce.cache_key([changed], 'event')
