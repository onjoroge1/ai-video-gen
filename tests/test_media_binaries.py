"""Regression tests for portable quiz media binaries on Vercel/Linux/macOS."""

import os
import shutil

import pytest

import quiz_pipeline as qp


def test_media_binaries_are_not_pinned_to_homebrew():
    assert not qp.FF.startswith("/opt/homebrew/")
    assert not qp.FP.startswith("/opt/homebrew/")


def test_resolved_media_binaries_exist_in_ci():
    for binary in (qp.FF, qp.FP):
        resolved = binary if os.path.isabs(binary) else shutil.which(binary)
        assert resolved, f"{binary} does not resolve"
        assert os.path.isfile(resolved), f"{resolved} is not a file"
        assert os.access(resolved, os.X_OK), f"{resolved} is not executable"


def test_legacy_renderer_uses_same_resolved_binaries():
    assert qp._legacy.FF == qp.FF
    assert qp._legacy.FP == qp.FP


def test_explicit_media_override_wins(monkeypatch):
    monkeypatch.setenv("FFMPEG_BIN", "/custom/ffmpeg")
    assert qp._resolve_media_bin("ffmpeg", "FFMPEG_BIN") == "/custom/ffmpeg"


def test_missing_binary_falls_back_to_bare_name(monkeypatch):
    monkeypatch.delenv("FFPROBE_BIN", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(os.path, "exists", lambda _path: False)
    assert qp._resolve_media_bin("ffprobe", "FFPROBE_BIN") == "ffprobe"


def test_file_not_found_becomes_terminal_value_error(monkeypatch):
    def fail(*_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory", "/opt/homebrew/bin/ffprobe")

    monkeypatch.setattr(qp._legacy, "run_quiz_pipeline", fail)
    with pytest.raises(ValueError, match="Required media binary or input was not found"):
        qp.run_quiz_pipeline("animals", "/tmp/unused")
