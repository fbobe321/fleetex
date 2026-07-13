"""Project CRUD + listing tests."""

from __future__ import annotations

import pytest
from bson import ObjectId

from fleetex_service_kit.contract import call_asgi
from fleetex_web.projects import ProjectManager, validate_project_name, InvalidNameError
from fleetex_web.sessions import generate_session_id, serialize_user
from fleetex_web.users import UserManager


async def _user(db, email):
    return await UserManager(db, bcrypt_rounds=4).create_user(email, "pw", first_name="F", last_name="L")


async def _session(app, config, user) -> dict:
    sid = generate_session_id()
    await app.state.store.save(sid, {"passport": {"user": serialize_user(user)}})
    return {"cookie": f"{config.cookie_name}={app.state.store.sign_cookie(sid)}"}


# --- name validation ----------------------------------------------------- #
def test_validate_project_name():
    assert validate_project_name("My Paper") == "My Paper"
    for bad in ["", "a/b", "a\\b", " lead", "trail ", "x" * 151]:
        with pytest.raises(InvalidNameError):
            validate_project_name(bad)


# --- create -------------------------------------------------------------- #
async def test_create_project(app, db, config):
    user = await _user(db, "a@b.com")
    headers = await _session(app, config, user)
    r = await call_asgi(app, "POST", "/project/new", headers=headers, json={"projectName": "  Thesis  "})
    assert r.status == 200
    pid = r.json["project_id"]
    assert r.json["owner_ref"] == str(user["_id"])
    # the doc exists with a rootFolder + main.tex + rootDoc_id
    project = await app.state.projects.find_by_id(pid)
    assert project["name"] == "Thesis"  # trimmed
    root = project["rootFolder"][0]
    assert root["docs"][0]["name"] == "main.tex"
    assert project["rootDoc_id"] == root["docs"][0]["_id"]
    assert project["archived"] == [] and project["trashed"] == []


class _RecordingDocstore:
    def __init__(self):
        self.seeded = []

    async def update_doc(self, project_id, doc_id, lines, version=0, ranges=None):
        self.seeded.append({"project_id": project_id, "doc_id": doc_id, "lines": lines, "version": version})


async def test_create_seeds_compilable_root_doc(db, config):
    # a fresh project must open with content and compile out of the box (an empty
    # main.tex fails with "no legal \\end found")
    from fakeredis import FakeAsyncRedis
    from fleetex_web.app import build_app

    docstore = _RecordingDocstore()
    app = build_app(config, db=db, redis=FakeAsyncRedis(decode_responses=True), docstore=docstore)
    user = await _user(db, "seed@b.com")
    headers = await _session(app, config, user)
    r = await call_asgi(app, "POST", "/project/new", headers=headers, json={"projectName": "Seeded"})
    assert r.status == 200
    pid = r.json["project_id"]
    project = await app.state.projects.find_by_id(pid)
    assert len(docstore.seeded) == 1
    seed = docstore.seeded[0]
    assert seed["project_id"] == pid
    assert seed["doc_id"] == str(project["rootDoc_id"])
    assert seed["lines"][0].startswith("\\documentclass")
    assert any("\\begin{document}" in ln for ln in seed["lines"])
    assert any("\\end{document}" in ln for ln in seed["lines"])


async def test_create_requires_login(app):
    r = await call_asgi(app, "POST", "/project/new", json={"projectName": "X"})
    assert r.status == 401


async def test_create_invalid_name_400(app, db, config):
    user = await _user(db, "a@b.com")
    headers = await _session(app, config, user)
    r = await call_asgi(app, "POST", "/project/new", headers=headers, json={"projectName": "bad/name"})
    assert r.status == 400


