import struct

import pytest

import hippo_recovery


def _box(kind: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def test_mp4_top_level_boxes_accepts_standard_container(tmp_path):
    path = tmp_path / "standard.mp4"
    path.write_bytes(_box(b"ftyp") + _box(b"mdat") + _box(b"moov"))
    assert hippo_recovery._mp4_top_level_boxes(path) == ["ftyp", "mdat", "moov"]


def test_mp4_top_level_boxes_exposes_fragmented_container(tmp_path):
    path = tmp_path / "fragmented.mp4"
    path.write_bytes(_box(b"ftyp") + _box(b"moov") + _box(b"moof") + _box(b"mdat"))
    assert "moof" in hippo_recovery._mp4_top_level_boxes(path)


def test_mp4_top_level_boxes_rejects_trailing_bytes(tmp_path):
    path = tmp_path / "bad.mp4"
    path.write_bytes(_box(b"ftyp") + b"x")
    with pytest.raises(hippo_recovery.HippoRecoveryError, match="trailing bytes"):
        hippo_recovery._mp4_top_level_boxes(path)
