"""web -> project-history proxy routes."""

from __future__ import annotations

import httpx
import pytest

from fleetex_service_kit.contract import call_asgi
from fleetex_web.app import build_app
from fleetex_web.sessions import generate_session_id, serialize_user
from fleetex_web.users import UserManager


class FakeHistory:
    """Stands in for the project-history service; records forwarded calls."""

    def __init__(self):
        self.calls = []

    async def get(self, path, params=None):
        self.calls.append(("GET", path, dict(params or {})))
        if path.endswith("/versions"):
            return httpx.Response(200, json={"versions": [
                {"version": 2, "source": "save", "ts": 2, "doc_id": "d"},
                {"version": 1, "source": "save", "ts": 1, "doc_id": "d"},
            ]})
        if path.endswith("/diff"):
            return httpx.Response(200, json={"from": 1, "to": 2, "diff": [{"u": "a "}, {"d": "b"}, {"i": "c"}], "stats": {"added": 1, "removed": 1}})
        if "/version/" in path:
            return httpx.Response(200, json={"content": "old content", "version": 2})
        return httpx.Response(404, json={})

    async def post(self, path, json=None):
        self.calls.append(("POST", path, json))
        if "/diff-against/" in path:
            return httpx.Response(200, json={"from": 1, "to": "current", "diff": [{"u": "a "}, {"i": "z"}], "stats": {"added": 1, "removed": 0}})
        return httpx.Response(201, json={"created": True, "version": {"version": 3, "source": (json or {}).get("source")}})


@pytest.fixture
def history():
    return FakeHistory()


@pytest.fixture
def happ(config, db, redis, history):
    return build_app(config, db=db, redis=redis, history=history)


async def _user(db, email):
    return await UserManager(db, bcrypt_rounds=4).create_user(email, "pw", first_name="F", last_name="L")


async def _session(app, config, user):
    sid = generate_session_id()
    await app.state.store.save(sid, {"passport": {"user": serialize_user(user)}})
    return {"cookie": f"{config.cookie_name}={app.state.store.sign_cookie(sid)}"}


async def test_doc_history_requires_access_then_forwards(happ, db, config, history):
    owner = await _user(db, "owner@x.com")
    stranger = await _user(db, "s@x.com")
    project = await happ.state.projects.create_basic(str(owner["_id"]), "P")
    pid, did = str(project["_id"]), str(project["rootDoc_id"])
    # stranger has no access
    r = await call_asgi(happ, "GET", f"/project/{pid}/doc/{did}/history", headers=await _session(happ, config, stranger))
    assert r.status in (401, 403)
    # owner gets the forwarded timeline
    r = await call_asgi(happ, "GET", f"/project/{pid}/doc/{did}/history", headers=await _session(happ, config, owner))
    assert r.status == 200 and [v["version"] for v in r.json["versions"]] == [2, 1]
    assert ("GET", f"/project/{pid}/doc/{did}/versions", {}) in history.calls


async def test_diff_forwards_to_query(happ, db, config, history):
    owner = await _user(db, "owner@x.com")
    project = await happ.state.projects.create_basic(str(owner["_id"]), "P")
    pid, did = str(project["_id"]), str(project["rootDoc_id"])
    r = await call_asgi(happ, "GET", f"/project/{pid}/doc/{did}/history/diff?to=2", headers=await _session(happ, config, owner))
    assert r.status == 200 and r.json["diff"][1] == {"d": "b"}
    assert ("GET", f"/project/{pid}/doc/{did}/diff", {"to": "2"}) in history.calls


async def test_diff_against_forwards_buffer(happ, db, config, history):
    owner = await _user(db, "owner@x.com")
    project = await happ.state.projects.create_basic(str(owner["_id"]), "P")
    pid, did = str(project["_id"]), str(project["rootDoc_id"])
    r = await call_asgi(happ, "POST", f"/project/{pid}/doc/{did}/history/diff-against/1",
                        headers=await _session(happ, config, owner), json={"content": "a z"})
    assert r.status == 200 and r.json["to"] == "current"
    method, path, payload = history.calls[-1]
    assert method == "POST" and path == f"/project/{pid}/doc/{did}/diff-against/1"
    assert payload == {"content": "a z"}


async def test_version_content_proxied(happ, db, config, history):
    owner = await _user(db, "owner@x.com")
    project = await happ.state.projects.create_basic(str(owner["_id"]), "P")
    pid = str(project["_id"])
    r = await call_asgi(happ, "GET", f"/project/{pid}/history/version/2", headers=await _session(happ, config, owner))
    assert r.status == 200 and r.json["content"] == "old content"
    assert ("GET", f"/project/{pid}/version/2", {}) in history.calls


async def test_record_version_needs_write_and_injects_pathname_user(happ, db, config, history):
    owner = await _user(db, "owner@x.com")
    project = await happ.state.projects.create_basic(str(owner["_id"]), "P")
    pid, did = str(project["_id"]), str(project["rootDoc_id"])
    r = await call_asgi(happ, "POST", f"/project/{pid}/doc/{did}/history/version",
                        headers=await _session(happ, config, owner), json={"content": "hello", "source": "save"})
    assert r.status == 201 and r.json["created"] is True
    method, path, payload = history.calls[-1]
    assert method == "POST" and path == f"/project/{pid}/doc/{did}/version"
    assert payload["content"] == "hello" and payload["source"] == "save"
    assert payload["user_id"] == str(owner["_id"])
    assert payload["pathname"]  # resolved from the project tree (root doc)


async def test_record_requires_content(happ, db, config):
    owner = await _user(db, "owner@x.com")
    project = await happ.state.projects.create_basic(str(owner["_id"]), "P")
    pid, did = str(project["_id"]), str(project["rootDoc_id"])
    r = await call_asgi(happ, "POST", f"/project/{pid}/doc/{did}/history/version",
                        headers=await _session(happ, config, owner), json={"source": "save"})
    assert r.status == 400


async def test_readonly_member_cannot_record(happ, db, config):
    owner = await _user(db, "owner@x.com")
    reader = await _user(db, "r@x.com")
    project = await happ.state.projects.create_basic(str(owner["_id"]), "P")
    pid, did = str(project["_id"]), str(project["rootDoc_id"])
    await happ.state.db["projects"].update_one({"_id": project["_id"]}, {"$addToSet": {"readOnly_refs": reader["_id"]}})
    # can read history
    r = await call_asgi(happ, "GET", f"/project/{pid}/doc/{did}/history", headers=await _session(happ, config, reader))
    assert r.status == 200
    # but cannot record a version
    w = await call_asgi(happ, "POST", f"/project/{pid}/doc/{did}/history/version",
                        headers=await _session(happ, config, reader), json={"content": "x"})
    assert w.status in (401, 403)
