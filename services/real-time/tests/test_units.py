"""Unit tests for the pure/faithful pieces: redis bridge, managers, controller."""

from __future__ import annotations

import httpx
import pytest

from fleetex_realtime.connected_users import ConnectedUsersManager
from fleetex_realtime.controller import (
    assert_can_apply_update,
    encode_line_for_websocket,
    join_doc,
    prepare_update,
)
from fleetex_realtime.document_updater import DocumentUpdaterManager, pending_updates_key
from fleetex_realtime.errors import ClientRequestedMissingOpsError, NotAuthorizedError, UpdateTooLargeError
from fleetex_realtime.redis_bridge import build_editor_event, parse_message, plan_applied_op_emits
from fleetex_realtime.web_api import WebApiManager
from tests.conftest import mock_http


# --- redis bridge -------------------------------------------------------- #
def test_build_editor_event_shape():
    raw = build_editor_event("proj1", "reciveNewDoc", [{"a": 1}])
    assert parse_message(raw) == {"room_id": "proj1", "message": "reciveNewDoc", "payload": [{"a": 1}]}


def test_plan_applied_op_source_gets_ack_others_get_op():
    update = {"meta": {"source": "P.alice", "tsRT": 12.3}, "v": 7, "doc": "d1", "op": [{"i": "x", "p": 0}]}
    message = {"doc_id": "d1", "op": update}
    emits = plan_applied_op_emits(message, [("sidA", "P.alice"), ("sidB", "P.bob")])
    assert ("sidA", "otUpdateApplied", {"v": 7, "doc": "d1"}) in emits
    bob = next(p for s, e, p in emits if s == "sidB")
    assert bob["v"] == 7 and "tsRT" not in bob["meta"]  # tsRT stripped from broadcast


def test_plan_applied_op_skips_dup_for_others():
    update = {"meta": {"source": "P.alice"}, "v": 1, "doc": "d1", "op": [], "dup": True}
    emits = plan_applied_op_emits({"doc_id": "d1", "op": update}, [("sidB", "P.bob")])
    assert emits == []


# --- connected users (fakeredis) ----------------------------------------- #
async def test_connected_users_roundtrip(redis):
    cu = ConnectedUsersManager(redis)
    await cu.update_user_position("proj", "P.1", {"user_id": "u1", "first_name": "A", "last_name": "B", "email": "a@b"})
    assert await cu.count_connected_clients("proj") == 1
    users = await cu.get_connected_users("proj")
    assert len(users) == 1 and users[0]["user_id"] == "u1" and users[0]["client_id"] == "P.1"
    await cu.mark_user_as_disconnected("proj", "P.1")
    assert await cu.count_connected_clients("proj") == 0


async def test_connected_users_with_cursor(redis):
    cu = ConnectedUsersManager(redis)
    await cu.update_user_position("proj", "P.1", {"user_id": "u1"}, {"row": 3, "column": 5, "doc_id": "d1"})
    users = await cu.get_connected_users("proj")
    assert users[0]["cursorData"] == {"row": 3, "column": 5, "doc_id": "d1"}


# --- document updater (fakeredis + mock http) ---------------------------- #
async def test_queue_change_pushes_both_lists(redis):
    du = DocumentUpdaterManager(redis, "http://du", shard_count=1)  # shard 1 -> base key
    await du.queue_change("proj", "doc1", {"op": [{"i": "x"}], "v": 1, "doc": "doc1"}, max_update_size=10_000)
    assert await redis.llen(pending_updates_key("doc1")) == 1
    assert await redis.lrange("pending-updates-list", 0, -1) == ["proj:doc1"]


async def test_queue_change_too_large(redis):
    du = DocumentUpdaterManager(redis, "http://du", shard_count=1)
    with pytest.raises(UpdateTooLargeError):
        await du.queue_change("p", "d", {"op": [{"i": "x" * 100}]}, max_update_size=10)


async def test_get_document_ok_and_errors(redis):
    def handler(request):
        if "missing" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, json={"lines": ["a"], "version": 3, "ops": [], "ranges": {}, "type": "sharejs-text-ot"})

    du = DocumentUpdaterManager(redis, "http://du", http=mock_http(handler), shard_count=1)
    doc = await du.get_document("proj", "doc1")
    assert doc["version"] == 3
    with pytest.raises(ClientRequestedMissingOpsError):
        await du.get_document("proj", "missing")


# --- web api (mock http) ------------------------------------------------- #
async def test_web_join_success_and_403():
    def handler(request):
        if "denied" in str(request.url):
            return httpx.Response(403)
        return httpx.Response(200, json={"project": {"name": "P"}, "privilegeLevel": "readAndWrite", "isRestrictedUser": False})

    web = WebApiManager("http://web", "u", "p", http=mock_http(handler))
    data = await web.join_project("proj", "u1")
    assert data["privilegeLevel"] == "readAndWrite"
    with pytest.raises(NotAuthorizedError):
        await web.join_project("denied", "u1")


# --- controller ---------------------------------------------------------- #
def test_encode_line_for_websocket():
    assert encode_line_for_websocket("café") == "cafÃ©"  # UTF-8 bytes as latin-1


async def test_join_doc_encodes_and_clears_comments_for_restricted(redis):
    def handler(request):
        return httpx.Response(200, json={"lines": ["café"], "version": 2, "ops": [],
                                         "ranges": {"comments": [{"id": "c1"}], "changes": []}, "type": "sharejs-text-ot"})

    du = DocumentUpdaterManager(redis, "http://du", http=mock_http(handler), shard_count=1)
    lines, version, ops, ranges, doc_type = await join_doc(du, "proj", "doc1", -1, {}, is_restricted_user=True)
    assert lines == ["cafÃ©"] and version == 2
    assert ranges["comments"] == []  # restricted users don't see comments


def test_assert_can_apply_update_by_op_type():
    comment = {"op": [{"c": "x", "p": 0}]}
    assert_can_apply_update(comment, "readOnly")  # view perm ok for comment
    edit = {"op": [{"i": "x", "p": 0}]}
    with pytest.raises(NotAuthorizedError):
        assert_can_apply_update(edit, "readOnly")  # edit needs readAndWrite
    assert_can_apply_update(edit, "readAndWrite")
    tracked = {"op": [{"i": "x"}], "meta": {"tc": "1"}}
    with pytest.raises(NotAuthorizedError):
        assert_can_apply_update(tracked, "readOnly")


def test_prepare_update_stamps_metadata():
    up = prepare_update({"op": []}, "doc1", "P.me", "u1")
    assert up["doc"] == "doc1" and up["meta"]["source"] == "P.me" and up["meta"]["user_id"] == "u1"
    with pytest.raises(ValueError):
        prepare_update({"doc": "other"}, "doc1", "P.me", "u1")
