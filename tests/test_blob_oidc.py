import blob_compat
import requests


def _clear_blob_env(monkeypatch):
    for key in (
        "BLOB_READ_WRITE_TOKEN",
        "VERCEL_BLOB_READ_WRITE_TOKEN",
        "BLOB_STORE_ID",
        "BLOB_READ_WRITE_TOKEN_STORE_ID",
        "VERCEL_OIDC_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)


def test_oidc_store_id_is_valid_blob_auth(monkeypatch):
    _clear_blob_env(monkeypatch)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "oidc-runtime-token")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN_STORE_ID", "store_bb8fbHhPoA33u6A0")

    credentials = blob_compat.resolve_credentials()

    assert credentials.mode == "oidc"
    assert credentials.token == "oidc-runtime-token"
    assert credentials.store_id == "bb8fbHhPoA33u6A0"
    assert blob_compat.enabled() is True


def test_static_token_still_takes_precedence(monkeypatch):
    _clear_blob_env(monkeypatch)
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_staticStore_secret")
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "oidc-runtime-token")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN_STORE_ID", "store_oidcStore")

    credentials = blob_compat.resolve_credentials()

    assert credentials.mode == "read_write"
    assert credentials.token == "vercel_blob_rw_staticStore_secret"
    assert credentials.store_id == "oidcStore"


def test_oidc_upload_sends_store_id_separately(tmp_path, monkeypatch):
    _clear_blob_env(monkeypatch)
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "oidc-runtime-token")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN_STORE_ID", "store_testStore")
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    seen = {}

    class Response:
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "url": "https://testStore.public.blob.vercel-storage.com/video.mp4",
                "pathname": "finished/job/video.mp4",
                "contentType": "video/mp4",
            }

    def fake_put(url, **kwargs):
        seen.update({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(blob_compat.requests, "put", fake_put)
    result = blob_compat.upload_file(
        str(source), "finished/job/video.mp4", content_type="video/mp4")

    assert seen["headers"]["Authorization"] == "Bearer oidc-runtime-token"
    assert seen["headers"]["x-vercel-blob-store-id"] == "testStore"
    assert result["url"].startswith("https://testStore.public.blob.vercel-storage.com/")


def test_artifact_store_readiness_accepts_oidc(monkeypatch):
    import artifact_store

    _clear_blob_env(monkeypatch)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "oidc-runtime-token")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN_STORE_ID", "store_testStore")
    monkeypatch.setenv("DATABASE_URL", "postgres://configured")
    monkeypatch.setattr(artifact_store.db, "db_enabled", lambda: True)

    state = artifact_store.readiness()
    assert state["blob"] is True
    assert state["ready"] is True
    artifact_store.assert_ready()


def test_durable_blobstore_uses_oidc_credentials(monkeypatch):
    import durable_execution

    _clear_blob_env(monkeypatch)
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "oidc-runtime-token")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN_STORE_ID", "store_testStore")

    store = durable_execution.BlobStore()
    assert store.credentials.mode == "oidc"
    assert store.credentials.store_id == "testStore"


def test_upload_auto_retries_private_when_store_rejects_public(tmp_path, monkeypatch):
    _clear_blob_env(monkeypatch)
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_testStore_secret")
    source = tmp_path / "checkpoint.tar.gz"
    source.write_bytes(b"checkpoint")
    seen = []

    class Response:
        def __init__(self, access):
            self.access = access
            self.status_code = 400 if access == "public" else 200
            self.text = ('{"error":{"message":"Cannot use public access on a private store."}}'
                         if access == "public" else "")

        def raise_for_status(self):
            if self.status_code != 200:
                raise requests.HTTPError("400 Client Error")

        def json(self):
            return {
                "url": "https://testStore.private.blob.vercel-storage.com/checkpoint.tar.gz",
                "pathname": "jobs/job/checkpoint.tar.gz",
                "contentType": "application/gzip",
            }

    def fake_put(_url, **kwargs):
        access = kwargs["headers"]["x-vercel-blob-access"]
        seen.append(access)
        return Response(access)

    monkeypatch.setattr(blob_compat.requests, "put", fake_put)
    result = blob_compat.upload_file(
        str(source), "jobs/job/checkpoint.tar.gz", access="auto")

    assert seen == ["public", "private"]
    assert result["access"] == "private"


def test_private_download_sends_blob_credentials(tmp_path, monkeypatch):
    _clear_blob_env(monkeypatch)
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_testStore_secret")
    seen = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            assert chunk_size > 0
            yield b"private-bytes"

        def close(self):
            return None

    def fake_get(url, **kwargs):
        seen.update({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(blob_compat.requests, "get", fake_get)
    output = tmp_path / "download.bin"
    blob_compat.download_file(
        "https://testStore.private.blob.vercel-storage.com/object",
        str(output), access="private")

    assert seen["headers"]["Authorization"] == "Bearer vercel_blob_rw_testStore_secret"
    assert output.read_bytes() == b"private-bytes"
