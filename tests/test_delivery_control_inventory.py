from pathlib import Path
import subprocess
import sys
import pytest
from scripts.inventory_delivery_control import inventory


def test_inventory_is_non_spending_and_does_not_infer_a_complete_control(tmp_path):
    (tmp_path / '_state.json').write_text('{"script":{}}')
    (tmp_path / 'explainer.mp4').write_bytes(b'not a real video')
    result = inventory(tmp_path)
    assert result['presence']['saved_script']
    assert result['presence']['original_mp4']
    assert not result['presence']['image_files']
    assert not result['reproducibility_verified']
    assert result['provider_calls'] == 0 and result['approval'] is False


def test_credentials_hidden_files_fonts_and_symlinks_are_never_inventoried(tmp_path):
    (tmp_path / '.env').write_text('private')
    (tmp_path / 'youtube_token.json').write_text('private')
    (tmp_path / 'images').mkdir()
    (tmp_path / 'images' / '.env').write_text('private')
    (tmp_path / 'images' / 'scene.png').write_bytes(b'png')
    (tmp_path / 'images' / 'font.ttf').write_bytes(b'font')
    (tmp_path / 'images' / 'outside.jpg').symlink_to(tmp_path / '.env')
    result = inventory(tmp_path)
    assert [f['path'] for f in result['files']] == ['images/scene.png']
    assert result['ignored_symlinks'] == ['images/outside.jpg']


def test_missing_directory_is_an_error_not_an_empty_baseline(tmp_path):
    with pytest.raises(ValueError, match='unavailable'):
        inventory(tmp_path / 'missing')


def test_cli_refuses_overwriting_or_writing_inside_control(tmp_path):
    job = tmp_path / 'job'; job.mkdir()
    cli = Path(__file__).parents[1] / 'scripts/inventory_delivery_control.py'
    existing = tmp_path / 'inventory.json'; existing.write_text('keep')
    for out in [existing, job / 'inventory.json']:
        run = subprocess.run([sys.executable, str(cli), str(job), '--output', str(out)], capture_output=True, text=True)
        assert run.returncode == 2
    assert existing.read_text() == 'keep'
    assert not (job / 'inventory.json').exists()
