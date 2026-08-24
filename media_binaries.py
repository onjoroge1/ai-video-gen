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

Step 4 means a plain ``pip install -r requirements.txt`` yields a usable ffmpeg with no system
package. ``imageio-ffmpeg`` does **not** bundle ffprobe, so ffprobe still requires the host to
provide it — which every normal ffmpeg install does. :func:`preflight` exists so that gap is
reported at startup for $0 instead of surfacing deep inside a render that has already spent
money on image, motion, and narration calls.
"""
from __future__ import annotations

import os
import shutil
import subprocess

__all__ = [
    "MediaBinaryError", "ffmpeg", "ffprobe", "resolve", "preflight",
    "require", "bundled_ffmpeg", "reset_cache",
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
    return {
        "ready": not missing,
        "binaries": binaries,
        "missing": missing,
        "remedy": (
            "" if not missing else
            "Install ffmpeg/ffprobe on the render host (`apt-get install -y ffmpeg`) or set "
            "FFMPEG_BIN/FFPROBE_BIN. `pip install imageio-ffmpeg` supplies ffmpeg only."
        ),
    }
