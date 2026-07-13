"""Compile wiring: gather docs -> clsi -> proxy PDF."""

from __future__ import annotations

import pytest

from fleetex_service_kit.contract import call_asgi
from fleetex_web.app import build_app
from fleetex_web.compile import ClsiManager, _doc_entities
from fleetex_web.sessions import generate_session_id, serialize_user
from fleetex_web.users import UserManager


class FakeClsi(ClsiManager):
    def __init__(self):
        self.compiled = None

    async def compile(self, project_id, project):
        # capture what web sent, return a success with an output.pdf
        self.compiled = {"project_id": project_id, "root": project.get("rootDoc_id"),
                         "docs": _doc_entities(project)}
        return {"compile": {"status": "success", "outputFiles": [
            {"path": "output.pdf", "type": "pdf", "build": "b1-b2", "size": 123},
            {"path": "output.log", "type": "log", "build": "b1-b2"},
        ]}}

    async def get_output(self, project_id, build_id, file_path):
        class R:
            status_code = 200
            content = b"%PDF fake"
            headers = {"content-type": "application/pdf"}
        return R()


@pytest.fixture
def clsi():
    return FakeClsi()


@pytest.fixture
def app(config, db, redis, clsi):
    return build_app(config, db=db, redis=redis, clsi=clsi)


async def _owner(db):
    return await UserManager(db, bcrypt_rounds=4).create_user("o@x.com", "pw")


async def _session(app, config, user):
    sid = generate_session_id()
    await app.state.store.save(sid, {"passport": {"user": serialize_user(user)}})
    return {"cookie": f"{config.cookie_name}={app.state.store.sign_cookie(sid)}"}


async def test_compile_returns_pdf_with_proxied_url(app, db, config, clsi):
    owner = await _owner(db)
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/compile", headers=await _session(app, config, owner))
    assert r.status == 200
    c = r.json["compile"]
    assert c["status"] == "success"
    pdf = next(f for f in c["outputFiles"] if f["path"] == "output.pdf")
    # url rewritten to a web-proxied, single-origin path
    assert pdf["url"] == f"/project/{project['_id']}/output/b1-b2/output.pdf"
    # web gathered the project's docs (main.tex) and passed the root doc
    assert ("main.tex" in [p.split("/")[-1] for _id, p in clsi.compiled["docs"]])


async def test_compile_requires_login(app, db):
    owner = await _owner(db)
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    r = await call_asgi(app, "POST", f"/project/{project['_id']}/compile")
    assert r.status == 401


async def test_output_proxy_streams_pdf(app, db, config):
    owner = await _owner(db)
    project = await app.state.projects.create_basic(str(owner["_id"]), "P")
    r = await call_asgi(app, "GET", f"/project/{project['_id']}/output/b1-b2/output.pdf", headers=await _session(app, config, owner))
    assert r.status == 200 and r.text == "%PDF fake"
    assert "application/pdf" in r.headers.get("content-type", "")


def test_doc_entities_walks_tree():
    from bson import ObjectId
    d1, d2 = ObjectId(), ObjectId()
    project = {"rootFolder": [{"_id": ObjectId(), "name": "rootFolder",
        "docs": [{"_id": d1, "name": "main.tex"}], "fileRefs": [],
        "folders": [{"_id": ObjectId(), "name": "ch", "docs": [{"_id": d2, "name": "intro.tex"}], "fileRefs": [], "folders": []}]}]}
    entities = _doc_entities(project)
    assert (str(d1), "/main.tex") in entities and (str(d2), "/ch/intro.tex") in entities
