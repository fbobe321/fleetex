"""AuthenticationManager.authenticate — look up by email + verify bcrypt."""

from __future__ import annotations

from .passwords import verify_password
from .users import UserManager


async def authenticate(users: UserManager, email: str, password: str) -> dict | None:
    """Return the user doc on success, else None."""
    user = await users.find_by_email(email)
    if not user or not user.get("hashedPassword"):
        return None
    if verify_password(password, user["hashedPassword"]):
        return user
    return None
