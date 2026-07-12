"""UserManager — the `users` collection auth operations."""

from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from .passwords import hash_password


class UserManager:
    def __init__(self, db, bcrypt_rounds: int = 12) -> None:
        self.users = db["users"]
        self.bcrypt_rounds = bcrypt_rounds

    async def find_by_email(self, email: str) -> dict | None:
        return await self.users.find_one({"email": email.strip().lower()})

    async def find_by_id(self, user_id: str) -> dict | None:
        try:
            oid = ObjectId(user_id)
        except (InvalidId, TypeError):
            return None
        return await self.users.find_one({"_id": oid})

    async def create_user(self, email: str, password: str, first_name: str = "", last_name: str = "") -> dict:
        email = email.strip().lower()
        doc = {
            "email": email,
            "emails": [{"email": email, "createdAt": datetime.now(timezone.utc)}],
            "hashedPassword": hash_password(password, self.bcrypt_rounds),
            "first_name": first_name,
            "last_name": last_name,
            "loginCount": 0,
            "isAdmin": False,
        }
        result = await self.users.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    async def set_password(self, user_id, password: str) -> None:
        await self.users.update_one(
            {"_id": ObjectId(user_id)}, {"$set": {"hashedPassword": hash_password(password, self.bcrypt_rounds)}}
        )

    async def record_login(self, user_id, ip: str | None = None) -> None:
        await self.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"loginCount": 1}, "$set": {"lastLoggedIn": datetime.now(timezone.utc), "lastLoginIp": ip}},
        )
