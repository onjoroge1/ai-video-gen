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


def test_loop_xfade_normalizes_both_inputs_to_explicit_cfr(monkeypatch, tmp_path):
    import quiz_pipeline as facade

    legacy = facade._legacy
    captured = {}

    def successful_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(legacy.subprocess, "run", successful_run)
    monkeypatch.setattr(legacy, "_dur", lambda path: 1.0)

    legacy._render_sequence(
        [
            (str(tmp_path / "head.png"), 1.0, False),
            (str(tmp_path / "loop.png"), 0.5, False, {"xfade_prev": 0.4}),
        ],
        str(tmp_path / "out.mp4"),
        1.0,
    )

    command = captured["command"]
    graph = command[command.index("-filter_complex") + 1]
    normalizer = "format=yuv420p,setpts=PTS-STARTPTS,fps=30,settb=AVTB"
    assert f"concat=n=1:v=1:a=0,{normalizer}[pre]" in graph
    assert f"[v1]{normalizer}[loop]" in graph
    assert "[pre][loop]xfade=" in graph
