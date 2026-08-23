"""Single-user, cookie-based access control for the FastAPI studio.

The studio can spend provider credits, so production fails closed: on Vercel every route except
the login flow and health check requires a valid signed session cookie.  Local development stays
frictionless when no password is configured.

This middleware also registers each ASGI request's headers with Vercel's Python SDK. Vercel delivers
OIDC credentials in the ``x-vercel-oidc-token`` request header in production; registering the request
context is required before helpers such as ``vercel.oidc.get_vercel_oidc_token()`` can see it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse


COOKIE_NAME = "reelforge_session"
PUBLIC_PATHS = frozenset(("/login", "/api/auth/login", "/api/auth/session", "/healthz"))


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _password() -> str:
    # APP_SHARED_SECRET remains a compatibility fallback for existing deployments.
    return (os.environ.get("APP_PASSWORD") or os.environ.get("APP_SHARED_SECRET") or "").strip()


def _username() -> str:
    return (os.environ.get("APP_USERNAME") or "admin").strip()


def _session_key() -> bytes:
    configured = os.environ.get("APP_SESSION_SECRET", "").strip()
    material = configured or _password()
    return hashlib.sha256(("reelforge-session-v1:" + material).encode()).digest()


def auth_required() -> bool:
    return bool(_password()) or bool(os.environ.get("VERCEL"))


def auth_configured() -> bool:
    return bool(_password())


def create_session(username: str | None = None, now: int | None = None) -> str:
    if not auth_configured():
        raise RuntimeError("APP_PASSWORD is not configured")
    issued = int(time.time() if now is None else now)
    ttl = max(300, int(os.environ.get("APP_SESSION_TTL_SEC", str(12 * 3600))))
    payload = {"sub": username or _username(), "iat": issued, "exp": issued + ttl, "v": 1}
    encoded = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = _b64encode(hmac.new(_session_key(), encoded.encode(), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def verify_session(token: str, now: int | None = None) -> dict | None:
    if not token or not auth_configured():
        return None
    try:
        encoded, supplied = token.split(".", 1)
        expected = _b64encode(hmac.new(_session_key(), encoded.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied, expected):
            return None
        payload = json.loads(_b64decode(encoded))
        current = int(time.time() if now is None else now)
        if payload.get("v") != 1 or payload.get("sub") != _username():
            return None
        if int(payload.get("iat", 0)) > current + 60 or int(payload.get("exp", 0)) <= current:
            return None
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def _cookie_from_scope(scope) -> str:
    headers = dict(scope.get("headers") or [])
    raw = headers.get(b"cookie", b"").decode("latin1")
    for pair in raw.split(";"):
        name, _, value = pair.strip().partition("=")
        if name == COOKIE_NAME:
            return value
    return ""


def _api_request(scope) -> bool:
    path = scope.get("path", "")
    if path.startswith("/api/"):
        return True
    accept = dict(scope.get("headers") or []).get(b"accept", b"").decode("latin1")
    return "text/html" not in accept and path != "/"


def _vercel_headers_context(scope):
    """Build a request-local Vercel header context without making local dev depend on the SDK."""
    try:
        from vercel.headers import HeadersContext, headers_from_asgi_scope
        return HeadersContext(headers_from_asgi_scope(scope))
    except Exception:
        return None


class PrivateAccessMiddleware:
    """Pure ASGI middleware so long-lived SSE responses are never buffered."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # Vercel's Python OIDC helper reads x-vercel-oidc-token from a ContextVar populated by
        # vercel.headers. Register it for the ENTIRE request before authentication/storage code runs,
        # and restore the previous context afterward so concurrent requests cannot leak credentials.
        context = _vercel_headers_context(scope)
        if context is None:
            await self._handle_http(scope, receive, send)
            return
        with context.use():
            await self._handle_http(scope, receive, send)

    async def _handle_http(self, scope, receive, send):
        if not auth_required():
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in PUBLIC_PATHS or verify_session(_cookie_from_scope(scope)):
            await self.app(scope, receive, send)
            return

        # Vercel Cron and the detached render worker cannot carry a browser cookie. They remain
        # private: Vercel sends CRON_SECRET as a bearer token, while manual recovery uses the
        # independently scoped RENDER_WORKER_SECRET.
        headers = dict(scope.get("headers") or [])
        if path.startswith(("/api/cron/", "/api/internal/")):
            supplied_bearer = headers.get(b"authorization", b"").decode()
            allowed = [value for value in (
                os.environ.get("CRON_SECRET", "").strip(),
                os.environ.get("RENDER_WORKER_SECRET", "").strip(),
            ) if value]
            if any(hmac.compare_digest(supplied_bearer, f"Bearer {secret}") for secret in allowed):
                await self.app(scope, receive, send)
                return

        # Existing headless clients may continue to use X-App-Secret, but the browser UI never
        # stores credentials in localStorage anymore.
        supplied = headers.get(b"x-app-secret", b"").decode()
        shared = os.environ.get("APP_SHARED_SECRET", "").strip()
        if shared and hmac.compare_digest(supplied, shared):
            await self.app(scope, receive, send)
            return

        if _api_request(scope):
            await JSONResponse({"detail": "authentication required"}, status_code=401)(
                scope, receive, send
            )
            return
        target = path or "/"
        await RedirectResponse(f"/login?next={quote(target, safe='/')}", status_code=303)(
            scope, receive, send
        )


