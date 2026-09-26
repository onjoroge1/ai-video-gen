"""Smoke-test an extracted wheel away from the repository checkout (no provider calls)."""
import pathlib
import json
import subprocess
import sys
import tempfile
import zipfile

wheel = pathlib.Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='reelforge-installed-') as directory:
    with zipfile.ZipFile(wheel) as package:
        package.extractall(directory)
    code = '''
import pathlib, sys, json
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.extend(json.loads(sys.argv[2]))
sys.path.insert(0, str(root))
import app, durable_execution, illustrated_story, illustrated_score, provider_readiness, reference_corpus
import claim_entailment, cost_ledger, event_functions, prompt_contract
import story_compiler, story_fact_model, story_planning, research_handoff, topic_fit
import nature_short_presentation, nature_story_flow
for module in (app, durable_execution, illustrated_story, illustrated_score, provider_readiness, reference_corpus,
               claim_entailment, cost_ledger, event_functions, prompt_contract,
               story_compiler, story_fact_model, story_planning, research_handoff, topic_fit,
               nature_short_presentation, nature_story_flow):
    assert pathlib.Path(module.__file__).resolve().is_relative_to(root), module.__file__
assert len(reference_corpus.load()) == 7
assert reference_corpus.coverage()['backfiring_solution'] == 2
assert reference_corpus.coverage()['removed_keystone'] == 0
assert reference_corpus.adherence_for_engine('backfiring_solution') == 'balanced'
assert topic_fit.CHANNELS['history']['name'] == 'Bolt Explains History'
assert (root / 'static' / 'agent_actions.html').is_file()
assert (root / 'spec' / 'hippo_illustrated_story_v4.json').is_file()
episode = json.loads((root / 'spec' / 'harp_seal_nature_story_v2.json').read_text())
bundle = json.loads((root / 'spec' / 'harp_seal_nature_short_v2.json').read_text())
assert nature_story_flow.compile_directed_short(episode) == bundle
assert 'stated_policy_goal' in story_compiler.factual_plan_prompt('test', 90, 8, 'backfiring_solution')
print('Installed wheel: imports, seven references, channel profiles, approval page, bundled pilots and Nature compiler passed')
'''
    dependencies = [p for p in sys.path if pathlib.Path(p).name in {'site-packages', 'dist-packages'}]
    subprocess.run([sys.executable, '-I', '-c', code, directory, json.dumps(dependencies)],
                   cwd=directory, check=True)
