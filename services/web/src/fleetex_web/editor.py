"""Editor page-load API — bootstrap, entities, and the doc-content bridge.

Three endpoints so the editor can open a project and load a doc:
* ``GET /project/:id``              — bootstrap JSON (projects + users + config)
* ``GET /project/:id/entities``     — flat file-tree list (projects walk)
* ``GET /project/:id/doc/:doc_id``  — doc content (pathname from tree + lines/
                                       version/ranges bridged from the docstore service)

The join model view stays in the auth-slice ``/project/:id/join`` endpoint.
"""

from __future__ import annotations

import httpx
from bson import ObjectId
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from .frontend import EDITOR_PAGE
from .projects import DEFAULT_DOC_LINES, ProjectManager, can_read, can_write, load_with_access


# --- tree walking -------------------------------------------------------- #
def _root(project: dict) -> dict:
    folders = project.get("rootFolder") or [{}]
    return folders[0] if folders else {}


def find_doc_pathname(project: dict, doc_id: str) -> str | None:
    def walk(folder: dict, prefix: str) -> str | None:
        for doc in folder.get("docs", []):
            if str(doc["_id"]) == doc_id:
                return f"{prefix}/{doc['name']}"
        for sub in folder.get("folders", []):
            found = walk(sub, f"{prefix}/{sub['name']}")
            if found:
                return found
        return None

    return walk(_root(project), "")


def list_entities(project: dict) -> list[dict]:
    entities: list[dict] = []

    def walk(folder: dict, prefix: str) -> None:
        for doc in folder.get("docs", []):
            entities.append({"path": f"{prefix}/{doc['name']}", "type": "doc"})
        for file_ref in folder.get("fileRefs", []):
            entities.append({"path": f"{prefix}/{file_ref['name']}", "type": "file"})
        for sub in folder.get("folders", []):
            walk(sub, f"{prefix}/{sub['name']}")

    walk(_root(project), "")
    return sorted(entities, key=lambda e: e["path"])


def list_entities_with_ids(project: dict) -> list[dict]:
    entities: list[dict] = []

    def walk(folder: dict, prefix: str) -> None:
        for doc in folder.get("docs", []):
            entities.append({"id": str(doc["_id"]), "path": f"{prefix}/{doc['name']}", "type": "doc"})
        for file_ref in folder.get("fileRefs", []):
            entities.append({"id": str(file_ref["_id"]), "path": f"{prefix}/{file_ref['name']}", "type": "file"})
        for sub in folder.get("folders", []):
            walk(sub, f"{prefix}/{sub['name']}")

    walk(_root(project), "")
    return sorted(entities, key=lambda e: e["path"])


# --- bootstrap ----------------------------------------------------------- #
def build_user_settings(user: dict) -> dict:
    ace = (user or {}).get("ace") or {}
    return {
        "editorTheme": ace.get("theme", "textmate"),
        "editorLightTheme": ace.get("lightTheme", "textmate"),
        "editorDarkTheme": ace.get("darkTheme", "overleaf_dark"),
        "overallTheme": ace.get("overallTheme", ""),
        "mode": ace.get("mode", "none"),
        "fontSize": ace.get("fontSize", 12),
        "fontFamily": ace.get("fontFamily", "lucida"),
        "lineHeight": ace.get("lineHeight", "normal"),
        "autoComplete": ace.get("autoComplete", True),
        "autoPairDelimiters": ace.get("autoPairDelimiters", True),
        "spellCheckLanguage": ace.get("spellCheckLanguage", "en"),
        "pdfViewer": ace.get("pdfViewer", "pdfjs"),
        "mathPreview": ace.get("mathPreview", True),
    }


def build_bootstrap(project: dict, user: dict | None, uid: str | None, config) -> dict:
    history = (project.get("overleaf") or {}).get("history") or {}
    return {
        "projectId": str(project["_id"]),
        "projectName": project.get("name"),
        "user": None if user is None else {
            "id": str(user["_id"]),
            "email": user.get("email"),
            "first_name": user.get("first_name", ""),
            "last_name": user.get("last_name", ""),
            "isAdmin": user.get("isAdmin", False),
        },
        "userSettings": build_user_settings(user) if user else {},
        "anonymous": uid is None,
        "isTokenMember": False,
        "wsUrl": config.ws_url,
        "wsRetryHandshake": config.ws_retry_handshake,
        "maxDocLength": config.max_doc_length,
        "defaultLatexCompiler": config.default_compiler,
        "languages": config.languages,
        "compiler": project.get("compiler", "pdflatex"),
        "imageName": project.get("imageName"),
        "rootDocId": str(project["rootDoc_id"]) if project.get("rootDoc_id") else None,
        "publicAccesLevel": project.get("publicAccesLevel", "private"),
        "otMigrationStage": history.get("otMigrationStage", 0),
    }


