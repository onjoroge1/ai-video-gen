"""Media binary resolution for the long-form explainer path.

The explainer pipeline used bare "ffmpeg"/"ffprobe" strings in ~27 places, so it rendered only
where those happened to be on PATH. CI installs them explicitly; the Vercel Python runtime does
not ship them, so code that passed CI could not render in production.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

import media_binaries as mb


@pytest.fixture(autouse=True)
def _clean_cache():
    mb.reset_cache()
    yield
    mb.reset_cache()


def _blind(monkeypatch, *, keep_bundled: bool = True):
    """Simulate a host with no system ffmpeg/ffprobe, like Vercel's Python runtime."""
    monkeypatch.setattr(mb.shutil, "which", lambda _name: None)
    monkeypatch.setattr(mb, "_SEARCH_DIRS", ())
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.delenv("FFPROBE_BIN", raising=False)
    if not keep_bundled:
        monkeypatch.setattr(mb, "bundled_ffmpeg", lambda: None)


def test_system_binaries_resolve_when_present():
    assert os.path.isfile(mb.ffmpeg())
    assert os.path.isfile(mb.ffprobe())


def test_an_explicit_override_wins_over_everything(monkeypatch):
    monkeypatch.setenv("FFMPEG_BIN", "/custom/ffmpeg")
    monkeypatch.setenv("FFPROBE_BIN", "/custom/ffprobe")
    assert mb.resolve("ffmpeg") == "/custom/ffmpeg"
    assert mb.resolve("ffprobe") == "/custom/ffprobe"


def test_a_host_without_system_ffmpeg_still_resolves_the_bundled_build(monkeypatch):
    # This is the production case the repo previously could not handle at all.
    _blind(monkeypatch)
    resolved = mb.resolve("ffmpeg")
    assert resolved and os.path.isfile(resolved)
    assert resolved == mb.bundled_ffmpeg()


def test_the_bundled_ffmpeg_actually_runs(monkeypatch):
    _blind(monkeypatch)
    result = subprocess.run([mb.ffmpeg(), "-version"], capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, timeout=30)
    assert result.returncode == 0
    assert "ffmpeg version" in result.stdout


def test_missing_ffprobe_raises_an_actionable_error_not_a_bare_filenotfound(monkeypatch):
    # imageio-ffmpeg ships ffmpeg only, so ffprobe is the real remaining host requirement.
    _blind(monkeypatch)
    with pytest.raises(mb.MediaBinaryError) as exc:
        mb.ffprobe()
    message = str(exc.value)
    assert "ffprobe" in message
    assert "FFPROBE_BIN" in message and "apt-get install" in message


def test_preflight_reports_a_renderable_host():
    report = mb.preflight()
    assert report["ready"] is True
    assert report["missing"] == []
    assert "ffmpeg version" in report["binaries"]["ffmpeg"]["version"]


def test_preflight_names_what_is_missing_before_any_spend(monkeypatch):
    _blind(monkeypatch)
    report = mb.preflight()
    assert report["ready"] is True
    assert report["missing"] == ["ffprobe"]
    assert report["binaries"]["ffmpeg"]["source"] == "bundled"
    assert report["probe_source"] == "ffmpeg-fallback"
    assert report["remedy"] == ""


def test_bundled_ffmpeg_probes_media_without_system_ffprobe(tmp_path, monkeypatch):
    source = tmp_path / "probe.mp4"
    subprocess.run([
        mb.ffmpeg(), "-y", "-f", "lavfi", "-i",
        "color=c=black:s=320x180:d=1", "-an", "-c:v", "libx264", str(source),
    ], check=True, capture_output=True, timeout=30)
    _blind(monkeypatch)
    mb.reset_cache()

    report = mb.probe_media(str(source))

    assert report["source"] == "ffmpeg-fallback"
    assert report["duration"] >= 0.9
    assert (report["width"], report["height"]) == (320, 180)


def test_preflight_reports_a_completely_unrenderable_host(monkeypatch):
    _blind(monkeypatch, keep_bundled=False)
    report = mb.preflight()
    assert report["ready"] is False
    assert report["missing"] == ["ffmpeg", "ffprobe"]
    assert report["binaries"]["ffmpeg"]["source"] == "missing"


