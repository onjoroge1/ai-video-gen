"""Portable Pillow font loading for macOS, Linux, Windows, and minimal containers."""
from pathlib import Path
from PIL import ImageFont


_SEARCH_ROOTS = (
    Path("/System/Library/Fonts/Supplemental"),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/liberation2"),
    Path("C:/Windows/Fonts"),
)


def load_font(preferred: str | None, size: int, index: int = 0, bold: bool = False):
    candidates = []
    if preferred:
        candidates.append(Path(preferred))
    names = (("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf") if bold else
             ("DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Arial.ttf"))
    candidates.extend(root / name for root in _SEARCH_ROOTS for name in names)
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size, index=index)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default(size=size)
