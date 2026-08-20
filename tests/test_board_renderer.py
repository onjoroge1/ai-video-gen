from pathlib import Path

from PIL import Image

import board_pipeline


def test_board_renders_with_portable_fonts_and_left_right_control(tmp_path: Path):
    state = {
        "title": "EPISODE REVIEW", "subtitle": "Example · S1E2",
        "left": {"name": "THREAD A", "accent": "steel", "chips": []},
        "right": {"name": "THREAD B", "accent": "green", "chips": []},
        "control": {"label": "THE MYSTERY", "held_by": "left", "text": "New clue"},
        "assets": {"label": "CLUES", "left": 2, "right": 1},
    }
    out = tmp_path / "board.png"
    board_pipeline.render_board(state, str(out))
    assert out.exists()
    assert Image.open(out).size == (1920, 1080)
