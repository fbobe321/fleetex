"""Unit tests for rev/version semantics and the archive round-trip."""

from __future__ import annotations

import pytest
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient

from fleetex_docstore.archive import DocArchiveManager, InMemoryArchiveStore
from fleetex_docstore.docmanager import DocManager
from fleetex_docstore.errors import DocVersionDecrementedError
from fleetex_docstore.mongo import MongoManager


@pytest.fixture
def dm():
    db = AsyncMongoMockClient()["sharelatex"]
    mongo = MongoManager(db)
    archive = DocArchiveManager(mongo, InMemoryArchiveStore(), "bucket", "fs")
    return DocManager(mongo, archive)


PID, DID = str(ObjectId()), str(ObjectId())


async def test_insert_sets_rev_1(dm):
    modified, rev = await dm.update_doc(PID, DID, ["a", "b"], 1, {})
    assert modified is True and rev == 1


async def test_lines_change_bumps_rev(dm):
    await dm.update_doc(PID, DID, ["a"], 1, {})
    modified, rev = await dm.update_doc(PID, DID, ["a", "c"], 2, {})
    assert modified is True and rev == 2


async def test_unchanged_is_not_modified(dm):
    await dm.update_doc(PID, DID, ["a"], 1, {})
    modified, rev = await dm.update_doc(PID, DID, ["a"], 1, {})
    assert modified is False and rev == 1


async def test_version_only_change_does_not_bump_rev(dm):
    await dm.update_doc(PID, DID, ["a"], 1, {})
    modified, rev = await dm.update_doc(PID, DID, ["a"], 2, {})  # same lines, newer version
    assert modified is True and rev == 1  # rev unchanged


async def test_version_decrement_raises(dm):
    await dm.update_doc(PID, DID, ["a"], 5, {})
    with pytest.raises(DocVersionDecrementedError):
        await dm.update_doc(PID, DID, ["a"], 3, {})


async def test_archive_then_unarchive_roundtrip(dm):
    await dm.update_doc(PID, DID, ["hello", "world"], 1, {})
    await dm.archive.archive_doc(PID, DID)
    # after archiving: inS3 set, lines/ranges removed from mongo
    raw = await dm.mongo.find_doc(PID, DID, {"inS3": 1, "lines": 1})
    assert raw["inS3"] is True
    assert raw.get("lines") is None
    # get_full_doc transparently unarchives
    doc = await dm.get_full_doc(PID, DID)
    assert doc["lines"] == ["hello", "world"]
    assert not doc.get("inS3")


async def test_peek_does_not_unarchive(dm):
    await dm.update_doc(PID, DID, ["x"], 1, {})
    await dm.archive.archive_doc(PID, DID)
    doc, status = await dm.peek_doc(PID, DID)
    assert status == "archived"
    assert doc["lines"] == ["x"]
    # still archived in mongo (peek didn't write back)
    raw = await dm.mongo.find_doc(PID, DID, {"inS3": 1})
    assert raw["inS3"] is True
