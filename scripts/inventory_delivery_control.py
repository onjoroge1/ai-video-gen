"""Read-only inventory of a saved local control. No imports of the paid pipeline.

Example: python scripts/inventory_delivery_control.py jobs/canetoad01 --output /tmp/canetoad01-inventory.json
This writes hashes/presence only, not the files, credentials, or an approval. Existing
files are never changed. File presence alone does not prove that a run is reproducible.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

# Only known artifacts/media are read. Never inventory environment files, tokens,
# provider caches, hidden directories, font assets, or symlinks outside the job.
ROOT_FILES = {'_state.json', 'research_dossier.json', 'generation_manifest.json',
    'run_result.json', 'run.log', 'run_error.txt', 'request.json', 'run_request.json',
    'direction.txt', 'transcript.txt', 'captions.srt', 'storyboard.json',
    'illustrated_storyboard.json', 'rendered_contract.json', 'script_readiness.json',
    'explainer.mp4', 'explainer.recut.mp4'}
MEDIA_DIRS = {'audio', 'images', 'images_keep', 'scenes', 'segments', 'motion', 'music', 'recut'}
MEDIA_SUFFIXES = {'.mp4', '.mp3', '.wav', '.m4a', '.jpg', '.jpeg', '.png', '.webp'}


def inventory(root: Path) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError('Control job directory is unavailable')
    files = []
    ignored_links = []
    # Path.walk(follow_symlinks=False) would require Python 3.12; production CI is 3.11.
    import os
    for base, directories, names in os.walk(root, followlinks=False):
        rel_dir = Path(base).relative_to(root)
        for d in list(directories):
            full = Path(base) / d
            if full.is_symlink() or d.startswith('.') or (rel_dir == Path('.') and d not in MEDIA_DIRS):
                directories.remove(d)
                if full.is_symlink():
                    ignored_links.append(full.relative_to(root).as_posix())
        for name in names:
            path = Path(base) / name
            rel = path.relative_to(root)
            if path.is_symlink():
                ignored_links.append(rel.as_posix())
                continue
            allowed = (len(rel.parts) == 1 and name in ROOT_FILES) or (
                len(rel.parts) > 1 and rel.parts[0] in MEDIA_DIRS and not name.startswith('.')
                and path.suffix.lower() in MEDIA_SUFFIXES)
            if not allowed or not path.is_file():
                continue
            initial = path.stat()
            h = hashlib.sha256()
            with path.open('rb') as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b''):
                    h.update(block)
            final = path.stat()
            if (initial.st_size, initial.st_mtime_ns, initial.st_ino) != (final.st_size, final.st_mtime_ns, final.st_ino):
                raise ValueError('An artifact changed during inventory; stop the writer and retry')
            files.append({'path': rel.as_posix(), 'size_bytes': final.st_size, 'sha256': h.hexdigest()})
    paths = {f['path'] for f in files}
    presence = {
        'saved_script': '_state.json' in paths,
        'research': 'research_dossier.json' in paths,
        'explicit_request_file': bool(paths & {'request.json', 'run_request.json'}),
        'recorded_result': 'run_result.json' in paths,
        'generation_manifest': 'generation_manifest.json' in paths,
        'original_mp4': 'explainer.mp4' in paths,
        'recut_mp4': 'explainer.recut.mp4' in paths,
        'audio_files': any(f['path'].startswith('audio/') for f in files),
        'image_files': any(f['path'].startswith(('images/', 'images_keep/')) for f in files),
    }
    return {'version': 1, 'job_directory_name': root.name, 'mode': 'read_only_inventory',
        'provider_calls': 0, 'approval': False, 'reproducibility_verified': False,
        'presence': presence, 'missing_or_unavailable': [k for k, v in presence.items() if not v],
        'ignored_symlinks': sorted(ignored_links), 'files': sorted(files, key=lambda f: f['path']),
        'limits': 'No decoding, source validation, completeness check, or inference of original environment/settings. A request may be embedded elsewhere; absent standalone files are not proof no request was recorded.'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job_directory', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.output.resolve().is_relative_to(args.job_directory.resolve()):
            raise ValueError('Write the inventory outside the saved control directory')
        report = inventory(args.job_directory)
        with args.output.open('x', encoding='utf-8') as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.write('\n')
    except (OSError, ValueError) as exc:
        parser.exit(2, f'Inventory not completed: {exc}\n')
    print('Read-only inventory saved; reproducibility and approval remain unverified.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
