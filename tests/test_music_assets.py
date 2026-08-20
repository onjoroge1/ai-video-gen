import hashlib
from pathlib import Path

import music_assets


def _fake_mp3(payload: bytes = b"audio") -> bytes:
    return b"ID3" + payload * 20_000


def test_get_music_path_downloads_verifies_and_caches(monkeypatch, tmp_path):
    content = _fake_mp3()
    checksum = hashlib.sha256(content).hexdigest()
    config = {
        "slug": "upbeat", "filename": "upbeat.mp3", "object_url": "https://example.test/upbeat.mp3",
        "sha256": checksum, "size_bytes": len(content), "mime_type": "audio/mpeg",
        "storage_provider": "test", "license": "CC-BY-4.0",
    }
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            calls.append(chunk_size)
            yield content

    monkeypatch.setattr(music_assets, "_config", lambda _mood: config)
    monkeypatch.setattr(music_assets, "_BUNDLED_DIR", tmp_path / "not-bundled")
    monkeypatch.setattr(music_assets, "_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(music_assets.requests, "get", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(music_assets.db, "music_asset_upsert", lambda _asset: True)

    first = music_assets.get_music_path("upbeat")
    second = music_assets.get_music_path("upbeat")

    assert first == second == str(tmp_path / "cache" / "upbeat.mp3")
    assert Path(first).read_bytes() == content
    assert len(calls) == 1


def test_get_music_path_rejects_wrong_checksum(monkeypatch, tmp_path):
    content = _fake_mp3()
    config = {
        "slug": "upbeat", "filename": "upbeat.mp3", "object_url": "https://example.test/upbeat.mp3",
        "sha256": "0" * 64, "size_bytes": len(content), "mime_type": "audio/mpeg",
        "storage_provider": "test", "license": "CC-BY-4.0",
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield content

    monkeypatch.setattr(music_assets, "_config", lambda _mood: config)
    monkeypatch.setattr(music_assets, "_BUNDLED_DIR", tmp_path / "not-bundled")
    monkeypatch.setattr(music_assets, "_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(music_assets.requests, "get", lambda *_args, **_kwargs: Response())

    assert music_assets.get_music_path("upbeat") is None
    assert not (tmp_path / "cache" / "upbeat.mp3").exists()
