"""CSRF Origin guard."""

from __future__ import annotations

import pytest

from fleetex_service_kit.contract import call_asgi
from fleetex_web.security import origin_allowed


def test_origin_allowed_rules():
    # no origin -> allowed (non-browser)
    assert origin_allowed(None, "site.com", [])
    # same host -> allowed
    assert origin_allowed("https://site.com", "site.com", [])
    assert origin_allowed("http://localhost:3000", "localhost:3000", [])
    # foreign origin -> rejected
    assert not origin_allowed("https://evil.com", "site.com", [])
    # allowlisted foreign origin -> allowed
    assert origin_allowed("https://trusted.com", "site.com", ["https://trusted.com"])


async def test_cross_origin_post_is_rejected(app, config):
    r = await call_asgi(app, "POST", "/login", headers={"origin": "https://evil.example", "host": "site.example"}, json={"email": "a@b.com", "password": "x"})
    assert r.status == 403
    assert "CSRF" in r.json["message"]["text"]


async def test_same_origin_post_passes_guard(app, config):
    # same-origin -> guard lets it through to the login handler (bad creds -> 401, not 403)
    r = await call_asgi(app, "POST", "/login", headers={"origin": "http://site.example", "host": "site.example"}, json={"email": "nobody@b.com", "password": "x"})
    assert r.status != 403


async def test_no_origin_post_passes_guard(app, config):
    # non-browser client (no Origin header) is unaffected by the guard
    r = await call_asgi(app, "POST", "/login", json={"email": "nobody@b.com", "password": "x"})
    assert r.status != 403


async def test_safe_method_never_blocked(app, config):
    r = await call_asgi(app, "GET", "/login", headers={"origin": "https://evil.example", "host": "site.example"})
    assert r.status != 403
