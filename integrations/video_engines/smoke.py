#!/usr/bin/env python3
"""Provider-free media-boundary smoke checks, not full production-flow acceptance."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

HERE = Path(__file__).resolve().parent


def run(args: list[str], **kwargs):
    return subprocess.run(args, check=True, timeout=300, **kwargs)


def probe(path: Path) -> dict:
    result = run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
                 capture_output=True, text=True)
    data = json.loads(result.stdout)
    video = next(s for s in data['streams'] if s['codec_type'] == 'video')
    assert video['codec_name'] == 'h264', data
    assert video['pix_fmt'] == 'yuv420p', data
    assert any(s['codec_type'] == 'audio' for s in data['streams']), data
    assert 1.9 <= float(data['format']['duration']) <= 4.2, data
    return {'width': video['width'], 'height': video['height'],
            'duration': float(data['format']['duration']), 'bytes': path.stat().st_size}


def worker(engine: str, target: Path, output: Path) -> None:
    # This fixture provides every asset locally. Refuse accidental calls from
    # new upstream versions, including model downloads and auto-publish calls.
    def reject_network(event, args):
        if event in {'socket.connect', 'socket.getaddrinfo'}:
            raise RuntimeError('Network access is forbidden during engine smoke tests')
    sys.addaudithook(reject_network)
    sys.path.insert(0, str(target))
    os.environ['FFMPEG_ENCODER'] = 'x264'
    os.environ['AUDIO_NORMALIZE'] = '0'
    source, audio = output / 'source.mp4', output / 'narration.wav'
    # MPT requires both source dimensions to be at least 480 pixels.
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=540x960:r=24:d=4',
         '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
         '-c:a', 'aac', '-shortest', str(source)])
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-vn', str(audio)])
    result_path = output / 'result.mp4'
    if engine == 'moneyprinterturbo':
        from app.models.schema import MaterialInfo, VideoParams
        from app.services import task
        from app.utils import utils
        task.config.app['upload_post_auto_upload'] = False
        task.config.app['upload_post_enabled'] = False
        # Honor upstream's allowed-directory guard; never widen it for a test.
        local_asset = Path(utils.storage_dir('local_videos', create=True)).resolve() / ('reelforge-smoke-' + uuid.uuid4().hex + '.mp4')
        shutil.copy2(source, local_asset)
        try:
            params = VideoParams(video_subject='Local installation fixture',
                video_script='This is a local technical fixture, not a published story.',
                video_source='local', video_materials=[MaterialInfo(provider='local', url=str(local_asset), duration=4)],
                custom_audio_file=str(audio), video_aspect='9:16', video_fit_mode='contain',
                video_concat_mode='sequential', video_clip_duration=2, video_count=1,
                bgm_type='', bgm_volume=0, subtitle_enabled=False, n_threads=2)
            result = task.start('reelforge-smoke-' + uuid.uuid4().hex, params, allow_server_file_input=True)
            if not result or not result.get('videos'):
                raise RuntimeError(f'MoneyPrinterTurbo produced no final video: {result}')
            shutil.copy2(result['videos'][0], result_path)
        finally:
            local_asset.unlink(missing_ok=True)
        scope = 'local-script/local-audio/local-materials assembly; no stock retrieval or TTS'
    else:
        from ffmpeg_utils import cut_clip
        cut_clip(str(source), str(result_path), 1, 3, 1)
        scope = 'OpenShorts cut_clip media boundary only; no moment selection, tracking or captions'
    report = {'engine': engine, 'status': 'media_smoke_passed', 'scope': scope,
              'network_blocked': True, 'production_ready': False, 'probe': probe(result_path)}
    (output / 'smoke-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('engine', choices=['moneyprinterturbo', 'openshorts'])
    parser.add_argument('--runtime-root', type=Path, default=HERE / 'runtime')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    runtime = args.runtime_root.resolve()
    target = runtime / args.engine
    try:
        if args.worker:
            if args.output is None: raise ValueError('worker needs output')
            worker(args.engine, target, args.output)
        else:
            for binary in ('ffmpeg', 'ffprobe'):
                if not shutil.which(binary): raise RuntimeError(f'{binary} is required')
            venv = '.venv' if args.engine == 'moneyprinterturbo' else '.reelforge-venv'
            interpreter = target / venv / 'bin/python'
            if not interpreter.is_file(): raise RuntimeError('Install the isolated engine first')
            reports = runtime / 'reports'
            reports.mkdir(parents=True, exist_ok=True)
            # Keep small fixtures as CI evidence, never mix them into /finished.
            output = Path(tempfile.mkdtemp(prefix=f'smoke-{args.engine}-', dir=reports))
            run([str(interpreter), str(Path(__file__).resolve()), args.engine,
                 '--runtime-root', str(runtime), '--worker', '--output', str(output)], cwd=target)
    except (OSError, RuntimeError, subprocess.SubprocessError, AssertionError) as exc:
        print(f'Media smoke failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
