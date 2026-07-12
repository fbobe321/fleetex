"""Project management (dashboard/CRUD) — port of ProjectController/ProjectListController
/ ProjectDeleter / ProjectCreationHandler (a faithful subset).

Reuses sessions.py (auth) and authorization.py (privilege levels). Doc/file
*contents* live in docstore/filestore (deferred) — this slice manages the project
document + tree metadata.
"""

from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from . import authorization as authz
from .sessions import get_logged_in_user_id

MAX_PROJECT_NAME_LENGTH = 150
DEFAULT_MAIN_TEX = "main.tex"


class InvalidNameError(ValueError):
    pass


def validate_project_name(name: str) -> str:
    if not isinstance(name, str):
        raise InvalidNameError("project name must be a string")
    cleaned = "".join(ch for ch in name if ord(ch) >= 32 and ord(ch) != 127)
    if not cleaned:
        raise InvalidNameError("project name cannot be blank")
    if len(cleaned) > MAX_PROJECT_NAME_LENGTH:
        raise InvalidNameError("project name is too long")
    if "/" in cleaned or "\\" in cleaned:
        raise InvalidNameError("project name cannot contain '/' or '\\\\'")
    if cleaned != cleaned.strip():
        raise InvalidNameError("project name has leading/trailing whitespace")
    return cleaned


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def is_archived(project: dict, user_id: str) -> bool:
    archived = project.get("archived")
    if isinstance(archived, bool):
        return archived
    return any(str(uid) == user_id for uid in (archived or []))


def is_trashed(project: dict, user_id: str) -> bool:
    return any(str(uid) == user_id for uid in (project.get("trashed") or []))


