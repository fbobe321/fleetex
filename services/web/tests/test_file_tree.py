"""File-tree mutation tests: add/rename/move/delete/upload + events + bridges."""

from __future__ import annotations

import pytest
from bson import ObjectId

from fleetex_service_kit.contract import call_asgi
from fleetex_web.app import build_app
from fleetex_web.file_tree import find_element, find_folder, is_clean_filename
from fleetex_web.sessions import generate_session_id, serialize_user
from fleetex_web.users import UserManager


class FakeDocstore:
    def __init__(self):
        self.updated, self.deleted = [], []

    async def update_doc(self, pid, did, lines, version=0, ranges=None):
        self.updated.append((str(did), lines))

    async def delete_doc(self, pid, did, name, deleted_at):
        self.deleted.append((str(did), name))

    async def get_doc(self, pid, did):
        return None


class FakeEvents:
    def __init__(self):
        self.emits = []

    async def emit(self, pid, message, *payload):
        self.emits.append((message, payload))

    def of(self, message):
        return [p for m, p in self.emits if m == message]


@pytest.fixture
def docstore():
    return FakeDocstore()


@pytest.fixture
def events():
    return FakeEvents()


class FakeFilestore:
    def __init__(self):
        self.uploaded = []

    async def upload(self, project_id, file_id, content):
        self.uploaded.append((project_id, file_id, content))
        import hashlib
        return hashlib.sha256(content).hexdigest()


@pytest.fixture
def filestore():
    return FakeFilestore()


@pytest.fixture
def app(config, db, redis, docstore, events, filestore):
    return build_app(config, db=db, redis=redis, docstore=docstore, events=events, filestore=filestore)


async def _owner(db):
    return await UserManager(db, bcrypt_rounds=4).create_user("o@x.com", "pw", first_name="O", last_name="W")


async def _session(app, config, user):
    sid = generate_session_id()
    await app.state.store.save(sid, {"passport": {"user": serialize_user(user)}})
    return {"cookie": f"{config.cookie_name}={app.state.store.sign_cookie(sid)}"}


async def _project(app, owner):
    return await app.state.projects.create_basic(str(owner["_id"]), "P")


# --- name validation ----------------------------------------------------- #
def test_is_clean_filename():
    assert is_clean_filename("main.tex")
    for bad in ["", ".", "..", "a/b", "a\\b", "a*b", " lead", "trail ", "x" * 1025]:
        assert not is_clean_filename(bad)


# --- add ----------------------------------------------------------------- #
async def test_add_doc(app, db, config, docstore, events):
    owner = await _owner(db)
    project = await _project(app, owner)
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/doc", headers=await _session(app, config, owner), json={"name": "chapter.tex"})
    assert r.status == 200 and r.json["name"] == "chapter.tex"
    doc_id = r.json["_id"]
    # docstore got an empty new doc; event emitted; tree + version updated
    assert (doc_id, []) in docstore.updated
    assert events.of("reciveNewDoc")
    updated = await app.state.projects.find_by_id(str(project["_id"]))
    assert any(d["name"] == "chapter.tex" for d in updated["rootFolder"][0]["docs"])
    assert updated["version"] == project["version"] + 1


async def test_add_doc_duplicate_and_invalid(app, db, config):
    owner = await _owner(db)
    project = await _project(app, owner)
    headers = await _session(app, config, owner)
    dup = await call_asgi(app, "POST", f"/project/{project['_id']}/doc", headers=headers, json={"name": "main.tex"})
    assert dup.status == 400  # main.tex already exists
    bad = await call_asgi(app, "POST", f"/project/{project['_id']}/doc", headers=headers, json={"name": "a/b.tex"})
    assert bad.status == 400


async def test_add_folder(app, db, config, events):
    owner = await _owner(db)
    project = await _project(app, owner)
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/folder", headers=await _session(app, config, owner), json={"name": "chapters"})
    assert r.status == 200
    assert r.json["docs"] == [] and r.json["folders"] == []
    assert events.of("reciveNewFolder")


# --- rename -------------------------------------------------------------- #
async def test_rename_doc(app, db, config, events):
    owner = await _owner(db)
    project = await _project(app, owner)
    doc_id = str(project["rootDoc_id"])
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/doc/{doc_id}/rename", headers=await _session(app, config, owner), json={"name": "thesis.tex"})
    assert r.status == 204
    updated = await app.state.projects.find_by_id(str(project["_id"]))
    assert updated["rootFolder"][0]["docs"][0]["name"] == "thesis.tex"
    assert events.of("reciveEntityRename")


async def test_rename_blocked_name(app, db, config):
    owner = await _owner(db)
    project = await _project(app, owner)
    doc_id = str(project["rootDoc_id"])
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/doc/{doc_id}/rename", headers=await _session(app, config, owner), json={"name": "__proto__"})
    assert r.status == 400


