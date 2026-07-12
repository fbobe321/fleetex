"""Editor page-load API tests: bootstrap, entities, and the docstore doc bridge."""

from __future__ import annotations

import pytest
from bson import ObjectId

from fleetex_service_kit.contract import call_asgi
from fleetex_web.app import build_app
from fleetex_web.editor import find_doc_pathname, list_entities
from fleetex_web.projects import ProjectManager
from fleetex_web.sessions import generate_session_id, serialize_user
from fleetex_web.users import UserManager


class FakeDocstore:
    def __init__(self, docs: dict) -> None:
        self.docs = docs  # doc_id(str) -> {lines, version, ranges}

    async def get_doc(self, project_id, doc_id):
        return self.docs.get(str(doc_id))


@pytest.fixture
def docstore():
    return FakeDocstore({})


@pytest.fixture
def app(config, db, redis, docstore):
    return build_app(config, db=db, redis=redis, docstore=docstore)


async def _user(db, email="a@b.com"):
    return await UserManager(db, bcrypt_rounds=4).create_user(email, "pw", first_name="F", last_name="L")


async def _session(app, config, user):
    sid = generate_session_id()
    await app.state.store.save(sid, {"passport": {"user": serialize_user(user)}})
    return {"cookie": f"{config.cookie_name}={app.state.store.sign_cookie(sid)}"}


# --- tree helpers -------------------------------------------------------- #
def _project_with_tree():
    main_id, nested_id, file_id = ObjectId(), ObjectId(), ObjectId()
    project = {
        "_id": ObjectId(),
        "rootFolder": [{
            "_id": ObjectId(), "name": "rootFolder",
            "docs": [{"_id": main_id, "name": "main.tex"}],
            "fileRefs": [{"_id": file_id, "name": "logo.png"}],
            "folders": [{
                "_id": ObjectId(), "name": "chapters",
                "docs": [{"_id": nested_id, "name": "intro.tex"}], "fileRefs": [], "folders": [],
            }],
        }],
    }
    return project, main_id, nested_id


def test_find_doc_pathname():
    project, main_id, nested_id = _project_with_tree()
    assert find_doc_pathname(project, str(main_id)) == "/main.tex"
    assert find_doc_pathname(project, str(nested_id)) == "/chapters/intro.tex"
    assert find_doc_pathname(project, str(ObjectId())) is None


def test_list_entities_sorted():
    project, _m, _n = _project_with_tree()
    entities = list_entities(project)
    assert entities == [
        {"path": "/chapters/intro.tex", "type": "doc"},
        {"path": "/logo.png", "type": "file"},
        {"path": "/main.tex", "type": "doc"},
    ]


# --- bootstrap ----------------------------------------------------------- #
async def test_bootstrap(app, db, config):
    owner = await _user(db)
    await db["users"].update_one({"_id": owner["_id"]}, {"$set": {"ace": {"theme": "monokai", "fontSize": 14}}})
    project = await app.state.projects.create_basic(str(owner["_id"]), "Paper")
    r = await call_asgi(app, "GET", f"/project/{project['_id']}", headers=await _session(app, config, owner))
    assert r.status == 200
    b = r.json
    assert b["projectId"] == str(project["_id"]) and b["projectName"] == "Paper"
    assert b["user"]["email"] == "a@b.com" and b["anonymous"] is False
    assert b["userSettings"]["editorTheme"] == "monokai" and b["userSettings"]["fontSize"] == 14
    assert b["rootDocId"] == str(project["rootDoc_id"])
    assert b["wsUrl"] == config.ws_url and b["compiler"] == "pdflatex"


async def test_bootstrap_requires_login_and_access(app, db, config):
    assert (await call_asgi(app, "GET", f"/project/{ObjectId()}")).status == 401
    owner = await _user(db, "o@x.com")
    stranger = await _user(db, "s@x.com")
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    r = await call_asgi(app, "GET", f"/project/{project['_id']}", headers=await _session(app, config, stranger))
    assert r.status == 403


# --- entities ------------------------------------------------------------ #
async def test_entities_endpoint(app, db, config):
    owner = await _user(db)
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    r = await call_asgi(app, "GET", f"/project/{project['_id']}/entities", headers=await _session(app, config, owner))
    assert r.status == 200
    assert r.json["project_id"] == str(project["_id"])
    assert r.json["entities"] == [{"path": "/main.tex", "type": "doc"}]


# --- doc content bridge -------------------------------------------------- #
async def test_get_document_bridges_docstore(app, db, config, docstore):
    owner = await _user(db)
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    doc_id = str(project["rootDoc_id"])
    docstore.docs[doc_id] = {"lines": ["hello", "world"], "version": 7, "ranges": {"comments": []}}
    r = await call_asgi(app, "GET", f"/project/{project['_id']}/doc/{doc_id}", headers=await _session(app, config, owner))
    assert r.status == 200
    assert r.json["lines"] == ["hello", "world"]
    assert r.json["version"] == 7
    assert r.json["pathname"] == "/main.tex"
    assert r.json["otMigrationStage"] == 0 and r.json["resolvedCommentIds"] == []


async def test_get_document_plain(app, db, config, docstore):
    owner = await _user(db)
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    doc_id = str(project["rootDoc_id"])
    docstore.docs[doc_id] = {"lines": ["a", "b"], "version": 1, "ranges": {}}
    r = await call_asgi(app, "GET", f"/project/{project['_id']}/doc/{doc_id}?plain=true", headers=await _session(app, config, owner))
    assert r.status == 200 and r.text == "a\nb"


async def test_get_document_not_in_tree_404(app, db, config):
    owner = await _user(db)
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    r = await call_asgi(app, "GET", f"/project/{project['_id']}/doc/{ObjectId()}", headers=await _session(app, config, owner))
    assert r.status == 404


async def test_get_document_missing_in_docstore_404(app, db, config):
    owner = await _user(db)
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    # doc is in the tree (rootDoc) but docstore has no content for it
    r = await call_asgi(app, "GET", f"/project/{project['_id']}/doc/{project['rootDoc_id']}", headers=await _session(app, config, owner))
    assert r.status == 404
