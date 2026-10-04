"""Offline regression replay of exact Studio script artifacts. No provider calls."""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import script_readiness
import script_revisions
from script_stages import digest

results = []
for pr in (164, 165):
    path = Path(__file__).resolve().parents[1] / f'tests/fixtures/pr{pr}_saved_script.json'
    script = json.loads(path.read_text())
    row = {'id': f'pr{pr}-offline-replay', 'kind': 'explainer', 'status': 'error',
        'checkpoint': {'sha256': 'offline-fixture'}, 'request': {
            'question': script['title'], 'duration_sec': 180, 'visual_style': 'illustrated_story'}}
    _, request = script_revisions.prepare(row, {'script': script, 'checkpoint_sha256': 'offline-fixture'},
        mode='evaluate', checkpoint_sha256='offline-fixture',
        content_sha256=script_readiness.content_hash(script), cost_ceiling_usd=5)
    out = script_revisions.restore(request['script_revision'], stop_after_script=True)
    results.append({'pr': pr, 'source_sha256': digest(script),
        'result_sha256': digest(out), 'context_migration': out['_context_migration'],
        'numerical_resolution': out['_numerical_resolution'],
        'changed_narration': [{'beat_id': a['beat_id'], 'before': a['narration'], 'after': b['narration']}
                              for a, b in zip(script['scenes'], out['scenes']) if a['narration'] != b['narration']]})
print(json.dumps({'paid_calls': 0, 'approval': False,
    'scope': 'prepare/restore replay; request title and checkpoint identity are offline fixture values, not a production request',
    'results': results}, indent=2, ensure_ascii=False))
