"""Ranges normalization — port of RangeManager.js.

* ``json_ranges_to_mongo``: coerce ids/user_ids to ObjectId (best-effort — invalid
  stays a string), ``metadata.ts`` to Date, force ``comment.id == comment.op.t``,
  and strip ``op.resolved``.
* ``fix_comment_ids``: re-sync ``comment.id = comment.op.t`` on read.
* ``should_update_ranges``: deep inequality (missing ranges treated as ``{}``).
"""

from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId


def _to_object_id(value):
    try:
        return ObjectId(value)
    except Exception:
        return value


def _to_date(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


def _fix_metadata(md):
    if not isinstance(md, dict):
        return md
    md = dict(md)
    if "ts" in md:
        md["ts"] = _to_date(md["ts"])
    if "user_id" in md:
        md["user_id"] = _to_object_id(md["user_id"])
    return md


def _fix_change(change: dict) -> dict:
    change = dict(change)
    if "id" in change:
        change["id"] = _to_object_id(change["id"])
    if "metadata" in change:
        change["metadata"] = _fix_metadata(change["metadata"])
    return change


def _fix_comment(comment: dict) -> dict:
    comment = dict(comment)
    op = dict(comment.get("op", {}))
    op.pop("resolved", None)
    if "t" in op:
        op["t"] = _to_object_id(op["t"])
    comment["op"] = op
    comment["id"] = op.get("t")  # id is forced to op.t
    if "metadata" in comment:
        comment["metadata"] = _fix_metadata(comment["metadata"])
    return comment


def json_ranges_to_mongo(ranges) -> dict:
    if not ranges:
        return {}
    out: dict = {}
    if ranges.get("changes"):
        out["changes"] = [_fix_change(c) for c in ranges["changes"]]
    if ranges.get("comments"):
        out["comments"] = [_fix_comment(c) for c in ranges["comments"]]
    return out


def fix_comment_ids(doc: dict) -> None:
    ranges = doc.get("ranges") or {}
    for comment in ranges.get("comments", []):
        t = comment.get("op", {}).get("t")
        if t is not None:
            comment["id"] = t


def _clean(ranges: dict) -> dict:
    return {k: ranges[k] for k in ("changes", "comments") if ranges.get(k)}


def should_update_ranges(doc_ranges, new_ranges) -> bool:
    return _clean(doc_ranges or {}) != _clean(json_ranges_to_mongo(new_ranges or {}))
