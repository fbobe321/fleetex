"""Client-side formatting — port of ``MessageFormatter.js``.

* ``format_message_for_client``: ``_id`` -> ``id`` (string), drop ``room_id``,
  include ``edited_at`` only if present.
* ``group_messages_by_threads``: build a dict keyed by thread_id string. Only
  threads that have at least one message appear (grouping is message-driven).
  Each thread's messages are sorted ascending by timestamp.
"""

from __future__ import annotations

from bson import ObjectId


def _user_id(value):
    return str(value) if isinstance(value, ObjectId) else value


def format_message_for_client(message: dict) -> dict:
    out = {
        "id": str(message["_id"]),
        "content": message["content"],
        "timestamp": message["timestamp"],
        "user_id": _user_id(message["user_id"]),
    }
    if message.get("edited_at") is not None:
        out["edited_at"] = message["edited_at"]
    return out


def group_messages_by_threads(rooms: list[dict], messages: list[dict]) -> dict:
    rooms_by_id = {str(r["_id"]): r for r in rooms}
    threads: dict[str, dict] = {}

    def get_thread(room: dict) -> dict:
        thread_id = str(room["thread_id"])
        existing = threads.get(thread_id)
        if existing is not None:
            return existing
        thread: dict = {"messages": []}
        resolved = room.get("resolved")
        if resolved:
            thread["resolved"] = True
            thread["resolved_at"] = resolved["ts"]
            thread["resolved_by_user_id"] = resolved["user_id"]
        threads[thread_id] = thread
        return thread

    for message in messages:
        room = rooms_by_id.get(str(message["room_id"]))
        if room is None:
            continue
        get_thread(room)["messages"].append(format_message_for_client(message))

    for thread in threads.values():
        thread["messages"].sort(key=lambda m: m["timestamp"])
    return threads
