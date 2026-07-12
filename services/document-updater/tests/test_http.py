"""HTTP API tests."""

from __future__ import annotations

import pytest
from fakeredis import FakeAsyncRedis

from fleetex_document_updater.app import build_app
from fleetex_document_updater.config import DocUpdaterConfig
from fleetex_document_updater.persistence import PersistenceManager
from fleetex_document_updater.redis_manager import RedisManager
from fleetex_service_kit.contract import call_asgi

PID, DID = "5f9f1b0b0b0b0b0b0b0b0b0b", "600000000000000000000001"


class FakePersistence(PersistenceManager):
    def __init__(self, docs=None):
        self.docs = docs or {}

    async def get_doc(self, project_id, doc_id):
        return self.docs.get(str(doc_id))

    async def set_doc(self, *a, **k):
        pass


@pytest.fixture
def redis():
    return FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def app(redis):
    persistence = FakePersistence({DID: {"lines": ["from docstore"], "version": 2, "ranges": {}, "pathname": "main.tex"}})
    return build_app(DocUpdaterConfig(), redis=redis, persistence=persistence)


async def test_status(app):
    r = await call_asgi(app, "GET", "/status")
    assert r.status == 200 and r.text == "document-updater is alive"


async def test_get_doc_loads_from_docstore(app):
    r = await call_asgi(app, "GET", f"/project/{PID}/doc/{DID}")
    assert r.status == 200
    assert r.json["lines"] == ["from docstore"]
    assert r.json["version"] == 2
    assert r.json["type"] == "sharejs-text-ot" and r.json["ops"] == []


async def test_get_doc_not_found(app):
    r = await call_asgi(app, "GET", f"/project/{PID}/doc/{'0'*24}")
    assert r.status == 404


async def test_get_doc_with_from_version_returns_ops(app, redis):
    rm = RedisManager(redis)
    await rm.put_doc_in_memory(PID, DID, [""], 0, {}, "m")
    await rm.update_document(PID, DID, ["a"], 1, [{"op": [{"i": "a", "p": 0}], "v": 0}], {}, None)
    r = await call_asgi(app, "GET", f"/project/{PID}/doc/{DID}?fromVersion=0")
    assert r.status == 200 and r.json["version"] == 1
    assert r.json["ops"] == [{"op": [{"i": "a", "p": 0}], "v": 0}]


async def test_set_doc_and_delete(app, redis):
    setr = await call_asgi(app, "POST", f"/project/{PID}/doc/{DID}", json={"lines": ["new content"]})
    assert setr.status == 204
    assert (await RedisManager(redis).get_doc(PID, DID))["lines"] == ["new content"]
    delr = await call_asgi(app, "DELETE", f"/project/{PID}/doc/{DID}")
    assert delr.status == 204
    assert await RedisManager(redis).get_doc(PID, DID) is None
