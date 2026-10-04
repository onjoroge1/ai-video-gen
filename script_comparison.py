"""Matched writer experiment, not production approval or a complete flow benchmark.

Two drafting protocols, one fixed evidence pack, identical provider/model/token
settings and a common review. Four calls maximum, zero retries for semantic quality.
Requires the durable Studio reservation/checkpoint boundary for paid execution.
"""
from copy import deepcopy
import json
from pathlib import Path
import narrative_template as nt
import script_contracts
import script_stages as stages
import story_compiler
from storyboard_repair import response_data

VERSION = 'matched_writer_v1'
REPORT = 'script_comparison.json'
SYSTEM = 'You are a factual documentary writer and editor. Use only supplied evidence. Submit the requested object using the tool.'
MAX_TOKENS = 12000
DOCUMENT_TOOL = {'name': 'submit_document', 'description': 'Submit a continuous factual narration.',
    'input_schema': {'type': 'object', 'properties': {
        'narration': {'type': 'string'}, 'evidence_gaps': {'type': 'array', 'items': {'type': 'string'}},
        'editorial_weaknesses': {'type': 'array', 'items': {'type': 'string'}}},
        'required': ['narration', 'evidence_gaps', 'editorial_weaknesses'], 'additionalProperties': False}}
REVIEW_TOOL = {'name': 'submit_review', 'description': 'Review the supplied narration without rewriting it.',
    'input_schema': {'type': 'object', 'properties': {
        'issues': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'quote': {'type': 'string'}, 'code': {'type': 'string'}, 'reason': {'type': 'string'},
            'claim_ids': {'type': 'array', 'items': {'type': 'string'}}},
            'required': ['quote', 'code', 'reason', 'claim_ids'], 'additionalProperties': False}},
        'hook': {'type': 'string'}, 'causal_story': {'type': 'string'},
        'cadence': {'type': 'string'}, 'payoff': {'type': 'string'}, 'repetition': {'type': 'string'}},
        'required': ['issues', 'hook', 'causal_story', 'cadence', 'payoff', 'repetition'],
        'additionalProperties': False}}


def experiment(script, question, duration, direction=''):
    """Pure preparation, including prompts; no local credentials or provider required."""
    import explainer_pipeline as ep
    import script_replay
    script = script_replay.prepare_input(script)
    plan = {'_spine': deepcopy(script.get('_spine') or {})}
    beats = story_compiler.presentation_beats(plan['_spine']['beats'], script['_story_engine'])
    evidence = nt.brief(plan, beats, script['_research_dossier'], script['_story_engine'])
    target = ep.runtime_word_bounds(duration, len(beats))[0]
    shared = {'question': question, 'duration_sec': duration, 'word_target': target,
              'direction': direction, 'evidence': evidence, 'accepted_plan': plan,
              'model': script_contracts.model_identity(), 'system': SYSTEM,
              'max_tokens': MAX_TOKENS, 'temperature': 'provider default (omitted)'}
    current = nt.draft_prompt(evidence, question, duration, target, direction)
    current += "\nNumerical resolution instructions override inconsistent percentages in original quotes."
    document = (
        'Write one continuous factual YouTube narration using the supplied evidence and seven '
        'section jobs. Choose the supported answer and opening promise together. Start with a '
        'specific consequential question or contradiction. Explain why the intervention seemed '
        'reasonable, the overlooked mechanism, distinct supported consequences, the answer and '
        'an earned callback. Vary sentence length and connect paragraphs naturally. No invented '
        'motives, incidents, initial success, rescues or causal links between parallel effects. '
        'Keep historical and geographic scope and uncertainty. No padding to fill runtime. '
        'No spoken labels or visual directions. The evidence paragraphs are factual reference '
        'units, not mandatory narration slots: organize the complete document as needed. '
        'Numerical resolution instructions override inconsistent percentages in original quotes. '
        'If evidence is missing, report the gap.\n'
        f'Topic: {question}\nRequested seconds: {duration}; total target words: {target}.\n'
        f'Operator direction: {direction}\nEVIDENCE BRIEF:\n' + json.dumps(evidence, ensure_ascii=False))
    # Both writers see EXACTLY the same evidence JSON. Structural instructions are the treatment.
    return {'version': VERSION, 'shared': shared, 'shared_sha256': stages.digest(shared),
        'scope': 'writer and common review only; excludes research, planner selection, production repair loops and final approval',
        'arms': {'current': {'prompt': current, 'tool': nt.draft_tool(evidence)},
                 'document': {'prompt': document, 'tool': DOCUMENT_TOOL}},
        'input_repairs': {k: script[k] for k in ('_context_migration', '_numerical_resolution') if k in script}}


