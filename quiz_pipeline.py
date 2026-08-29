"""Compatibility facade for the quiz renderer with portable media binary resolution.

The renderer implementation lives in ``_quiz_pipeline_legacy.py`` — currently the
Rapid Reveal V2.2 renderer (see ``docs/QUIZ_RETENTION_V2.md``). This facade only fixes
the runtime boundary that was macOS-specific: ffmpeg/ffprobe selection and terminal
classification of a missing binary/input. The module name is historical; sibling
renderers import this facade as ``qp`` and rely on its re-exported helpers.
"""
from __future__ import annotations

import os
import shutil

import _quiz_pipeline_legacy as _legacy
import media_binaries


# Re-export the full legacy module surface, including underscored helpers used by sibling
# renderers such as longform_quiz, health_pipeline and sim_drop_pipeline.
for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)


def _resolve_media_bin(name: str, env_var: str) -> str:
    """Resolve ffmpeg/ffprobe on Vercel, Linux, macOS and local development.

    Order:
      1. explicit FFMPEG_BIN / FFPROBE_BIN override
      2. executable on PATH
      3. known install locations
      4. bare command name so any final failure names the real missing binary
    """
    explicit = os.environ.get(env_var, "").strip()
    if explicit:
        return explicit

    found = shutil.which(name)
    if found:
        return found

    for candidate in (
        f"/usr/bin/{name}",
        f"/usr/local/bin/{name}",
        f"/opt/homebrew/bin/{name}",
    ):
        if os.path.exists(candidate):
            return candidate

    # Last resort before the bare name: the static build bundled in the imageio-ffmpeg
    # wheel, so a host with no system ffmpeg can still render. That wheel ships ffmpeg
    # only, so ffprobe still falls through to the bare name and names itself on failure.
    bundled = media_binaries.bundled_ffmpeg() if name == "ffmpeg" else None
    if bundled:
        return bundled

    return name


FF = _resolve_media_bin("ffmpeg", "FFMPEG_BIN")
FP = _resolve_media_bin("ffprobe", "FFPROBE_BIN")

# Functions defined in the preserved implementation resolve FF/FP from that module's
# globals, so patch them there as well. Sibling modules importing qp.FF/qp.FP also see
# the resolved paths from this facade.
_legacy.FF = FF
_legacy.FP = FP


def run_quiz_pipeline(*args, **kwargs):
    """Run the preserved quiz pipeline and fail terminally on missing media binaries/inputs.

    app.py already classifies ValueError as a hard durable failure. Converting a
    FileNotFoundError here prevents a deterministic missing-binary failure from being
    marked ``retry`` and leaving the SSE client on keepalives indefinitely.
    """
    try:
        return _legacy.run_quiz_pipeline(*args, **kwargs)
    except FileNotFoundError as exc:
        raise ValueError(f"Required media binary or input was not found: {exc}") from exc