# --- list ---------------------------------------------------------------- #
async def test_list_owned_and_shared_with_dedupe(app, db, config):
    owner = await _user(db, "owner@x.com")
    me = await _user(db, "me@x.com")
    headers = await _session(app, config, me)
    pm: ProjectManager = app.state.projects
    # I own one project
    mine = await pm.create_basic(str(me["_id"]), "Mine")
    # I collaborate on another (owned by owner)
    shared = await pm.create_basic(str(owner["_id"]), "Shared")
    await db["projects"].update_one({"_id": shared["_id"]}, {"$set": {"collaberator_refs": [me["_id"]]}})
    # I also have token access to my own project -> must dedupe to owner
    await db["projects"].update_one({"_id": mine["_id"]}, {"$set": {"publicAccesLevel": "tokenBased", "tokenAccessReadOnly_refs": [me["_id"]]}})

    r = await call_asgi(app, "POST", "/api/project", headers=headers, json={})
    assert r.status == 200
    by_id = {p["id"]: p for p in r.json["projects"]}
    assert by_id[str(mine["_id"])]["accessLevel"] == "owner"  # not token
    assert by_id[str(mine["_id"])]["source"] == "owner"
    assert by_id[str(shared["_id"])]["accessLevel"] == "readWrite"
    assert by_id[str(shared["_id"])]["source"] == "invite"
    # owner info injected
    assert by_id[str(shared["_id"])]["owner"]["email"] == "owner@x.com"
    assert r.json["totalSize"] == 2


async def test_list_hides_archived_by_default(app, db, config):
    me = await _user(db, "me@x.com")
    headers = await _session(app, config, me)
    pm = app.state.projects
    a = await pm.create_basic(str(me["_id"]), "Active")
    arch = await pm.create_basic(str(me["_id"]), "Archived")
    await pm.archive(str(arch["_id"]), str(me["_id"]))
    default = await call_asgi(app, "POST", "/api/project", headers=headers, json={})
    assert {p["name"] for p in default.json["projects"]} == {"Active"}
    only_archived = await call_asgi(app, "POST", "/api/project", headers=headers, json={"filters": {"archived": True}})
    assert {p["name"] for p in only_archived.json["projects"]} == {"Archived"}


# --- rename / settings --------------------------------------------------- #
async def test_rename_owner_only(app, db, config):
    owner = await _user(db, "owner@x.com")
    other = await _user(db, "other@x.com")
    pm = app.state.projects
    project = await pm.create_basic(str(owner["_id"]), "Old")
    await db["projects"].update_one({"_id": project["_id"]}, {"$set": {"collaberator_refs": [other["_id"]]}})

    # collaborator cannot rename (needs admin/owner)
    r_other = await call_asgi(app, "POST", f"/project/{project['_id']}/rename", headers=await _session(app, config, other), json={"newProjectName": "Hacked"})
    assert r_other.status == 403

    r_owner = await call_asgi(app, "POST", f"/project/{project['_id']}/rename", headers=await _session(app, config, owner), json={"newProjectName": "New Name"})
    assert r_owner.status == 200
    assert (await pm.find_by_id(str(project["_id"])))["name"] == "New Name"


async def test_update_settings_compiler_validation(app, db, config):
    owner = await _user(db, "owner@x.com")
    headers = await _session(app, config, owner)
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    bad = await call_asgi(app, "POST", f"/project/{project['_id']}/settings", headers=headers, json={"compiler": "wordstar"})
    assert bad.status == 400
    ok = await call_asgi(app, "POST", f"/project/{project['_id']}/settings", headers=headers, json={"compiler": "XeLaTeX"})
    assert ok.status == 204
    assert (await app.state.projects.find_by_id(str(project["_id"])))["compiler"] == "xelatex"


async def test_admin_settings_public_access(app, db, config):
    owner = await _user(db, "owner@x.com")
    headers = await _session(app, config, owner)
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/settings/admin", headers=headers, json={"publicAccessLevel": "tokenBased"})
    assert r.status == 204
    assert (await app.state.projects.find_by_id(str(project["_id"])))["publicAccesLevel"] == "tokenBased"