class ProjectManager:
    def __init__(self, db) -> None:
        self.projects = db["projects"]
        self.deleted = db["deletedProjects"]

    async def find_by_id(self, project_id: str) -> dict | None:
        try:
            return await self.projects.find_one({"_id": ObjectId(project_id)})
        except (InvalidId, TypeError):
            return None

    async def create_basic(self, owner_id: str, name: str, compiler="pdflatex", image_name=None, spell="en") -> dict:
        owner_oid = ObjectId(owner_id)
        root_doc_id = ObjectId()
        root_folder = {
            "_id": ObjectId(),
            "name": "rootFolder",
            "docs": [{"_id": root_doc_id, "name": DEFAULT_MAIN_TEX}],
            "fileRefs": [],
            "folders": [],
        }
        doc = {
            "name": name,
            "owner_ref": owner_oid,
            "lastUpdatedBy": owner_oid,
            "lastUpdated": _now(),
            "collaberator_refs": [],
            "readOnly_refs": [],
            "reviewer_refs": [],
            "tokenAccessReadAndWrite_refs": [],
            "tokenAccessReadOnly_refs": [],
            "publicAccesLevel": "private",
            "compiler": compiler,
            "spellCheckLanguage": spell,
            "imageName": image_name,
            "archived": [],
            "trashed": [],
            "version": 1,
            "rootFolder": [root_folder],
            "rootDoc_id": root_doc_id,
            "overleaf": {"history": {"id": None, "display": True}},
        }
        result = await self.projects.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    async def find_all_users_projects(self, user_id: str) -> dict:
        oid = ObjectId(user_id)

        async def find(query):
            return await self.projects.find(query).to_list(length=None)

        return {
            "owned": await find({"owner_ref": oid}),
            "readAndWrite": await find({"collaberator_refs": oid}),
            "review": await find({"reviewer_refs": oid}),
            "readOnly": await find({"readOnly_refs": oid}),
            "tokenReadAndWrite": await find({"tokenAccessReadAndWrite_refs": oid, "publicAccesLevel": "tokenBased"}),
            "tokenReadOnly": await find({"tokenAccessReadOnly_refs": oid, "publicAccesLevel": "tokenBased"}),
        }

    async def rename(self, project_id: str, name: str) -> None:
        await self.projects.update_one(
            {"_id": ObjectId(project_id)}, {"$set": {"name": name, "lastUpdated": _now()}}
        )

    async def update_settings(self, project_id: str, fields: dict) -> None:
        allowed = {"compiler", "imageName", "spellCheckLanguage", "name", "rootDoc_id"}
        update = {k: v for k, v in fields.items() if k in allowed}
        if update:
            update["lastUpdated"] = _now()
            await self.projects.update_one({"_id": ObjectId(project_id)}, {"$set": update})

    async def set_public_access_level(self, project_id: str, level: str) -> None:
        await self.projects.update_one({"_id": ObjectId(project_id)}, {"$set": {"publicAccesLevel": level}})

    async def archive(self, project_id, user_id) -> None:
        oid = ObjectId(user_id)
        await self.projects.update_one({"_id": ObjectId(project_id)}, {"$addToSet": {"archived": oid}, "$pull": {"trashed": oid}})

    async def unarchive(self, project_id, user_id) -> None:
        await self.projects.update_one({"_id": ObjectId(project_id)}, {"$pull": {"archived": ObjectId(user_id)}})

    async def trash(self, project_id, user_id) -> None:
        oid = ObjectId(user_id)
        await self.projects.update_one({"_id": ObjectId(project_id)}, {"$addToSet": {"trashed": oid}, "$pull": {"archived": oid}})

    async def untrash(self, project_id, user_id) -> None:
        await self.projects.update_one({"_id": ObjectId(project_id)}, {"$pull": {"trashed": ObjectId(user_id)}})

    async def soft_delete(self, project: dict, deleter_id: str, ip: str | None) -> None:
        deleter_data = {
            "deletedAt": _now(),
            "deleterId": ObjectId(deleter_id),
            "deleterIpAddress": ip,
            "deletedProjectId": project["_id"],
            "deletedProjectOwnerId": project.get("owner_ref"),
            "deletedProjectCollaboratorIds": project.get("collaberator_refs", []),
            "deletedProjectReadOnlyIds": project.get("readOnly_refs", []),
            "deletedProjectLastUpdatedAt": project.get("lastUpdated"),
        }
        await self.deleted.update_one(
            {"deleterData.deletedProjectId": project["_id"]},
            {"$set": {"project": project, "deleterData": deleter_data}},
            upsert=True,
        )
        await self.projects.delete_one({"_id": project["_id"]})

    async def clone(self, owner_id: str, source: dict, new_name: str) -> dict:
        new = await self.create_basic(
            owner_id, new_name,
            compiler=source.get("compiler", "pdflatex"),
            image_name=source.get("imageName"),
            spell=source.get("spellCheckLanguage", "en"),
        )
        # Copy the folder tree metadata with fresh ids (contents live in docstore/filestore).
        cloned_root, root_doc = _clone_tree(source.get("rootFolder", [{}])[0])
        await self.projects.update_one(
            {"_id": new["_id"]},
            {"$set": {"rootFolder": [cloned_root], "rootDoc_id": root_doc}},
        )
        new["rootFolder"] = [cloned_root]
        new["rootDoc_id"] = root_doc
        return new


def _clone_tree(folder: dict):
    """Deep-copy a folder tree, regenerating every _id. Returns (folder, first_doc_id)."""
    first_doc = None

    def clone_folder(f):
        nonlocal first_doc
        docs = []
        for d in f.get("docs", []):
            new_id = ObjectId()
            if first_doc is None:
                first_doc = new_id
            docs.append({"_id": new_id, "name": d.get("name")})
        files = [{"_id": ObjectId(), "name": fr.get("name"), "hash": fr.get("hash")} for fr in f.get("fileRefs", [])]
        return {
            "_id": ObjectId(),
            "name": f.get("name", "rootFolder"),
            "docs": docs,
            "fileRefs": files,
            "folders": [clone_folder(sub) for sub in f.get("folders", [])],
        }

    return clone_folder(folder), first_doc


