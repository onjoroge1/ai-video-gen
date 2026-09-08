"""Regression coverage for private finished videos on a full serverless disk."""
import errno
import tempfile
from pathlib import Path

import anyio
import httpx
import pytest
from fastapi import FastAPI

import blob_compat
import finished_api
import private_access


AsyncClient = httpx.AsyncClient
VIDEO_PATH = "/api/finished/cb76c3ab/artifact/video"
PRIVATE_URL = "https://teststore.private.blob.vercel-storage.com/finished/video.mp4"
BODY = bytes(range(256)) * 1024


class TrackedBody(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body
        self.read_bytes = 0
        self.closed = False

    async def __aiter__(self):
        for offset in range(0, len(self.body), 16 * 1024):
            chunk = self.body[offset:offset + 16 * 1024]
            self.read_bytes += len(chunk)
            yield chunk

    async def aclose(self):
        self.closed = True


def setup_proxy(monkeypatch, *, status=200, body=BODY, headers=None, error=None,
                access="private", url=PRIVATE_URL):
    monkeypatch.setenv("APP_PASSWORD", "studio-test-password")
    monkeypatch.setenv("APP_SESSION_SECRET", "studio-test-session-key")
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_teststore_test-token")
    monkeypatch.setenv("BLOB_STORE_ID", "teststore")
    app = FastAPI()
    app.add_middleware(private_access.PrivateAccessMiddleware)
    finished_api.mount(app, "/unused", Path("static"))
    monkeypatch.setattr(finished_api, "_get", lambda *_: {
        "id": "cb76c3ab", "artifacts": {"video": {
            "url": url, "pathname": "finished/video.mp4", "access": access,
            "content_type": "video/mp4", "size_bytes": len(BODY),
        }},
    })
    stream = TrackedBody(body)
    requests = []
    clients = []

    async def handle(request):
        requests.append(request)
        if error:
            raise error
        return httpx.Response(status, headers={
            "Content-Type": "video/mp4", "Content-Length": str(len(body)),
            "Accept-Ranges": "bytes", "ETag": '"stored-etag"',
            "Cache-Control": "public, max-age=31536000",
            "Set-Cookie": "upstream-secret=must-not-leak",
            **(headers or {}),
        }, stream=stream)

    def client_factory(**kwargs):
        client = AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(blob_compat.httpx, "AsyncClient", client_factory)
    return app, stream, requests, clients


async def get(app, method="GET", path=VIDEO_PATH, headers=None, authenticated=True):
    cookies = ({private_access.COOKIE_NAME: private_access.create_session("admin")}
               if authenticated else {})
    async with AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test",
                           cookies=cookies) as client:
        return await client.request(method, path, headers=headers)


