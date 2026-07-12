"""WebsocketController — port of WebsocketController.js core logic (no socket layer).

Kept free of socket.io so it is unit-testable; the sio adapter calls these.
"""

from __future__ import annotations

import time

from .document_updater import DocumentUpdaterManager
from .errors import NotAuthorizedError

PROTOCOL_VERSION = 2

# Permission tiers (least -> most).
_VIEW = {"readOnly", "review", "readAndWrite", "owner"}
_REVIEW = {"review", "readAndWrite", "owner"}
_EDIT = {"readAndWrite", "owner"}


def encode_line_for_websocket(line: str) -> str:
    """Equivalent of JS ``unescape(encodeURIComponent(line))`` — UTF-8 bytes as latin-1."""
    return line.encode("utf-8").decode("latin-1")


async def join_doc(
    du: DocumentUpdaterManager,
    project_id: str,
    doc_id: str,
    from_version: int,
    options: dict,
    is_restricted_user: bool,
) -> tuple[list, int, list, dict, str]:
    """Returns the joinDoc ack args: (lines, version, ops, ranges, type)."""
    doc = await du.get_document(project_id, doc_id, from_version)
    lines = doc.get("lines", [])
    version = doc.get("version", 0)
    ops = doc.get("ops", [])
    ranges = doc.get("ranges") or {}
    doc_type = doc.get("type", "sharejs-text-ot")

    if doc_type != "history-ot":
        lines = [encode_line_for_websocket(line) for line in lines]
    if is_restricted_user:
        ranges = {**ranges, "comments": []}
    return lines, version, ops, ranges, doc_type


def _is_all_comment_op(update: dict) -> bool:
    ops = update.get("op") or []
    return bool(ops) and all("c" in o for o in ops)


def assert_can_apply_update(update: dict, privilege_level: str) -> None:
    """Authorize an update by op type (comment->view, tracked->review, else edit)."""
    if _is_all_comment_op(update):
        allowed = _VIEW
    elif (update.get("meta") or {}).get("tc"):
        allowed = _REVIEW
    else:
        allowed = _EDIT
    if privilege_level not in allowed:
        raise NotAuthorizedError()


def prepare_update(update: dict, doc_id: str, public_id: str, user_id: str) -> dict:
    """Stamp the update with doc/source/user metadata (WebsocketController.applyOtUpdate)."""
    if update.get("doc") is not None and update["doc"] != doc_id:
        raise ValueError("update.doc must be identical to docId parameter")
    update = dict(update)
    update["doc"] = doc_id
    meta = dict(update.get("meta") or {})
    meta["source"] = public_id
    meta["user_id"] = user_id
    meta["tsRT"] = time.perf_counter() * 1000
    update["meta"] = meta
    return update


async def apply_ot_update(
    du: DocumentUpdaterManager,
    project_id: str,
    doc_id: str,
    update: dict,
    public_id: str,
    user_id: str,
    privilege_level: str,
    max_update_size: int,
) -> None:
    update = prepare_update(update, doc_id, public_id, user_id)
    assert_can_apply_update(update, privilege_level)
    await du.queue_change(project_id, doc_id, update, max_update_size)