def narration(value, arm):
    if not isinstance(value, dict):
        return ''
    if arm == 'document':
        return value.get('narration') if isinstance(value.get('narration'), str) else ''
    rows = value.get('paragraphs')
    if not isinstance(rows, list):
        return ''
    return '\n\n'.join(p['narration'] for p in rows
                       if isinstance(p, dict) and isinstance(p.get('narration'), str))


def review_prompt(shared, text):
    return ('Review this narration against only the supplied evidence. Do not infer quality from '
        'its format or claim it predicts audience retention. Identify unsupported facts, numeric '
        'conflicts, scope changes, broken grammar, missing causal links, repetition and an unanswered '
        'opening. Cite exact narration spans and supporting claim IDs. Assess the specificity and '
        'earned stakes of the hook, story progression, spoken cadence and closing payoff. No '
        'rewrite and no approval decision. Original source quotes may contain an explicitly '
        'resolved numerical conflict; enforce the count-only resolution.\n'
        + json.dumps({'question': shared['question'], 'duration_sec': shared['duration_sec'],
                     'evidence': shared['evidence'], 'narration': text}, ensure_ascii=False))


def run(script, question, duration, direction, output_dir, cost_sink, log):
    import durable_execution
    import explainer_pipeline as ep
    runtime = durable_execution.current()
    if runtime is None:
        raise ValueError('MATCHED_COMPARISON_REQUIRES_DURABLE_STUDIO_BUDGET')
    inputs = experiment(script, question, duration, direction)
    state = stages.load('matched-writer-progress', inputs) or {
        'version': VERSION, 'status': 'running', 'approved': False,
        'experiment': inputs, 'results': {}, 'cost_usd': 0.0}

    def save():
        path = Path(output_dir) / REPORT
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        temporary.replace(path)
        stages.save('matched-writer-progress', inputs, state)

    def call(prompt, tool):
        response = ep._claude().messages.create(model=ep.ANTHROPIC_MODEL, max_tokens=MAX_TOKENS,
            system=SYSTEM, messages=[{'role': 'user', 'content': prompt}],
            tools=[tool], tool_choice={'type': 'tool', 'name': tool['name']})
        cost = ep._charge(cost_sink, ep._ledger.EXPANSION, ep._msg_cost(response.usage), 'matched writer experiment')
        raw = [{'type': b.type, **({'text': b.text} if b.type == 'text' else
            {'name': b.name, 'input': b.input.model_dump() if hasattr(b.input, 'model_dump') else b.input})}
            for b in response.content if getattr(b, 'type', None) in {'text', 'tool_use'}]
        try:
            value = response_data(response, tool_name=tool['name'])
            error = None
        except (ValueError, TypeError, AttributeError) as exc:
            value, error = None, type(exc).__name__
        return {'value': value, 'raw': raw, 'parse_error': error, 'cost_usd': cost}

    save()  # Persist the experiment and exact shared inputs before spending.
    # Deterministic counterbalancing; stable over resume, neither arm always drafts first.
    order = ['current', 'document'] if int(inputs['shared_sha256'][0], 16) % 2 else ['document', 'current']
    for arm in order:
        result = state['results'].setdefault(arm, {})
        if 'draft' not in result:
            log('Matched comparison: drafting ' + arm)
            spec = inputs['arms'][arm]
            result['draft'] = call(spec['prompt'], spec['tool'])
            state['cost_usd'] += result['draft']['cost_usd']
            save()
        if 'narration' not in result:
            value = result['draft']['value']
            result['narration'] = narration(value, arm)
            result['contract_issues'] = (nt.draft_issues(value, inputs['shared']['evidence'])
                if arm == 'current' else ([{'code': 'EMPTY_DOCUMENT'}] if not result['narration'].strip() else
                      [{'code': 'EVIDENCE_GAP'}] if value.get('evidence_gaps') else []))
            save()  # Invalid drafts are retained and never silently bought again.
    for arm in order:
        result = state['results'][arm]
        if 'review' not in result:
            if result['narration'].strip():
                log('Matched comparison: reviewing ' + arm)
                result['review'] = call(review_prompt(inputs['shared'], result['narration']), REVIEW_TOOL)
                state['cost_usd'] += result['review']['cost_usd']
            else:
                result['review'] = {'skipped': 'No readable draft', 'value': None}
            save()
    state['status'] = 'awaiting_human_comparison'
    state['blind_drafts'] = {label: state['results'][arm]['narration'] for label, arm in zip(('A', 'B'), order)}
    state['arm_mapping'] = dict(zip(('A', 'B'), order))
    save()
    return state
