import anyio
import httpx
from fastapi import FastAPI

import private_access


def test_signed_session_rejects_tampering_and_expiry(monkeypatch):
    monkeypatch.setenv("APP_USERNAME", "owner")
    monkeypatch.setenv("APP_PASSWORD", "correct horse battery staple")
    monkeypatch.setenv("APP_SESSION_SECRET", "a-separate-random-signing-secret")
    token = private_access.create_session("owner", now=1_000)
    assert private_access.verify_session(token, now=1_001)["sub"] == "owner"
    assert private_access.verify_session(token + "x", now=1_001) is None
    assert private_access.verify_session(token, now=1_000 + 12 * 3600 + 1) is None


def test_middleware_protects_gets_and_api_routes(monkeypatch):
    monkeypatch.setenv("APP_USERNAME", "admin")
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("APP_SESSION_SECRET", "session-secret")
    app = FastAPI()
    app.add_middleware(private_access.PrivateAccessMiddleware)

    @app.get("/")
    async def root():
        return {"ok": True}

    @app.get("/api/private")
    async def api_private():
        return {"ok": True}

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            root = await client.get("/", headers={"Accept": "text/html"}, follow_redirects=False)
            assert root.status_code == 303
            assert root.headers["location"].startswith("/login")
            assert (await client.get("/api/private")).status_code == 401
            client.cookies.set(private_access.COOKIE_NAME, private_access.create_session("admin"))
            assert (await client.get("/api/private")).status_code == 200

    anyio.run(run)


def test_vercel_fails_closed_without_password(monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("APP_SHARED_SECRET", raising=False)
    monkeypatch.setenv("VERCEL", "1")
    assert private_access.auth_required() is True
    assert private_access.auth_configured() is False


def test_worker_routes_require_their_bearer_secret(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "studio-secret")
    monkeypatch.setenv("APP_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("RENDER_WORKER_SECRET", "worker-secret")
    monkeypatch.setenv("CRON_SECRET", "cron-secret")
    app = FastAPI()
    app.add_middleware(private_access.PrivateAccessMiddleware)

    @app.get("/api/internal/render-worker")
    async def worker():
        return {"ok": True}

    @app.get("/api/cron/render-recovery")
    async def cron():
        return {"ok": True}

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/api/internal/render-worker")).status_code == 401
            assert (await client.get(
                "/api/internal/render-worker",
                headers={"Authorization": "Bearer worker-secret"},
            )).status_code == 200
            assert (await client.get(
                "/api/cron/render-recovery",
                headers={"Authorization": "Bearer cron-secret"},
            )).status_code == 200
            assert (await client.get(
                "/api/cron/render-recovery",
                headers={"Authorization": "Bearer wrong"},
            )).status_code == 401

    anyio.run(run)


def test_middleware_registers_vercel_oidc_request_header(monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("APP_SHARED_SECRET", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    app = FastAPI()
    app.add_middleware(private_access.PrivateAccessMiddleware)

    @app.get("/oidc-probe")
    async def oidc_probe():
        from vercel.headers import get_headers
        from vercel.oidc.token import get_vercel_oidc_token_from_context

        headers = get_headers() or {}
        return {
            "header_seen": bool(headers.get("x-vercel-oidc-token")),
            "token": get_vercel_oidc_token_from_context(),
        }

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/oidc-probe",
                headers={"x-vercel-oidc-token": "oidc-test-token"},
            )
            assert response.status_code == 200
            assert response.json() == {"header_seen": True, "token": "oidc-test-token"}

    anyio.run(run)
