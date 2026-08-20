"""Create/update Neon metadata rows for externally stored render music."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from music_assets import sync_music_metadata  # noqa: E402


if __name__ == "__main__":
    written, total = sync_music_metadata()
    if written != total:
        raise SystemExit(f"Music metadata sync incomplete: {written}/{total} rows written")
    print(f"Music metadata sync complete: {written}/{total} rows written")
