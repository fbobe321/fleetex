"""The server-model transform loop — port of sharejs/server/model.js makeOpQueue.

An incoming update carries the client's base version ``v`` and its op. The server
transforms that op forward through every concurrent op applied since ``v`` (always
as side ``'left'``, matching model.js:187), then applies it at the current version.
"""

from __future__ import annotations

import re

from . import ot_text
from .errors import OpAtFutureVersionError, OpTooOldError

_LINE_SPLIT = re.compile(r"\r\n|\n|\r")


def lines_to_snapshot(lines: list) -> str:
    return "\n".join(lines)


def snapshot_to_lines(snapshot: str) -> list:
    return _LINE_SPLIT.split(snapshot)


def process_update(lines: list, version: int, previous_ops: list, update: dict, max_age: int = 80):
    """Transform + apply an update. Returns (new_lines, new_version, applied_update).

    ``previous_ops`` are the ops applied at versions [update.v, version) — the
    concurrent server ops the incoming op must be rebased over.
    """
    op_v = update["v"]
    if op_v > version:
        raise OpAtFutureVersionError(f"op at future version {op_v} > {version}")
    if op_v + max_age < version:
        raise OpTooOldError(f"op too old: {op_v} + {max_age} < {version}")

    dup_if_source = update.get("dupIfSource") or []
    transformed = update["op"]
    for old in previous_ops:
        old_source = (old.get("meta") or {}).get("source")
        if old_source is not None and old_source in dup_if_source:
            # This op was already submitted by us — ack it as a duplicate.
            applied = {**update, "op": transformed, "v": version, "dup": True}
            return lines, version, applied
        transformed = ot_text.transform(transformed, old["op"], "left")

    snapshot = lines_to_snapshot(lines)
    new_snapshot = ot_text.apply(snapshot, transformed)
    new_lines = snapshot_to_lines(new_snapshot)
    applied = {**update, "op": transformed, "v": version}
    return new_lines, version + 1, applied
