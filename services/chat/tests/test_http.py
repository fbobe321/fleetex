from __future__ import annotations

from bson import ObjectId

from fleetex_service_kit.contract import call_asgi

PID = "5f9f1b0b0b0b0b0b0b0b0b0b"
UID = "600000000000000000000001"
TID = "600000000000000000000002"


async def test_status(app):
    r = await call_asgi(app, "GET", "/status")
    assert r.status == 200 and r.text == "chat is alive"


async def test_send_global_returns_201_with_room_id(app):
    r = await call_asgi(app, "POST", f"/project/{PID}/messages", json={"user_id": UID, "content": "hello"})
    assert r.status == 201
    assert r.json["content"] == "hello"
    assert r.json["user_id"] == UID
    assert r.json["room_id"] == PID  # send re-adds room_id = projectId
    assert isinstance(r.json["id"], str) and len(r.json["id"]) == 24


async def test_global_list_is_newest_first(app):
    for c in ("first", "second", "third"):
        await call_asgi(app, "POST", f"/project/{PID}/messages", json={"user_id": UID, "content": c})
    r = await call_asgi(app, "GET", f"/project/{PID}/messages")
    assert r.status == 200
    assert [m["content"] for m in r.json] == ["third", "second", "first"]
    assert all("room_id" not in m for m in r.json)  # stripped from lists


async def test_missing_content_is_validation_error(app):
    r = await call_asgi(app, "POST", f"/project/{PID}/messages", json={"user_id": UID})
    assert r.status == 400
    assert r.json == {"message": "Validation errors"}


async def test_invalid_project_id_plain_text_400(app):
    r = await call_asgi(app, "POST", "/project/not-an-id/messages", json={"user_id": UID, "content": "x"})
    assert r.status == 400
    assert r.text == "Invalid projectId"


async def test_invalid_user_id_400(app):
    r = await call_asgi(app, "POST", f"/project/{PID}/messages", json={"user_id": "bad", "content": "x"})
    assert r.status == 400
    assert r.text == "Invalid userId"


async def test_content_too_long_400(app):
    big = "a" * (10240 + 1)
    r = await call_asgi(app, "POST", f"/project/{PID}/messages", json={"user_id": UID, "content": big})
    assert r.status == 400
    assert r.text == "Content too long (> 10240 bytes)"


async def test_unknown_route_is_json_404(app):
    r = await call_asgi(app, "GET", "/no/such/route")
    assert r.status == 404
    assert r.json == {"message": "Not found"}


async def test_thread_send_list_and_getthreads(app):
    await call_asgi(app, "POST", f"/project/{PID}/thread/{TID}/messages", json={"user_id": UID, "content": "t1"})
    await call_asgi(app, "POST", f"/project/{PID}/thread/{TID}/messages", json={"user_id": UID, "content": "t2"})
    threads = await call_asgi(app, "GET", f"/project/{PID}/threads")
    assert threads.status == 200
    assert TID in threads.json
    # thread messages sorted ascending
    assert [m["content"] for m in threads.json[TID]["messages"]] == ["t1", "t2"]


async def test_get_thread_404_when_empty(app):
    # create the room (via send then delete message) — but simplest: unknown thread
    r = await call_asgi(app, "GET", f"/project/{PID}/thread/{TID}")
    assert r.status == 404


async def test_resolve_reopen_and_resolved_ids(app):
    await call_asgi(app, "POST", f"/project/{PID}/thread/{TID}/messages", json={"user_id": UID, "content": "t"})
    res = await call_asgi(app, "POST", f"/project/{PID}/thread/{TID}/resolve", json={"user_id": UID})
    assert res.status == 204
    ids = await call_asgi(app, "GET", f"/project/{PID}/resolved-thread-ids")
    assert ids.json == {"resolvedThreadIds": [TID]}
    # grouped thread shows resolved metadata
    threads = await call_asgi(app, "GET", f"/project/{PID}/threads")
    assert threads.json[TID]["resolved"] is True
    assert threads.json[TID]["resolved_by_user_id"] == UID
    reopen = await call_asgi(app, "POST", f"/project/{PID}/thread/{TID}/reopen")
    assert reopen.status == 204
    ids2 = await call_asgi(app, "GET", f"/project/{PID}/resolved-thread-ids")
    assert ids2.json == {"resolvedThreadIds": []}


async def test_resolve_requires_user_id(app):
    r = await call_asgi(app, "POST", f"/project/{PID}/thread/{TID}/resolve", json={})
    assert r.status == 400
    assert r.json == {"message": "Validation errors"}


async def test_edit_message_204_then_404(app):
    send = await call_asgi(app, "POST", f"/project/{PID}/messages", json={"user_id": UID, "content": "orig"})
    mid = send.json["id"]
    ok = await call_asgi(app, "POST", f"/project/{PID}/messages/{mid}/edit", json={"content": "edited"})
    assert ok.status == 204
    got = await call_asgi(app, "GET", f"/project/{PID}/messages/{mid}")
    assert got.json["content"] == "edited"
    assert got.json["edited_at"] is not None
    missing = await call_asgi(app, "POST", f"/project/{PID}/messages/{ObjectId()}/edit", json={"content": "x"})
    assert missing.status == 404


async def test_get_missing_global_message_404(app):
    r = await call_asgi(app, "GET", f"/project/{PID}/messages/{ObjectId()}")
    assert r.status == 404


async def test_delete_message_always_204(app):
    r = await call_asgi(app, "DELETE", f"/project/{PID}/messages/{ObjectId()}")
    assert r.status == 204


async def test_destroy_project(app):
    await call_asgi(app, "POST", f"/project/{PID}/messages", json={"user_id": UID, "content": "g"})
    await call_asgi(app, "POST", f"/project/{PID}/thread/{TID}/messages", json={"user_id": UID, "content": "t"})
    d = await call_asgi(app, "DELETE", f"/project/{PID}")
    assert d.status == 204
    assert (await call_asgi(app, "GET", f"/project/{PID}/messages")).json == []
    assert (await call_asgi(app, "GET", f"/project/{PID}/threads")).json == {}


async def test_duplicate_and_generate_thread_data(app):
    await call_asgi(app, "POST", f"/project/{PID}/thread/{TID}/messages", json={"user_id": UID, "content": "orig"})
    dup = await call_asgi(app, "POST", f"/project/{PID}/duplicate-comment-threads", json={"threads": [TID]})
    assert dup.status == 200
    new_id = dup.json["newThreads"][TID]["duplicateId"]
    gen = await call_asgi(app, "POST", f"/project/{PID}/generate-thread-data", json={"threads": [new_id]})
    assert new_id in gen.json
    assert [m["content"] for m in gen.json[new_id]["messages"]] == ["orig"]


async def test_duplicate_missing_thread_reports_not_found(app):
    dup = await call_asgi(app, "POST", f"/project/{PID}/duplicate-comment-threads", json={"threads": [str(ObjectId())]})
    assert dup.status == 200
    (only,) = dup.json["newThreads"].values()
    assert only == {"error": "not found"}


async def test_clone_comment_threads(app):
    target = str(ObjectId())
    await call_asgi(app, "POST", f"/project/{PID}/thread/{TID}/messages", json={"user_id": UID, "content": "c"})
    r = await call_asgi(app, "POST", f"/project/{PID}/clone-comment-threads", json={"targetProjectId": target})
    assert r.status == 204
    cloned = await call_asgi(app, "GET", f"/project/{target}/threads")
    assert TID in cloned.json
    assert [m["content"] for m in cloned.json[TID]["messages"]] == ["c"]
