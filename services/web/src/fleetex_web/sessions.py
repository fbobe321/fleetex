"""Session store + cookie signing — the critical Node-interop piece.

Cookie value: ``s:<sessionId>.<sig>`` where ``sig = base64(HMAC-SHA256(secret, sid))``
with ``=`` padding stripped, then URL-encoded in the header. Signing uses the first
secret; verification tries all. The Redis session lives at ``sess:<sid>`` as JSON,
and MUST carry ``validationToken = "v1:" + sid[-4:]`` or the Node CustomSessionStore
rejects it. The user id lives at ``session.passport.user._id``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from urllib.parse import quote, unquote

SESSION_KEY_PREFIX = "sess:"


def generate_session_id() -> str:
    # uid-safe: 24 random bytes, base64url, no padding.
    return base64.urlsafe_b64encode(os.urandom(24)).decode("ascii").rstrip("=")


def _sign(sid: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), sid.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii").rstrip("=")


def validation_token(sid: str) -> str:
    return "v1:" + sid[-4:]


def serialize_user(user: dict) -> dict:
    """passport serializeUser shape (needs at least _id + email)."""
    return {
        "_id": str(user["_id"]),
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "email": user.get("email", ""),
        "referal_id": user.get("referal_id"),
        "isAdmin": user.get("isAdmin", False),
    }


def get_logged_in_user_id(session: dict | None) -> str | None:
    if not session:
        return None
    user = session.get("user") or (session.get("passport") or {}).get("user")
    return user.get("_id") if user else None


class SessionStore:
    def __init__(self, redis, secrets: list[str], ttl_seconds: int) -> None:
        self.redis = redis  # decode_responses=True
        self.secrets = secrets
        self.ttl = ttl_seconds

    # -- cookie signing --------------------------------------------------- #
    def sign_cookie(self, sid: str) -> str:
        return quote(f"s:{sid}.{_sign(sid, self.secrets[0])}", safe="")

    def unsign_cookie(self, raw: str | None) -> str | None:
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
        for secret in self.secrets:
            if hmac.compare_digest(_sign(sid, secret), sig):
                return sid
        return None

    # -- redis store ------------------------------------------------------ #
    async def load(self, sid: str) -> dict | None:
        raw = await self.redis.get(SESSION_KEY_PREFIX + sid)
        if not raw:
            return None
        session = json.loads(raw)
        if session.get("validationToken") != validation_token(sid):
            return None
        return session

    async def save(self, sid: str, session: dict) -> None:
        session["validationToken"] = validation_token(sid)
        session.setdefault("cookie", {"originalMaxAge": self.ttl * 1000, "httpOnly": True, "path": "/", "sameSite": "lax"})
        await self.redis.set(SESSION_KEY_PREFIX + sid, json.dumps(session), ex=self.ttl)

    async def destroy(self, sid: str) -> None:
        await self.redis.delete(SESSION_KEY_PREFIX + sid)

    async def load_from_cookie(self, raw_cookie: str | None) -> tuple[str | None, dict | None]:
        sid = self.unsign_cookie(raw_cookie)
        if sid is None:
            return None, None
        return sid, await self.load(sid)
