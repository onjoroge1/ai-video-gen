from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one target block, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    "_quiz_pipeline_legacy.py",
    '''    result = subprocess.run(
        [FF, "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[out]",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), out],
        capture_output=True)
    actual = _dur(out)
    if result.returncode != 0 or actual < expected_duration - 0.2:
        err = result.stderr.decode(errors="replace")[-400:] if result.stderr else ""
        raise RuntimeError(f"quiz sequence render failed: expected {expected_duration:.2f}s, "
                           f"got {actual:.2f}s; {err}")
''',
    '''    result = subprocess.run(
        [FF, "-y", *inputs, "-filter_complex", ";".join(filters), "-map", "[out]",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), out],
        capture_output=True)
    err = result.stderr.decode(errors="replace")[-1600:] if result.stderr else ""
    # Never probe a failed encode. The previous order called `_dur(out)` first, so an absent or
    # malformed output raised MediaBinaryError and erased the FFmpeg stderr that explained the
    # actual filter/codec failure. That made a paid quiz render impossible to diagnose.
    if result.returncode != 0:
        raise RuntimeError(
            f"quiz sequence FFmpeg failed with exit {result.returncode}: {err}")
    try:
        actual = _dur(out)
    except Exception as exc:
        size = os.path.getsize(out) if os.path.exists(out) else 0
        raise RuntimeError(
            f"quiz sequence produced an unreadable output ({size} bytes): {err}") from exc
    if actual < expected_duration - 0.2:
        raise RuntimeError(f"quiz sequence render failed: expected {expected_duration:.2f}s, "
                           f"got {actual:.2f}s; {err}")
''',
)

Path("tests/test_quiz_render_sequence_errors.py").write_text(
    '''from types import SimpleNamespace

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
''',
    encoding="utf-8",
)

print("Applied fail-first quiz sequence diagnostics and regression test.")
