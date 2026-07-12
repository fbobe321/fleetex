"""Mongo data layer — port of MongoManager.js. Single collection: ``docs``.

Concurrency note: the Node original issues its rev-bump as an aggregation
pipeline with ``$literal`` wrapping (to stop Mongo interpreting ``$``-prefixed
line/range values). A plain ``update_one`` with a ``$set`` **dict** already stores
values literally and gives the identical optimistic lock (``{rev: previousRev}``
filter + ``rev = previousRev + 1``), so we use that — same observable behavior.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from .constants import ARCHIVING_LOCK_DURATION_MS, MAX_DELETED_DOCS
from .errors import DocRevValueError


def oid(value: Any) -> ObjectId:
    return value if isinstance(value, ObjectId) else ObjectId(value)


class MongoManager:
    def __init__(self, db) -> None:
        self.docs = db["docs"]

    async def find_doc(self, project_id, doc_id, projection: dict) -> dict | None:
        doc = await self.docs.find_one({"_id": oid(doc_id), "project_id": oid(project_id)}, projection)
        if doc is not None and "version" in projection and doc.get("version") is None:
            doc["version"] = 0
        return doc

    async def get_projects_docs(self, project_id, include_deleted: bool, projection: dict) -> list[dict]:
        query: dict = {"project_id": oid(project_id)}
        if not include_deleted:
            query["deleted"] = {"$ne": True}
        return await self.docs.find(query, projection).to_list(length=None)

    async def get_projects_deleted_docs(self, project_id, projection: dict) -> list[dict]:
        cursor = (
            self.docs.find({"project_id": oid(project_id), "deleted": True}, projection)
            .sort("deletedAt", -1)
            .limit(MAX_DELETED_DOCS)
        )
        return await cursor.to_list(length=None)

    async def get_non_archived_project_doc_ids(self, project_id) -> list[ObjectId]:
        cursor = self.docs.find(
            {"project_id": oid(project_id), "inS3": {"$ne": True}}, {"_id": 1}
        )
        return [d["_id"] for d in await cursor.to_list(length=None)]

    async def get_archived_project_docs(self, project_id, include_deleted: bool) -> list[ObjectId]:
        query: dict = {"project_id": oid(project_id), "inS3": True}
        if not include_deleted:
            query["deleted"] = {"$ne": True}
        cursor = self.docs.find(query, {"_id": 1})
        return [d["_id"] for d in await cursor.to_list(length=None)]

    async def get_all_doc_versions(self, project_id) -> list[dict]:
        return await self.get_projects_docs(project_id, False, {"_id": 1, "version": 1})

    async def upsert_into_doc_collection(self, project_id, doc_id, updates: dict, previous_rev: int | None) -> int:
        """Insert (previous_rev None) or optimistically update. Returns the new rev.

        rev increments only when ``lines`` or ``ranges`` are part of ``updates``.
        """
        if previous_rev is not None:
            set_doc = dict(updates)
            if "lines" in updates or "ranges" in updates:
                set_doc["rev"] = previous_rev + 1
            result = await self.docs.update_one(
                {"_id": oid(doc_id), "project_id": oid(project_id), "rev": previous_rev},
                {"$set": set_doc, "$unset": {"inS3": ""}},
            )
            if result.matched_count != 1:
                raise DocRevValueError("doc rev changed under us")
            return set_doc.get("rev", previous_rev)
        doc = {"_id": oid(doc_id), "project_id": oid(project_id), "rev": 1, **updates}
        try:
            await self.docs.insert_one(doc)
        except DuplicateKeyError:
            raise DocRevValueError("doc already exists")
        return 1

    async def patch_doc(self, project_id, doc_id, meta: dict) -> int:
        result = await self.docs.update_one(
            {"_id": oid(doc_id), "project_id": oid(project_id)}, {"$set": meta}
        )
        return result.matched_count

    async def get_doc_for_archiving(self, project_id, doc_id) -> dict | None:
        now = datetime.now(timezone.utc)
        until = now + timedelta(milliseconds=ARCHIVING_LOCK_DURATION_MS)
        return await self.docs.find_one_and_update(
            {
                "_id": oid(doc_id),
                "project_id": oid(project_id),
                "inS3": {"$ne": True},
                "$or": [{"archivingUntil": None}, {"archivingUntil": {"$lt": now}}],
            },
            {"$set": {"archivingUntil": until}},
            projection={"lines": 1, "ranges": 1, "rev": 1},
        )

    async def mark_doc_as_archived(self, doc_id, rev: int) -> None:
        await self.docs.update_one(
            {"_id": oid(doc_id), "rev": rev},
            {"$set": {"inS3": True}, "$unset": {"lines": 1, "ranges": 1, "archivingUntil": 1}},
        )

    async def restore_archived_doc(self, project_id, doc_id, archived: dict) -> None:
        result = await self.docs.update_one(
            {"_id": oid(doc_id), "project_id": oid(project_id), "rev": archived["rev"]},
            {"$set": {"lines": archived["lines"], "ranges": archived.get("ranges") or {}}, "$unset": {"inS3": ""}},
        )
        if result.matched_count != 1:
            raise DocRevValueError("archived doc rev mismatch on restore")

    async def destroy_project(self, project_id) -> None:
        await self.docs.delete_many({"project_id": oid(project_id)})
