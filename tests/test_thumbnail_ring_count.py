"""Exactly one crossed-out circle reaches the viewer.

The delivered killer bees thumbnail carried two: the image prompt tells the model not to draw a
prohibition sign, it drew one anyway, and `compose` then added the renderer's own on top. The
prompt was already correct, so the defect was never going to be fixed by rewording it -- the
count has to be enforced where the pixels are.
"""
import backfire_packaging as bp
from PIL import Image


def _bg(tmp_path):
    path = tmp_path / "bg.jpg"
    Image.new("RGB", (1536, 1024), (200, 190, 170)).save(path)
    return str(path)


def test_the_overlay_ring_can_be_left_off(tmp_path):
    """Without a switch there is no way to decline the second ring."""
    with_ring = tmp_path / "with.jpg"
    without = tmp_path / "without.jpg"
    bp.compose(_bg(tmp_path), str(with_ring), ring_overlay=True)
    bp.compose(_bg(tmp_path), str(without), ring_overlay=False)
    a = Image.open(with_ring).convert("RGB")
    b = Image.open(without).convert("RGB")
    assert a.size == b.size == (1280, 720)
    assert a.tobytes() != b.tobytes(), "ring_overlay=False changed nothing; the switch is inert"


def test_the_ring_is_drawn_by_default(tmp_path):
    """The flag is additive: packaging that never passes it behaves exactly as before."""
    out = tmp_path / "default.jpg"
    bp.compose(_bg(tmp_path), str(out))
    geo = bp.geometry(1280, 720)
    cx, cy = geo["ring_center"]
    r = geo["ring_radius"]
    px = Image.open(out).convert("RGB")
    # The ring's left edge should be far redder than the flat background it was drawn over.
    edge = px.getpixel((cx - r + geo["ring_width"] // 2, cy))
    assert edge[0] > edge[2] + 40, f"no red ring at the ring's edge: {edge}"


def test_a_failed_vision_call_does_not_claim_the_artwork_is_clean(monkeypatch, tmp_path):
    """A swallowed config error reported 'no ring', which is how two circles shipped."""
    said = []
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = bp.detect_drawn_ring(_bg(tmp_path), None, said.append)
    assert result is False, "an unavailable check must not block packaging"
    assert said and "unavailable" in said[0], f"the failure was silent: {said!r}"
