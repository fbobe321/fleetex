"""HTTP layer for project-history.

Routes:
* POST   /project/:id/doc/:doc/version        record a snapshot (dedup vs latest)
* GET    /project/:id/versions                project timeline (metadata, newest first)
* GET    /project/:id/doc/:doc/versions       one doc's timeline
* GET    /project/:id/version/:v              a version's full content
* GET    /project/:id/doc/:doc/diff?from&to   segment diff between two versions
* POST   /project/:id/doc/:doc/restore/:v     restore a past version into the live doc
* DELETE /project/:id                         purge a project's history
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fleetex_service_kit import Settings, create_app

from . import diff as diffmod
from .doc_updater_client import DocUpdaterClient
from .history import HistoryManager


def _now_ms() -> int:
    return int(time.time() * 1000)


def _int_param(request: Request, name: str) -> int | None:
    raw = request.query_params.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def build_app(settings: Settings | None = None, *, doc_updater: DocUpdaterClient | None = None) -> FastAPI:
    settings = settings or Settings.from_env("project-history", default_port=3054)
    app = create_app(settings, connect_redis=False, status_text="project-history is alive")

    du_url = os.environ.get("DOCUMENT_UPDATER_URL", "http://document-updater:3003")
    app.state.doc_updater = doc_updater if doc_updater is not None else DocUpdaterClient(du_url)

    def _hm(request: Request) -> HistoryManager:
        return HistoryManager(request.app.state.db)

    @app.get("/health_check")
    async def health_check():
        return Response(status_code=200)

    # ---- record ---------------------------------------------------------- #
    @app.post("/project/{project_id}/doc/{doc_id}/version")
    async def record_version(project_id: str, doc_id: str, request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict) or not isinstance(body.get("content"), str):
            return JSONResponse({"message": "content (string) is required"}, status_code=400)
        result = await _hm(request).record_version(
            project_id, doc_id, body["content"],
            pathname=body.get("pathname", ""), user_id=body.get("user_id"),
            source=body.get("source", "save"), ts=body.get("ts") or _now_ms(),
        )
        return JSONResponse(result, status_code=201 if result["created"] else 200)

    # ---- timelines ------------------------------------------------------- #
    @app.get("/project/{project_id}/versions")
    async def project_versions(project_id: str, request: Request):
        limit = _int_param(request, "limit") or 50
        before = _int_param(request, "before")
        versions = await _hm(request).list_project_versions(project_id, limit=min(limit, 500), before=before)
        return JSONResponse({"versions": versions})

    @app.get("/project/{project_id}/doc/{doc_id}/versions")
    async def doc_versions(project_id: str, doc_id: str, request: Request):
        versions = await _hm(request).list_doc_versions(project_id, doc_id)
        return JSONResponse({"versions": versions})

    @app.get("/project/{project_id}/version/{v}")
    async def get_version(project_id: str, v: int, request: Request):
        version = await _hm(request).get_version(project_id, v)
        if version is None:
            return Response(status_code=404)
        return JSONResponse(version)

    # ---- diff ------------------------------------------------------------ #
    @app.get("/project/{project_id}/doc/{doc_id}/diff")
    async def doc_diff(project_id: str, doc_id: str, request: Request):
        hm = _hm(request)
        to_v = _int_param(request, "to")
        to_doc = await hm.get_doc_version(project_id, doc_id, to_v) if to_v is not None else await hm.latest_doc_version(project_id, doc_id)
        if to_doc is None:
            return Response(status_code=404)
        to_content = to_doc.get("content", "")
        to_version = to_doc["v"] if "v" in to_doc else to_doc.get("version")
        from_v = _int_param(request, "from")
        if from_v is not None:
            from_doc = await hm.get_doc_version(project_id, doc_id, from_v)
        else:
            from_doc = await hm.version_before(project_id, doc_id, to_version)
        from_content = from_doc.get("content", "") if from_doc else ""
        from_version = (from_doc.get("version") if from_doc else None)
        segments = diffmod.segment_diff(from_content, to_content)
        return JSONResponse({
            "from": from_version,
            "to": to_version,
            "diff": segments,
            "stats": diffmod.diff_stats(segments),
            "unified": diffmod.unified(from_content, to_content, from_label=f"v{from_version}", to_label=f"v{to_version}"),
        })

    # ---- restore --------------------------------------------------------- #
    @app.post("/project/{project_id}/doc/{doc_id}/restore/{v}")
    async def restore_version(project_id: str, doc_id: str, v: int, request: Request):
        hm = _hm(request)
        version = await hm.get_doc_version(project_id, doc_id, v)
        if version is None:
            return Response(status_code=404)
        try:
            body = await request.json()
        except Exception:
            body = {}
        user_id = (body or {}).get("user_id")
        content = version["content"]
        pushed = await request.app.state.doc_updater.set_doc(project_id, doc_id, content, user_id)
        recorded = await hm.record_version(
            project_id, doc_id, content, pathname=version.get("pathname", ""),
            user_id=user_id, source="restore", ts=_now_ms(),
        )
        return JSONResponse({"restoredFrom": v, "pushed": pushed, **recorded})

    # ---- purge ----------------------------------------------------------- #
    @app.delete("/project/{project_id}")
    async def delete_project(project_id: str, request: Request):
        await _hm(request).delete_project(project_id)
        return Response(status_code=204)

    return app


app = build_app()
