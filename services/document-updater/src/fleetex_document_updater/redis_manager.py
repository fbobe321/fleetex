"""RedisManager — the live doc working-set in Redis (port of RedisManager.js).

Key formats match the Node original so this service interoperates with the
ported real-time service (which RPUSHes to PendingUpdates:{docId} and consumes
applied-ops). Doc lines are a JSON array; version is an absolute int advanced by
the number of applied ops; DocOps is the applied-op history buffer used for
transform catch-up.
"""

from __future__ import annotations

import hashlib
import json
import time

from .errors import OpRangeNotAvailableError, VersionMismatchError

DOC_OPS_MAX_LENGTH = 100
DOC_OPS_TTL = 60 * 60
MAX_OPS_PER_ITERATION = 8


def _doclines(doc_id):
    return f"doclines:{{{doc_id}}}"


def _version(doc_id):
    return f"DocVersion:{{{doc_id}}}"


def _hash(doc_id):
    return f"DocHash:{{{doc_id}}}"


def _project_id(doc_id):
    return f"ProjectId:{{{doc_id}}}"


def _docs_in(project_id):
    return f"DocsIn:{{{project_id}}}"


def _ranges(doc_id):
    return f"Ranges:{{{doc_id}}}"


def _pathname(doc_id):
    return f"Pathname:{{{doc_id}}}"


def _doc_ops(doc_id):
    return f"DocOps:{{{doc_id}}}"


def _pending_updates(doc_id):
    return f"PendingUpdates:{{{doc_id}}}"


def _unflushed(doc_id):
    return f"UnflushedTime:{{{doc_id}}}"


def _compute_hash(lines: list) -> str:
    return hashlib.sha1(json.dumps(lines).encode("utf-8")).hexdigest()


class RedisManager:
    def __init__(self, redis) -> None:
        self.redis = redis  # decode_responses=True

    async def put_doc_in_memory(self, project_id, doc_id, lines, version, ranges, pathname) -> None:
        await self.redis.sadd(_docs_in(project_id), doc_id)
        mapping = {
            _doclines(doc_id): json.dumps(lines),
            _project_id(doc_id): str(project_id),
            _version(doc_id): str(version),
            _hash(doc_id): _compute_hash(lines),
            _ranges(doc_id): json.dumps(ranges) if ranges else "",
            _pathname(doc_id): pathname or "",
        }
        await self.redis.mset(mapping)

    async def has_doc(self, doc_id) -> bool:
        return await self.redis.exists(_doclines(doc_id)) == 1

    async def get_doc(self, project_id, doc_id) -> dict | None:
        raw = await self.redis.get(_doclines(doc_id))
        if raw is None:
            return None
        lines = json.loads(raw)
        version = int(await self.redis.get(_version(doc_id)) or 0)
        ranges_raw = await self.redis.get(_ranges(doc_id))
        ranges = json.loads(ranges_raw) if ranges_raw else {}
        pathname = await self.redis.get(_pathname(doc_id)) or ""
        return {"lines": lines, "version": version, "ranges": ranges, "pathname": pathname}

    async def get_doc_version(self, doc_id) -> int:
        return int(await self.redis.get(_version(doc_id)) or 0)

    async def get_previous_doc_ops(self, doc_id, start: int, end: int) -> list[dict]:
        length = await self.redis.llen(_doc_ops(doc_id))
        version = await self.get_doc_version(doc_id)
        first = version - length
        if start < first or end > version:
            raise OpRangeNotAvailableError(f"ops [{start},{end}) not available (redis has [{first},{version}))")
        if start >= end:
            return []
        raw = await self.redis.lrange(_doc_ops(doc_id), start - first, end - first - 1)
        return [json.loads(o) for o in raw]

    async def update_document(self, project_id, doc_id, lines, new_version, applied_ops, ranges, meta) -> None:
        current = await self.get_doc_version(doc_id)
        if current + len(applied_ops) != new_version:
            raise VersionMismatchError(f"version mismatch: {current} + {len(applied_ops)} != {new_version}")
        mapping = {
            _doclines(doc_id): json.dumps(lines),
            _version(doc_id): str(new_version),
            _hash(doc_id): _compute_hash(lines),
            _ranges(doc_id): json.dumps(ranges) if ranges else "",
            f"lastUpdatedAt:{{{doc_id}}}": str(int(time.time() * 1000)),
        }
        if meta and meta.get("user_id"):
            mapping[f"lastUpdatedBy:{{{doc_id}}}"] = str(meta["user_id"])
        await self.redis.mset(mapping)
        for op in applied_ops:
            await self.redis.rpush(_doc_ops(doc_id), json.dumps(op))
        await self.redis.ltrim(_doc_ops(doc_id), -DOC_OPS_MAX_LENGTH, -1)
        await self.redis.expire(_doc_ops(doc_id), DOC_OPS_TTL)
        await self.redis.set(_unflushed(doc_id), str(int(time.time() * 1000)), nx=True)

    async def get_pending_updates(self, doc_id) -> list[dict]:
        raw = await self.redis.lrange(_pending_updates(doc_id), 0, MAX_OPS_PER_ITERATION - 1)
        await self.redis.ltrim(_pending_updates(doc_id), MAX_OPS_PER_ITERATION, -1)
        return [json.loads(u) for u in raw]

    async def get_updates_length(self, doc_id) -> int:
        return await self.redis.llen(_pending_updates(doc_id))

    async def remove_doc_from_memory(self, project_id, doc_id) -> None:
        keys = [_doclines(doc_id), _version(doc_id), _hash(doc_id), _project_id(doc_id),
                _ranges(doc_id), _pathname(doc_id), _doc_ops(doc_id), _unflushed(doc_id)]
        await self.redis.delete(*keys)
        await self.redis.srem(_docs_in(project_id), doc_id)

    async def get_docs_in_project(self, project_id) -> list[str]:
        return list(await self.redis.smembers(_docs_in(project_id)))