# --- list view assembly -------------------------------------------------- #
_BUCKETS = [
    ("owned", "owner", "owner"),
    ("readAndWrite", "readWrite", "invite"),
    ("review", "review", "invite"),
    ("readOnly", "readOnly", "invite"),
    ("tokenReadAndWrite", "readAndWrite", "token"),
    ("tokenReadOnly", "readOnly", "token"),
]


def _format_project_info(project: dict, user_id: str, access_level: str, source: str) -> dict:
    archived = is_archived(project, user_id)
    trashed = is_trashed(project, user_id) and not archived
    token_readonly = source == "token" and access_level == "readOnly"
    return {
        "id": str(project["_id"]),
        "name": project.get("name"),
        "archived": archived,
        "trashed": trashed,
        "accessLevel": access_level,
        "source": source,
        "lastUpdated": _iso(project.get("lastUpdated")),
        "_owner_ref": None if token_readonly else project.get("owner_ref"),
        "_lastUpdatedBy": None if token_readonly else project.get("lastUpdatedBy"),
    }


async def build_project_list(pm: ProjectManager, db, user_id: str) -> list[dict]:
    buckets = await pm.find_all_users_projects(user_id)
    seen: set[str] = set()
    views: list[dict] = []
    for bucket_name, access_level, source in _BUCKETS:
        for project in buckets[bucket_name]:
            pid = str(project["_id"])
            if pid in seen:
                continue  # cascading dedupe: owner/invite wins over token
            seen.add(pid)
            views.append(_format_project_info(project, user_id, access_level, source))
    await _inject_project_users(db, views)
    return views


async def _inject_project_users(db, views: list[dict]) -> None:
    ids = set()
    for v in views:
        for key in ("_owner_ref", "_lastUpdatedBy"):
            if v[key] is not None:
                ids.add(v[key])
    users = {}
    if ids:
        cursor = db["users"].find({"_id": {"$in": [ObjectId(str(i)) for i in ids]}}, {"first_name": 1, "last_name": 1, "email": 1})
        for u in await cursor.to_list(length=None):
            users[str(u["_id"])] = {"id": str(u["_id"]), "email": u.get("email"), "firstName": u.get("first_name"), "lastName": u.get("last_name")}
    for v in views:
        owner = v.pop("_owner_ref")
        last = v.pop("_lastUpdatedBy")
        v["owner"] = users.get(str(owner)) if owner is not None else None
        v["lastUpdatedBy"] = users.get(str(last)) if last is not None else None


# --- filters / sort ------------------------------------------------------ #
_SAFE_COMPILERS = {"latex", "pdflatex", "xelatex", "lualatex"}


def _apply_filters(views: list[dict], filters: dict) -> list[dict]:
    out = views
    if filters.get("archived"):
        out = [v for v in out if v["archived"]]
    elif filters.get("trashed"):
        out = [v for v in out if v["trashed"]]
    else:
        # default dashboard view hides archived+trashed
        out = [v for v in out if not v["archived"] and not v["trashed"]]
    if filters.get("ownedByUser"):
        out = [v for v in out if v["source"] == "owner"]
    if filters.get("sharedWithUser"):
        out = [v for v in out if v["source"] in ("invite", "token")]
    return out


def _sort(views: list[dict], sort: dict) -> list[dict]:
    by = sort.get("by", "lastUpdated")
    reverse = sort.get("order", "desc") != "asc"
    keys = {"lastUpdated": lambda v: v["lastUpdated"] or "", "title": lambda v: (v["name"] or "").lower()}
    return sorted(views, key=keys.get(by, keys["lastUpdated"]), reverse=reverse)


# --- access checks (shared with editor routes) --------------------------- #
def can_admin(project: dict, uid: str) -> bool:
    return str(project.get("owner_ref")) == uid


