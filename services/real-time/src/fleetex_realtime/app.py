"""HTTP layer + socket.io wiring.

``build_app`` returns the FastAPI (HTTP routes + a wired socket.io server on
``app.state``). ``build_asgi`` wraps it with the socket.io ASGI app for uvicorn.

NOTE: the socket.io *protocol* here is python-socketio (EIO3/4), which is NOT
wire-compatible with Overleaf's frontend socket.io-client v0.9. See README.
"""

from __future__ import annotations

from urllib.parse import parse_qs

import socketio
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fleetex_service_kit import Settings, create_app
from redis import asyncio as aioredis

from .config import RealtimeConfig
from .connected_users import ConnectedUsersManager
from .document_updater import DocumentUpdaterManager
from .redis_bridge import EDITOR_EVENTS_CHANNEL, build_editor_event
from .server import RealtimeServer
from .web_api import WebApiManager


def _parse_join_doc_args(args: tuple):
    doc_id = args[0]
    from_version, options = -1, {}
    for a in args[1:]:
        if isinstance(a, bool):
            continue
        if isinstance(a, (int, float)):
            from_version = int(a)
        elif isinstance(a, dict):
            options = a
    return doc_id, from_version, options


def _register_sio_handlers(sio: socketio.AsyncServer, server: RealtimeServer) -> None:
    @sio.event
    async def connect(sid, environ, auth):
        qs = parse_qs(environ.get("QUERY_STRING", ""))
        project_id = qs.get("projectId", [None])[0]
        if not project_id:
            await sio.emit("connectionRejected", {"message": "missing ?projectId query flag on handshake"}, to=sid)
            return False
        auth = auth or {}
        return await server.connect(sid, project_id, auth.get("user_id", "anonymous-user"), auth.get("anonymousAccessToken"))

    @sio.on("joinDoc")
    async def join_doc(sid, *args):
        doc_id, from_version, options = _parse_join_doc_args(args)
        return await server.join_doc(sid, doc_id, from_version, options)

    @sio.on("leaveDoc")
    async def leave_doc(sid, doc_id):
        return await server.leave_doc(sid, doc_id)

    @sio.on("applyOtUpdate")
    async def apply_ot_update(sid, doc_id, update):
        return await server.apply_ot_update(sid, doc_id, update)

    @sio.on("clientTracking.updatePosition")
    async def update_position(sid, cursor):
        return await server.update_position(sid, cursor)

    @sio.on("clientTracking.getConnectedUsers")
    async def get_connected_users(sid):
        return await server.get_connected_users(sid)

    @sio.event
    async def disconnect(sid):
        await server.on_disconnect(sid)


def build_app(config: RealtimeConfig | None = None, *, redis=None, web_api=None, du=None) -> FastAPI:
    config = config or RealtimeConfig.from_env()
    settings = Settings.from_env("real-time", default_port=config.port, env={})
    app = create_app(settings, connect_mongo=False, connect_redis=False, status_text="real-time is alive")

    redis = redis if redis is not None else aioredis.from_url(config.redis_url, decode_responses=True)
    web_api = web_api or WebApiManager(config.web_url, config.web_api_user, config.web_api_password)
    du = du or DocumentUpdaterManager(redis, config.document_updater_url, shard_count=config.pending_update_list_shard_count)
    connected = ConnectedUsersManager(redis)

    sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

    async def _emit(event, data, sid):
        await sio.emit(event, data, to=sid)

    async def _disconnect(sid):
        await sio.disconnect(sid)

    server = RealtimeServer(emit=_emit, disconnect=_disconnect, web_api=web_api, du=du, connected_users=connected)
    _register_sio_handlers(sio, server)

    app.state.config = config
    app.state.redis = redis
    app.state.connected = connected
    app.state.server = server
    app.state.sio = sio

    # ---- HTTP routes ---------------------------------------------------- #
    @app.get("/", response_class=PlainTextResponse)
    async def root():
        return "real-time is open"

    @app.get("/health_check")
    async def health_check():
        return Response(status_code=200)

    @app.get("/clients")
    async def clients():
        return JSONResponse([
            {
                "client_id": ctx.sid,
                "project_id": ctx.project_id,
                "user_id": ctx.user_id,
                "first_name": ctx.first_name,
                "last_name": ctx.last_name,
                "email": ctx.email,
                "rooms": [room for room, members in server.rooms.items() if ctx.sid in members],
            }
            for ctx in server.sessions.values()
        ])

    @app.get("/project/{project_id}/count-connected-clients")
    async def count_connected_clients(project_id: str):
        return JSONResponse({"nConnectedClients": await connected.count_connected_clients(project_id)})

    @app.post("/project/{project_id}/message/{message}")
    async def send_message(project_id: str, message: str, request: Request):
        try:
            body = await request.json()
        except Exception:
            body = None
        elements = body if isinstance(body, list) else [body]
        for element in elements:
            await redis.publish(EDITOR_EVENTS_CHANNEL, build_editor_event(project_id, message, [element]))
        return Response(status_code=204)

    @app.post("/drain")
    async def drain():
        return Response(status_code=204)

    @app.post("/client/{client_id}/disconnect")
    async def disconnect_client(client_id: str):
        if client_id in server.sessions:
            await server.on_disconnect(client_id)
            return Response(status_code=204)
        return Response(status_code=404)

    return app


def build_asgi(config: RealtimeConfig | None = None):
    app = build_app(config)
    return socketio.ASGIApp(app.state.sio, other_asgi_app=app, socketio_path="socket.io")
