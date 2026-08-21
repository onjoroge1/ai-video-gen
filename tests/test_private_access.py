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
