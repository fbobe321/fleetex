"""Data-access layer for notifications — a line-for-line port of Overleaf's
``app/js/Notifications.js``.

Key behaviors preserved from the Node original:
* "unread" == the document still has a ``templateKey`` field. Marking read is a
  ``$unset`` of ``templateKey`` (and ``messageOpts`` for the by-id route), NOT a
  delete. Only the ``/bulk`` route actually removes documents.
* Create dedups on ``(user_id, key)``: if one already exists and ``forceCreate``
  is falsy, it is a silent no-op.
* ``expires`` is stored as a Date; an unparseable value raises (→ HTTP 500).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId


def parse_expires(value: Any) -> datetime:
    """Mirror JS ``new Date(value)``. Raise ValueError on an unparseable value.

    Accepts epoch milliseconds (int/float) or an ISO-8601 string (with optional
    trailing 'Z'). A ValueError here propagates to a 500, matching the Node
    controller which returns 500 when ``expires`` cannot be turned into a Date.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"cannot parse expires: {value!r}")


class NotificationsManager:
    def __init__(self, db) -> None:
        self.collection = db["notifications"]

    async def get_user_notifications(self, user_id: ObjectId) -> list[dict]:
        # find({ user_id, templateKey: { $exists: true } }) — natural order, no sort.
        cursor = self.collection.find(
            {"user_id": user_id, "templateKey": {"$exists": True}}
        )
        return await cursor.to_list(length=None)

    async def _count_existing(self, user_id: ObjectId, key: str) -> int:
        return await self.collection.count_documents({"user_id": user_id, "key": key})

    async def add_notification(self, user_id: ObjectId, notification: dict) -> None:
        key = notification.get("key")
        force_create = bool(notification.get("forceCreate"))
        # Dedup guard: existing (user_id, key) and not forceCreate → no-op.
        existing = await self._count_existing(user_id, key)
        if existing != 0 and not force_create:
            return

        doc: dict[str, Any] = {
            "user_id": user_id,
            "key": key,
            "messageOpts": notification.get("messageOpts"),
            "templateKey": notification.get("templateKey"),
        }
        if notification.get("expires") is not None:
            doc["expires"] = parse_expires(notification["expires"])

        await self.collection.update_one(
            {"user_id": user_id, "key": key},
            {"$set": doc},
            upsert=True,
        )

    async def remove_notification_id(
        self, user_id: ObjectId, notification_id: ObjectId
    ) -> None:
        await self.collection.update_one(
            {"user_id": user_id, "_id": notification_id},
            {"$unset": {"templateKey": True, "messageOpts": True}},
        )

    async def remove_notification_key(self, user_id: ObjectId, key: str) -> None:
        await self.collection.update_one(
            {"user_id": user_id, "key": key},
            {"$unset": {"templateKey": True}},
        )

    async def remove_notification_by_key_only(self, key: str) -> None:
        await self.collection.update_one(
            {"key": key},
            {"$unset": {"templateKey": True}},
        )

    async def count_notifications_by_key_only(self, key: str) -> int:
        return await self.collection.count_documents(
            {"key": key, "templateKey": {"$exists": True}}
        )

    async def delete_unread_by_key_only_bulk(self, key: str) -> int:
        if not isinstance(key, str):
            raise ValueError("refusing to bulk delete arbitrary notifications")
        result = await self.collection.delete_many(
            {"key": key, "templateKey": {"$exists": True}}
        )
        return result.deleted_count
