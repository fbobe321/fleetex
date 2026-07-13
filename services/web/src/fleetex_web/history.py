"""History — proxy the browser's history requests to the project-history service.

The browser only ever talks to web (single origin), so web forwards the
cookie-authorized history calls to project-history (an internal service). Reads
need read access; recording a version needs write access.
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .editor import find_doc_pathname
from .projects import ProjectManager, can_read, can_write, load_with_access


class HistoryProxy:
    def __init__(self, base_url: str, http: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http or httpx.AsyncClient(timeout=30)

    async def get(self, path: str, params: dict | None = None) -> httpx.Response:
        return await self.http.get(f"{self.base_url}{path}", params=params)

    async def post(self, path: str, json: dict | None = None) -> httpx.Response:
        return await self.http.post(f"{self.base_url}{path}", json=json)


def _forward(resp: httpx.Response) -> JSONResponse:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    return JSONResponse(body, status_code=resp.status_code)


def register_history_routes(app: FastAPI, *, pm: ProjectManager, db, store, config, history: HistoryProxy) -> None:
    async def _access(request: Request, project_id: str, check):
        return await load_with_access(request, project_id, pm=pm, store=store, config=config, check=check)

    # ---- doc timeline ---------------------------------------------------- #
    @app.get("/project/{project_id}/doc/{doc_id}/history")
    async def doc_history(project_id: str, doc_id: str, request: Request):
        _loaded, err = await _access(request, project_id, can_read)
        if err:
            return err
        return _forward(await history.get(f"/project/{project_id}/doc/{doc_id}/versions"))

    # ---- what-changed diff for a version --------------------------------- #
    @app.get("/project/{project_id}/doc/{doc_id}/history/diff")
    async def doc_diff(project_id: str, doc_id: str, request: Request):
        _loaded, err = await _access(request, project_id, can_read)
        if err:
            return err
        params = {k: request.query_params[k] for k in ("from", "to") if k in request.query_params}
        return _forward(await history.get(f"/project/{project_id}/doc/{doc_id}/diff", params=params))

    # ---- live diff: a version vs the caller's current buffer ------------- #
    @app.post("/project/{project_id}/doc/{doc_id}/history/diff-against/{v}")
    async def doc_diff_against(project_id: str, doc_id: str, v: int, request: Request):
        _loaded, err = await _access(request, project_id, can_read)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            body = {}
        content = body.get("content") if isinstance(body, dict) else None
        return _forward(await history.post(f"/project/{project_id}/doc/{doc_id}/diff-against/{v}", json={"content": content or ""}))

    # ---- full content of a version --------------------------------------- #
    @app.get("/project/{project_id}/history/version/{v}")
    async def version_content(project_id: str, v: int, request: Request):
        _loaded, err = await _access(request, project_id, can_read)
        if err:
            return err
        return _forward(await history.get(f"/project/{project_id}/version/{v}"))

    # ---- record a snapshot (called on save) ------------------------------ #
    @app.post("/project/{project_id}/doc/{doc_id}/history/version")
    async def record_version(project_id: str, doc_id: str, request: Request):
        loaded, err = await _access(request, project_id, can_write)
        if err:
            return err
        _uid, project = loaded
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict) or not isinstance(body.get("content"), str):
            return Response(status_code=400)
        pathname = find_doc_pathname(project, doc_id) or ""
        payload = {"content": body["content"], "pathname": pathname, "source": body.get("source", "save"), "user_id": _uid}
        return _forward(await history.post(f"/project/{project_id}/doc/{doc_id}/version", json=payload))
