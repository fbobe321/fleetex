"""RealtimeServer — the socket event logic, decoupled from socket.io.

It manages sessions + room membership itself and talks to the outside only through
``emit(event, data, sid)`` and ``disconnect(sid)`` callables, so it is fully unit
testable with a recorder. The socket.io adapter (app.py) wires those to the server.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import controller
from .connected_users import ConnectedUsersManager
from .document_updater import DocumentUpdaterManager
from .errors import UpdateTooLargeError, serialize_error
from .redis_bridge import plan_applied_op_emits
from .web_api import WebApiManager

MAX_UPDATE_SIZE = 7 * 1024 * 1024


@dataclass
class ClientContext:
    sid: str
    public_id: str
    project_id: str
    user_id: str
    privilege_level: str = "readOnly"
    is_restricted_user: bool = False
    first_name: str = ""
    last_name: str = ""
    email: str = ""


@dataclass
class RealtimeServer:
    emit: object  # async (event, data, sid)
    disconnect: object  # async (sid)
    web_api: WebApiManager
    du: DocumentUpdaterManager
    connected_users: ConnectedUsersManager
    sessions: dict = field(default_factory=dict)
    rooms: dict = field(default_factory=dict)  # room -> set(sid)

    # -- room helpers ----------------------------------------------------- #
    def _join_room(self, sid: str, room: str) -> None:
        self.rooms.setdefault(room, set()).add(sid)

    def _leave_room(self, sid: str, room: str) -> None:
        members = self.rooms.get(room)
        if members:
            members.discard(sid)
            if not members:
                del self.rooms[room]

    def _room_members(self, room: str) -> set:
        return self.rooms.get(room, set())

    async def _emit_to_room(self, room: str, event: str, data) -> None:
        for sid in list(self._room_members(room)):
            await self.emit(event, data, sid)

    # -- connection ------------------------------------------------------- #
    async def connect(self, sid: str, project_id: str, user_id: str, anon_token: str | None) -> bool:
        try:
            data = await self.web_api.join_project(project_id, user_id, anon_token)
        except Exception as exc:  # noqa: BLE001 - rejection is the contract
            await self.emit("connectionRejected", serialize_error(exc), sid)
            return False
        public_id = "P." + os.urandom(9).hex()
        ctx = ClientContext(
            sid=sid,
            public_id=public_id,
            project_id=project_id,
            user_id=user_id,
            privilege_level=data.get("privilegeLevel", "readOnly"),
            is_restricted_user=bool(data.get("isRestrictedUser")),
        )
        self.sessions[sid] = ctx
        self._join_room(sid, project_id)
        await self.connected_users.update_user_position(
            project_id, public_id, {"user_id": user_id, "first_name": "", "last_name": "", "email": ""}
        )
        await self.emit(
            "joinProjectResponse",
            {
                "publicId": public_id,
                "project": data["project"],
                "permissionsLevel": data.get("privilegeLevel"),
                "protocolVersion": controller.PROTOCOL_VERSION,
            },
            sid,
        )
        return True

    # -- doc events ------------------------------------------------------- #
    async def join_doc(self, sid: str, doc_id: str, from_version: int = -1, options: dict | None = None):
        ctx = self.sessions[sid]
        try:
            result = await controller.join_doc(
                self.du, ctx.project_id, doc_id, from_version, options or {}, ctx.is_restricted_user
            )
        except Exception as exc:  # noqa: BLE001
            return (serialize_error(exc),)
        self._join_room(sid, doc_id)
        return (None, *result)

    async def leave_doc(self, sid: str, doc_id: str):
        self._leave_room(sid, doc_id)
        return (None,)

    async def apply_ot_update(self, sid: str, doc_id: str, update: dict):
        ctx = self.sessions[sid]
        try:
            await controller.apply_ot_update(
                self.du, ctx.project_id, doc_id, update, ctx.public_id, ctx.user_id,
                ctx.privilege_level, MAX_UPDATE_SIZE,
            )
            return None
        except UpdateTooLargeError:
            message = {"project_id": ctx.project_id, "doc_id": doc_id, "error": "update is too large"}
            await self.emit("otUpdateError", (message["error"], message), sid)
            await self.disconnect(sid)
            return None
        except Exception as exc:  # noqa: BLE001
            return (serialize_error(exc),)

    # -- client tracking -------------------------------------------------- #
    async def update_position(self, sid: str, cursor: dict):
        ctx = self.sessions[sid]
        await self.connected_users.update_user_position(
            ctx.project_id, ctx.public_id,
            {"user_id": ctx.user_id, "first_name": ctx.first_name, "last_name": ctx.last_name, "email": ctx.email},
            cursor,
        )
        payload = {**cursor, "id": ctx.public_id, "user_id": ctx.user_id,
                   "name": f"{ctx.first_name} {ctx.last_name}".strip(), "email": ctx.email}
        await self._emit_to_room(ctx.project_id, "clientTracking.clientUpdated", payload)
        return None

    async def get_connected_users(self, sid: str):
        ctx = self.sessions[sid]
        if ctx.is_restricted_user:
            return (None, [])
        users = await self.connected_users.get_connected_users(ctx.project_id)
        return (None, users)

    # -- disconnect ------------------------------------------------------- #
    async def on_disconnect(self, sid: str):
        ctx = self.sessions.pop(sid, None)
        if ctx is None:
            return
        for room in [r for r, members in self.rooms.items() if sid in members]:
            self._leave_room(sid, room)
        await self.connected_users.mark_user_as_disconnected(ctx.project_id, ctx.public_id)
        await self._emit_to_room(ctx.project_id, "clientTracking.clientDisconnected", ctx.public_id)
        if not self._room_members(ctx.project_id):
            await self.du.flush_project(ctx.project_id)

    # -- redis pub/sub dispatch (background subscriber calls these) -------- #
    async def dispatch_applied_ops(self, message: dict) -> None:
        doc_id = message["doc_id"]
        if "error" in message:
            for sid in list(self._room_members(doc_id)):
                await self.emit("otUpdateError", (message["error"], message), sid)
                await self.disconnect(sid)
            return
        clients = [(sid, self.sessions[sid].public_id) for sid in self._room_members(doc_id) if sid in self.sessions]
        for sid, event, payload in plan_applied_op_emits(message, clients):
            await self.emit(event, payload, sid)

    async def dispatch_editor_event(self, message: dict) -> None:
        room_id = message["room_id"]
        event = message["message"]
        payload = message.get("payload") or []
        data = payload[0] if len(payload) == 1 else payload
        targets = set().union(*self.rooms.values()) if room_id == "all" else self._room_members(room_id)
        for sid in list(targets):
            await self.emit(event, data, sid)
