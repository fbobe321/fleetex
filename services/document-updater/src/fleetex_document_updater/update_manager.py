"""DocumentUpdater — ties Redis + engine + persistence + applied-ops publish.

Flow (port of UpdateManager/ShareJsUpdateManager): fetch pending updates a doc,
apply each via the engine (transform + apply), commit to Redis, and publish the
applied op to the ``applied-ops`` channel that the real-time service consumes.
"""

from __future__ import annotations

import json

from . import engine, ranges
from .errors import DocUpdaterError
from .persistence import PersistenceManager
from .redis_manager import RedisManager

APPLIED_OPS_CHANNEL = "applied-ops"


class AppliedOpsPublisher:
    def __init__(self, redis) -> None:
        self.redis = redis
        self._seq = 0

    async def publish_op(self, project_id, doc_id, applied_update) -> None:
        self._seq += 1
        blob = json.dumps({"project_id": str(project_id), "doc_id": str(doc_id), "op": applied_update, "_id": f"doc:{self._seq}"})
        await self.redis.publish(APPLIED_OPS_CHANNEL, blob)

    async def publish_error(self, project_id, doc_id, message) -> None:
        self._seq += 1
        blob = json.dumps({"project_id": str(project_id), "doc_id": str(doc_id), "error": message, "_id": f"doc:{self._seq}"})
        await self.redis.publish(APPLIED_OPS_CHANNEL, blob)


class DocumentUpdater:
    def __init__(self, rm: RedisManager, persistence: PersistenceManager, publisher: AppliedOpsPublisher, max_age: int = 80) -> None:
        self.rm = rm
        self.persistence = persistence
        self.publisher = publisher
        self.max_age = max_age

    async def get_doc(self, project_id, doc_id) -> dict:
        """Redis-first; on miss, load from docstore and populate Redis."""
        doc = await self.rm.get_doc(project_id, doc_id)
        if doc is not None:
            return doc
        loaded = await self.persistence.get_doc(project_id, doc_id)
        if loaded is None:
            raise DocUpdaterError(f"doc {doc_id} not found")
        await self.rm.put_doc_in_memory(
            project_id, doc_id, loaded["lines"], loaded["version"], loaded["ranges"], loaded["pathname"]
        )
        return loaded

    async def apply_update(self, project_id, doc_id, update) -> dict:
        doc = await self.get_doc(project_id, doc_id)
        previous_ops = await self.rm.get_previous_doc_ops(doc_id, update["v"], doc["version"])
        try:
            new_lines, new_version, applied = engine.process_update(
                doc["lines"], doc["version"], previous_ops, update, self.max_age
            )
        except DocUpdaterError:
            raise
        except Exception as exc:  # OTError etc.
            await self.publisher.publish_error(project_id, doc_id, str(exc))
            raise

        if applied.get("dup"):
            await self.publisher.publish_op(project_id, doc_id, applied)
            return applied

        new_ranges = ranges.apply_op_to_ranges(doc.get("ranges"), applied["op"])
        await self.rm.update_document(project_id, doc_id, new_lines, new_version, [applied], new_ranges, update.get("meta"))
        await self.publisher.publish_op(project_id, doc_id, applied)
        return applied

    async def process_pending(self, project_id, doc_id) -> list[dict]:
        applied = []
        updates = await self.rm.get_pending_updates(doc_id)
        for update in updates:
            applied.append(await self.apply_update(project_id, doc_id, update))
        return applied

    async def set_doc(self, project_id, doc_id, lines, ranges_val=None) -> None:
        """Overwrite the doc (HTTP setDoc). Simplified: replace Redis snapshot."""
        current = await self.rm.get_doc(project_id, doc_id)
        version = (current or {}).get("version", 0)
        await self.rm.put_doc_in_memory(project_id, doc_id, lines, version, ranges_val or {}, (current or {}).get("pathname", ""))

    async def flush_and_delete_doc(self, project_id, doc_id) -> None:
        doc = await self.rm.get_doc(project_id, doc_id)
        if doc is not None:
            await self.persistence.set_doc(project_id, doc_id, doc["lines"], doc["version"], doc.get("ranges") or {})
        await self.rm.remove_doc_from_memory(project_id, doc_id)

    async def flush_and_delete_project(self, project_id) -> None:
        for doc_id in await self.rm.get_docs_in_project(project_id):
            await self.flush_and_delete_doc(project_id, doc_id)