def test_an_unsupported_binary_name_is_rejected():
    with pytest.raises(ValueError, match="Unsupported media binary"):
        mb.resolve("rm")


# ---------------------------------------------------------------------------------------------
# The long-form path must actually use the resolver
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("module", [
    "explainer_pipeline", "longform_rendered_gate", "overlays", "highlights",
])
def test_no_long_form_module_shells_out_to_a_bare_binary_name(module):
    source = open(f"{module}.py", encoding="utf-8").read()
    # The only permitted bare "ffmpeg" literal is the -nostdin basename guard, which compares
    # a resolved path's basename rather than invoking anything.
    invocations = source.count('"ffprobe"') + source.count('"ffmpeg"')
    allowed = 1 if module == "explainer_pipeline" else 0
    assert invocations == allowed, f"{module} still invokes a bare binary name"
    assert "_ffmpeg_bin" in source or "_ffprobe_bin" in source


def test_nostdin_is_still_injected_for_a_resolved_path(monkeypatch):
    import explainer_pipeline as ep

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(ep.subprocess, "run", fake_run)
    ep._run_ffmpeg(["/usr/bin/ffmpeg", "-i", "in.mp4"])
    assert captured["cmd"][:2] == ["/usr/bin/ffmpeg", "-nostdin"]

    # The bundled build is named ffmpeg-linux-x86_64-vN, not "ffmpeg".
    ep._run_ffmpeg(["/pkg/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2", "-i", "in.mp4"])
    assert captured["cmd"][1] == "-nostdin"

    # A non-ffmpeg command is left alone.
    ep._run_ffmpeg(["/usr/bin/ffprobe", "-i", "in.mp4"])
    assert "-nostdin" not in captured["cmd"]


def test_moviepy_is_not_a_runtime_dependency():
    requirements = open("requirements.txt", encoding="utf-8").read()
    active = [line for line in requirements.splitlines()
              if line.strip() and not line.strip().startswith("#")]
    assert not any(line.startswith("moviepy") for line in active), (
        "moviepy 1.0.3 fails to build against modern setuptools and is unused by the "
        "explainer path; it must not break a clean install")
    assert any(line.startswith("imageio-ffmpeg") for line in active)


def test_the_explainer_path_does_not_import_moviepy():
    for module in ("explainer_pipeline", "longform_rendered_gate", "overlays", "highlights"):
        assert "moviepy" not in open(f"{module}.py", encoding="utf-8").read()
    assert "moviepy" not in sys.modules


# ---------------------------------------------------------------------------------------------
# End-to-end: the real assembly path must produce a real MP4
# ---------------------------------------------------------------------------------------------

def test_the_real_assembly_path_renders_a_valid_mp4(tmp_path):
    """Drives explainer_pipeline's own _make_scene_segment/_assemble — no provider calls."""
    from scripts.render_smoke import render_smoke

    report = render_smoke(str(tmp_path))
    assert report["ok"] is True, report
    assert report["video_codec"] == "h264"
    assert report["audio_codec"] == "aac"
    assert report["resolution"] == "1920x1080"
    assert report["duration_sec"] > 0
    assert os.path.getsize(report["output_path"]) > 50_000


def test_the_render_path_works_with_only_the_bundled_ffmpeg(tmp_path, monkeypatch):
    """The production case: a host with no system ffmpeg still renders."""
    from scripts.render_smoke import render_smoke

    bundled = mb.bundled_ffmpeg()
    assert bundled, "imageio-ffmpeg must supply a static ffmpeg"
    monkeypatch.setenv("FFMPEG_BIN", bundled)
    mb.reset_cache()

    report = render_smoke(str(tmp_path))
    assert report["ok"] is True, report
    assert report["preflight"]["binaries"]["ffmpeg"]["source"] == "override"
    assert report["video_codec"] == "h264"


def test_render_smoke_fails_closed_when_a_binary_is_missing(tmp_path, monkeypatch):
    from scripts.render_smoke import render_smoke

    _blind(monkeypatch, keep_bundled=False)
    report = render_smoke(str(tmp_path))
    assert report["ok"] is False
    assert report["stage"] == "preflight"
    assert "ffmpeg" in report["error"]
    # It must not have attempted, or half-written, a render.
    assert not list(tmp_path.glob("*.mp4"))
