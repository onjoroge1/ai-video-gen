"""Field Guide thumbnail overlay: pure Pillow, no provider."""
import pytest
from PIL import Image

import field_guide_thumbnail as ft


def test_headline_is_two_short_lines():
    assert ft.headline_lines("wrong ocean") == ["WRONG", "OCEAN"]
    assert ft.headline_lines("STILL / BREEDING") == ["STILL", "BREEDING"]
    for bad in ("WRONG", "IT LIVES HERE NOW", "WHY / HERE?", "A / " + "B" * 15):
        with pytest.raises(ValueError):
            ft.headline_lines(bad)


def test_compose_writes_1280x720_with_headline_and_you(tmp_path):
    src = tmp_path / "scene.png"
    Image.new("RGB", (1536, 1024), (20, 60, 110)).save(src)
    out = ft.compose(str(src), str(tmp_path / "t.jpg"), headline="WRONG OCEAN",
                     you_at=(0.174, 0.572), focus_y=0.47)
    card = Image.open(out).convert("RGB")
    assert card.size == (1280, 720)
    # The headline paints white and orange pixels into the top-left; the plain scene has neither.
    top_left = card.crop((40, 22, 640, 320)).getcolors(1 << 20)
    assert any(r > 240 and g > 240 and b > 240 for _, (r, g, b) in top_left)
    assert any(r > 230 and 110 < g < 170 and b < 80 for _, (r, g, b) in top_left)
    # No person, no arrow: still a valid thumbnail.
    plain = ft.compose(str(src), str(tmp_path / "p.jpg"), headline="STILL / BREEDING",
                       you_at=None, side="right")
    assert Image.open(plain).size == (1280, 720)
