#!/usr/bin/env python3
"""Install optional engines outside ReelForge's application environment.

Installation never calls a media provider, launches a server or publishes video.
Run with --source-only for a pinned source checkout without dependency installation.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LOCK = json.loads((HERE / 'sources.lock.json').read_text())


def run(args: list[str], cwd: Path | None = None, capture: bool = False) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            timeout=1500)
    return (result.stdout or '').strip()


def executable(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f'Required executable not found: {name}')
    return path


def checkout(engine: str, runtime: Path) -> Path:
    source = LOCK['sources'][engine]
    target = runtime / engine
    git = executable('git')
    if not target.exists():
        run([git, 'clone', '--filter=blob:none', '--no-checkout', '--depth', '1',
             source['repository'], str(target)])
    if not (target / '.git').is_dir():
        raise RuntimeError(f'Refusing to overwrite non-repository directory: {target}')
    origin = run([git, 'remote', 'get-url', 'origin'], target, capture=True)
    if origin != source['repository']:
        raise RuntimeError(f'{engine}: origin differs from sources.lock.json')
    dirty = run([git, 'status', '--porcelain', '--untracked-files=no'], target, capture=True)
    if dirty:
        raise RuntimeError(f'{engine}: tracked changes exist; preserve them before upgrading')
    run([git, 'fetch', '--depth', '1', 'origin', source['revision']], target)
    run([git, '-c', 'core.hooksPath=/dev/null', 'checkout', '--detach', source['revision']], target)
    actual = run([git, 'rev-parse', 'HEAD'], target, capture=True)
    if actual != source['revision']:
        raise RuntimeError(f'{engine}: pinned revision mismatch')
    return target


def install(engine: str, runtime: Path, python: str, source_only: bool) -> dict:
    report: dict = {'engine': engine, 'provider_calls': 0, 'server_started': False,
                    'render_verified': False}
    if engine == 'motion_canvas':
        project = ROOT / 'integrations' / 'motion-canvas'
        report['version'] = LOCK['motion_canvas']['version']
        if source_only:
            return {**report, 'status': 'manifest_present'}
        npm = executable('npm')
        command = 'ci' if (project / 'package-lock.json').exists() else 'install'
        run([npm, command, '--no-audit', '--no-fund'], project)
        run([npm, 'run', 'build'], project)
        report['status'] = 'installed_and_built'
    else:
        target = checkout(engine, runtime)
        report['revision'] = LOCK['sources'][engine]['revision']
        if source_only:
            return {**report, 'status': 'source_checked_out'}
        py = executable(python)
        version = run([py, '-c', 'import sys; print("%s.%s" % sys.version_info[:2])'], capture=True)
        if version != '3.11':
            raise RuntimeError(f'Use Python 3.11 for isolated engines, got {version}')
        if engine == 'moneyprinterturbo':
            run([executable('uv'), 'sync', '--frozen', '--no-dev', '--python', py], target)
            vpython = target / '.venv' / 'bin' / 'python'
            run([str(vpython), '-c', 'import moviepy; from app.models.schema import VideoParams; print(VideoParams(video_subject="Installation probe").video_aspect)'], target)
            run([executable('uv'), 'pip', 'check', '--python', str(vpython)], target)
        else:
            venv = target / '.reelforge-venv'
            if not venv.exists():
                run([py, '-m', 'venv', str(venv)])
            vpython = venv / 'bin' / 'python'
            requirements = (target / 'requirements.txt').read_text().splitlines()
            # CPU wheels avoid installing multi-gigabyte CUDA runtimes on CPU hosts.
            torch_pins = [s for s in requirements if s.startswith(('torch==', 'torchvision=='))]
            if len(torch_pins) != 2:
                raise RuntimeError('Pinned OpenShorts torch contract changed; review before installing')
            run([str(vpython), '-m', 'pip', 'install', *torch_pins,
                 '--index-url', 'https://download.pytorch.org/whl/cpu'], target)
            # Deliberately do not install requirements-billing.txt or render-service.
            run([str(vpython), '-m', 'pip', 'install', '-r', 'requirements.txt'], target)
            run([str(vpython), '-m', 'pip', 'check'], target)
            run([str(vpython), '-c', 'import fastapi, cv2, torch, mediapipe; print("Core runtime imports passed; no model inference performed")'], target)
        report['status'] = 'installed_and_imported'
    out = runtime / 'reports'
    out.mkdir(parents=True, exist_ok=True)
    (out / f'{engine}.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('engine', choices=['all', 'moneyprinterturbo', 'motion_canvas', 'openshorts'])
    parser.add_argument('--runtime-root', type=Path, default=HERE / 'runtime')
    parser.add_argument('--python', default='python3.11')
    parser.add_argument('--source-only', action='store_true')
    args = parser.parse_args()
    if os.name != 'posix':
        parser.error('Use Linux, macOS or WSL; native Windows is not yet supported by this wrapper')
    runtime = args.runtime_root.expanduser().resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    engines = ['moneyprinterturbo', 'motion_canvas', 'openshorts'] if args.engine == 'all' else [args.engine]
    try:
        for engine in engines:
            print(json.dumps(install(engine, runtime, args.python, args.source_only), indent=2), flush=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f'Installation failed; this engine is not marked ready: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
