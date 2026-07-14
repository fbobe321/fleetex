"""File-tree mutations — port of EditorController/ProjectEntityUpdateHandler.

Operations (all require write access, all publish an editor-events message):
add doc, add folder, rename, move, delete, upload. Bridges: docstore (doc
content create/delete), filestore (binary upload), real-time editor-events.

Tree mutation strategy: load project, mutate the in-memory rootFolder, save the
whole tree + bump ``version`` (a documented simplification of Node's positional-$
updates — same result, guarded by the LockManager upstream anyway).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import httpx
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from .projects import ProjectManager, can_write, load_with_access

MAX_ENTITIES_PER_PROJECT = 2000
MAX_NAME_LENGTH = 150
_SEG = {"doc": "docs", "file": "fileRefs", "folder": "folders"}
_BAD_CHARS = set("/\\*")
_BLOCKED_NAMES = {
    "prototype", "constructor", "toString", "toLocaleString", "valueOf",
    "hasOwnProperty", "isPrototypeOf", "propertyIsEnumerable", "__defineGetter__",
    "__lookupGetter__", "__defineSetter__", "__lookupSetter__", "__proto__",
}


class FileTreeError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def is_clean_filename(name) -> bool:
    if not isinstance(name, str) or not (1 <= len(name) <= 1024):
        return False
    if name in (".", "..") or name != name.strip():
        return False
    for ch in name:
        o = ord(ch)
        if ch in _BAD_CHARS or o < 0x20 or o == 0x7F or 0x80 <= o <= 0x9F or 0xD800 <= o <= 0xDFFF:
            return False
    return True


# --- tree helpers -------------------------------------------------------- #
def _root(project: dict) -> dict:
    return project["rootFolder"][0]


def find_folder(project: dict, folder_id) -> dict | None:
    root = _root(project)
    if folder_id is None or str(root["_id"]) == str(folder_id):
        return root

    def walk(folder):
        for sub in folder.get("folders", []):
            if str(sub["_id"]) == str(folder_id):
                return sub
            found = walk(sub)
            if found:
                return found
        return None

    return walk(root)


def find_element(project: dict, entity_id, entity_type: str):
    seg = _SEG[entity_type]

    def walk(folder):
        for el in folder.get(seg, []):
            if str(el["_id"]) == str(entity_id):
                return el, folder
        for sub in folder.get("folders", []):
            found = walk(sub)
            if found:
                return found
        return None

    return walk(_root(project))


def _names(folder: dict) -> set:
    return {e["name"] for e in folder.get("docs", []) + folder.get("fileRefs", []) + folder.get("folders", [])}


def _count_entities(project: dict) -> int:
    def walk(folder):
        n = len(folder.get("docs", [])) + len(folder.get("fileRefs", []))
        for sub in folder.get("folders", []):
            n += 1 + walk(sub)
        return n

    return walk(_root(project))


def _subtree_docs(element: dict, entity_type: str) -> list[dict]:
    if entity_type == "doc":
        return [element]
    if entity_type == "file":
        return []
    docs = list(element.get("docs", []))
    for sub in element.get("folders", []):
        docs += _subtree_docs(sub, "folder")
    return docs


def _is_self_or_descendant(moved_folder: dict, dest_id) -> bool:
    if str(moved_folder["_id"]) == str(dest_id):
        return True

    def walk(folder):
        for sub in folder.get("folders", []):
            if str(sub["_id"]) == str(dest_id) or walk(sub):
                return True
        return False

    return walk(moved_folder)


def _is_top_level(project: dict, parent: dict) -> bool:
    return str(parent["_id"]) == str(_root(project)["_id"])


# --- bridges ------------------------------------------------------------- #
class FilestoreClient:
    """Stores an uploaded binary in filestore and returns its content hash.

    POSTs to the filestore project-file route (a Fleetex extension). A filestore
    outage doesn't fail the tree mutation — the fileRef/hash is still recorded.
    Injectable for tests.
    """

    def __init__(self, base_url: str = "", http=None) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.http = http

    async def upload(self, project_id: str, file_id: str, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        if self.base_url:
            try:
                client = self.http or httpx.AsyncClient(timeout=30)
                await client.post(f"{self.base_url}/project/{project_id}/file/{file_id}", content=content)
            except Exception:  # noqa: BLE001 - persistence best-effort; metadata still recorded
                pass
        return digest

    async def get(self, project_id: str, file_id: str) -> bytes | None:
        """Fetch a stored binary (used by the project zip download)."""
        if not self.base_url:
            return None
        try:
            client = self.http or httpx.AsyncClient(timeout=30)
            resp = await client.get(f"{self.base_url}/project/{project_id}/file/{file_id}")
            return resp.content if resp.status_code == 200 else None
        except Exception:  # noqa: BLE001
            return None


class EditorEventsPublisher:
    """Publishes editor-events to Redis in the shape real-time consumes."""

    def __init__(self, redis) -> None:
        self.redis = redis
        self._seq = 0

    async def emit(self, project_id: str, message: str, *payload) -> None:
        self._seq += 1
        blob = json.dumps({"room_id": project_id, "message": message, "payload": list(payload), "_id": f"web:{self._seq}"})
        await self.redis.publish("editor-events", blob)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- manager ------------------------------------------------------------- #
class FileTreeManager:
    def __init__(self, db, docstore, filestore: FilestoreClient, events: EditorEventsPublisher) -> None:
        self.projects = db["projects"]
        self.docstore = docstore
        self.filestore = filestore
        self.events = events

    async def _save(self, project: dict) -> None:
        await self.projects.update_one(
            {"_id": project["_id"]},
            {"$set": {"rootFolder": project["rootFolder"], "version": project.get("version", 0), "lastUpdated": datetime.now(timezone.utc), "rootDoc_id": project.get("rootDoc_id")}},
        )

    def _validate_name(self, project: dict, parent: dict, name: str, entity_type: str) -> None:
        if not is_clean_filename(name):
            raise FileTreeError("invalid_file_name")
        if entity_type in ("doc", "file") and _is_top_level(project, parent) and name in _BLOCKED_NAMES:
            raise FileTreeError("invalid_file_name")
        if name in _names(parent):
            raise FileTreeError("duplicate_file_name")
        if _count_entities(project) >= MAX_ENTITIES_PER_PROJECT:
            raise FileTreeError("project_has_too_many_files")

    async def add_doc(self, project: dict, parent_folder_id, name: str, user_id: str, source="editor") -> dict:
        parent = find_folder(project, parent_folder_id)
        if parent is None:
            raise FileTreeError("folder_not_found")
        self._validate_name(project, parent, name, "doc")
        doc_id = ObjectId()
        await self.docstore.update_doc(str(project["_id"]), str(doc_id), [], 0, {})
        doc = {"_id": doc_id, "name": name}
        parent["docs"].append(doc)
        project["version"] = project.get("version", 0) + 1
        await self._save(project)
        view = {"_id": str(doc_id), "name": name}
        await self.events.emit(str(project["_id"]), "reciveNewDoc", parent_folder_id, view, source, user_id)
        return view

    async def add_folder(self, project: dict, parent_folder_id, name: str, user_id: str) -> dict:
        parent = find_folder(project, parent_folder_id)
        if parent is None:
            raise FileTreeError("folder_not_found")
        self._validate_name(project, parent, name, "folder")
        folder = {"_id": ObjectId(), "name": name, "docs": [], "fileRefs": [], "folders": []}
        parent["folders"].append(folder)
        project["version"] = project.get("version", 0) + 1
        await self._save(project)
        view = {"_id": str(folder["_id"]), "name": name, "docs": [], "fileRefs": [], "folders": []}
        await self.events.emit(str(project["_id"]), "reciveNewFolder", parent_folder_id, view, user_id)
        return view

    async def rename_entity(self, project: dict, entity_type: str, entity_id: str, name: str) -> None:
        found = find_element(project, entity_id, entity_type)
        if found is None:
            raise FileTreeError("not_found")
        element, parent = found
        if not is_clean_filename(name):
            raise FileTreeError("invalid_file_name")
        if entity_type in ("doc", "file") and _is_top_level(project, parent) and name in _BLOCKED_NAMES:
            raise FileTreeError("invalid_file_name")
        if name != element["name"] and name in _names(parent):
            raise FileTreeError("duplicate_file_name")
        element["name"] = name
        project["version"] = project.get("version", 0) + 1
        await self._save(project)
        await self.events.emit(str(project["_id"]), "reciveEntityRename", entity_id, name)

    async def move_entity(self, project: dict, entity_type: str, entity_id: str, folder_id: str) -> None:
        found = find_element(project, entity_id, entity_type)
        if found is None:
            raise FileTreeError("not_found")
        element, old_parent = found
        dest = find_folder(project, folder_id)
        if dest is None:
            raise FileTreeError("folder_not_found")
        if entity_type == "folder" and _is_self_or_descendant(element, folder_id):
            raise FileTreeError("invalid_file_name")  # into itself/descendant
        if element["name"] in _names(dest):
            raise FileTreeError("duplicate_file_name")
        old_parent[_SEG[entity_type]].remove(element)
        dest[_SEG[entity_type]].append(element)
        project["version"] = project.get("version", 0) + 2  # put + remove
        await self._save(project)
        await self.events.emit(str(project["_id"]), "reciveEntityMove", entity_id, folder_id)

    async def delete_entity(self, project: dict, entity_type: str, entity_id: str, source="editor") -> None:
        found = find_element(project, entity_id, entity_type)
        if found is None:
            raise FileTreeError("not_found")
        element, parent = found
        docs = _subtree_docs(element, entity_type)
        root_doc_id = str(project["rootDoc_id"]) if project.get("rootDoc_id") else None
        for doc in docs:
            await self.docstore.delete_doc(str(project["_id"]), str(doc["_id"]), doc["name"], _now_iso())
            if str(doc["_id"]) == root_doc_id:
                project["rootDoc_id"] = None
        parent[_SEG[entity_type]].remove(element)
        project["version"] = project.get("version", 0) + 1
        await self._save(project)
        await self.events.emit(str(project["_id"]), "removeEntity", entity_id, source)

    async def upload(self, project: dict, folder_id, name: str, content: bytes, user_id: str) -> dict:
        parent = find_folder(project, folder_id)
        if parent is None:
            raise FileTreeError("folder_not_found")
        if not name or len(name) > MAX_NAME_LENGTH or not is_clean_filename(name):
            raise FileTreeError("invalid_filename")
        if name in _names(parent):
            raise FileTreeError("duplicate_file_name")
        if _count_entities(project) >= MAX_ENTITIES_PER_PROJECT:
            raise FileTreeError("project_has_too_many_files")
        if _is_text(content):
            doc_id = ObjectId()
            lines = content.decode("utf-8").splitlines()
            await self.docstore.update_doc(str(project["_id"]), str(doc_id), lines, 0, {})
            parent["docs"].append({"_id": doc_id, "name": name})
            project["version"] = project.get("version", 0) + 1
            await self._save(project)
            await self.events.emit(str(project["_id"]), "reciveNewDoc", folder_id, {"_id": str(doc_id), "name": name}, "upload", user_id)
            return {"entity_id": str(doc_id), "entity_type": "doc", "hash": None}
        file_id = ObjectId()
        file_hash = await self.filestore.upload(str(project["_id"]), str(file_id), content)
        file_ref = {"_id": file_id, "name": name, "rev": 0, "created": datetime.now(timezone.utc), "hash": file_hash}
        parent["fileRefs"].append(file_ref)
        project["version"] = project.get("version", 0) + 1
        await self._save(project)
        await self.events.emit(str(project["_id"]), "reciveNewFile", folder_id, {"_id": str(file_id), "name": name, "hash": file_hash}, "upload", None, user_id)
        return {"entity_id": str(file_id), "entity_type": "file", "hash": file_hash}


def _is_text(content: bytes) -> bool:
    if b"\x00" in content:
        return False
    try:
        content.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


# --- routes -------------------------------------------------------------- #
def register_file_tree_routes(app: FastAPI, *, pm: ProjectManager, db, store, config, ft: FileTreeManager) -> None:
    async def _load(request: Request, project_id: str):
        return await load_with_access(request, project_id, pm=pm, store=store, config=config, check=can_write)

    def _err(exc: FileTreeError, status: int):
        return JSONResponse({"message": {"type": "error", "text": exc.code}}, status_code=status)

    @app.post("/project/{project_id}/doc")
    async def add_doc(project_id: str, request: Request):
        loaded, err = await _load(request, project_id)
        if err:
            return err
        uid, project = loaded
        body = await _json(request)
        name = (body.get("name") or "").strip()
        if not (0 < len(name) < MAX_NAME_LENGTH):
            return Response(status_code=400)
        try:
            doc = await ft.add_doc(project, body.get("parent_folder_id"), name, uid)
        except FileTreeError as exc:
            return _err(exc, 400)
        return JSONResponse(doc)

    @app.post("/project/{project_id}/folder")
    async def add_folder(project_id: str, request: Request):
        loaded, err = await _load(request, project_id)
        if err:
            return err
        uid, project = loaded
        body = await _json(request)
        name = (body.get("name") or "").strip()
        try:
            folder = await ft.add_folder(project, body.get("parent_folder_id"), name, uid)
        except FileTreeError as exc:
            return _err(exc, 400)
        return JSONResponse(folder)

    @app.post("/project/{project_id}/{entity_type}/{entity_id}/rename")
    async def rename_entity(project_id: str, entity_type: str, entity_id: str, request: Request):
        if entity_type not in _SEG:
            return Response(status_code=404)
        loaded, err = await _load(request, project_id)
        if err:
            return err
        _uid, project = loaded
        body = await _json(request)
        name = (body.get("name") or "").strip()
        if not (0 < len(name) < MAX_NAME_LENGTH):
            return Response(status_code=400)
        try:
            await ft.rename_entity(project, entity_type, entity_id, name)
        except FileTreeError as exc:
            return Response(status_code=404) if exc.code == "not_found" else _err(exc, 400)
        return Response(status_code=204)

    @app.post("/project/{project_id}/{entity_type}/{entity_id}/move")
    async def move_entity(project_id: str, entity_type: str, entity_id: str, request: Request):
        if entity_type not in _SEG:
            return Response(status_code=404)
        loaded, err = await _load(request, project_id)
        if err:
            return err
        _uid, project = loaded
        body = await _json(request)
        try:
            await ft.move_entity(project, entity_type, entity_id, body.get("folder_id"))
        except FileTreeError as exc:
            return Response(status_code=404) if exc.code == "not_found" else _err(exc, 400)
        return Response(status_code=204)

    @app.delete("/project/{project_id}/{entity_type}/{entity_id}")
    async def delete_entity(project_id: str, entity_type: str, entity_id: str, request: Request):
        if entity_type not in _SEG:
            return Response(status_code=404)
        loaded, err = await _load(request, project_id)
        if err:
            return err
        _uid, project = loaded
        try:
            await ft.delete_entity(project, entity_type, entity_id)
        except FileTreeError as exc:
            return Response(status_code=404) if exc.code == "not_found" else _err(exc, 400)
        return Response(status_code=204)

    @app.post("/project/{project_id}/upload")
    async def upload_file(project_id: str, request: Request, qqfile: UploadFile = File(...), name: str = Form(...), folder_id: str = Form(None)):
        loaded, err = await _load(request, project_id)
        if err:
            return err
        uid, project = loaded
        content = await qqfile.read()
        if len(content) > 50 * 1024 * 1024:
            return JSONResponse({"success": False, "error": "file_too_large"}, status_code=422)
        try:
            # accept folder_id as a form field (what the editor sends) or a query param
            fid = folder_id or request.query_params.get("folder_id")
            if fid in (None, "", "null", "None"):
                fid = None  # default to the root folder
            result = await ft.upload(project, fid, name, content, uid)
        except FileTreeError as exc:
            return JSONResponse({"success": False, "error": exc.code}, status_code=422)
        return JSONResponse({"success": True, **result})


async def _json(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}
