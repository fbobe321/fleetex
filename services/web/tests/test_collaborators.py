"""Sharing / collaborator management."""

from __future__ import annotations

import pytest
from bson import ObjectId

from fleetex_service_kit.contract import call_asgi
from fleetex_web.sessions import generate_session_id, serialize_user
from fleetex_web.users import UserManager


async def _user(db, email):
    return await UserManager(db, bcrypt_rounds=4).create_user(email, "pw", first_name="F", last_name="L")


async def _session(app, config, user):
    sid = generate_session_id()
    await app.state.store.save(sid, {"passport": {"user": serialize_user(user)}})
    return {"cookie": f"{config.cookie_name}={app.state.store.sign_cookie(sid)}"}


async def test_owner_adds_collaborator_who_then_has_access(app, db, config):
    owner = await _user(db, "owner@x.com")
    friend = await _user(db, "friend@x.com")
    project = await app.state.projects.create_basic(str(owner["_id"]), "Shared")
    # friend has no access yet
    before = await call_asgi(app, "GET", f"/project/{project['_id']}?format=json", headers=await _session(app, config, friend))
    assert before.status == 403
    # owner adds friend as editor
    add = await call_asgi(app, "POST", f"/project/{project['_id']}/members",
                          headers=await _session(app, config, owner), json={"email": "friend@x.com", "privilegeLevel": "readAndWrite"})
    assert add.status == 200 and add.json["member"]["privilegeLevel"] == "readAndWrite"
    # now friend can open it and edit (rename exercises write access; no docstore)
    after = await call_asgi(app, "GET", f"/project/{project['_id']}?format=json", headers=await _session(app, config, friend))
    assert after.status == 200
    ren = await call_asgi(app, "POST", f"/project/{project['_id']}/doc/{project['rootDoc_id']}/rename",
                          headers=await _session(app, config, friend), json={"name": "friend.tex"})
    assert ren.status == 204


async def test_list_members(app, db, config):
    owner = await _user(db, "owner@x.com")
    friend = await _user(db, "friend@x.com")
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    await call_asgi(app, "POST", f"/project/{project['_id']}/members", headers=await _session(app, config, owner), json={"email": "friend@x.com", "privilegeLevel": "readOnly"})
    r = await call_asgi(app, "GET", f"/project/{project['_id']}/members", headers=await _session(app, config, owner))
    by_email = {m["email"]: m["privilegeLevel"] for m in r.json["members"]}
    assert by_email == {"owner@x.com": "owner", "friend@x.com": "readOnly"}


async def test_add_requires_owner(app, db, config):
    owner = await _user(db, "owner@x.com")
    other = await _user(db, "other@x.com")
    target = await _user(db, "t@x.com")
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    # a non-owner (not even a member) cannot add
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/members", headers=await _session(app, config, other), json={"email": "t@x.com"})
    assert r.status in (401, 403)


async def test_add_unknown_email_and_owner_email(app, db, config):
    owner = await _user(db, "owner@x.com")
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    headers = await _session(app, config, owner)
    unknown = await call_asgi(app, "POST", f"/project/{project['_id']}/members", headers=headers, json={"email": "nobody@x.com"})
    assert unknown.status == 404
    self_add = await call_asgi(app, "POST", f"/project/{project['_id']}/members", headers=headers, json={"email": "owner@x.com"})
    assert self_add.status == 400


async def test_change_level_and_remove(app, db, config):
    owner = await _user(db, "owner@x.com")
    friend = await _user(db, "friend@x.com")
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    headers = await _session(app, config, owner)
    await call_asgi(app, "POST", f"/project/{project['_id']}/members", headers=headers, json={"email": "friend@x.com", "privilegeLevel": "readAndWrite"})
    # change to readOnly -> should move (not duplicate)
    await call_asgi(app, "POST", f"/project/{project['_id']}/members", headers=headers, json={"email": "friend@x.com", "privilegeLevel": "readOnly"})
    doc = await app.state.projects.find_by_id(str(project["_id"]))
    assert friend["_id"] not in (doc.get("collaberator_refs") or [])
    assert friend["_id"] in (doc.get("readOnly_refs") or [])
    # remove
    rem = await call_asgi(app, "DELETE", f"/project/{project['_id']}/members/{friend['_id']}", headers=headers)
    assert rem.status == 204
    doc2 = await app.state.projects.find_by_id(str(project["_id"]))
    assert friend["_id"] not in (doc2.get("readOnly_refs") or [])
    # friend loses access
    lost = await call_asgi(app, "GET", f"/project/{project['_id']}?format=json", headers=await _session(app, config, friend))
    assert lost.status == 403
