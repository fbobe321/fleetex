"""FastAPI application factory shared by every Fleetex Python service.

Provides:
* a lifespan that connects/disconnects Mongo and Redis (opt-out for pure tests),
* ``/health`` (JSON) and ``/status`` (plain text) endpoints matching what the
  Overleaf stack and its healthchecks expect.

A service builds on this::

    settings = Settings.from_env("notifications", default_port=3042)
    app = create_app(settings)

    @app.get("/user/{user_id}/notifications")
    async def list_notifications(user_id: str):
        db = app.state.db
        ...
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from .config import Settings
from .db import create_mongo_client, create_redis, get_database
from .logging import configure_logging


def create_app(
    settings: Settings,
    *,
    connect_mongo: bool = True,
    connect_redis: bool = True,
    status_text: str | None = None,
    on_startup: list | None = None,
) -> FastAPI:
    """``on_startup`` is a list of async callables ``fn(app)`` run during lifespan
    startup — use it to launch background workers (dispatchers, pub/sub subscribers).
    NOTE: FastAPI ignores ``@app.on_event`` when a lifespan is set, so background
    tasks MUST be registered here. (Not triggered by httpx ASGITransport in tests.)
    """
    logger = configure_logging(settings.service_name, settings.log_level)
    on_startup = on_startup or []

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if connect_mongo:
            app.state.mongo = create_mongo_client(settings.mongo_url)
            app.state.db = get_database(app.state.mongo, settings.mongo_url)
        if connect_redis:
            app.state.redis = create_redis(settings.redis_url)
        for callback in on_startup:
            await callback(app)
        logger.info("service started", extra={"port": settings.port})
        try:
            yield
        finally:
            if connect_mongo:
                app.state.mongo.close()
            if connect_redis:
                await app.state.redis.aclose()
            logger.info("service stopped")

    app = FastAPI(title=f"fleetex-{settings.service_name}", lifespan=lifespan)
    app.state.settings = settings

    @app.get("/health", include_in_schema=False)
    async def health() -> dict:
        return {"status": "ok", "service": settings.service_name}

    # Each ported service can match its Node original's exact /status body.
    _status_body = status_text or f"{settings.service_name} is alive (fleetex)\n"

    @app.get("/status", include_in_schema=False, response_class=PlainTextResponse)
    async def status() -> str:
        return _status_body

    return app
