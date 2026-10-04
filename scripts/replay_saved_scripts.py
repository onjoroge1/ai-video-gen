"""Replay saved narration through the real revision boundary without buying anything.

The script payloads are retained fixtures. The job/checkpoint envelope is synthetic:
this is not a production restart, a semantic review, or a rendered-film comparison.
Run the same file with --code-root at the pinned baseline and the recovery candidate.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path
import socket
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--fixtures', type=Path, default=Path(__file__).resolve().parents[1] / 'tests/fixtures')
    args = parser.parse_args()
    calls = []

    def no_network(*a, **kw):
        calls.append('blocked')
        raise RuntimeError('Offline replay refuses network/provider access')

    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    sys.path.insert(0, str(args.code_root.resolve()))
    import script_contracts
    import script_readiness
    import script_revisions
    from script_stages import digest
    from story_fact_model import context_events

    results = []
    for pr in (164, 165):
        script = json.loads((args.fixtures / f'pr{pr}_saved_script.json').read_text())
        before = deepcopy(script)
        row = {'id': f'pr{pr}-offline-replay', 'kind': 'explainer', 'status': 'error',
            'checkpoint': {'sha256': 'offline-fixture'}, 'request': {
                'question': 'Why did New Zealand deliberately release stoats onto its islands, and what did they do to the kiwi?',
                'duration_sec': 180, 'fact_check': True, 'visual_style': 'illustrated_story',
                'video_format': 'landscape'}}
        child, request = script_revisions.prepare(row,
            {'script': script, 'checkpoint_sha256': 'offline-fixture'}, mode='evaluate',
            checkpoint_sha256='offline-fixture', content_sha256=script_readiness.content_hash(script),
            cost_ceiling_usd=3)
        out = script_revisions.restore(request['script_revision'], stop_after_script=True)
        assert before == script, 'Replay mutated its saved input'
        assert out == script_revisions.restore(request['script_revision'], stop_after_script=True), 'Replay not deterministic'
        assert not out.get('_script_readiness', {}).get('passed'), 'Replay must not approve a script'
        results.append({'pr': pr, 'source_sha256': digest(script), 'result_sha256': digest(out),
            'child_identity': child, 'parent_unchanged': before == script,
            'historical_cascade_unchanged': out['_spine']['compiled']['cascade'] == before['_spine']['compiled']['cascade'],
            'context': {s['beat_id']: {'refs': s.get('context_refs'),
                'resolved': [c['beat_id'] for c in context_events(s, out['scenes'])]}
                for s in out['scenes'] if s['beat_id'] in ('event_04:hinge', 'event_09:tool')},
            'claim_c22': next(c['claim'] for c in out['_research_dossier']['claims'] if c['claim_id'] == 'c22'),
            'input_repairs': {k: out[k] for k in ('_context_migration', '_numerical_resolution') if k in out},
            'changed_narration': [{'beat_id': a['beat_id'], 'before': a['narration'], 'after': b['narration']}
                for a, b in zip(script['scenes'], out['scenes']) if a['narration'] != b['narration']]})
    print(json.dumps({'provider_calls': 0, 'blocked_network_attempts': len(calls),
        'approval_granted': False, 'acceptance_policy': script_contracts.acceptance_policy(),
        'scope': 'Offline prepare/restore only; synthetic job/checkpoint envelope, no model judgments or film reconstruction',
        'results': results}, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
