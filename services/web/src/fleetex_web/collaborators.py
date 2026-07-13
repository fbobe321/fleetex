"""Collaborators — add/list/remove project members (sharing).

The privilege logic (authorization.py) already reads collaberator_refs /
readOnly_refs / reviewer_refs; this module manages them. Fleetex adds members
directly by email (the trusted-users CE model) rather than email-invite tokens.
"""

from __future__ import annotations

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .projects import ProjectManager, can_admin, can_read, load_with_access

# privilegeLevel -> the project ref array that grants it
LEVEL_TO_FIELD = {
    "readAndWrite": "collaberator_refs",
    "review": "reviewer_refs",
    "readOnly": "readOnly_refs",
}
_ALL_FIELDS = list(LEVEL_TO_FIELD.values())


async def member_views(project: dict, db) -> list[dict]:
    level_by_id: dict[str, str] = {}
    for level, field in LEVEL_TO_FIELD.items():
        for uid in project.get(field, []) or []:
            level_by_id[str(uid)] = level
    owner_ref = project.get("owner_ref")
    ids = set(level_by_id) | ({str(owner_ref)} if owner_ref else set())
    users: dict[str, dict] = {}
    if ids:
        cursor = db["users"].find({"_id": {"$in": [ObjectId(i) for i in ids]}}, {"email": 1, "first_name": 1, "last_name": 1})
        for u in await cursor.to_list(length=None):
            users[str(u["_id"])] = u

    def view(uid: str, level: str) -> dict:
        u = users.get(uid, {})
        return {"user_id": uid, "email": u.get("email"), "first_name": u.get("first_name", ""), "last_name": u.get("last_name", ""), "privilegeLevel": level}

    members = []
    if owner_ref:
        members.append(view(str(owner_ref), "owner"))
    for uid, level in level_by_id.items():
        members.append(view(uid, level))
    return members


def register_collaborator_routes(app: FastAPI, *, pm: ProjectManager, db, store, config) -> None:
    @app.get("/project/{project_id}/members")
    async def list_members(project_id: str, request: Request):
        loaded, err = await load_with_access(request, project_id, pm=pm, store=store, config=config, check=can_read)
        if err:
            return err
        _uid, project = loaded
        return JSONResponse({"members": await member_views(project, db)})

    @app.post("/project/{project_id}/members")
    async def add_member(project_id: str, request: Request):
        loaded, err = await load_with_access(request, project_id, pm=pm, store=store, config=config, check=can_admin)
        if err:
            return err
        _uid, project = loaded
        body = await request.json()
        email = (body.get("email") or "").strip().lower()
        level = body.get("privilegeLevel", "readAndWrite")
        if level not in LEVEL_TO_FIELD:
            return JSONResponse({"message": {"type": "error", "text": "invalid privilege level"}}, status_code=400)
        if not email:
            return JSONResponse({"message": {"type": "error", "text": "email is required"}}, status_code=400)
        user = await db["users"].find_one({"email": email})
        if not user:
            return JSONResponse({"message": {"type": "error", "text": "no account with that email"}}, status_code=404)
        if str(user["_id"]) == str(project.get("owner_ref")):
            return JSONResponse({"message": {"type": "error", "text": "that user is the owner"}}, status_code=400)
        # move the user to exactly the requested level
        await db["projects"].update_one({"_id": project["_id"]}, {"$pull": {f: user["_id"] for f in _ALL_FIELDS}})
        await db["projects"].update_one({"_id": project["_id"]}, {"$addToSet": {LEVEL_TO_FIELD[level]: user["_id"]}})
        return JSONResponse({"member": {"user_id": str(user["_id"]), "email": user["email"], "privilegeLevel": level}})

    @app.delete("/project/{project_id}/members/{user_id}")
    async def remove_member(project_id: str, user_id: str, request: Request):
        loaded, err = await load_with_access(request, project_id, pm=pm, store=store, config=config, check=can_admin)
        if err:
            return err
        _uid, project = loaded
        try:
            oid = ObjectId(user_id)
        except (InvalidId, TypeError):
            return Response(status_code=404)
        await db["projects"].update_one({"_id": project["_id"]}, {"$pull": {f: oid for f in _ALL_FIELDS}})
        return Response(status_code=204)
