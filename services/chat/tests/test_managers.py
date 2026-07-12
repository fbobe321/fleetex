from __future__ import annotations

import pytest
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient

from fleetex_chat.constants import GLOBAL_THREAD
from fleetex_chat.errors import MissingMessageError, MissingThreadError
from fleetex_chat.messages import MessageManager
from fleetex_chat.threads import ThreadManager


@pytest.fixture
def db():
    return AsyncMongoMockClient()["sharelatex"]


async def test_find_or_create_thread_is_idempotent(db):
    tm = ThreadManager(db)
    pid = ObjectId()
    tid = ObjectId()
    a = await tm.find_or_create_thread(pid, tid)
    b = await tm.find_or_create_thread(pid, tid)
    assert a["_id"] == b["_id"]  # same room, not a duplicate
    assert a["thread_id"] == tid


async def test_global_room_has_no_thread_id(db):
    tm = ThreadManager(db)
    room = await tm.find_or_create_thread(ObjectId(), GLOBAL_THREAD)
    assert "thread_id" not in room


async def test_find_thread_missing_raises(db):
    tm = ThreadManager(db)
    with pytest.raises(MissingThreadError):
        await tm.find_thread(ObjectId(), ObjectId())


async def test_messages_sorted_desc_with_before_cursor(db):
    mm = MessageManager(db)
    room = ObjectId()
    for ts in (100, 200, 300):
        await mm.create_message(room, ObjectId(), f"m{ts}", ts)
    latest = await mm.get_messages(room, limit=50)
    assert [m["timestamp"] for m in latest] == [300, 200, 100]  # newest first
    before = await mm.get_messages(room, limit=50, before=250)
    assert [m["timestamp"] for m in before] == [200, 100]


async def test_get_message_missing_raises(db):
    mm = MessageManager(db)
    with pytest.raises(MissingMessageError):
        await mm.get_message(ObjectId(), ObjectId())


async def test_update_message_sets_edited_at(db):
    mm = MessageManager(db)
    room = ObjectId()
    msg = await mm.create_message(room, ObjectId(), "orig", 100)
    ok = await mm.update_message(room, msg["_id"], None, "changed", 200)
    assert ok is True
    stored = await mm.get_message(room, msg["_id"])
    assert stored["content"] == "changed"
    assert stored["edited_at"] == 200


async def test_update_message_wrong_room_is_noop(db):
    mm = MessageManager(db)
    msg = await mm.create_message(ObjectId(), ObjectId(), "orig", 100)
    ok = await mm.update_message(ObjectId(), msg["_id"], None, "x", 200)
    assert ok is False


async def test_resolve_and_reopen(db):
    tm = ThreadManager(db)
    pid, tid = ObjectId(), ObjectId()
    await tm.find_or_create_thread(pid, tid)
    await tm.resolve_thread(pid, tid, "user-42")
    assert await tm.get_resolved_thread_ids(pid) == [str(tid)]
    await tm.reopen_thread(pid, tid)
    assert await tm.get_resolved_thread_ids(pid) == []


async def test_duplicate_room_drops_id_and_edited_at(db):
    mm = MessageManager(db)
    src, dst = ObjectId(), ObjectId()
    m = await mm.create_message(src, ObjectId(), "hi", 100)
    await mm.update_message(src, m["_id"], None, "hi2", 150)
    await mm.duplicate_room_to_other_room(src, dst)
    copies = await mm.find_all_messages_in_rooms([dst])
    assert len(copies) == 1
    assert copies[0]["content"] == "hi2"
    assert "edited_at" not in copies[0]
    assert copies[0]["_id"] != m["_id"]
