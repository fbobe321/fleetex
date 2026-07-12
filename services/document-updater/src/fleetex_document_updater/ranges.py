"""Basic ranges position-shifting — a subset of ranges-tracker.

Shifts comment/change positions when text ops apply: insert shifts everything at
or after the insert by +len; delete shifts everything after by -len and clamps
overlaps. The full track-changes merge/undo logic is deferred (documented).
"""

from __future__ import annotations


def _shift_entry(entry: dict, op: dict) -> dict | None:
    inner = entry.get("op") or {}
    p = inner.get("p")
    if p is None:
        return entry
    if isinstance(op.get("i"), str):
        length = len(op["i"])
        if op["p"] <= p:
            inner = {**inner, "p": p + length}
    elif isinstance(op.get("d"), str):
        length = len(op["d"])
        if op["p"] + length <= p:
            inner = {**inner, "p": p - length}
        elif op["p"] < p:
            inner = {**inner, "p": op["p"]}  # clamp into the deleted region
    return {**entry, "op": inner}


def apply_op_to_ranges(ranges: dict, op_components: list) -> dict:
    if not ranges:
        return {}
    changes = ranges.get("changes") or []
    comments = ranges.get("comments") or []
    for component in op_components:
        if isinstance(component.get("c"), str):
            continue  # comment components don't move ranges here
        changes = [e for e in (_shift_entry(c, component) for c in changes) if e is not None]
        comments = [e for e in (_shift_entry(c, component) for c in comments) if e is not None]
    out: dict = {}
    if changes:
        out["changes"] = changes
    if comments:
        out["comments"] = comments
    return out