def can_write(project: dict, uid: str) -> bool:
    return authz.privilege_level_for_user(project, uid) in (authz.OWNER, authz.READ_AND_WRITE)


def can_read(project: dict, uid: str) -> bool:
    return authz.privilege_level_for_user(project, uid) is not authz.NONE


async def load_with_access(request: Request, project_id: str, *, pm, store, config, check):
    """Return ((uid, project), None) or (None, Response) short-circuit."""
    _sid, session = await store.load_from_cookie(request.cookies.get(config.cookie_name))
    uid = get_logged_in_user_id(session)
    if not uid:
        return None, Response(status_code=401)
    project = await pm.find_by_id(project_id)
    if project is None:
        return None, Response(status_code=404)
    if not check(project, uid):
        return None, Response(status_code=403)
    return (uid, project), None


def register_project_routes(app: FastAPI, *, pm: ProjectManager, db, store, config) -> None:
    async def _user_id(request: Request) -> str | None:
        _sid, session = await store.load_from_cookie(request.cookies.get(config.cookie_name))
        return get_logged_in_user_id(session)

    _can_admin, _can_write, _can_read = can_admin, can_write, can_read

    async def _load(request: Request, project_id: str, check):
        """Return (uid, project) or a Response to short-circuit."""
        uid = await _user_id(request)
        if not uid:
            return None, Response(status_code=401)
        project = await pm.find_by_id(project_id)
        if project is None:
            return None, Response(status_code=404)
        if not check(project, uid):
            return None, Response(status_code=403)
        return (uid, project), None

    # ---- list ----------------------------------------------------------- #
    @app.post("/api/project")
    async def get_projects_json(request: Request):
        uid = await _user_id(request)
        if not uid:
            return Response(status_code=401)
        body = await _json(request)
        views = await build_project_list(pm, db, uid)
        views = _apply_filters(views, body.get("filters") or {})
        views = _sort(views, body.get("sort") or {})
        return JSONResponse({"totalSize": len(views), "projects": views})

    @app.get("/user/projects")
    async def user_projects_json(request: Request):
        uid = await _user_id(request)
        if not uid:
            return Response(status_code=401)
        views = await build_project_list(pm, db, uid)
        active = [v for v in views if not v["archived"] and not v["trashed"]]
        return JSONResponse({"projects": [{"_id": v["id"], "name": v["name"], "accessLevel": v["accessLevel"]} for v in active]})

    # ---- create --------------------------------------------------------- #
    @app.post("/project/new")
    async def new_project(request: Request):
        uid = await _user_id(request)
        if not uid:
            return Response(status_code=401)
        body = await _json(request)
        try:
            name = validate_project_name((body.get("projectName") or "").strip())
        except InvalidNameError as exc:
            return JSONResponse({"message": {"type": "error", "text": str(exc)}}, status_code=400)
        project = await pm.create_basic(uid, name, image_name=config.__dict__.get("current_image_name"))
        owner = await db["users"].find_one({"_id": ObjectId(uid)}, {"first_name": 1, "last_name": 1, "email": 1})
        return JSONResponse({
            "project_id": str(project["_id"]),
            "owner_ref": uid,
            "owner": {"_id": uid, "first_name": owner.get("first_name") if owner else "", "last_name": owner.get("last_name") if owner else "", "email": owner.get("email") if owner else ""},
        })

    # ---- rename / settings (owner / write) ------------------------------ #
    @app.post("/project/{project_id}/rename")
    async def rename_project(project_id: str, request: Request):
        loaded, err = await _load(request, project_id, _can_admin)
        if err:
            return err
        body = await _json(request)
        try:
            name = validate_project_name((body.get("newProjectName") or "").strip())
        except InvalidNameError as exc:
            return JSONResponse({"message": {"type": "error", "text": str(exc)}}, status_code=400)
        await pm.rename(project_id, name)
        return Response(status_code=200)

    @app.post("/project/{project_id}/settings")
    async def update_settings(project_id: str, request: Request):
        loaded, err = await _load(request, project_id, _can_write)
        if err:
            return err
        body = await _json(request)
        fields: dict = {}
        if "compiler" in body:
            if str(body["compiler"]).lower() not in _SAFE_COMPILERS:
                return JSONResponse({"message": {"type": "error", "text": "invalid compiler"}}, status_code=400)
            fields["compiler"] = str(body["compiler"]).lower()
        for key, target in (("spellCheckLanguage", "spellCheckLanguage"), ("imageName", "imageName"), ("rootDocId", "rootDoc_id")):
            if key in body:
                fields[target] = body[key]
        if "name" in body:
            try:
                fields["name"] = validate_project_name(str(body["name"]).strip())
            except InvalidNameError as exc:
                return JSONResponse({"message": {"type": "error", "text": str(exc)}}, status_code=400)
        await pm.update_settings(project_id, fields)
        return Response(status_code=204)

    @app.post("/project/{project_id}/settings/admin")
    async def update_admin_settings(project_id: str, request: Request):
        loaded, err = await _load(request, project_id, _can_admin)
        if err:
            return err
        body = await _json(request)
        level = body.get("publicAccessLevel")
        if level not in ("private", "tokenBased"):
            return JSONResponse({"message": {"type": "error", "text": "invalid access level"}}, status_code=400)
        await pm.set_public_access_level(project_id, level)
        return Response(status_code=204)

    # ---- delete / archive / trash --------------------------------------- #
    @app.delete("/project/{project_id}")
    async def delete_project(project_id: str, request: Request):
        loaded, err = await _load(request, project_id, _can_admin)
        if err:
            return err
        uid, project = loaded
        await pm.soft_delete(project, uid, request.client.host if request.client else None)
        return Response(status_code=200)

    @app.post("/project/{project_id}/archive")
    async def archive_project(project_id: str, request: Request):
        loaded, err = await _load(request, project_id, _can_read)
        if err:
            return err
        uid, _project = loaded
        await pm.archive(project_id, uid)
        return Response(status_code=200)

    @app.delete("/project/{project_id}/archive")
    async def unarchive_project(project_id: str, request: Request):
        loaded, err = await _load(request, project_id, _can_read)
        if err:
            return err
        uid, _project = loaded
        await pm.unarchive(project_id, uid)
        return Response(status_code=200)

    @app.post("/project/{project_id}/trash")
    async def trash_project(project_id: str, request: Request):
        loaded, err = await _load(request, project_id, _can_read)
        if err:
            return err
        uid, _project = loaded
        await pm.trash(project_id, uid)
        return Response(status_code=200)

    @app.delete("/project/{project_id}/trash")
    async def untrash_project(project_id: str, request: Request):
        loaded, err = await _load(request, project_id, _can_read)
        if err:
            return err
        uid, _project = loaded
        await pm.untrash(project_id, uid)
        return Response(status_code=200)

    # ---- clone ---------------------------------------------------------- #
    @app.post("/project/{project_id}/clone")
    async def clone_project(project_id: str, request: Request):
        loaded, err = await _load(request, project_id, _can_read)
        if err:
            return err
        uid, project = loaded
        body = await _json(request)
        try:
            name = validate_project_name((body.get("projectName") or "").strip())
        except InvalidNameError as exc:
            return JSONResponse({"message": {"type": "error", "text": str(exc)}}, status_code=400)
        clone = await pm.clone(uid, project, name)
        owner = await db["users"].find_one({"_id": ObjectId(uid)}, {"first_name": 1, "last_name": 1, "email": 1})
        return JSONResponse({
            "name": name,
            "project_id": str(clone["_id"]),
            "owner_ref": uid,
            "owner": {"_id": uid, "first_name": owner.get("first_name") if owner else "", "last_name": owner.get("last_name") if owner else "", "email": owner.get("email") if owner else ""},
        })


async def _json(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}
