"""RealtimeServer tests using an emit recorder (no socket.io network)."""

from __future__ import annotations

import httpx
import pytest

from fleetex_realtime.connected_users import ConnectedUsersManager
from fleetex_realtime.document_updater import DocumentUpdaterManager, pending_updates_key
from fleetex_realtime.server import RealtimeServer
from fleetex_realtime.web_api import WebApiManager
from tests.conftest import EmitRecorder, mock_http


def make_server(redis, *, privilege="readAndWrite", restricted=False, http_calls=None):
    def web_handler(request):
        return httpx.Response(200, json={"project": {"name": "Proj"}, "privilegeLevel": privilege, "isRestrictedUser": restricted})

    def du_handler(request):
        if http_calls is not None:
            http_calls.append((request.method, str(request.url)))
        if request.method == "GET":
            return httpx.Response(200, json={"lines": ["hello"], "version": 5, "ops": [], "ranges": {}, "type": "sharejs-text-ot"})
        return httpx.Response(204)

    rec = EmitRecorder()
    web = WebApiManager("http://web", "u", "p", http=mock_http(web_handler))
    du = DocumentUpdaterManager(redis, "http://du", http=mock_http(du_handler), shard_count=1)
    server = RealtimeServer(emit=rec.emit, disconnect=rec.disconnect, web_api=web, du=du, connected_users=ConnectedUsersManager(redis))
    return server, rec


async def test_connect_success_emits_join_response(redis):
    server, rec = make_server(redis)
    ok = await server.connect("sid1", "proj1", "u1", None)
    assert ok is True
    (sid, data), = rec.events("joinProjectResponse")
    assert sid == "sid1" and data["project"] == {"name": "Proj"} and data["permissionsLevel"] == "readAndWrite"
    assert data["protocolVersion"] == 2
    assert "sid1" in server.rooms["proj1"]
    assert await server.connected_users.count_connected_clients("proj1") == 1


async def test_connect_rejected_on_web_403(redis):
    def web_handler(request):
        return httpx.Response(403)

    rec = EmitRecorder()
    web = WebApiManager("http://web", "u", "p", http=mock_http(web_handler))
    du = DocumentUpdaterManager(redis, "http://du", shard_count=1)
    server = RealtimeServer(emit=rec.emit, disconnect=rec.disconnect, web_api=web, du=du, connected_users=ConnectedUsersManager(redis))
    ok = await server.connect("sid1", "proj1", "u1", None)
    assert ok is False
    (sid, data), = rec.events("connectionRejected")
    assert data["message"] == "not authorized"


async def test_join_doc_returns_ack_and_joins_room(redis):
    server, rec = make_server(redis)
    await server.connect("sid1", "proj1", "u1", None)
    ack = await server.join_doc("sid1", "doc1", -1, {})
    assert ack == (None, ["hello"], 5, [], {}, "sharejs-text-ot")
    assert "sid1" in server.rooms["doc1"]


async def test_apply_ot_update_queues_change(redis):
    server, rec = make_server(redis, privilege="readAndWrite")
    await server.connect("sid1", "proj1", "u1", None)
    result = await server.apply_ot_update("sid1", "doc1", {"op": [{"i": "x", "p": 0}], "v": 1})
    assert result is None  # acked with no error
    assert await redis.llen(pending_updates_key("doc1")) == 1


async def test_apply_ot_update_unauthorized_readonly(redis):
    server, rec = make_server(redis, privilege="readOnly")
    await server.connect("sid1", "proj1", "u1", None)
    result = await server.apply_ot_update("sid1", "doc1", {"op": [{"i": "x", "p": 0}], "v": 1})
    assert result == ({"message": "not authorized"},)


async def test_update_position_broadcasts(redis):
    server, rec = make_server(redis)
    await server.connect("sid1", "proj1", "u1", None)
    await server.connect("sid2", "proj1", "u2", None)
    await server.update_position("sid1", {"row": 1, "column": 2, "doc_id": "doc1"})
    updated = rec.events("clientTracking.clientUpdated")
    assert len(updated) == 2  # both clients in project room
    assert updated[0][1]["row"] == 1


async def test_get_connected_users_restricted_empty(redis):
    server, rec = make_server(redis, restricted=True)
    await server.connect("sid1", "proj1", "u1", None)
    assert await server.get_connected_users("sid1") == (None, [])


async def test_disconnect_flushes_when_last_client(redis):
    calls = []
    server, rec = make_server(redis, http_calls=calls)
    await server.connect("sid1", "proj1", "u1", None)
    await server.on_disconnect("sid1")
    assert "sid1" not in server.sessions
    # project room empty -> document-updater flush (DELETE) issued
    assert any(method == "DELETE" for method, _url in calls)


async def test_disconnect_notifies_other_clients_and_no_flush(redis):
    calls = []
    server, rec = make_server(redis, http_calls=calls)
    await server.connect("sid1", "proj1", "u1", None)
    await server.connect("sid2", "proj1", "u2", None)
    await server.on_disconnect("sid1")
    # sid2 (still connected) is told sid1 left; project not empty -> no flush
    notified = rec.events("clientTracking.clientDisconnected")
    assert [sid for sid, _ in notified] == ["sid2"]
    assert not any(method == "DELETE" for method, _url in calls)


async def test_dispatch_applied_ops_fans_out(redis):
    server, rec = make_server(redis)
    await server.connect("sid1", "proj1", "u1", None)
    await server.join_doc("sid1", "doc1", -1, {})
    update = {"meta": {"source": "P.other"}, "v": 9, "doc": "doc1", "op": [{"i": "z", "p": 0}]}
    await server.dispatch_applied_ops({"doc_id": "doc1", "op": update})
    applied = rec.events("otUpdateApplied")
    assert len(applied) == 1 and applied[0][1]["v"] == 9


async def test_dispatch_editor_event_to_room(redis):
    server, rec = make_server(redis)
    await server.connect("sid1", "proj1", "u1", None)
    await server.dispatch_editor_event({"room_id": "proj1", "message": "projectNameUpdated", "payload": [{"name": "New"}]})
    ev = rec.events("projectNameUpdated")
    assert ev == [("sid1", {"name": "New"})]
