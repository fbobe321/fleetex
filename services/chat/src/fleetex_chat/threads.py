"""Thread/room data layer — port of ``app/js/Features/Threads/ThreadManager.js``.

A *room* is a *thread*. The global room has no ``thread_id`` field; that absence
is how "global" is distinguished. ``resolved`` is ``{user_id: <raw str>, ts: Date}``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument

from .constants import GLOBAL_THREAD
from .errors import MissingThreadError
from .messages import oid


def _thread_filter(project_id: ObjectId, thread_id) -> dict:
    if thread_id == GLOBAL_THREAD:
        return {"project_id": project_id, "thread_id": {"$exists": False}}
    return {"project_id": project_id, "thread_id": oid(thread_id)}


class ThreadManager:
    def __init__(self, db) -> None:
        self.collection = db["rooms"]

    async def find_or_create_thread(self, project_id, thread_id) -> dict:
        pid = oid(project_id)
        if thread_id == GLOBAL_THREAD:
            query = {"project_id": pid, "thread_id": {"$exists": False}}
            update = {"$set": {"project_id": pid}}
        else:
            tid = oid(thread_id)
            query = {"project_id": pid, "thread_id": tid}
            update = {"$set": {"project_id": pid, "thread_id": tid}}
        return await self.collection.find_one_and_update(
            query, update, upsert=True, return_document=ReturnDocument.AFTER
        )

    async def find_thread(self, project_id, thread_id) -> dict:
        doc = await self.collection.find_one(_thread_filter(oid(project_id), thread_id))
        if doc is None:
            raise MissingThreadError()
        return doc

    async def find_all_thread_rooms(self, project_id) -> list[dict]:
        cursor = self.collection.find(
            {"project_id": oid(project_id), "thread_id": {"$exists": True}},
            {"thread_id": 1, "resolved": 1},
        )
        return await cursor.to_list(length=None)

    async def find_all_thread_rooms_and_global(self, project_id) -> list[dict]:
        cursor = self.collection.find(
            {"project_id": oid(project_id)}, {"thread_id": 1, "resolved": 1}
        )
        return await cursor.to_list(length=None)

    async def get_resolved_thread_ids(self, project_id) -> list[str]:
        cursor = self.collection.find(
            {
                "project_id": oid(project_id),
                "thread_id": {"$exists": True},
                "resolved": {"$exists": True},
            },
            {"thread_id": 1},
        )
        rooms = await cursor.to_list(length=None)
        return [str(r["thread_id"]) for r in rooms]

    async def find_threads_by_id(self, project_id, thread_ids) -> list[dict]:
        cursor = self.collection.find(
            {"project_id": oid(project_id), "thread_id": {"$in": [oid(t) for t in thread_ids]}}
        )
        return await cursor.to_list(length=None)

    async def resolve_thread(self, project_id, thread_id, user_id: str) -> None:
        await self.collection.update_one(
            _thread_filter(oid(project_id), thread_id),
            {"$set": {"resolved": {"user_id": user_id, "ts": datetime.now(timezone.utc)}}},
        )

    async def reopen_thread(self, project_id, thread_id) -> None:
        await self.collection.update_one(
            _thread_filter(oid(project_id), thread_id), {"$unset": {"resolved": True}}
        )

    async def delete_thread(self, project_id, thread_id) -> ObjectId:
        room = await self.find_or_create_thread(project_id, thread_id)
        await self.collection.delete_one({"_id": room["_id"]})
        return room["_id"]

    async def delete_all_threads_in_project(self, project_id) -> None:
        await self.collection.delete_many({"project_id": oid(project_id)})

    async def duplicate_thread(self, project_id, source_room: dict) -> dict:
        pid = oid(project_id)
        new_thread_id = ObjectId()
        doc: dict[str, Any] = {"project_id": pid, "thread_id": new_thread_id}
        if source_room.get("resolved") is not None:
            doc["resolved"] = source_room["resolved"]
        result = await self.collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    async def clone_thread_into_project(self, source_room: dict, target_project_id) -> dict:
        doc: dict[str, Any] = {
            "project_id": oid(target_project_id),
            "thread_id": source_room["thread_id"],
        }
        if source_room.get("resolved") is not None:
            doc["resolved"] = source_room["resolved"]
        result = await self.collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc
