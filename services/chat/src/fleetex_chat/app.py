"""HTTP layer — port of MessageHttpController + server.js (exegesis) behavior.

Validation/status contract preserved from the Node original:
* missing required body field (user_id/content) -> 400 JSON {"message":"Validation errors"}
* invalid projectId/threadId path param         -> 400 plain-text "Invalid projectId"/"Invalid threadId"
* invalid userId in body                         -> 400 plain-text "Invalid userId"
* empty content                                  -> 400 plain-text "No content provided"
* content > 10240                                -> 400 plain-text "Content too long (> 10240 bytes)"
* unmatched route                                -> 404 JSON {"message":"Not found"}
* uncaught error                                 -> 500 JSON {"message":"Internal error: <msg>"}
* missing thread/message on read-only getters    -> 404 empty body
"""

from __future__ import annotations

import time

from bson import ObjectId
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fleetex_service_kit import Settings, create_app

from .constants import DEFAULT_MESSAGE_LIMIT, GLOBAL_THREAD, MAX_MESSAGE_LENGTH
from .errors import MissingMessageError, MissingThreadError
from .formatter import format_message_for_client, group_messages_by_threads
from .messages import MessageManager
from .serialize import encode
from .threads import ThreadManager


def _now_ms() -> int:
    return int(time.time() * 1000)


def _bad(text: str) -> PlainTextResponse:
    return PlainTextResponse(text, status_code=400)


def _validation_error() -> JSONResponse:
    return JSONResponse({"message": "Validation errors"}, status_code=400)


def _managers(request: Request) -> tuple[MessageManager, ThreadManager]:
    db = request.app.state.db
    return MessageManager(db), ThreadManager(db)


