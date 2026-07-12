"""JSON encoding + docView builder.

``build_doc_view`` matches _buildDocView: always ``_id`` (hex string), then each
of lines/rev/version/ranges/deleted **only when not None** (nulls are omitted).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId


def js_iso(dt: datetime) -> str:
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


def build_doc_view(doc: dict) -> dict:
    view: dict = {"_id": str(doc["_id"])}
    if doc.get("lines") is not None:
        view["lines"] = doc["lines"]
    if doc.get("rev") is not None:
        view["rev"] = doc["rev"]
    if doc.get("version") is not None:
        view["version"] = doc["version"]
    if doc.get("ranges") is not None:
        view["ranges"] = encode(doc["ranges"])
    if doc.get("deleted") is not None:
        view["deleted"] = doc["deleted"]
    return view
