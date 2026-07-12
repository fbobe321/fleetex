"""Frontend pages + registration + doc-save + tree endpoints."""

from __future__ import annotations

import pytest
from bson import ObjectId

from fleetex_service_kit.contract import call_asgi
from fleetex_web.app import build_app
from fleetex_web.sessions import generate_session_id, serialize_user
from fleetex_web.users import UserManager

HTML = {"accept": "text/html,application/xhtml+xml"}


class FakeDocstore:
    def __init__(self):
        self.saved = []

    async def update_doc(self, pid, did, lines, version=0, ranges=None):
        self.saved.append((str(did), lines))

    async def delete_doc(self, *a, **k):
        pass

    async def get_doc(self, pid, did):
        return None


@pytest.fixture
def docstore():
    return FakeDocstore()


@pytest.fixture
def app(config, db, redis, docstore):
    return build_app(config, db=db, redis=redis, docstore=docstore)


async def _user(db, email="a@b.com"):
    return await UserManager(db, bcrypt_rounds=4).create_user(email, "pw", first_name="A", last_name="B")


async def _session(app, config, user):
    sid = generate_session_id()
    await app.state.store.save(sid, {"passport": {"user": serialize_user(user)}})
    return {"cookie": f"{config.cookie_name}={app.state.store.sign_cookie(sid)}"}


# --- pages --------------------------------------------------------------- #
async def test_pages_render(app):
    for path in ("/login", "/register", "/projects"):
        r = await call_asgi(app, "GET", path)
        assert r.status == 200 and "Fleetex" in r.text


async def test_root_redirects(app):
    r = await call_asgi(app, "GET", "/", follow_redirects=False)
    assert r.status in (302, 307) and r.headers["location"] == "/projects"


# --- registration -------------------------------------------------------- #
async def test_register_creates_user_and_session(app, db, config):
    r = await call_asgi(app, "POST", "/register", json={"email": "new@x.com", "password": "secret1"})
    assert r.status == 200 and r.json == {"redir": "/projects"}
    assert "set-cookie" in r.headers
    # user exists and can log in
    assert await db["users"].find_one({"email": "new@x.com"}) is not None
    login = await call_asgi(app, "POST", "/login", json={"email": "new@x.com", "password": "secret1"})
    assert login.status == 200


async def test_register_validations(app, db):
    await _user(db, "taken@x.com")
    dup = await call_asgi(app, "POST", "/register", json={"email": "taken@x.com", "password": "secret1"})
    assert dup.status == 400
    short = await call_asgi(app, "POST", "/register", json={"email": "x@y.com", "password": "no"})
    assert short.status == 400
    bad = await call_asgi(app, "POST", "/register", json={"email": "notanemail", "password": "secret1"})
    assert bad.status == 400


async def test_register_disabled(config, db, redis):
    config.open_registration = False
    app = build_app(config, db=db, redis=redis)
    assert (await call_asgi(app, "POST", "/register", json={"email": "a@b.com", "password": "secret1"})).status == 403
    assert (await call_asgi(app, "GET", "/register", follow_redirects=False)).status in (302, 307)


# --- editor page negotiation --------------------------------------------- #
async def test_editor_html_vs_json(app, db, config):
    owner = await _user(db)
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    # browser (Accept: text/html) gets the editor HTML page (no auth needed to serve shell)
    html = await call_asgi(app, "GET", f"/project/{project['_id']}", headers=HTML)
    assert html.status == 200 and "Fleetex — Editor" in html.text
    # API (?format=json) gets JSON bootstrap, auth-gated
    unauth = await call_asgi(app, "GET", f"/project/{project['_id']}?format=json")
    assert unauth.status == 401
    ok = await call_asgi(app, "GET", f"/project/{project['_id']}?format=json", headers=await _session(app, config, owner))
    assert ok.status == 200 and ok.json["projectName"] == "P"


# --- tree (with ids) ----------------------------------------------------- #
async def test_tree_includes_ids(app, db, config):
    owner = await _user(db)
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    r = await call_asgi(app, "GET", f"/project/{project['_id']}/tree", headers=await _session(app, config, owner))
    assert r.status == 200
    entities = r.json["entities"]
    assert entities[0]["path"] == "/main.tex" and entities[0]["type"] == "doc"
    assert entities[0]["id"] == str(project["rootDoc_id"])


# --- save ---------------------------------------------------------------- #
async def test_save_document(app, db, config, docstore):
    owner = await _user(db)
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    doc_id = str(project["rootDoc_id"])
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/doc/{doc_id}",
                        headers=await _session(app, config, owner), json={"content": "hello\nworld"})
    assert r.status == 200 and r.json == {"saved": True}
    assert (doc_id, ["hello", "world"]) in docstore.saved


async def test_save_requires_write_and_existing_doc(app, db, config):
    owner = await _user(db)
    reader = await UserManager(db, bcrypt_rounds=4).create_user("r@x.com", "pw")
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    await db["projects"].update_one({"_id": project["_id"]}, {"$set": {"readOnly_refs": [reader["_id"]]}})
    doc_id = str(project["rootDoc_id"])
    ro = await call_asgi(app, "POST", f"/project/{project['_id']}/doc/{doc_id}", headers=await _session(app, config, reader), json={"content": "x"})
    assert ro.status == 403
    missing = await call_asgi(app, "POST", f"/project/{project['_id']}/doc/{ObjectId()}", headers=await _session(app, config, owner), json={"content": "x"})
    assert missing.status == 404
