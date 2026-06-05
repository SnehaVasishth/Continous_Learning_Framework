"""Full-site HTTP Basic Auth — gates the entire app behind a single
username/password. Browser handles the credential prompt natively, so the SPA
HTML, JS, CSS, and API all sit behind the same gate without a React login
screen.

Enable by setting BOTH env vars before starting uvicorn:
  APP_BASIC_AUTH_USER=demo
  APP_BASIC_AUTH_PASS=<password>

Health endpoints (/api/health, /api/ready) are exempt so external monitors
keep working. The Cloudflare quick-tunnel callback path is also exempt.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from fastapi.responses import PlainTextResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


_EXEMPT = {"/api/health", "/api/ready"}
# Prefix-exempt paths. Lambda Document Intelligence fetches /files/uploads/<name>
# without basic-auth credentials (it has no way to pass them), so the entire
# uploads root is exempt from the demo gate. Other /files/ subdirectories
# (e.g. /files/outputs/) stay gated.
_EXEMPT_PREFIXES = ("/files/uploads/",)
_REALM = "Keysight SalesOps Demo"
_COOKIE_NAME = "salesops_auth"


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """HTTP Basic Auth on every path except a small exempt set."""

    def __init__(self, app, user: str | None = None, password: str | None = None):
        super().__init__(app)
        self.user = (user if user is not None else os.environ.get("APP_BASIC_AUTH_USER", "")).strip()
        self.password = (password if password is not None else os.environ.get("APP_BASIC_AUTH_PASS", ""))
        self.enabled = bool(self.user and self.password)

    def _cookie_value(self) -> str:
        return hashlib.sha256(f"{self.user}:{self.password}:salesops-cookie-v1".encode()).hexdigest()

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        host = (request.headers.get("host") or "").lower()
        if "trycloudflare.com" not in host:
            return await call_next(request)

        path = request.url.path
        if path in _EXEMPT:
            return await call_next(request)
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return await call_next(request)

        expected_cookie = self._cookie_value()
        cookie_val = request.cookies.get(_COOKIE_NAME, "")
        if cookie_val and hmac.compare_digest(cookie_val, expected_cookie):
            return await call_next(request)

        header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
        if header.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(header.split(" ", 1)[1].strip()).decode("utf-8", "ignore")
                u, _, p = decoded.partition(":")
            except Exception:
                u, p = "", ""
            if hmac.compare_digest(u, self.user) and hmac.compare_digest(p, self.password):
                response = await call_next(request)
                response.set_cookie(
                    key=_COOKIE_NAME,
                    value=expected_cookie,
                    max_age=60 * 60 * 12,
                    path="/",
                    secure=True,
                    httponly=True,
                    samesite="lax",
                )
                return response

        return Response(
            status_code=401,
            content="Authentication required.",
            media_type="text/plain",
            headers={"WWW-Authenticate": f'Basic realm="{_REALM}", charset="UTF-8"'},
        )