@pytest.mark.parametrize("download", [False, True])
@pytest.mark.parametrize("access", ["private", None])
def test_private_video_streams_when_temp_disk_is_full(monkeypatch, download, access):
    app, stream, requests, clients = setup_proxy(monkeypatch, access=access)

    def disk_full(*_args, **_kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(tempfile, "mkdtemp", disk_full)

    async def run():
        response = await get(app, path=VIDEO_PATH + ("?download=true" if download else ""))
        assert response.status_code == 200
        assert response.content == BODY
        assert response.headers["content-length"] == str(len(BODY))
        assert response.headers["cache-control"] == "private, no-store"
        assert "set-cookie" not in response.headers
        assert "location" not in response.headers
        assert "authorization" not in response.headers
        if download:
            assert response.headers["content-disposition"] == (
                "attachment; filename*=UTF-8''video.mp4")
        else:
            assert "content-disposition" not in response.headers
        assert requests[0].headers["Authorization"] == (
            "Bearer vercel_blob_rw_teststore_test-token")
        assert requests[0].headers["x-vercel-blob-store-id"] == "teststore"
        assert requests[0].headers["accept-encoding"] == "identity"
        assert "cookie" not in requests[0].headers
        assert stream.closed
        assert all(client.is_closed for client in clients)

    anyio.run(run)


@pytest.mark.parametrize("request_range,status,body,content_range", [
    ("bytes=0-1", 206, BODY[:2], f"bytes 0-1/{len(BODY)}"),
    ("bytes=123-", 206, BODY[123:], f"bytes 123-{len(BODY)-1}/{len(BODY)}"),
    ("bytes=-64", 206, BODY[-64:], f"bytes {len(BODY)-64}-{len(BODY)-1}/{len(BODY)}"),
    ("bytes=999999-", 416, b"", f"bytes */{len(BODY)}"),
])
def test_playback_ranges_preserve_upstream_semantics(
        monkeypatch, request_range, status, body, content_range):
    app, stream, requests, clients = setup_proxy(
        monkeypatch, status=status, body=body, headers={"Content-Range": content_range})

    async def run():
        response = await get(app, headers={"Range": request_range, "If-Range": '"stored-etag"'})
        assert response.status_code == status
        assert response.content == body
        assert response.headers["content-range"] == content_range
        assert response.headers["content-length"] == str(len(body))
        assert requests[0].headers["range"] == request_range
        assert requests[0].headers["if-range"] == '"stored-etag"'
        assert stream.closed and all(client.is_closed for client in clients)

    anyio.run(run)


@pytest.mark.parametrize("method,status,request_headers", [
    ("HEAD", 200, {}),
    ("GET", 304, {"If-None-Match": '"stored-etag"'}),
])
def test_metadata_requests_do_not_consume_the_video(monkeypatch, method, status, request_headers):
    app, stream, requests, clients = setup_proxy(monkeypatch, status=status)

    async def run():
        response = await get(app, method=method, headers=request_headers)
        assert response.status_code == status
        assert response.content == b""
        assert stream.read_bytes == 0
        assert requests[0].method == method
        for name, value in request_headers.items():
            assert requests[0].headers[name] == value
        assert stream.closed and all(client.is_closed for client in clients)

    anyio.run(run)


@pytest.mark.parametrize("status", [302, 401, 403, 404, 500])
def test_blob_failures_return_structured_error_before_sending_video(monkeypatch, status):
    app, stream, _, clients = setup_proxy(monkeypatch, status=status)

    async def run():
        response = await get(app)
        assert response.status_code == 503
        assert response.json()["detail"] == {
            "code": "FINISHED_ARTIFACT_UNAVAILABLE",
            "message": f"Private Blob returned HTTP {status}", "retryable": True,
        }
        assert "test-token" not in response.text
        assert PRIVATE_URL not in response.text
        assert stream.read_bytes == 0
        assert stream.closed and all(client.is_closed for client in clients)

    anyio.run(run)


def test_connection_failure_closes_client(monkeypatch):
    app, _, _, clients = setup_proxy(
        monkeypatch, error=httpx.ConnectTimeout("sensitive upstream diagnostic"))

    async def run():
        response = await get(app)
        assert response.status_code == 503
        assert "sensitive" not in response.text
        assert all(client.is_closed for client in clients)

    anyio.run(run)


def test_private_playback_requires_studio_auth_before_blob_access(monkeypatch):
    app, _, requests, clients = setup_proxy(monkeypatch)

    async def run():
        assert (await get(app, authenticated=False)).status_code == 401
        assert requests == [] and clients == []

    anyio.run(run)


def test_blob_credentials_cannot_be_sent_to_another_host(monkeypatch):
    app, _, requests, clients = setup_proxy(monkeypatch, url="https://example.com/video.mp4")

    async def run():
        assert (await get(app)).status_code == 503
        assert requests == [] and clients == []

    anyio.run(run)


def test_private_stream_supports_runtime_oidc_auth(monkeypatch):
    app, _, requests, _ = setup_proxy(monkeypatch)
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN")
    monkeypatch.delenv("VERCEL_BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "test-runtime-oidc")

    async def run():
        assert (await get(app)).status_code == 200
        assert requests[0].headers["Authorization"] == "Bearer test-runtime-oidc"
        assert requests[0].headers["x-vercel-blob-store-id"] == "teststore"

    anyio.run(run)


def test_public_artifacts_keep_direct_delivery(monkeypatch):
    url = "https://teststore.public.blob.vercel-storage.com/finished/video.mp4"
    app, _, requests, clients = setup_proxy(monkeypatch, url=url, access="public")

    async def run():
        response = await get(app)
        assert response.status_code == 307
        assert response.headers["location"] == url
        assert requests == [] and clients == []

    anyio.run(run)


def test_disconnected_player_closes_upstream_without_reading_rest(monkeypatch):
    app, stream, _, clients = setup_proxy(monkeypatch)

    async def run():
        messages = []
        disconnected = anyio.Event()

        async def receive():
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.body" and message.get("body"):
                assert len(message["body"]) <= 64 * 1024
                disconnected.set()
                await anyio.sleep_forever()

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1", "scheme": "https", "method": "GET", "path": VIDEO_PATH,
            "raw_path": VIDEO_PATH.encode(), "query_string": b"", "root_path": "",
            "headers": [(b"cookie", (
                f"{private_access.COOKIE_NAME}={private_access.create_session('admin')}"
            ).encode())], "server": ("test", 443), "client": ("test", 1234),
        }
        with anyio.fail_after(3):
            await app(scope, receive, send)
        assert messages[0]["status"] == 200
        assert 0 < stream.read_bytes < len(BODY)
        assert stream.closed and all(client.is_closed for client in clients)

    anyio.run(run)
