"""The generated frame reaches the screen as sharp as the model drew it.

Measured on the delivered bee film: the API's PNG was re-encoded at JPEG 82 with 4:2:0 chroma,
upscaled 2.5x into a 3840x2160 supersample with the default scaler, zoomed into at 1.14-1.16, and
downsampled to 1080p -- so the pixels on screen came from a ~1,320-px-wide region of a JPEG-82
source. Invisible on a phone; soft on a desktop, which is where the operator noticed.
"""
import io
import os

from PIL import Image, JpegImagePlugin

import explainer_pipeline as ep


def _flat_art(path):
    # Flat gouache blocks and a hard ink line: the content JPEG artifacts land on.
    im = Image.new("RGB", (1536, 1024), (236, 229, 210))
    px = im.load()
    for x in range(1536):
        for y in range(1024):
            if 300 < x < 900 and 200 < y < 700:
                px[x, y] = (178, 46, 52)
            if 598 <= x <= 602:
                px[x, y] = (20, 18, 16)
    im.save(path, "PNG")


def test_the_render_input_keeps_full_chroma_and_high_quality(tmp_path):
    path = str(tmp_path / "scene_00.jpg")
    _flat_art(path)
    ep._normalize_generated_image(path)
    with Image.open(path) as im:
        assert im.format == "JPEG"
        assert JpegImagePlugin.get_sampling(im) == 0, "4:4:4 chroma; 4:2:0 blurs the ink lines"
    # ...and is materially heavier than the old q82 of the same art, which is the point.
    old = io.BytesIO()
    with Image.open(path) as im:
        im.save(old, "JPEG", quality=82, optimize=True, progressive=True)
    assert os.path.getsize(path) > len(old.getvalue()) * 1.5


def test_the_zoom_ceiling_keeps_most_of_the_source_in_frame():
    z, _, _ = ep._motion("kenburns_in", 30)
    assert f"{ep._KB_ZOOM:.2f}" in z and "1.14" not in z
    assert ep._KB_ZOOM <= 1.10, "a 1.14+ zoom shows ~1,320 px of a 1,536-px frame on a 1,920 canvas"
    for preset in ("pan_right", "pan_left", "pan_up", "pan_down"):
        assert ep._motion(preset, 30)[0] == f"{ep._KB_ZOOM:.2f}"
    corner, _, _ = ep._motion("zoom_tl", 30)
    assert f"{ep._KB_ZOOM + 0.02:.2f}" in corner and "1.16" not in corner


def test_both_scale_chains_use_lanczos():
    source = open(ep.__file__, encoding="utf-8").read()
    assert source.count("force_original_aspect_ratio=increase:flags=lanczos") >= 2
