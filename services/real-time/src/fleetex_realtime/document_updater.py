"""DocumentUpdaterManager — port of DocumentUpdaterManager.js.

document-updater stays Node at this phase, so we bridge to it:
* fetch a doc over HTTP,
* flush/delete a project over HTTP,
* queue an update by RPUSHing to Redis lists (the exact key shapes it consumes).
"""

from __future__ import annotations

import json
import random

import httpx

from .errors import (
    ClientRequestedMissingOpsError,
    DocumentUpdaterRequestFailedError,
    NullBytesInOpError,
    UpdateTooLargeError,
)

_ALLOWED_UPDATE_KEYS = ("doc", "op", "v", "dupIfSource", "meta", "lastV", "hash")


def pending_updates_key(doc_id: str) -> str:
    # Literal braces = Redis cluster hash-tag (RedisManager.pendingUpdates).
    return f"PendingUpdates:{{{doc_id}}}"


class DocumentUpdaterManager:
    def __init__(self, redis, base_url: str, http: httpx.AsyncClient | None = None, shard_count: int = 10) -> None:
        self.redis = redis
        self.base_url = base_url.rstrip("/")
        self.http = http or httpx.AsyncClient()
        self.shard_count = shard_count

    async def get_document(self, project_id, doc_id, from_version: int = -1) -> dict:
        url = f"{self.base_url}/project/{project_id}/doc/{doc_id}"
        resp = await self.http.get(url, params={"fromVersion": from_version, "historyOTSupport": "true"})
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 422:
            body = _safe_json(resp)
            raise ClientRequestedMissingOpsError(422, body.get("firstVersionInRedis") if body else None)
        if resp.status_code == 404:
            raise ClientRequestedMissingOpsError(404)
        raise DocumentUpdaterRequestFailedError("getDocument", resp.status_code)

    async def flush_project(self, project_id, shutdown: bool = False) -> None:
        url = f"{self.base_url}/project/{project_id}"
        params = {"background": "true"}
        if shutdown:
            params["shutdown"] = "true"
        await self.http.delete(url, params=params)

    def _pending_update_list_key(self) -> str:
        shard = random.randint(0, self.shard_count - 1)
        return "pending-updates-list" if shard == 0 else f"pending-updates-list-{shard}"

    async def queue_change(self, project_id, doc_id, change: dict, max_update_size: int) -> None:
        allowed = {k: change[k] for k in _ALLOWED_UPDATE_KEYS if k in change}
        blob = json.dumps(allowed)
        if "\x00" in blob:
            raise NullBytesInOpError()
        if len(blob.encode("utf-8")) > max_update_size:
            raise UpdateTooLargeError(len(blob))
        # Order matters: push the change onto the per-doc list first...
        await self.redis.rpush(pending_updates_key(doc_id), blob)
        # ...then notify a dispatcher shard.
        await self.redis.rpush(self._pending_update_list_key(), f"{project_id}:{doc_id}")


def _safe_json(resp: httpx.Response):
    try:
        return resp.json()
    except (json.JSONDecodeError, ValueError):
        return None