async def _json(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env("chat", default_port=3010)
    app = create_app(settings, connect_redis=False, status_text="chat is alive")

    # ---- fallbacks matching server.js ---------------------------------- #
    async def _not_found_handler(request: Request, exc) -> JSONResponse:
        if exc.status_code == 404:
            return JSONResponse({"message": "Not found"}, status_code=404)
        return JSONResponse({"message": str(exc.detail)}, status_code=exc.status_code)

    from starlette.exceptions import HTTPException as StarletteHTTPException

    app.add_exception_handler(StarletteHTTPException, _not_found_handler)

    @app.exception_handler(Exception)
    async def _internal_error(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"message": f"Internal error: {exc}"}, status_code=500)

    # ---- shared message send ------------------------------------------- #
    async def _send(project_id: str, thread_id, body: dict, messages, threads):
        user_id = body.get("user_id")
        content = body.get("content")
        if user_id is None or content is None:  # exegesis body validation
            return _validation_error()
        if not ObjectId.is_valid(project_id):
            return _bad("Invalid projectId")
        if thread_id != GLOBAL_THREAD and not ObjectId.is_valid(thread_id):
            return _bad("Invalid threadId")
        if not ObjectId.is_valid(user_id):
            return _bad("Invalid userId")
        if not content:
            return _bad("No content provided")
        if len(content) > MAX_MESSAGE_LENGTH:
            return _bad(f"Content too long (> {MAX_MESSAGE_LENGTH} bytes)")
        room = await threads.find_or_create_thread(project_id, thread_id)
        message = await messages.create_message(room["_id"], user_id, content, _now_ms())
        formatted = format_message_for_client(message)
        formatted["room_id"] = project_id  # quirk: send returns projectId as room_id
        return JSONResponse(encode(formatted), status_code=201)

    async def _get_messages(project_id: str, thread_id, request: Request):
        if not ObjectId.is_valid(project_id):
            return _bad("Invalid projectId")
        if thread_id != GLOBAL_THREAD and not ObjectId.is_valid(thread_id):
            return _bad("Invalid threadId")
        messages, threads = _managers(request)
        before = request.query_params.get("before")
        limit = request.query_params.get("limit")
        room = await threads.find_or_create_thread(project_id, thread_id)
        docs = await messages.get_messages(
            room["_id"],
            int(limit) if limit is not None else DEFAULT_MESSAGE_LIMIT,
            int(before) if before is not None else None,
        )
        return JSONResponse(encode([format_message_for_client(d) for d in docs]))

    async def _get_single(project_id: str, thread_id, message_id: str, request: Request):
        if not ObjectId.is_valid(project_id):
            return _bad("Invalid projectId")
        if thread_id != GLOBAL_THREAD and not ObjectId.is_valid(thread_id):
            return _bad("Invalid threadId")
        messages, threads = _managers(request)
        try:
            room = await threads.find_thread(project_id, thread_id)
            doc = await messages.get_message(room["_id"], message_id)
        except (MissingThreadError, MissingMessageError):
            return Response(status_code=404)
        return JSONResponse(encode(format_message_for_client(doc)))

    async def _edit(project_id: str, thread_id, message_id: str, body: dict, request: Request):
        content = body.get("content")
        if content is None:
            return _validation_error()
        if not ObjectId.is_valid(project_id):
            return _bad("Invalid projectId")
        if thread_id != GLOBAL_THREAD and not ObjectId.is_valid(thread_id):
            return _bad("Invalid threadId")
        messages, threads = _managers(request)
        room = await threads.find_or_create_thread(project_id, thread_id)
        ok = await messages.update_message(
            room["_id"], message_id, body.get("userId"), content, _now_ms()
        )
        return Response(status_code=204 if ok else 404)

    # ================= GLOBAL MESSAGES ================================== #
    @app.get("/project/{project_id}/messages")
    async def get_global_messages(project_id: str, request: Request):
        return await _get_messages(project_id, GLOBAL_THREAD, request)

    @app.post("/project/{project_id}/messages")
    async def send_global_message(project_id: str, request: Request):
        messages, threads = _managers(request)
        return await _send(project_id, GLOBAL_THREAD, await _json(request), messages, threads)

    @app.get("/project/{project_id}/messages/{message_id}")
    async def get_global_message(project_id: str, message_id: str, request: Request):
        return await _get_single(project_id, GLOBAL_THREAD, message_id, request)

    @app.post("/project/{project_id}/messages/{message_id}/edit")
    async def edit_global_message(project_id: str, message_id: str, request: Request):
        return await _edit(project_id, GLOBAL_THREAD, message_id, await _json(request), request)

    @app.delete("/project/{project_id}/messages/{message_id}")
    async def delete_global_message(project_id: str, message_id: str, request: Request):
        if not ObjectId.is_valid(project_id):
            return _bad("Invalid projectId")
        messages, threads = _managers(request)
        room = await threads.find_or_create_thread(project_id, GLOBAL_THREAD)
        await messages.delete_message(room["_id"], message_id)
        return Response(status_code=204)

    # ================= THREAD MESSAGES ================================= #
    @app.post("/project/{project_id}/thread/{thread_id}/messages")
    async def send_thread_message(project_id: str, thread_id: str, request: Request):
        messages, threads = _managers(request)
        return await _send(project_id, thread_id, await _json(request), messages, threads)

    @app.get("/project/{project_id}/thread/{thread_id}/messages/{message_id}")
    async def get_thread_message(project_id: str, thread_id: str, message_id: str, request: Request):
        return await _get_single(project_id, thread_id, message_id, request)

    @app.post("/project/{project_id}/thread/{thread_id}/messages/{message_id}/edit")
    async def edit_thread_message(project_id: str, thread_id: str, message_id: str, request: Request):
        return await _edit(project_id, thread_id, message_id, await _json(request), request)

    @app.delete("/project/{project_id}/thread/{thread_id}/messages/{message_id}")
    async def delete_thread_message(project_id: str, thread_id: str, message_id: str, request: Request):
        if not ObjectId.is_valid(project_id) or not ObjectId.is_valid(thread_id):
            return _bad("Invalid projectId" if not ObjectId.is_valid(project_id) else "Invalid threadId")
        messages, threads = _managers(request)
        room = await threads.find_or_create_thread(project_id, thread_id)
        await messages.delete_message(room["_id"], message_id)
        return Response(status_code=204)

    @app.delete("/project/{project_id}/thread/{thread_id}/user/{user_id}/messages/{message_id}")
    async def delete_user_message(project_id: str, thread_id: str, user_id: str, message_id: str, request: Request):
        if not ObjectId.is_valid(project_id) or not ObjectId.is_valid(thread_id):
            return _bad("Invalid projectId" if not ObjectId.is_valid(project_id) else "Invalid threadId")
        messages, threads = _managers(request)
        room = await threads.find_or_create_thread(project_id, thread_id)
        await messages.delete_user_message(user_id, room["_id"], message_id)
        return Response(status_code=204)

    # ================= THREADS ========================================= #
    @app.get("/project/{project_id}/threads")
    async def get_threads(project_id: str, request: Request):
        if not ObjectId.is_valid(project_id):
            return _bad("Invalid projectId")
        messages, threads = _managers(request)
        rooms = await threads.find_all_thread_rooms(project_id)
        msgs = await messages.find_all_messages_in_rooms([r["_id"] for r in rooms])
        return JSONResponse(encode(group_messages_by_threads(rooms, msgs)))

    @app.get("/project/{project_id}/thread/{thread_id}")
    async def get_thread(project_id: str, thread_id: str, request: Request):
        if not ObjectId.is_valid(project_id) or not ObjectId.is_valid(thread_id):
            return _bad("Invalid projectId" if not ObjectId.is_valid(project_id) else "Invalid threadId")
        messages, threads = _managers(request)
        try:
            room = await threads.find_thread(project_id, thread_id)
        except MissingThreadError:
            return Response(status_code=404)
        msgs = await messages.find_all_messages_in_rooms([room["_id"]])
        grouped = group_messages_by_threads([room], msgs)
        thread = grouped.get(str(ObjectId(thread_id)))
        if thread is None:
            return Response(status_code=404)
        return JSONResponse(encode(thread))

    @app.delete("/project/{project_id}/thread/{thread_id}")
    async def delete_thread(project_id: str, thread_id: str, request: Request):
        if not ObjectId.is_valid(project_id) or not ObjectId.is_valid(thread_id):
            return _bad("Invalid projectId" if not ObjectId.is_valid(project_id) else "Invalid threadId")
        messages, threads = _managers(request)
        room_id = await threads.delete_thread(project_id, thread_id)
        await messages.delete_all_messages_in_room(room_id)
        return Response(status_code=204)

    @app.post("/project/{project_id}/thread/{thread_id}/resolve")
    async def resolve_thread(project_id: str, thread_id: str, request: Request):
        body = await _json(request)
        if body.get("user_id") is None:
            return _validation_error()
        if not ObjectId.is_valid(project_id) or not ObjectId.is_valid(thread_id):
            return _bad("Invalid projectId" if not ObjectId.is_valid(project_id) else "Invalid threadId")
        _messages, threads = _managers(request)
        await threads.resolve_thread(project_id, thread_id, body["user_id"])
        return Response(status_code=204)

    @app.post("/project/{project_id}/thread/{thread_id}/reopen")
    async def reopen_thread(project_id: str, thread_id: str, request: Request):
        if not ObjectId.is_valid(project_id) or not ObjectId.is_valid(thread_id):
            return _bad("Invalid projectId" if not ObjectId.is_valid(project_id) else "Invalid threadId")
        _messages, threads = _managers(request)
        await threads.reopen_thread(project_id, thread_id)
        return Response(status_code=204)

    @app.get("/project/{project_id}/resolved-thread-ids")
    async def get_resolved_thread_ids(project_id: str, request: Request):
        if not ObjectId.is_valid(project_id):
            return _bad("Invalid projectId")
        _messages, threads = _managers(request)
        ids = await threads.get_resolved_thread_ids(project_id)
        return JSONResponse({"resolvedThreadIds": ids})

    # ================= PROJECT-LEVEL =================================== #
    @app.delete("/project/{project_id}")
    async def destroy_project(project_id: str, request: Request):
        if not ObjectId.is_valid(project_id):
            return _bad("Invalid projectId")
        messages, threads = _managers(request)
        rooms = await threads.find_all_thread_rooms_and_global(project_id)
        await messages.delete_all_messages_in_rooms([r["_id"] for r in rooms])
        await threads.delete_all_threads_in_project(project_id)
        return Response(status_code=204)

    @app.post("/project/{project_id}/duplicate-comment-threads")
    async def duplicate_comment_threads(project_id: str, request: Request):
        if not ObjectId.is_valid(project_id):
            return _bad("Invalid projectId")
        messages, threads = _managers(request)
        body = await _json(request)
        new_threads: dict = {}
        for old in body.get("threads", []):
            try:
                room = await threads.find_thread(project_id, old)
                new_room = await threads.duplicate_thread(project_id, room)
                await messages.duplicate_room_to_other_room(room["_id"], new_room["_id"])
                new_threads[old] = {"duplicateId": str(new_room["thread_id"])}
            except MissingThreadError:
                new_threads[old] = {"error": "not found"}
            except Exception:
                new_threads[old] = {"error": "unknown"}
        return JSONResponse({"newThreads": new_threads})

    @app.post("/project/{project_id}/generate-thread-data")
    async def generate_thread_data(project_id: str, request: Request):
        if not ObjectId.is_valid(project_id):
            return _bad("Invalid projectId")
        messages, threads = _managers(request)
        body = await _json(request)
        rooms = await threads.find_threads_by_id(project_id, body.get("threads", []))
        msgs = await messages.find_all_messages_in_rooms([r["_id"] for r in rooms])
        return JSONResponse(encode(group_messages_by_threads(rooms, msgs)))

    @app.post("/project/{project_id}/clone-comment-threads")
    async def clone_comment_threads(project_id: str, request: Request):
        if not ObjectId.is_valid(project_id):
            return _bad("Invalid projectId")
        messages, threads = _managers(request)
        body = await _json(request)
        target = body.get("targetProjectId")
        source_rooms = await threads.find_all_thread_rooms(project_id)
        for room in source_rooms:
            new_room = await threads.clone_thread_into_project(room, target)
            await messages.duplicate_room_to_other_room(room["_id"], new_room["_id"])
        return Response(status_code=204)

    return app


app = build_app()
