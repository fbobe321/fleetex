"""Session-cookie auth for the socket handshake.

The client used to hand real-time its own ``user_id`` in the socket.io auth
payload — so any connection could claim to be any account. That hole is closed
here: we read the ``overleaf.sid`` cookie off the WebSocket handshake, verify
the Node-compatible signature with the shared secret, load ``sess:<sid>`` from
the shared Redis, and take the user id from ``session.passport.user._id``.

The signing/validation scheme is byte-identical to web's SessionStore
(``s:<sid>.<base64(HMAC-SHA256(secret, sid))>`` + ``validationToken`` guard) so
a cookie minted by web verifies here without a round-trip to web.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from urllib.parse import unquote

SESSION_KEY_PREFIX = "sess:"


def _sign(sid: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), sid.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii").rstrip("=")


def _validation_token(sid: str) -> str:
    return "v1:" + sid[-4:]


def unsign(raw: str | None, secrets: list[str]) -> str | None:
    """Return the session id from a signed cookie value, or None if invalid."""
    if not raw:
        return None
    value = unquote(raw)
    if not value.startswith("s:"):
        return None
    body = value[2:]
    idx = body.rfind(".")
    if idx < 0:
        return None
    sid, sig = body[:idx], body[idx + 1:]
    for secret in secrets:
        if hmac.compare_digest(_sign(sid, secret), sig):
            return sid
    return None


def cookie_value(cookie_header: str | None, name: str) -> str | None:
    """Pull one cookie's raw value out of a ``Cookie:`` header string."""
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        key, _, val = part.strip().partition("=")
        if key == name:
            return val
    return None


class SessionAuthenticator:
    """Resolves the authenticated user id from a handshake cookie header."""

    def __init__(self, redis, cookie_name: str, secrets: list[str]) -> None:
        self.redis = redis  # decode_responses=True, shared with web
        self.cookie_name = cookie_name
        self.secrets = [s for s in secrets if s]

    async def user_id_from_cookie_header(self, cookie_header: str | None) -> str | None:
        raw = cookie_value(cookie_header, self.cookie_name)
        sid = unsign(raw, self.secrets)
        if not sid:
            return None
        data = await self.redis.get(SESSION_KEY_PREFIX + sid)
        if not data:
            return None
        try:
            session = json.loads(data)
        except (ValueError, TypeError):
            return None
        # the CustomSessionStore guard: a session missing/!matching this token is
        # treated as absent (mirrors web's SessionStore.load).
        if session.get("validationToken") != _validation_token(sid):
            return None
        user = session.get("user") or (session.get("passport") or {}).get("user")
        if not user:
            return None
        return user.get("_id")