def mount_auth_routes(app: FastAPI, static_dir: Path) -> None:
    @app.get("/healthz")
    async def healthz():
        # Safe operational diagnostics only: booleans, never credentials or identifiers. This lets us
        # prove that Vercel's request OIDC header reaches Python and that the configured Blob store can
        # resolve authentication before any paid render begins.
        storage = {
            "oidc_request": False,
            "blob_store": False,
            "blob_auth": False,
            "database": False,
        }
        try:
            from vercel.headers import get_headers
            headers = get_headers() or {}
            storage["oidc_request"] = bool(
                headers.get("x-vercel-oidc-token") or headers.get("X-Vercel-Oidc-Token")
            )
        except Exception:
            pass
        try:
            import blob_compat
            storage["blob_store"] = bool(blob_compat.configured_store_id())
            storage["blob_auth"] = bool(blob_compat.enabled())
        except Exception:
            pass
        try:
            import db
            storage["database"] = bool(db.db_enabled())
        except Exception:
            pass
        return {"ok": True, "storage": storage}

    @app.get("/login")
    async def login_page():
        response = FileResponse(str(static_dir / "login.html"), media_type="text/html")
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    @app.get("/api/auth/session")
    async def auth_session(request: Request):
        session = verify_session(request.cookies.get(COOKIE_NAME, ""))
        return {
            "authenticated": bool(session),
            "configured": auth_configured(),
            "required": auth_required(),
            "username": session.get("sub") if session else None,
        }

    @app.post("/api/auth/login")
    async def auth_login(request: Request):
        if not auth_configured():
            return JSONResponse(
                {"detail": "Private access is not configured. Set APP_PASSWORD in Vercel."},
                status_code=503,
            )
        try:
            body = await request.json()
        except Exception:
            body = {}
        username = str(body.get("username") or "")
        password = str(body.get("password") or "")
        valid_user = hmac.compare_digest(username, _username())
        valid_password = hmac.compare_digest(password, _password())
        if not (valid_user and valid_password):
            # Keep the response deliberately generic.
            return JSONResponse({"detail": "Invalid username or password"}, status_code=401)

        response = JSONResponse({"ok": True})
        response.set_cookie(
            COOKIE_NAME,
            create_session(username),
            max_age=max(300, int(os.environ.get("APP_SESSION_TTL_SEC", str(12 * 3600)))),
            httponly=True,
            secure=bool(os.environ.get("VERCEL")) or os.environ.get("COOKIE_SECURE") == "1",
            samesite="strict",
            path="/",
        )
        return response

    @app.post("/api/auth/logout")
    async def auth_logout():
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE_NAME, path="/", samesite="strict")
        return response
