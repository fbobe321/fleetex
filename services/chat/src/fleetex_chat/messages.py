"""Message data layer — port of ``app/js/Features/Messages/MessageManager.js``.

Note: ``room_id`` on a message points at ``rooms._id`` (NOT project_id).
Timestamps are plain numbers (ms since epoch), matching ``Date.now()``.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId

from .errors import MissingMessageError


def oid(value: Any) -> ObjectId:
    return value if isinstance(value, ObjectId) else ObjectId(value)


class MessageManager:
    def __init__(self, db) -> None:
        self.collection = db["messages"]

    async def create_message(
        self, room_id, user_id, content: str, timestamp: int
    ) -> dict:
        doc = {
            "content": content,
            "room_id": oid(room_id),
            "user_id": oid(user_id),
            "timestamp": timestamp,
        }
        result = await self.collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    async def get_messages(self, room_id, limit: int, before: int | None = None) -> list[dict]:
        query: dict[str, Any] = {"room_id": oid(room_id)}
        if before is not None:
            query["timestamp"] = {"$lt": before}
        cursor = self.collection.find(query).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(length=None)

    async def find_all_messages_in_rooms(self, room_ids) -> list[dict]:
        cursor = self.collection.find({"room_id": {"$in": [oid(r) for r in room_ids]}})
        return await cursor.to_list(length=None)

    async def get_message(self, room_id, message_id) -> dict:
        doc = await self.collection.find_one(
            {"_id": oid(message_id), "room_id": oid(room_id)}
        )
        if doc is None:
            raise MissingMessageError()
        return doc

    async def update_message(
        self, room_id, message_id, user_id, content: str, timestamp: int
    ) -> bool:
        query: dict[str, Any] = {"_id": oid(message_id), "room_id": oid(room_id)}
        if user_id:
            query["user_id"] = oid(user_id)
        result = await self.collection.update_one(
            query, {"$set": {"content": content, "edited_at": timestamp}}
        )
        return result.modified_count == 1

    async def delete_message(self, room_id, message_id) -> None:
        await self.collection.delete_one({"_id": oid(message_id), "room_id": oid(room_id)})

    async def delete_user_message(self, user_id, room_id, message_id) -> None:
        await self.collection.delete_one(
            {"_id": oid(message_id), "user_id": oid(user_id), "room_id": oid(room_id)}
        )

    async def delete_all_messages_in_room(self, room_id) -> None:
        await self.collection.delete_many({"room_id": oid(room_id)})

    async def delete_all_messages_in_rooms(self, room_ids) -> None:
        await self.collection.delete_many({"room_id": {"$in": [oid(r) for r in room_ids]}})

    async def duplicate_room_to_other_room(self, source_room_id, target_room_id) -> None:
        source = await self.find_all_messages_in_rooms([source_room_id])
        # Copies drop _id and edited_at (matching duplicateRoomToOtherRoom).
        copies = [
            {
                "room_id": oid(target_room_id),
                "content": m["content"],
                "timestamp": m["timestamp"],
                "user_id": m["user_id"],
            }
            for m in source
        ]
        if copies:
            await self.collection.insert_many(copies)