# --- move ---------------------------------------------------------------- #
async def test_move_doc_into_folder(app, db, config, events):
    owner = await _owner(db)
    project = await _project(app, owner)
    headers = await _session(app, config, owner)
    folder = (await call_asgi(app, "POST", f"/project/{project['_id']}/folder", headers=headers, json={"name": "sub"})).json
    doc_id = str(project["rootDoc_id"])
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/doc/{doc_id}/move", headers=headers, json={"folder_id": folder["_id"]})
    assert r.status == 204
    updated = await app.state.projects.find_by_id(str(project["_id"]))
    assert updated["rootFolder"][0]["docs"] == []  # moved out of root
    sub = updated["rootFolder"][0]["folders"][0]
    assert any(str(d["_id"]) == doc_id for d in sub["docs"])
    assert events.of("reciveEntityMove")


async def test_move_folder_into_itself_400(app, db, config):
    owner = await _owner(db)
    project = await _project(app, owner)
    headers = await _session(app, config, owner)
    folder = (await call_asgi(app, "POST", f"/project/{project['_id']}/folder", headers=headers, json={"name": "sub"})).json
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/folder/{folder['_id']}/move", headers=headers, json={"folder_id": folder["_id"]})
    assert r.status == 400


# --- delete -------------------------------------------------------------- #
async def test_delete_doc_bridges_docstore(app, db, config, docstore, events):
    owner = await _owner(db)
    project = await _project(app, owner)
    doc_id = str(project["rootDoc_id"])
    r = await call_asgi(app, "DELETE", f"/project/{project['_id']}/doc/{doc_id}", headers=await _session(app, config, owner))
    assert r.status == 204
    assert any(did == doc_id for did, _name in docstore.deleted)
    updated = await app.state.projects.find_by_id(str(project["_id"]))
    assert updated["rootFolder"][0]["docs"] == []
    assert updated.get("rootDoc_id") is None  # root doc unset
    assert events.of("removeEntity")


async def test_delete_folder_recursively_deletes_docs(app, db, config, docstore):
    owner = await _owner(db)
    project = await _project(app, owner)
    headers = await _session(app, config, owner)
    folder = (await call_asgi(app, "POST", f"/project/{project['_id']}/folder", headers=headers, json={"name": "sub"})).json
    nested = (await call_asgi(app, "POST", f"/project/{project['_id']}/doc", headers=headers, json={"name": "n.tex", "parent_folder_id": folder["_id"]})).json
    docstore.deleted.clear()
    r = await call_asgi(app, "DELETE", f"/project/{project['_id']}/folder/{folder['_id']}", headers=headers)
    assert r.status == 204
    assert any(did == nested["_id"] for did, _n in docstore.deleted)  # subtree doc deleted from docstore


# --- upload -------------------------------------------------------------- #
async def test_upload_text_becomes_doc(app, db, config, docstore, events):
    owner = await _owner(db)
    project = await _project(app, owner)
    r = await call_asgi(
        app, "POST", f"/project/{project['_id']}/upload?folder_id={project['rootFolder'][0]['_id']}",
        headers=await _session(app, config, owner),
        files={"qqfile": ("notes.tex", b"line1\nline2", "text/plain")}, data={"name": "notes.tex"},
    )
    assert r.status == 200 and r.json["success"] is True and r.json["entity_type"] == "doc"
    assert any(lines == ["line1", "line2"] for _did, lines in docstore.updated)
    assert events.of("reciveNewDoc")


async def test_upload_binary_becomes_file(app, db, config, events, filestore):
    owner = await _owner(db)
    project = await _project(app, owner)
    r = await call_asgi(
        app, "POST", f"/project/{project['_id']}/upload",
        headers=await _session(app, config, owner),
        files={"qqfile": ("logo.png", b"\x89PNG\x00\x01\x02", "image/png")}, data={"name": "logo.png"},
    )
    assert r.status == 200 and r.json["entity_type"] == "file"
    assert len(r.json["hash"]) == 64  # sha256 hex
    assert events.of("reciveNewFile")
    # binary was actually sent to filestore for persistence
    assert len(filestore.uploaded) == 1
    assert filestore.uploaded[0][2] == b"\x89PNG\x00\x01\x02"


# --- auth ---------------------------------------------------------------- #
async def test_write_ops_require_write_access(app, db, config):
    owner = await _owner(db)
    reader = await UserManager(db, bcrypt_rounds=4).create_user("r@x.com", "pw")
    project = await _project(app, owner)
    await db["projects"].update_one({"_id": project["_id"]}, {"$set": {"readOnly_refs": [reader["_id"]]}})
    # read-only collaborator cannot add a doc
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/doc", headers=await _session(app, config, reader), json={"name": "x.tex"})
    assert r.status == 403
    # anonymous -> 401
    anon = await call_asgi(app, "POST", f"/project/{project['_id']}/doc", json={"name": "x.tex"})
    assert anon.status == 401


async def test_unknown_entity_type_404(app, db, config):
    owner = await _owner(db)
    project = await _project(app, owner)
    r = await call_asgi(app, "DELETE", f"/project/{project['_id']}/widget/{ObjectId()}", headers=await _session(app, config, owner))
    assert r.status == 404
