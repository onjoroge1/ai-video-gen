"""Resolve render music from external object storage with a verified local cache.

The repository intentionally does not need to bundle the MP3 files. Each track
has an immutable source URL and checksum, while Neon stores the asset metadata
and can override the URL (for example, with a Vercel Blob URL) without a deploy.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import threading
from typing import Callable

import requests

import db


MUSIC_CREDIT = "Music: Kevin MacLeod (incompetech.com), licensed under Creative Commons BY 4.0."

_ARCHIVE_BASE = "https://archive.org/download/KevinMacLeod/"
MUSIC_ASSETS = {
    "energetic": {
        "filename": "energetic.mp3",
        "object_url": _ARCHIVE_BASE + "Funk/Funkorama.mp3",
        "sha256": "6be229815d85a0b99382b944d31098b882702c04ac7ad899e44ab7f8ba89b5ad",
        "size_bytes": 8_199_078,
    },
    "dramatic": {
        "filename": "dramatic.mp3",
        "object_url": _ARCHIVE_BASE + "Soundtrack/Achilles.mp3",
        "sha256": "03917669cba8086f921712e0db8c59d32e02d63e3be443d8d4458a9d2786ded3",
        "size_bytes": 2_540_613,
    },
    "corporate": {
        "filename": "corporate.mp3",
        "object_url": _ARCHIVE_BASE + "Contemporary/Bright%20Wish.mp3",
        "sha256": "1b0fa563ffad8f1d83bc4b308fe118096a4e25a5c818f67a167e933005216dd3",
        "size_bytes": 1_720_624,
    },
    "nostalgic": {
        "filename": "nostalgic.mp3",
        "object_url": _ARCHIVE_BASE + "Contemporary/Autumn%20Day.mp3",
        "sha256": "74b766d726f2292cb229b2961ea914c320285af382aaeb001579298384d7ae01",
        "size_bytes": 7_395_072,
    },
    "upbeat": {
        "filename": "upbeat.mp3",
        "object_url": _ARCHIVE_BASE + "Funk/Funky%20One.mp3",
        "sha256": "fae66b2676d115bf699accd0cb42d6680c27a375ad1837f6d3faecf5c5ee5f89",
        "size_bytes": 5_891_574,
    },
    "tense": {
        "filename": "tense.mp3",
        "object_url": _ARCHIVE_BASE + "Soundtrack/Ambush.mp3",
        "sha256": "90ffe95fd197860d6552d80c99a7215faf09c1afa4e744f619a3f8a8240739cd",
        "size_bytes": 1_787_273,
    },
}

_BUNDLED_DIR = Path(__file__).resolve().parent / "static" / "music"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_audio(path: Path, expected_sha256: str) -> bool:
    if not path.is_file() or path.stat().st_size < 50_000:
        return False
    with path.open("rb") as stream:
        header = stream.read(3)
    if not (header == b"ID3" or header.startswith((b"\xff\xfb", b"\xff\xf3"))):
        return False
    return not expected_sha256 or _sha256(path) == expected_sha256


def _config(mood: str) -> dict:
    slug = mood if mood in MUSIC_ASSETS else "corporate"
    config = {
        "slug": slug,
        "mime_type": "audio/mpeg",
        "storage_provider": "internet_archive",
        "license": "CC-BY-4.0",
        **MUSIC_ASSETS[slug],
    }

    # DB metadata allows an object-store migration or URL rotation without a code deploy.
    stored = db.music_asset_get(slug)
    if stored:
        config.update({key: value for key, value in stored.items() if value not in (None, "")})

    # Environment values are an emergency/preview override and take highest precedence.
    prefix = f"MUSIC_{slug.upper()}_"
    config["object_url"] = os.environ.get(prefix + "URL", config["object_url"])
    config["sha256"] = os.environ.get(prefix + "SHA256", config["sha256"])
    return config


def _cache_dir() -> Path:
    configured = os.environ.get("MUSIC_CACHE_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "reelforge" / "music"


def get_music_path(mood: str = "corporate",
                   progress_cb: Callable[[str], None] | None = None) -> str | None:
    """Return a checksum-verified local MP3, downloading it only on a cache miss.

    Existing local development checkouts may still use the bundled file. Vercel
    downloads into its writable ``/tmp`` filesystem and reuses it for warm calls.
    A failure returns ``None`` so the pipelines keep their existing silent fallback.
    """
    config = _config(mood)
    filename = str(config["filename"])
    expected_sha256 = str(config.get("sha256") or "")

    bundled = _BUNDLED_DIR / filename
    if _valid_audio(bundled, expected_sha256):
        db.music_asset_upsert(config)
        return str(bundled)

    cache_dir = _cache_dir()
    cache_path = cache_dir / filename
    if _valid_audio(cache_path, expected_sha256):
        return str(cache_path)

    cache_dir.mkdir(parents=True, exist_ok=True)
    partial = cache_path.with_suffix(cache_path.suffix + f".{os.getpid()}.{threading.get_ident()}.part")
    try:
        if progress_cb:
            progress_cb(f"Downloading {config['slug']} music to render cache...")
        with requests.get(
            str(config["object_url"]),
            timeout=(10, 90),
            stream=True,
            headers={"User-Agent": "ReelForge/1.0"},
        ) as response:
            response.raise_for_status()
            with partial.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        stream.write(chunk)
        if not _valid_audio(partial, expected_sha256):
            raise ValueError("downloaded music failed size, audio-header, or checksum validation")
        os.replace(partial, cache_path)
        db.music_asset_upsert(config)
        return str(cache_path)
    except Exception as exc:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
        print(f"[music] {config['slug']} unavailable: {exc}")
        return None


def sync_music_metadata() -> tuple[int, int]:
    """Upsert all known asset rows. Returns ``(written, total)``."""
    written = sum(bool(db.music_asset_upsert(_config(slug))) for slug in MUSIC_ASSETS)
    return written, len(MUSIC_ASSETS)