# --- docstore bridge ----------------------------------------------------- #
class DocstoreClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http or httpx.AsyncClient()

    async def get_doc(self, project_id: str, doc_id: str) -> dict | None:
        resp = await self.http.get(f"{self.base_url}/project/{project_id}/doc/{doc_id}")
        if resp.status_code == 200:
            return resp.json()
        return None

    async def update_doc(self, project_id: str, doc_id: str, lines: list, version: int = 0, ranges: dict | None = None) -> None:
        await self.http.post(
            f"{self.base_url}/project/{project_id}/doc/{doc_id}",
            json={"lines": lines, "version": version, "ranges": ranges or {}},
        )

    async def delete_doc(self, project_id: str, doc_id: str, name: str, deleted_at: str) -> None:
        await self.http.request(
            "PATCH",
            f"{self.base_url}/project/{project_id}/doc/{doc_id}",
            json={"deleted": True, "name": name, "deletedAt": deleted_at},
        )


def register_editor_routes(app: FastAPI, *, pm: ProjectManager, db, store, config, docstore: DocstoreClient) -> None:
    @app.get("/project/{project_id}")
    async def load_editor(project_id: str, request: Request):
        # Browsers (Accept: text/html) get the editor page; the page's JS then
        # fetches this same URL with ?format=json for the bootstrap data.
        wants_html = "text/html" in request.headers.get("accept", "") and request.query_params.get("format") != "json"
        if wants_html:
            return HTMLResponse(EDITOR_PAGE)
        loaded, err = await load_with_access(request, project_id, pm=pm, store=store, config=config, check=can_read)
        if err:
            return err
        uid, project = loaded
        user = await db["users"].find_one({"_id": ObjectId(uid)})
        return JSONResponse(build_bootstrap(project, user, uid, config))

    @app.post("/project/{project_id}/doc/{doc_id}")
    async def save_document(project_id: str, doc_id: str, request: Request):
        loaded, err = await load_with_access(request, project_id, pm=pm, store=store, config=config, check=can_write)
        if err:
            return err
        _uid, project = loaded
        if find_doc_pathname(project, doc_id) is None:
            return Response(status_code=404)
        body = await request.json()
        lines = body.get("lines")
        if lines is None:
            lines = (body.get("content") or "").split("\n")
        await docstore.update_doc(project_id, doc_id, lines, body.get("version", 0), body.get("ranges", {}))
        return JSONResponse({"saved": True})

    @app.get("/project/{project_id}/entities")
    async def project_entities(project_id: str, request: Request):
        loaded, err = await load_with_access(request, project_id, pm=pm, store=store, config=config, check=can_read)
        if err:
            return err
        _uid, project = loaded
        return JSONResponse({"project_id": project_id, "entities": list_entities(project)})

    @app.get("/project/{project_id}/tree")
    async def project_tree(project_id: str, request: Request):
        # Like /entities but includes entity ids — used by the Fleetex frontend.
        loaded, err = await load_with_access(request, project_id, pm=pm, store=store, config=config, check=can_read)
        if err:
            return err
        _uid, project = loaded
        return JSONResponse({"project_id": project_id, "entities": list_entities_with_ids(project)})

    @app.get("/project/{project_id}/doc/{doc_id}")
    async def get_document(project_id: str, doc_id: str, request: Request):
        loaded, err = await load_with_access(request, project_id, pm=pm, store=store, config=config, check=can_read)
        if err:
            return err
        _uid, project = loaded
        pathname = find_doc_pathname(project, doc_id)
        if pathname is None:
            return Response(status_code=404)
        doc = await docstore.get_doc(project_id, doc_id)
        if doc is None:
            # Auto-heal: the doc is registered in the project tree but has no
            # stored content (legacy/pre-seed projects, or a lost doc). Returning
            # 404 left the editor unable to open it — so it couldn't be saved or
            # compiled. Seed the default template (empty for non-.tex) and serve
            # it, persisting to docstore so compile sees it too.
            lines = list(DEFAULT_DOC_LINES) if pathname.endswith(".tex") else [""]
            try:
                await docstore.update_doc(project_id, doc_id, lines, 1)
            except Exception:  # noqa: BLE001 - healing is best-effort
                pass
            doc = {"lines": lines, "version": 1, "ranges": {}}
        if request.query_params.get("plain") == "true":
            return PlainTextResponse("\n".join(doc.get("lines", [])))
        return JSONResponse({
            "lines": doc.get("lines", []),
            "version": doc.get("version", 0),
            "ranges": doc.get("ranges", {}),
            "pathname": pathname,
            "otMigrationStage": 0,
            "resolvedCommentIds": [],
        })
