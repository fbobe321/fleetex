"""HTTP layer for the notifications service — port of ``NotificationsController``
and the route table in ``app.ts``.

Status-code contract (from the Node error handler):
* bad ObjectId in a path param        -> 404  (InvalidParamsError)
* missing/invalid required body field -> 400  (InvalidRequestError)
* handler raised                      -> 500
"""

from __future__ import annotations

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fleetex_service_kit import Settings, create_app

from .manager import NotificationsManager
from .serialize import serialize_notification


def _object_id(value: str) -> ObjectId:
    """Parse a 24-hex ObjectId or raise 404, matching Overleaf's zz.objectId()."""
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=404)


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400)
    if not isinstance(body, dict):
        raise HTTPException(status_code=400)
    return body


def _manager(request: Request) -> NotificationsManager:
    return NotificationsManager(request.app.state.db)


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env("notifications", default_port=3042)
    # No Redis: notifications is Mongo-only.
    app = create_app(
        settings,
        connect_redis=False,
        status_text="notifications is up",
    )

    @app.post("/user/{user_id}")
    async def add_notification(user_id: str, request: Request) -> Response:
        uid = _object_id(user_id)
        body = await _json_body(request)
        try:
            await _manager(request).add_notification(uid, body)
        except Exception:
            return Response(status_code=500)
        return Response(status_code=200)

    @app.get("/user/{user_id}")
    async def get_notifications(user_id: str, request: Request) -> JSONResponse:
        uid = _object_id(user_id)
        docs = await _manager(request).get_user_notifications(uid)
        return JSONResponse([serialize_notification(d) for d in docs])

    @app.delete("/user/{user_id}/notification/{notification_id}")
    async def remove_by_id(
        user_id: str, notification_id: str, request: Request
    ) -> Response:
        uid = _object_id(user_id)
        nid = _object_id(notification_id)
        await _manager(request).remove_notification_id(uid, nid)
        return Response(status_code=200)

    @app.delete("/user/{user_id}")
    async def remove_by_key(user_id: str, request: Request) -> Response:
        uid = _object_id(user_id)
        body = await _json_body(request)
        key = body.get("key")
        if not isinstance(key, str):
            raise HTTPException(status_code=400)
        await _manager(request).remove_notification_key(uid, key)
        return Response(status_code=200)

    @app.delete("/key/{key}")
    async def remove_by_key_all_users(key: str, request: Request) -> Response:
        await _manager(request).remove_notification_by_key_only(key)
        return Response(status_code=200)

    @app.get("/key/{key}/count")
    async def count_by_key(key: str, request: Request) -> JSONResponse:
        try:
            count = await _manager(request).count_notifications_by_key_only(key)
        except Exception:
            return Response(status_code=500)
        return JSONResponse({"count": count})

    @app.delete("/key/{key}/bulk")
    async def delete_bulk_by_key(key: str, request: Request) -> JSONResponse:
        try:
            count = await _manager(request).delete_unread_by_key_only_bulk(key)
        except Exception:
            return Response(status_code=500)
        return JSONResponse({"count": count})

    @app.get("/health_check")
    async def health_check(request: Request) -> Response:
        # Round-trip: create for a random user, read it back, then clean up.
        mgr = _manager(request)
        uid = ObjectId()
        try:
            await mgr.add_notification(
                uid,
                {"key": "health-check", "templateKey": "health-check", "messageOpts": {}},
            )
            found = await mgr.get_user_notifications(uid)
            if not any(n.get("key") == "health-check" for n in found):
                return Response(status_code=500)
            await mgr.remove_notification_key(uid, "health-check")
            await mgr.delete_unread_by_key_only_bulk("health-check")
        except Exception:
            return Response(status_code=500)
        return Response(status_code=200)

    # Any other GET -> 404 with empty body (Node: sendStatus(404)). Registered
    # last so the specific routes above win.
    @app.get("/{_path:path}")
    async def not_found(_path: str) -> Response:
        return Response(status_code=404)

    return app


app = build_app()
