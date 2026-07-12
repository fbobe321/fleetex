"""RedisManager + engine + full update-pipeline convergence tests."""

from __future__ import annotations

import json
import random

import pytest
from fakeredis import FakeAsyncRedis

from fleetex_document_updater import engine
from fleetex_document_updater.errors import OpAtFutureVersionError, OpRangeNotAvailableError
from fleetex_document_updater.ot_text import apply
from fleetex_document_updater.persistence import PersistenceManager
from fleetex_document_updater.redis_manager import RedisManager, _pending_updates
from fleetex_document_updater.update_manager import AppliedOpsPublisher, DocumentUpdater


@pytest.fixture
def redis():
    return FakeAsyncRedis(decode_responses=True)


class FakePersistence(PersistenceManager):
    def __init__(self, docs=None):
        self.docs = docs or {}
        self.flushed = []

    async def get_doc(self, project_id, doc_id):
        return self.docs.get(str(doc_id))

    async def set_doc(self, project_id, doc_id, lines, version, ranges):
        self.flushed.append((str(doc_id), lines, version))


PID, DID = "5f9f1b0b0b0b0b0b0b0b0b0b", "600000000000000000000001"


def _updater(redis, persistence=None):
    return DocumentUpdater(RedisManager(redis), persistence or FakePersistence(), AppliedOpsPublisher(redis))


# --- redis manager ------------------------------------------------------- #
async def test_put_and_get_doc(redis):
    rm = RedisManager(redis)
    await rm.put_doc_in_memory(PID, DID, ["hello", "world"], 3, {}, "main.tex")
    doc = await rm.get_doc(PID, DID)
    assert doc["lines"] == ["hello", "world"] and doc["version"] == 3
    assert await rm.get_doc_version(DID) == 3


async def test_get_previous_doc_ops_range(redis):
    rm = RedisManager(redis)
    await rm.put_doc_in_memory(PID, DID, [""], 0, {}, "m")
    await rm.update_document(PID, DID, ["a"], 1, [{"op": [{"i": "a", "p": 0}], "v": 0}], {}, None)
    await rm.update_document(PID, DID, ["ab"], 2, [{"op": [{"i": "b", "p": 1}], "v": 1}], {}, None)
    ops = await rm.get_previous_doc_ops(DID, 0, 2)
    assert [o["v"] for o in ops] == [0, 1]
    with pytest.raises(OpRangeNotAvailableError):
        await rm.get_previous_doc_ops(DID, 0, 5)  # end beyond current version


# --- engine -------------------------------------------------------------- #
def test_engine_transforms_against_previous_ops():
    # doc "A" at v1; incoming op was based on v0 (insert "B" at 0), one prior op (insert A at 0)
    prev = [{"op": [{"i": "A", "p": 0}], "v": 0, "meta": {"source": "clientA"}}]
    update = {"op": [{"i": "B", "p": 0}], "v": 0, "meta": {"source": "clientB"}}
    new_lines, new_version, applied = engine.process_update(["A"], 1, prev, update)
    assert "".join(new_lines) == "BA"  # B rebased to pos 0 (left), applied after A
    assert new_version == 2 and applied["v"] == 1


def test_engine_future_version_raises():
    with pytest.raises(OpAtFutureVersionError):
        engine.process_update([""], 0, [], {"op": [], "v": 5})


# --- THE PIPELINE CONVERGENCE TEST --------------------------------------- #
async def test_two_concurrent_clients_converge(redis):
    updater = _updater(redis)
    rm = RedisManager(redis)
    await rm.put_doc_in_memory(PID, DID, [""], 0, {}, "main.tex")
    # both clients edit from version 0 (concurrent)
    await redis.rpush(_pending_updates(DID), json.dumps({"op": [{"i": "A", "p": 0}], "v": 0, "meta": {"source": "clientA"}}))
    await redis.rpush(_pending_updates(DID), json.dumps({"op": [{"i": "B", "p": 0}], "v": 0, "meta": {"source": "clientB"}}))
    applied = await updater.process_pending(PID, DID)
    assert len(applied) == 2
    doc = await rm.get_doc(PID, DID)
    assert "".join(doc["lines"]) == "BA" and doc["version"] == 2  # deterministic server order


async def test_many_concurrent_clients_converge(redis):
    # N clients all edit from v0; the server serializes them via OT and the
    # resulting doc must equal folding each applied op onto the snapshot in order.
    updater = _updater(redis)
    rm = RedisManager(redis)
    rng = random.Random(7)
    for trial in range(30):
        doc_id = f"doc{trial}".ljust(24, "0")
        await rm.put_doc_in_memory(PID, doc_id, ["hello"], 0, {}, "m")
        for i in range(rng.randint(2, 6)):
            p = rng.randint(0, 5)
            await redis.rpush(_pending_updates(doc_id), json.dumps({"op": [{"i": chr(65 + i), "p": p}], "v": 0, "meta": {"source": f"c{i}"}}))
        applied = await updater.process_pending(PID, doc_id)
        doc = await rm.get_doc(PID, doc_id)
        # reconstruct: apply each (already-transformed) applied op in order onto "hello"
        snapshot = "hello"
        for a in applied:
            snapshot = apply(snapshot, a["op"])
        assert "".join(doc["lines"]) == snapshot  # Redis state == transform-folded result
        assert doc["version"] == len(applied)


async def test_publishes_applied_ops(redis):
    updater = _updater(redis)
    rm = RedisManager(redis)
    await rm.put_doc_in_memory(PID, DID, [""], 0, {}, "m")
    pubsub = redis.pubsub()
    await pubsub.subscribe("applied-ops")
    await redis.rpush(_pending_updates(DID), json.dumps({"op": [{"i": "X", "p": 0}], "v": 0, "meta": {"source": "c"}}))
    await updater.process_pending(PID, DID)
    # drain the subscribe confirmation + the published message
    got = None
    for _ in range(5):
        msg = await pubsub.get_message(timeout=0.5)
        if msg and msg["type"] == "message":
            got = json.loads(msg["data"])
            break
    assert got is not None and got["doc_id"] == DID and got["op"]["op"] == [{"i": "X", "p": 0}]


# --- get_doc with docstore fallback -------------------------------------- #
async def test_get_doc_falls_back_to_docstore(redis):
    persistence = FakePersistence({DID: {"lines": ["from docstore"], "version": 4, "ranges": {}, "pathname": "m.tex"}})
    updater = _updater(redis, persistence)
    doc = await updater.get_doc(PID, DID)
    assert doc["lines"] == ["from docstore"] and doc["version"] == 4
    # now it's cached in redis
    assert await RedisManager(redis).get_doc(PID, DID) is not None