# --- archive / trash ----------------------------------------------------- #
async def test_archive_and_trash_are_per_user(app, db, config):
    owner = await _user(db, "owner@x.com")
    collab = await _user(db, "collab@x.com")
    pm = app.state.projects
    project = await pm.create_basic(str(owner["_id"]), "P")
    await db["projects"].update_one({"_id": project["_id"]}, {"$set": {"collaberator_refs": [collab["_id"]]}})
    # collaborator archives their own view
    await call_asgi(app, "POST", f"/project/{project['_id']}/archive", headers=await _session(app, config, collab), json={})
    doc = await pm.find_by_id(str(project["_id"]))
    assert collab["_id"] in doc["archived"] and owner["_id"] not in doc["archived"]
    # trashing pulls from archived
    await call_asgi(app, "POST", f"/project/{project['_id']}/trash", headers=await _session(app, config, collab), json={})
    doc = await pm.find_by_id(str(project["_id"]))
    assert collab["_id"] in doc["trashed"] and collab["_id"] not in doc["archived"]
    # untrash
    await call_asgi(app, "DELETE", f"/project/{project['_id']}/trash", headers=await _session(app, config, collab))
    assert collab["_id"] not in (await pm.find_by_id(str(project["_id"])))["trashed"]


# --- delete -------------------------------------------------------------- #
async def test_delete_soft_deletes_to_collection(app, db, config):
    owner = await _user(db, "owner@x.com")
    headers = await _session(app, config, owner)
    project = await app.state.projects.create_basic(str(owner["_id"]), "DeleteMe")
    r = await call_asgi(app, "DELETE", f"/project/{project['_id']}", headers=headers)
    assert r.status == 200
    assert await app.state.projects.find_by_id(str(project["_id"])) is None
    deleted = await db["deletedProjects"].find_one({"deleterData.deletedProjectId": project["_id"]})
    assert deleted["project"]["name"] == "DeleteMe"
    assert deleted["deleterData"]["deleterId"] == owner["_id"]


async def test_delete_requires_owner(app, db, config):
    owner = await _user(db, "owner@x.com")
    other = await _user(db, "other@x.com")
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    r = await call_asgi(app, "DELETE", f"/project/{project['_id']}", headers=await _session(app, config, other))
    assert r.status == 403


# --- clone --------------------------------------------------------------- #
async def test_clone_copies_tree_with_new_ids(app, db, config):
    owner = await _user(db, "owner@x.com")
    cloner = await _user(db, "cloner@x.com")
    pm = app.state.projects
    source = await pm.create_basic(str(owner["_id"]), "Original")
    # make it token-readable so the cloner can read it
    await db["projects"].update_one({"_id": source["_id"]}, {"$set": {"publicAccesLevel": "tokenBased", "tokenAccessReadOnly_refs": [cloner["_id"]]}})
    r = await call_asgi(app, "POST", f"/project/{source['_id']}/clone", headers=await _session(app, config, cloner), json={"projectName": "Copy"})
    assert r.status == 200
    clone = await pm.find_by_id(r.json["project_id"])
    assert clone["name"] == "Copy"
    assert str(clone["owner_ref"]) == str(cloner["_id"])  # new owner
    # tree copied but with fresh doc ids
    src_doc = source["rootFolder"][0]["docs"][0]["_id"]
    clone_doc = clone["rootFolder"][0]["docs"][0]["_id"]
    assert clone["rootFolder"][0]["docs"][0]["name"] == "main.tex"
    assert clone_doc != src_doc


async def test_join_serializes_rootfolder_tree(app, db, config):
    # regression: the join view returned the rootFolder tree with ObjectId ids,
    # which broke JSON serialization (500). Verify a real created project joins OK.
    import base64
    owner = await _user(db, "owner@x.com")
    project = await app.state.projects.create_basic(str(owner["_id"]), "WithTree")
    basic = {"authorization": "Basic " + base64.b64encode(b"overleaf:password").decode()}
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/join", headers=basic, json={"userId": str(owner["_id"])})
    assert r.status == 200
    root = r.json["project"]["rootFolder"][0]
    assert isinstance(root["_id"], str)  # ids stringified
    assert isinstance(root["docs"][0]["_id"], str) and root["docs"][0]["name"] == "main.tex"


async def test_missing_project_404(app, db, config):
    owner = await _user(db, "owner@x.com")
    r = await call_asgi(app, "POST", f"/project/{ObjectId()}/rename", headers=await _session(app, config, owner), json={"newProjectName": "X"})
    assert r.status == 404
