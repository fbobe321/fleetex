"""Serialize Mongo docs exactly as Express's ``res.json`` would.

The Node service returns raw Mongo documents, so we must match its JSON encoding:
* ``ObjectId`` -> 24-char hex string (Mongo's ``ObjectId.toJSON``)
* ``datetime`` -> JS ``Date.toISOString()`` form: ``YYYY-MM-DDTHH:MM:SS.mmmZ``
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId


def js_iso(dt: datetime) -> str:
    """Match JavaScript ``Date.toISOString()`` (millisecond precision, 'Z')."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def encode(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return js_iso(value)
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [encode(v) for v in value]
    return value


def serialize_notification(doc: dict) -> dict:
    return encode(doc)
