"""CSRF defense for cookie-authenticated state-changing requests.

Two layers, both required to matter:

1. Session cookies are ``SameSite=Lax`` (see WebConfig), so the browser withholds
   them from cross-site POST/PUT/DELETE in the first place.
2. This Origin guard: browsers *always* attach an ``Origin`` header to
   cross-origin (and same-origin fetch) unsafe requests. A forged request from
   an attacker page therefore carries the attacker's Origin, which will not match
   our host — so we reject it. Requests with no Origin at all (curl, tests,
   server-to-server Basic-auth calls like real-time's ``/project/:id/join``) are
   left alone, since CSRF is strictly a browser-driven attack.
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def origin_allowed(origin: str | None, host: str | None, allowed: list[str]) -> bool:
    """True if an unsafe request's Origin is acceptable.

    No Origin -> allowed (non-browser client). Otherwise the Origin's host:port
    must equal the request's own Host, or appear in the configured allowlist.
    """
    if not origin:
        return True
    netloc = urlparse(origin).netloc
    if host and netloc == host:
        return True
    return origin in allowed or netloc in allowed


def register_csrf_guard(app: FastAPI, *, config) -> None:
    allowed = list(getattr(config, "allowed_origins", []) or [])

    @app.middleware("http")
    async def csrf_origin_guard(request: Request, call_next):
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and not origin_allowed(origin, request.headers.get("host"), allowed):
                return JSONResponse(
                    {"message": {"type": "error", "text": "CSRF validation failed: cross-origin request rejected"}},
                    status_code=403,
                )
        return await call_next(request)
