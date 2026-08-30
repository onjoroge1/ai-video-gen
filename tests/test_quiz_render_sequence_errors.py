from types import SimpleNamespace

import pytest


def test_render_sequence_reports_ffmpeg_stderr_before_probing(monkeypatch, tmp_path):
    # Import through the public facade at test time. Importing the legacy module during pytest
    # collection pinned its Mac development fallback before the facade could bind portable FFmpeg,
    # which then broke unrelated end-to-end render tests on Linux.
    import quiz_pipeline as facade

    legacy = facade._legacy
    calls = {"probed": False}

    def failed_run(*args, **kwargs):
        return SimpleNamespace(returncode=1, stderr=b"No such filter: deliberate-smoke-error")

    def forbidden_probe(path):
        calls["probed"] = True
        raise AssertionError("a failed encode must not be probed")

    monkeypatch.setattr(legacy.subprocess, "run", failed_run)
    monkeypatch.setattr(legacy, "_dur", forbidden_probe)

    with pytest.raises(RuntimeError, match="deliberate-smoke-error"):
        legacy._render_sequence(
            [(str(tmp_path / "card.png"), 1.0, False)],
            str(tmp_path / "out.mp4"),
            1.0,
        )

    assert calls["probed"] is False
