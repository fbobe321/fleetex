"""Session-cookie auth for the socket handshake."""

from __future__ import annotations

import json

import pytest

from fleetex_realtime.session_auth import SessionAuthenticator, _sign, _validation_token, cookie_value, unsign

SECRET = "test-secret"
COOKIE = "overleaf.sid"


def _signed_cookie(sid: str, secret: str = SECRET) -> str:
    # matches web's SessionStore.sign_cookie shape: s:<sid>.<sig> (url-encoded)
    from urllib.parse import quote

    return quote(f"s:{sid}.{_sign(sid, secret)}", safe="")


async def _store_session(redis, sid: str, user: dict | None):
    session = {"validationToken": _validation_token(sid)}
    if user is not None:
        session["passport"] = {"user": user}
    await redis.set("sess:" + sid, json.dumps(session))


def test_unsign_roundtrip_and_rejects_bad_sig():
    sid = "abc123def456"
    assert unsign(_signed_cookie(sid), [SECRET]) == sid
    assert unsign(_signed_cookie(sid, "other"), [SECRET]) is None
    assert unsign("not-signed", [SECRET]) is None
    assert unsign(None, [SECRET]) is None


def test_unsign_accepts_any_of_multiple_secrets():
    sid = "rotating"
    assert unsign(_signed_cookie(sid, "old"), ["new", "old"]) == sid


def test_cookie_value_extracts_named_cookie():
    header = "foo=1; overleaf.sid=xyz; bar=2"
    assert cookie_value(header, COOKIE) == "xyz"
    assert cookie_value(header, "missing") is None
    assert cookie_value(None, COOKIE) is None


async def test_resolves_logged_in_user(redis):
    auth = SessionAuthenticator(redis, COOKIE, [SECRET])
    sid = "session-1"
    await _store_session(redis, sid, {"_id": "user-42", "email": "a@b.com"})
    header = f"{COOKIE}={_signed_cookie(sid)}"
    assert await auth.user_id_from_cookie_header(header) == "user-42"


async def test_ignores_client_supplied_user_and_rejects_forgery(redis):
    auth = SessionAuthenticator(redis, COOKIE, [SECRET])
    # no cookie at all -> anonymous (None)
    assert await auth.user_id_from_cookie_header("") is None
    # a cookie signed with the wrong secret cannot mint a session
    assert await auth.user_id_from_cookie_header(f"{COOKIE}={_signed_cookie('s', 'evil')}") is None


async def test_rejects_session_with_bad_validation_token(redis):
    auth = SessionAuthenticator(redis, COOKIE, [SECRET])
    sid = "session-2"
    # store a session whose validationToken does not match sid -> treated as absent
    await redis.set("sess:" + sid, json.dumps({"validationToken": "v1:zzzz", "passport": {"user": {"_id": "u"}}}))
    assert await auth.user_id_from_cookie_header(f"{COOKIE}={_signed_cookie(sid)}") is None


async def test_missing_session_in_redis_is_anonymous(redis):
    auth = SessionAuthenticator(redis, COOKIE, [SECRET])
    sid = "never-stored"
    assert await auth.user_id_from_cookie_header(f"{COOKIE}={_signed_cookie(sid)}") is None
