"""ConnectedUsersManager — port of ConnectedUsersManager.js (Redis 'realtime' instance).

Keys (settings.defaults):
* ``clients_in_project:{<pid>}``            SET of client (public) ids,   TTL 4 days
* ``connected_user:{<pid>}:<clientId>``     HASH of user fields+cursor,    TTL 15 min

``get_connected_users`` returns only clients whose ``client_age < REFRESH_TIMEOUT``
(10s) — i.e. those that answered the last ``clientTracking.refresh``.
"""

from __future__ import annotations

import json
import time

FOUR_DAYS_IN_S = 4 * 24 * 60 * 60
USER_TIMEOUT_IN_S = 15 * 60
REFRESH_TIMEOUT_IN_S = 10


def _project_set_key(project_id: str) -> str:
    return f"clients_in_project:{{{project_id}}}"


def _user_key(project_id: str, client_id: str) -> str:
    return f"connected_user:{{{project_id}}}:{client_id}"


def _now_ms() -> int:
    return int(time.time() * 1000)


class ConnectedUsersManager:
    def __init__(self, redis) -> None:
        self.redis = redis  # redis.asyncio client, decode_responses=True

    async def update_user_position(self, project_id, client_id, user: dict, cursor: dict | None = None) -> None:
        set_key = _project_set_key(project_id)
        user_key = _user_key(project_id, client_id)
        await self.redis.sadd(set_key, client_id)
        await self.redis.expire(set_key, FOUR_DAYS_IN_S)
        fields = {
            "last_updated_at": str(_now_ms()),
            "user_id": user.get("user_id", ""),
            "first_name": user.get("first_name", ""),
            "last_name": user.get("last_name", ""),
            "email": user.get("email", ""),
        }
        if cursor is not None:
            fields["cursorData"] = json.dumps(cursor)
        await self.redis.hset(user_key, mapping=fields)
        await self.redis.expire(user_key, USER_TIMEOUT_IN_S)

    async def refresh_client(self, project_id, client_id) -> None:
        user_key = _user_key(project_id, client_id)
        await self.redis.hset(user_key, "last_updated_at", str(_now_ms()))
        await self.redis.expire(user_key, USER_TIMEOUT_IN_S)

    async def mark_user_as_disconnected(self, project_id, client_id) -> None:
        await self.redis.srem(_project_set_key(project_id), client_id)
        await self.redis.delete(_user_key(project_id, client_id))

    async def count_connected_clients(self, project_id) -> int:
        return await self.redis.scard(_project_set_key(project_id))

    async def _get_connected_user(self, project_id, client_id) -> dict | None:
        fields = await self.redis.hgetall(_user_key(project_id, client_id))
        if not fields:
            return {"connected": False, "client_id": client_id}
        last = int(fields.get("last_updated_at", "0"))
        cursor = json.loads(fields["cursorData"]) if fields.get("cursorData") else None
        return {
            "connected": True,
            "client_id": client_id,
            "client_age": (_now_ms() - last) / 1000,
            "user_id": fields.get("user_id"),
            "first_name": fields.get("first_name"),
            "last_name": fields.get("last_name"),
            "email": fields.get("email"),
            "cursorData": cursor,
        }

    async def get_connected_users(self, project_id) -> list[dict]:
        client_ids = await self.redis.smembers(_project_set_key(project_id))
        users = []
        for client_id in client_ids:
            user = await self._get_connected_user(project_id, client_id)
            if user and user.get("connected") and user["client_age"] < REFRESH_TIMEOUT_IN_S:
                users.append(user)
        return users
