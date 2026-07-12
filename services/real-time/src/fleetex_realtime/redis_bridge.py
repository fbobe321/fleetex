"""Redis pub/sub message shapes — port of WebsocketLoadBalancer + DocumentUpdaterController.

These are protocol-agnostic (plain JSON over Redis channels), so they interoperate
byte-for-byte with the existing Node real-time / web / document-updater instances.

Channels:
* ``editor-events`` — ``{room_id, message, payload:[...]}`` broadcast of editor events.
* ``applied-ops``   — ``{doc_id, op}`` (op = the full update) from document-updater.
"""

from __future__ import annotations

import copy
import json

EDITOR_EVENTS_CHANNEL = "editor-events"
APPLIED_OPS_CHANNEL = "applied-ops"


def build_editor_event(room_id: str, message: str, payload: list) -> str:
    """Serialize an editor-events publish (WebsocketLoadBalancer.emitToRoom)."""
    return json.dumps({"room_id": room_id, "message": message, "payload": list(payload)})


def parse_message(raw: str | bytes) -> dict:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _strip_tsrt(update: dict) -> dict:
    clean = copy.deepcopy(update)
    if isinstance(clean.get("meta"), dict):
        clean["meta"].pop("tsRT", None)
    return clean


def plan_applied_op_emits(message: dict, clients: list[tuple[str, str]]) -> list[tuple[str, str, object]]:
    """Fan-out plan for an applied-ops message (DocumentUpdaterController._applyUpdate).

    ``clients`` is a list of ``(sid, public_id)`` for the doc room. Returns a list of
    ``(sid, event, payload)``:
    * the update's source client gets the ack ``otUpdateApplied {v, doc}``;
    * every other client gets the full op (unless ``op.dup``).
    """
    update = message["op"]
    source = (update.get("meta") or {}).get("source")
    clean = _strip_tsrt(update)
    emits: list[tuple[str, str, object]] = []
    for sid, public_id in clients:
        if public_id == source:
            emits.append((sid, "otUpdateApplied", {"v": update["v"], "doc": update["doc"]}))
        elif not update.get("dup"):
            emits.append((sid, "otUpdateApplied", clean))
    return emits


def plan_error_emits(message: dict, clients: list[str]) -> list[tuple[str, str, object]]:
    """Fan-out for an applied-ops error: every client in the doc room, then disconnect."""
    error = message.get("error")
    return [(sid, "otUpdateError", (error, message)) for sid in clients]
