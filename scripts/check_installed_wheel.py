"""Smoke-test an extracted wheel away from the repository checkout (no provider calls)."""
import pathlib
import subprocess
import sys
import tempfile
import zipfile

wheel = pathlib.Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='reelforge-installed-') as directory:
    with zipfile.ZipFile(wheel) as package:
        package.extractall(directory)
    code = '''
import pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
import app, durable_execution, illustrated_story, provider_readiness, reference_corpus
for module in (app, durable_execution, illustrated_story, provider_readiness, reference_corpus):
    assert pathlib.Path(module.__file__).resolve().is_relative_to(root), module.__file__
assert len(reference_corpus.load()) == 6
assert (root / 'static' / 'agent_actions.html').is_file()
assert (root / 'spec' / 'hippo_illustrated_story_v4.json').is_file()
print('Installed wheel: imports, six references, approval page and bundled pilot passed')
'''
    subprocess.run([sys.executable, '-I', '-c', code, directory], cwd=directory, check=True)
