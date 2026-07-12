"""Password hashing — port of AuthenticationManager bcrypt usage.

bcrypt cost 12, minor ``'a'`` (``$2a$12$``), no pepper/HMAC pre-hash. Control
characters are sanitized and passwords longer than 72 bytes are rejected (bcrypt
truncation guard).
"""

from __future__ import annotations

import bcrypt

MAX_PASSWORD_LENGTH = 72


def sanitize_control_characters(password: str) -> str:
    # Strip C0/C1 control characters (keep tab/newline out too, matching intent).
    return "".join(ch for ch in password if ord(ch) >= 32 and ord(ch) != 127)


def hash_password(password: str, rounds: int = 12) -> str:
    password = sanitize_control_characters(password)
    if len(password.encode("utf-8")) > MAX_PASSWORD_LENGTH:
        raise ValueError("password is too long")
    salt = bcrypt.gensalt(rounds, prefix=b"2a")
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    password = sanitize_control_characters(password)
    if len(password.encode("utf-8")) > MAX_PASSWORD_LENGTH:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False
