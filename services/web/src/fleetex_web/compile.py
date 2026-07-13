"""Compile — gather the project's docs, call clsi, proxy the output PDF.

Port-ish of web's CompileController/ClsiManager (a functional subset): walk the
project tree for docs, fetch each doc's *live* content from document-updater
(Redis-authoritative, docstore fallback), build the clsi compile request, and
rewrite the returned output-file URLs to web-proxied paths so the browser fetches
the PDF from a single origin.
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .projects import ProjectManager, can_read, load_with_access


def _doc_entities(project: dict) -> list[tuple[str, str]]:
    """(doc_id, path) for every doc in the tree (paths absolute-from-root)."""
    out: list[tuple[str, str]] = []

    def walk(folder: dict, prefix: str) -> None:
        for doc in folder.get("docs", []):
            out.append((str(doc["_id"]), f"{prefix}/{doc['name']}"))
        for sub in folder.get("folders", []):
            walk(sub, f"{prefix}/{sub['name']}")

    root = (project.get("rootFolder") or [{}])[0]
    walk(root, "")
    return out


def _file_entities(project: dict) -> list[tuple[str, str]]:
    """(file_id, path) for every binary file (fileRef) in the tree."""
    out: list[tuple[str, str]] = []

    def walk(folder: dict, prefix: str) -> None:
        for f in folder.get("fileRefs", []):
            out.append((str(f["_id"]), f"{prefix}/{f['name']}"))
        for sub in folder.get("folders", []):
            walk(sub, f"{prefix}/{sub['name']}")

    root = (project.get("rootFolder") or [{}])[0]
    walk(root, "")
    return out


class ClsiManager:
    def __init__(self, clsi_url: str, document_updater_url: str, filestore_url: str = "", http: httpx.AsyncClient | None = None) -> None:
        self.clsi_url = clsi_url.rstrip("/")
        self.du_url = document_updater_url.rstrip("/")
        self.filestore_url = (filestore_url or "").rstrip("/")
        self.http = http or httpx.AsyncClient(timeout=60)

    async def _doc_content(self, project_id: str, doc_id: str) -> str:
        resp = await self.http.get(f"{self.du_url}/project/{project_id}/doc/{doc_id}")
        if resp.status_code == 200:
            return "\n".join(resp.json().get("lines", []))
        return ""

    async def compile(self, project_id: str, project: dict) -> dict:
        root_doc_id = str(project.get("rootDoc_id")) if project.get("rootDoc_id") else None
        resources = []
        root_path = None
        for doc_id, path in _doc_entities(project):
            rel = path.lstrip("/")
            resources.append({"path": rel, "content": await self._doc_content(project_id, doc_id)})
            if doc_id == root_doc_id:
                root_path = rel
        # binary files: clsi fetches them from filestore by URL (e.g. \includegraphics)
        for file_id, path in _file_entities(project):
            if self.filestore_url:
                resources.append({"path": path.lstrip("/"), "url": f"{self.filestore_url}/project/{project_id}/file/{file_id}"})
        body = {
            "compile": {
                "options": {"compiler": project.get("compiler", "pdflatex")},
                "rootResourcePath": root_path or "main.tex",
                "resources": resources,
            }
        }
        resp = await self.http.post(f"{self.clsi_url}/project/{project_id}/compile", json=body)
        return resp.json()

    async def get_output(self, project_id: str, build_id: str, file_path: str):
        return await self.http.get(f"{self.clsi_url}/project/{project_id}/build/{build_id}/output/{file_path}")


def register_compile_routes(app: FastAPI, *, pm: ProjectManager, store, config, clsi: ClsiManager) -> None:
    @app.post("/project/{project_id}/compile")
    async def compile_project(project_id: str, request: Request):
        loaded, err = await load_with_access(request, project_id, pm=pm, store=store, config=config, check=can_read)
        if err:
            return err
        _uid, project = loaded
        result = await clsi.compile(project_id, project)
        # rewrite output-file URLs to web-proxied, single-origin paths
        for f in result.get("compile", {}).get("outputFiles", []):
            if f.get("build") and f.get("path"):
                f["url"] = f"/project/{project_id}/output/{f['build']}/{f['path']}"
        return JSONResponse(result)

    @app.get("/project/{project_id}/output/{build_id}/{file_path:path}")
    async def get_output(project_id: str, build_id: str, file_path: str, request: Request):
        loaded, err = await load_with_access(request, project_id, pm=pm, store=store, config=config, check=can_read)
        if err:
            return err
        resp = await clsi.get_output(project_id, build_id, file_path)
        if resp.status_code != 200:
            return Response(status_code=404)
        return Response(resp.content, media_type=resp.headers.get("content-type", "application/octet-stream"))
