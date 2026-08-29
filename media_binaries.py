"""Single source of truth for locating ffmpeg and ffprobe.

Every render in this repository shells out to ffmpeg. Before this module the long-form
explainer path used the bare strings ``"ffmpeg"``/``"ffprobe"`` in ~27 places, so it worked
only where those happened to be on ``PATH``. CI installs them explicitly; the Vercel Python
runtime does not ship them, so the same code that passes CI cannot render in production.

Resolution order for each binary:

1. an explicit ``FFMPEG_BIN`` / ``FFPROBE_BIN`` override;
2. the executable on ``PATH``;
3. known system install locations;
4. for ffmpeg only, the static build bundled in the ``imageio-ffmpeg`` wheel.

``imageio-ffmpeg`` does not bundle ffprobe. When the host lacks it, the shared probe helpers read
duration and dimensions from ffmpeg's input inspection output instead. A plain requirements install
therefore provides both rendering and the metadata probes ReelForge needs on Vercel.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

__all__ = [
    "MediaBinaryError", "ffmpeg", "ffprobe", "resolve", "preflight",
    "require", "bundled_ffmpeg", "reset_cache", "probe_media",
    "probe_duration", "probe_dimensions",
]


class MediaBinaryError(RuntimeError):
    """A required media binary could not be located."""


_SEARCH_DIRS = ("/usr/bin", "/usr/local/bin", "/opt/homebrew/bin", "/opt/bin")
_ENV_VARS = {"ffmpeg": "FFMPEG_BIN", "ffprobe": "FFPROBE_BIN"}
_cache: dict[str, str] = {}


def bundled_ffmpeg() -> str | None:
    """Return the static ffmpeg shipped in the imageio-ffmpeg wheel, if installed."""
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    try:
        path = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
    return path if path and os.path.isfile(path) and os.access(path, os.X_OK) else None


def resolve(name: str, *, use_cache: bool = True) -> str | None:
    """Locate one binary, or return None when it cannot be found anywhere.

    Callers that need a hard failure should use :func:`require` instead, so the error names
    the missing binary and how to supply it.
    """
    if name not in _ENV_VARS:
        raise ValueError(f"Unsupported media binary: {name!r}")
    if use_cache and name in _cache:
        return _cache[name]

    explicit = (os.environ.get(_ENV_VARS[name]) or "").strip()
    found: str | None = None
    if explicit:
        # An explicit override is honoured verbatim so an operator can point at any build;
        # it is deliberately not validated away, but it also is not cached as a false
        # positive if it does not exist.
        found = explicit
    else:
        found = shutil.which(name)
        if not found:
            for directory in _SEARCH_DIRS:
                candidate = os.path.join(directory, name)
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    found = candidate
                    break
        if not found and name == "ffmpeg":
            found = bundled_ffmpeg()

    if found and use_cache:
        _cache[name] = found
    return found


def require(name: str) -> str:
    """Locate one binary or raise an actionable error."""
    found = resolve(name)
    if found:
        return found
    hint = (
        "install it (`apt-get install -y ffmpeg`), set "
        f"{_ENV_VARS[name]}=/path/to/{name}"
    )
    if name == "ffmpeg":
        hint += ", or `pip install imageio-ffmpeg` for a bundled static build"
    raise MediaBinaryError(f"Required media binary {name!r} was not found: {hint}.")


def ffmpeg() -> str:
    return require("ffmpeg")


def ffprobe() -> str:
    return require("ffprobe")


def probe_media(path: str) -> dict:
    """Read duration and dimensions with ffprobe or the bundled ffmpeg fallback."""
    native = resolve("ffprobe")
    if native:
        result = subprocess.run(
            [native, "-v", "quiet", "-print_format", "json", "-show_format",
             "-show_streams", path],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30.0)
        if result.returncode == 0:
            payload = json.loads(result.stdout or "{}")
            streams = payload.get("streams") or []
            video = next((item for item in streams if item.get("codec_type") == "video"), {})
            duration = (payload.get("format") or {}).get("duration")
            if duration is None:
                duration = next((item.get("duration") for item in streams
                                 if item.get("duration") is not None), 0)
            return {
                "duration": float(duration or 0),
                "width": int(video.get("width") or 0),
                "height": int(video.get("height") or 0),
                "has_video": bool(video),
                "source": "ffprobe",
            }

    # imageio-ffmpeg supplies this binary on Vercel. Inspecting an input exits immediately after
    # printing its container metadata, so this does not decode the full video.
    result = subprocess.run(
        [ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=30.0)
    output = (result.stderr or "") + "\n" + (result.stdout or "")
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    video_line = next((line for line in output.splitlines() if "Video:" in line), "")
    dimensions = re.search(r"(?<![\d.])(\d{2,5})x(\d{2,5})(?![\d.])", video_line)
    if not duration_match:
        raise MediaBinaryError(f"Could not read media duration from {path!r} with ffmpeg")
    hours, minutes, seconds = duration_match.groups()
    return {
        "duration": int(hours) * 3600 + int(minutes) * 60 + float(seconds),
        "width": int(dimensions.group(1)) if dimensions else 0,
        "height": int(dimensions.group(2)) if dimensions else 0,
        "has_video": bool(dimensions),
        "source": "ffmpeg-fallback",
    }


def probe_duration(path: str) -> float:
    return float(probe_media(path)["duration"])


def probe_dimensions(path: str) -> tuple[int, int]:
    result = probe_media(path)
    return int(result["width"]), int(result["height"])


def reset_cache() -> None:
    """Forget resolved paths. Used by tests and after changing the environment."""
    _cache.clear()


def _version(path: str) -> str:
    try:
        result = subprocess.run([path, "-version"], capture_output=True, text=True,
                                stdin=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    first = (result.stdout or result.stderr or "").splitlines()
    return first[0].strip() if first else ""


def preflight() -> dict:
    """Report whether this host can render, before anything is purchased.

    A render costs real money well before it reaches its first encode, so a missing binary
    should be visible at startup rather than after the spend.
    """
    binaries = {}
    for name in ("ffmpeg", "ffprobe"):
        path = resolve(name, use_cache=False)
        usable = bool(path) and bool(_version(path)) if path else False
        binaries[name] = {
            "path": path or "",
            "found": bool(path),
            "executable": usable,
            "source": ("override" if (os.environ.get(_ENV_VARS[name]) or "").strip()
                       else "bundled" if path and path == bundled_ffmpeg()
                       else "system" if path else "missing"),
            "version": _version(path) if path else "",
        }
    missing = sorted(name for name, item in binaries.items() if not item["executable"])
    probe_fallback = bool(binaries["ffmpeg"]["executable"])
    return {
        "ready": binaries["ffmpeg"]["executable"] and (
            binaries["ffprobe"]["executable"] or probe_fallback),
        "binaries": binaries,
        "missing": missing,
        "probe_source": "ffprobe" if binaries["ffprobe"]["executable"] else (
            "ffmpeg-fallback" if probe_fallback else "missing"),
        "remedy": (
            "" if probe_fallback else
            "Install ffmpeg/ffprobe on the render host (`apt-get install -y ffmpeg`) or set "
            "FFMPEG_BIN/FFPROBE_BIN. `pip install imageio-ffmpeg` supplies ffmpeg only."
        ),
    }
