"""Auditable, fail-closed repairs to saved narration inputs. Never approves prose."""
from copy import deepcopy
import narrative_template as nt
import story_compiler as compiler
import story_fact_model as facts
from script_stages import digest

VERSION = 'saved_context_v2'
SOURCE = 'C1928428882BB8312EC0EF0DF07BABC3'
QUOTE = 'Causes of mortality in 31 cases where the agent could be identified were: Stoats 19 (63%), cats 4 (13%), drowning 3 (10%)'
OLD_CLAIM = 'In a central Northland study of brown kiwi, stoats were the single largest identified cause of chick death, killing 19 of 31 chicks (63%) in cases where the agent could be identified.'
COUNT_CLAIM = 'In a central Northland study of brown kiwi, stoats were the single largest identified cause of chick death: 19 of 31 deaths where the cause could be identified.'


def migrate_context(script):
    """Rebuild compiler-owned links only, preserving exact facts, prose and order."""
    out = deepcopy(script)
    if out.get('_narrative_mode') != nt.MODE:
        return out
    if out.get('_production_status') != 'unplanned':
        raise ValueError('CONTEXT_MIGRATION_REQUIRES_UNPLANNED_NARRATION')
    plan = {'_spine': out.get('_spine') or {}}
    engine = out.get('_story_engine')
    if engine not in nt.ENGINES or not (plan['_spine'].get('compiled') or {}).get('passed'):
        raise ValueError('CONTEXT_MIGRATION_REQUIRES_ACCEPTED_PLAN')
    beats = compiler.presentation_beats(plan['_spine'].get('beats') or [], engine)
    nt.brief(plan, beats, out.get('_research_dossier') or {}, engine)
    scenes = out['scenes']
    ids = [b['beat_id'] for b in beats]
    if [s.get('beat_id') for s in scenes] != ids or [s.get('paragraph_id') for s in scenes] != ids:
        raise ValueError('CONTEXT_MIGRATION_PARAGRAPH_IDENTITY')
    changes = []
    for scene, beat in zip(scenes, beats):
        if (facts.event_of(scene) != facts.event_of(beat)
                or facts.case_identity(scene) != facts.case_identity(beat)
                or scene.get('causal_role') != beat.get('causal_role')):
            raise ValueError('CONTEXT_MIGRATION_FACT_MISMATCH: ' + beat['beat_id'])
        before = {'context_refs': scene.get('context_refs', []),
                  'parallel_case_id': scene.get('parallel_case_id')}
        # Keep intentional, explicitly bound hook context; never add the whole ledger.
        scene['context_refs'] = list(dict.fromkeys(before['context_refs'] + beat.get('context_refs', [])))
        scene['parallel_case_id'] = facts.case_identity(beat)[1]
        after = {k: scene[k] for k in before}
        if before != after:
            changes.append({'beat_id': beat['beat_id'], 'before': before, 'after': after})
    # Only context validity is checked here: production scenes use scene IDs for caused_by.
    by_id = {s['beat_id']: s for s in scenes}
    for scene in scenes:
        for ref in scene['context_refs']:
            parent = by_id.get(ref)
            if (not parent or ref == scene['beat_id'] or not facts.event_of(parent)['text']
                    or facts.case_identity(parent) != facts.case_identity(scene)):
                raise ValueError('CONTEXT_MIGRATION_INVALID_REF: ' + str(ref))
    if changes:
        out['_context_migration'] = {'version': VERSION, 'source_sha256': digest(script),
            'narration_sha256': digest([s['narration'] for s in scenes]), 'changes': changes}
    return out


def reconcile_numbers(script):
    """Source-specific adjudication, not a general percentage rewriting heuristic.

    Preserve verbatim source evidence. Omit the inconsistent conversion, never invent
    a corrected source percentage or a denominator. Unknown variants fail closed.
    """
    out = deepcopy(script)
    claims = (out.get('_research_dossier') or {}).get('claims') or []
    matches = [c for c in claims if c.get('source_url', '').rstrip('/').endswith(SOURCE)
               and c.get('support_quote') == QUOTE and c.get('claim') == OLD_CLAIM]
    if not matches:
        return out
    if len(matches) != 1:
        raise ValueError('NUMERIC_RESOLUTION_AMBIGUOUS_CLAIM')
    claim = matches[0]
    original = deepcopy(claim)
    claim['claim'] = COUNT_CLAIM
    claim['calculation'] = 'Use the reported count only: 19 of 31 identified-cause deaths. The source percentage is inconsistent and must not be narrated.'
    claim['numerical_resolution'] = {'version': 'northland_count_only_v1',
        'original_claim': original['claim'], 'original_calculation': original.get('calculation'),
        'numerator': 19, 'denominator': 31, 'source_percent': 63,
        'computed_percent_for_audit_only': 100 * 19 / 31,
        'policy': 'omit_percentage_preserve_count_and_identified_cause_scope'}
    replacements = {
        'killing 19 of 31 chicks (63%)': 'responsible for 19 of 31 identified-cause chick deaths',
        'stoats killed 19 of 31 chicks, about 63 percent': 'stoats were responsible for 19 of 31 identified-cause chick deaths',
    }
    changes = []
    # Only active factual events and spoken prose are rewritten. Historical reports,
    # original source quotes and rejected candidates remain evidence, not writer inputs.
    def change(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {'text', 'narration', 'narration_phrase', 'narration_phrase_model'} and isinstance(value, str):
                    revised = value
                    for old, new in replacements.items():
                        revised = revised.replace(old, new)
                    if revised != value:
                        node[key] = revised
                        changes.append({'path': path + '.' + key, 'before': value, 'after': revised})
                elif isinstance(value, (dict, list)):
                    change(value, path + '.' + key)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                change(value, f'{path}[{i}]')
    for key in ('scenes', '_spine', '_story_contract'):
        change(out.get(key), key)
    # A differently phrased percentage needs an explicit repair, not broad string removal.
    for scene in out.get('scenes', []):
        if claim['claim_id'] in facts.event_of(scene)['claim_refs']:
            if '63' in scene.get('narration', '') or '63' in facts.event_of(scene)['text']:
                raise ValueError('NUMERIC_RESOLUTION_UNHANDLED_WORDING: ' + scene.get('beat_id', '?'))
    out['_numerical_resolution'] = {'version': 'northland_count_only_v1',
        'source_sha256': digest(script), 'claim_id': claim['claim_id'],
        'original_claim': original, 'changes': changes}
    return out


def prepare_input(script):
    out = reconcile_numbers(migrate_context(script))
    if out != script:
        # Stale derived documents, verdicts and entailment caches cannot confer approval.
        for key in ('_script_readiness', '_final_factcheck_review', '_final_retention_review',
                    '_narrative_document', '_entailment_cache'):
            out.pop(key, None)
    return out
