"""HTTP layer — port of HttpController.js (the routes web/real-time call)."""

from __future__ import annotations

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fleetex_service_kit import Settings, create_app
from redis import asyncio as aioredis

from .config import DocUpdaterConfig
from .errors import DocUpdaterError, OpRangeNotAvailableError
from .history_client import HistoryClient
from .persistence import PersistenceManager
from .redis_manager import DOC_OPS_TTL, RedisManager
from .update_manager import AppliedOpsPublisher, DocumentUpdater


def build_app(config: DocUpdaterConfig | None = None, *, redis=None, persistence=None, history=None, with_workers: bool = False) -> FastAPI:
    config = config or DocUpdaterConfig.from_env()

    async def _start_workers(app):
        from .dispatch import start_dispatchers

        # Dedicated connection pool for the blocking BLPOP loops, so they never
        # contend with the request/publish redis operations.
        blocking_redis = aioredis.from_url(config.redis_url, decode_responses=True, socket_timeout=None)
        app.state.dispatchers = start_dispatchers(blocking_redis, app.state.updater, config.dispatcher_count)

    settings = Settings.from_env("document-updater", default_port=config.port, env={})
    app = create_app(
        settings, connect_mongo=False, connect_redis=False,
        status_text="document-updater is alive",
        on_startup=[_start_workers] if with_workers else None,
    )

    redis = redis if redis is not None else aioredis.from_url(config.redis_url, decode_responses=True)
    persistence = persistence or PersistenceManager(config.docstore_url)
    rm = RedisManager(redis)
    updater = DocumentUpdater(rm, persistence, AppliedOpsPublisher(redis), config.max_age_of_op)
    if history is None and config.project_history_url:
        history = HistoryClient(config.project_history_url)
    app.state.config = config
    app.state.redis = redis
    app.state.rm = rm
    app.state.updater = updater
    app.state.history = history

    async def _snapshot_history(project_id, doc_id, doc) -> None:
        if history is not None and doc is not None:
            await history.snapshot(project_id, doc_id, doc["lines"], doc.get("pathname", ""))

    @app.get("/project/{project_id}/doc/{doc_id}")
    async def get_doc(project_id: str, doc_id: str, request: Request):
        from_version = int(request.query_params.get("fromVersion", -1))
        try:
            doc = await updater.get_doc(project_id, doc_id)
        except DocUpdaterError:
            return Response(status_code=404)
        ops = []
        if from_version != -1:
            try:
                ops = await rm.get_previous_doc_ops(doc_id, from_version, doc["version"])
            except OpRangeNotAvailableError:
                return JSONResponse({"firstVersionInRedis": None}, status_code=422)
        return JSONResponse({
            "id": doc_id,
            "lines": doc["lines"],
            "version": doc["version"],
            "ops": ops,
            "ranges": doc.get("ranges") or {},
            "pathname": doc.get("pathname", ""),
            "ttlInS": DOC_OPS_TTL,
            "type": "sharejs-text-ot",
        })

    @app.post("/project/{project_id}/doc/{doc_id}")
    async def set_doc(project_id: str, doc_id: str, request: Request):
        body = await request.json()
        lines = body.get("lines")
        if not isinstance(lines, list):
            return Response(status_code=400)
        await updater.set_doc(project_id, doc_id, lines, body.get("ranges"))
        return Response(status_code=204)

    @app.post("/project/{project_id}/doc/{doc_id}/flush")
    async def flush_doc(project_id: str, doc_id: str):
        doc = await rm.get_doc(project_id, doc_id)
        if doc is not None:
            await persistence.set_doc(project_id, doc_id, doc["lines"], doc["version"], doc.get("ranges") or {})
            await _snapshot_history(project_id, doc_id, doc)
        return Response(status_code=204)

    @app.delete("/project/{project_id}/doc/{doc_id}")
    async def delete_doc(project_id: str, doc_id: str):
        doc = await rm.get_doc(project_id, doc_id)
        await _snapshot_history(project_id, doc_id, doc)
        await updater.flush_and_delete_doc(project_id, doc_id)
        return Response(status_code=204)

    @app.delete("/project/{project_id}")
    async def delete_project(project_id: str):
        await updater.flush_and_delete_project(project_id)
        return Response(status_code=204)

    @app.get("/health_check")
    async def health_check():
        return Response(status_code=200)

    return app


app = build_app()
