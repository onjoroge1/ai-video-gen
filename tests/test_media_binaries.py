"""Regression tests for portable quiz media binaries on Vercel/Linux/macOS."""

import os
import shutil
from unittest import mock

import pytest

import quiz_pipeline as qp


def test_ffmpeg_still_resolves_when_the_host_has_no_system_install():
    """Portability is about the host WITHOUT ffmpeg, not about this laptop's PATH.

    The previous assertion here was `not qp.FF.startswith("/opt/homebrew/")`, which fails on
    any Mac with Homebrew ffmpeg on PATH even though resolution is perfectly portable. It
    conflated "this machine happened to resolve to Homebrew" with "the code is pinned to
    Homebrew" -- and preferring a system install is the documented, intended order.

    The property that actually protects a deploy: with nothing on PATH and no system install,
    the imageio-ffmpeg wheel declared in requirements.txt still yields a usable binary.
    """
    import media_binaries

    # Resolved BEFORE patching: bundled_ffmpeg() itself calls os.path.isfile, so a mock that
    # consults it recurses.
    bundled = media_binaries.bundled_ffmpeg()
    assert bundled, "imageio-ffmpeg is in requirements.txt but not installed in this env"

    media_binaries.reset_cache()
    try:
        with mock.patch.object(shutil, "which", return_value=None), \
             mock.patch.object(os.path, "isfile", lambda p: p == bundled):
            resolved = media_binaries.resolve("ffmpeg", use_cache=False)
    finally:
        media_binaries.reset_cache()

    assert resolved, "no ffmpeg without a system install — the deploy host cannot render"
    assert resolved == bundled
    # Deliberately NOT asserting anything about the path prefix. On a Homebrew Python the
    # wheel's own binary lives under /opt/homebrew/lib/python3.x/site-packages/, so a prefix
    # check would flag the portable fallback as the pin it was written to detect.


def test_ffprobe_has_no_bundled_fallback_and_says_so():
    """imageio-ffmpeg ships ffmpeg only. A deploy host still has to provide ffprobe.

    Pinned deliberately: this is the half of the portability gap the wheel does NOT close,
    and preflight is what surfaces it for $0 rather than mid-render. If a future wheel starts
    bundling ffprobe, this test fails and the docstrings above it need updating.
    """
    import media_binaries

    media_binaries.reset_cache()
    try:
        with mock.patch.object(shutil, "which", return_value=None), \
             mock.patch.object(os.path, "isfile", return_value=False):
            assert media_binaries.resolve("ffprobe", use_cache=False) is None
    finally:
        media_binaries.reset_cache()


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
