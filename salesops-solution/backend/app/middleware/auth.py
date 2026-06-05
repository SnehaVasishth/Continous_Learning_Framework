from __future__ import annotations

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from ..config import APP_AUTH_ENABLED, APP_AUTH_TOKEN

_EXEMPT = {"/api/health", "/api/ready"}


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, enabled: bool | None = None, token: str | None = None):
        super().__init__(app)
        self.enabled = APP_AUTH_ENABLED if enabled is None else enabled
        self.token = (APP_AUTH_TOKEN if token is None else token) or ""

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        path = request.url.path
        if not path.startswith("/api/") or path in _EXEMPT:
            return await call_next(request)

        header = request.headers.get("authorization") or request.headers.get("Authorization")
        if not header or not header.lower().startswith("bearer "):
            return JSONResponse(status_code=401, content={"error": "unauthorized"})
        provided = header.split(" ", 1)[1].strip()
        if not self.token or provided != self.token:
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        return await call_next(request)
