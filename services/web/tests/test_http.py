"""HTTP tests: login/logout/password + the internal project-join API."""

from __future__ import annotations

import base64

import pytest
from bson import ObjectId

from fleetex_service_kit.contract import call_asgi
from fleetex_web.users import UserManager
from tests.conftest import cookie_header, parse_set_cookie

BASIC = {"authorization": "Basic " + base64.b64encode(b"overleaf:password").decode()}


async def _make_user(db, email="a@b.com", password="hunter2", **extra):
    user = await UserManager(db, bcrypt_rounds=4).create_user(email, password, first_name="A", last_name="B")
    if extra:
        await db["users"].update_one({"_id": user["_id"]}, {"$set": extra})
        user.update(extra)
    return user


async def test_login_success_writes_signed_cookie_and_session(app, db, config):
    await _make_user(db)
    r = await call_asgi(app, "POST", "/login", json={"email": "a@b.com", "password": "hunter2"})
    assert r.status == 200 and r.json == {"redir": "/project"}
    signed = parse_set_cookie(config, r.headers["set-cookie"])
    sid = app.state.store.unsign_cookie(signed)
    assert sid is not None
    session = await app.state.store.load(sid)
    assert session["passport"]["user"]["email"] == "a@b.com"


async def test_login_wrong_password_401(app, db):
    await _make_user(db)
    r = await call_asgi(app, "POST", "/login", json={"email": "a@b.com", "password": "nope"})
    assert r.status == 401 and r.json["message"]["key"] == "invalid-password-retry-or-reset"


async def test_login_invalid_email_400(app):
    r = await call_asgi(app, "POST", "/login", json={"password": "x"})
    assert r.status == 400


async def test_logout_destroys_session(app, db, config):
    user = await _make_user(db)
    login = await call_asgi(app, "POST", "/login", json={"email": "a@b.com", "password": "hunter2"})
    sid = app.state.store.unsign_cookie(parse_set_cookie(config, login.headers["set-cookie"]))
    out = await call_asgi(app, "POST", "/logout", headers=cookie_header(config, app.state.store, sid))
    assert out.status == 200 and out.json == {"redir": "/login"}
    assert await app.state.store.load(sid) is None


async def test_change_password_requires_session(app):
    r = await call_asgi(app, "POST", "/user/password/update", json={"currentPassword": "x", "newPassword1": "y", "newPassword2": "y"})
    assert r.status == 401


async def test_change_password_flow(app, db, config):
    user = await _make_user(db)
    login = await call_asgi(app, "POST", "/login", json={"email": "a@b.com", "password": "hunter2"})
    sid = app.state.store.unsign_cookie(parse_set_cookie(config, login.headers["set-cookie"]))
    headers = cookie_header(config, app.state.store, sid)
    # wrong current password -> 400
    bad = await call_asgi(app, "POST", "/user/password/update", headers=headers,
                          json={"currentPassword": "wrong", "newPassword1": "newpass", "newPassword2": "newpass"})
    assert bad.status == 400
    ok = await call_asgi(app, "POST", "/user/password/update", headers=headers,
                         json={"currentPassword": "hunter2", "newPassword1": "newpass", "newPassword2": "newpass"})
    assert ok.status == 200 and ok.json["message"]["type"] == "success"
    # the new password now works for login
    relogin = await call_asgi(app, "POST", "/login", json={"email": "a@b.com", "password": "newpass"})
    assert relogin.status == 200


# --- project join (internal API) ----------------------------------------- #
async def _make_project(db, owner_id, **extra):
    doc = {"_id": ObjectId(), "owner_ref": owner_id, "name": "Proj", "publicAccesLevel": "private", **extra}
    await db["projects"].insert_one(doc)
    return doc


async def test_join_requires_basic_auth(app, db):
    r = await call_asgi(app, "POST", f"/project/{ObjectId()}/join", json={"userId": "x"})
    assert r.status == 401


async def test_join_as_owner(app, db):
    owner = await _make_user(db)
    project = await _make_project(db, owner["_id"])
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/join", headers=BASIC, json={"userId": str(owner["_id"])})
    assert r.status == 200
    assert r.json["privilegeLevel"] == "owner"
    assert r.json["isRestrictedUser"] is False
    assert r.json["project"]["owner"]["email"] == "a@b.com"


async def test_join_as_collaborator(app, db):
    owner = await _make_user(db, email="o@w.com")
    collab = await _make_user(db, email="c@w.com")
    project = await _make_project(db, owner["_id"], collaberator_refs=[collab["_id"]])
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/join", headers=BASIC, json={"userId": str(collab["_id"])})
    assert r.json["privilegeLevel"] == "readAndWrite"


async def test_join_no_access_403(app, db):
    owner = await _make_user(db, email="o@w.com")
    stranger = await _make_user(db, email="s@w.com")
    project = await _make_project(db, owner["_id"])
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/join", headers=BASIC, json={"userId": str(stranger["_id"])})
    assert r.status == 403


async def test_join_anonymous_token_read_only_is_restricted(app, db):
    owner = await _make_user(db, email="o@w.com")
    project = await _make_project(db, owner["_id"], publicAccesLevel="tokenBased", tokens={"readOnly": "tok-ro"})
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/join", headers=BASIC,
                        json={"userId": "anonymous-user", "anonymousAccessToken": "tok-ro"})
    assert r.status == 200
    assert r.json["privilegeLevel"] == "readOnly"
    assert r.json["isRestrictedUser"] is True  # anon read-only -> restricted, project redacted
    assert r.json["project"]["owner"] == {"_id": str(owner["_id"])}
