"""Unit tests for the data layer — every behavior the Node original guarantees."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient

from fleetex_notifications.manager import NotificationsManager, parse_expires


@pytest.fixture
def mgr():
    db = AsyncMongoMockClient()["sharelatex"]
    return NotificationsManager(db)


async def test_add_then_get(mgr):
    uid = ObjectId()
    await mgr.add_notification(uid, {"key": "k1", "templateKey": "t1", "messageOpts": {"x": 1}})
    docs = await mgr.get_user_notifications(uid)
    assert len(docs) == 1
    assert docs[0]["key"] == "k1"
    assert docs[0]["templateKey"] == "t1"
    assert docs[0]["messageOpts"] == {"x": 1}
    assert docs[0]["user_id"] == uid


async def test_dedup_is_silent_noop(mgr):
    uid = ObjectId()
    n = {"key": "dup", "templateKey": "t1"}
    await mgr.add_notification(uid, n)
    await mgr.add_notification(uid, {"key": "dup", "templateKey": "t2"})  # should no-op
    docs = await mgr.get_user_notifications(uid)
    assert len(docs) == 1
    assert docs[0]["templateKey"] == "t1"  # unchanged


async def test_force_create_overwrites_in_place(mgr):
    uid = ObjectId()
    await mgr.add_notification(uid, {"key": "dup", "templateKey": "t1"})
    await mgr.add_notification(uid, {"key": "dup", "templateKey": "t2", "forceCreate": True})
    docs = await mgr.get_user_notifications(uid)
    assert len(docs) == 1  # same doc, not a duplicate
    assert docs[0]["templateKey"] == "t2"


async def test_remove_by_id_unsets_templatekey(mgr):
    uid = ObjectId()
    await mgr.add_notification(uid, {"key": "k", "templateKey": "t", "messageOpts": "m"})
    doc = (await mgr.get_user_notifications(uid))[0]
    await mgr.remove_notification_id(uid, doc["_id"])
    assert await mgr.get_user_notifications(uid) == []  # now "read" (invisible)
    # ...but the document still exists in the collection (soft delete).
    assert await mgr.collection.count_documents({"_id": doc["_id"]}) == 1


async def test_remove_by_key(mgr):
    uid = ObjectId()
    await mgr.add_notification(uid, {"key": "k", "templateKey": "t"})
    await mgr.remove_notification_key(uid, "k")
    assert await mgr.get_user_notifications(uid) == []


async def test_by_key_only_across_users(mgr):
    u1, u2 = ObjectId(), ObjectId()
    await mgr.add_notification(u1, {"key": "shared", "templateKey": "t"})
    await mgr.add_notification(u2, {"key": "shared", "templateKey": "t"})
    assert await mgr.count_notifications_by_key_only("shared") == 2
    await mgr.remove_notification_by_key_only("shared")
    # remove_by_key_only unsets templateKey on ONE doc (updateOne), matching Node.
    assert await mgr.count_notifications_by_key_only("shared") == 1


async def test_bulk_delete_removes_documents(mgr):
    u1, u2 = ObjectId(), ObjectId()
    await mgr.add_notification(u1, {"key": "b", "templateKey": "t"})
    await mgr.add_notification(u2, {"key": "b", "templateKey": "t"})
    deleted = await mgr.delete_unread_by_key_only_bulk("b")
    assert deleted == 2
    assert await mgr.collection.count_documents({"key": "b"}) == 0


async def test_bulk_delete_rejects_non_string_key(mgr):
    with pytest.raises(ValueError):
        await mgr.delete_unread_by_key_only_bulk({"$ne": "x"})  # type: ignore[arg-type]


async def test_expires_is_stored_as_date(mgr):
    uid = ObjectId()
    await mgr.add_notification(
        uid, {"key": "k", "templateKey": "t", "expires": "2030-01-01T00:00:00Z"}
    )
    doc = (await mgr.get_user_notifications(uid))[0]
    assert isinstance(doc["expires"], datetime)


def test_parse_expires_variants():
    assert parse_expires("2030-01-01T00:00:00Z").year == 2030
    assert parse_expires(1000).tzinfo is not None
    with pytest.raises(ValueError):
        parse_expires("not-a-date")
    with pytest.raises(ValueError):
        parse_expires([1, 2, 3])
