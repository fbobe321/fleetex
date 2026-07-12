"""HTTP layer — port of HttpController.js + app.js route table.

Validation: :project_id / :doc_id must be 24-hex (else 500 'invalid ... id').
Error map: NotFoundError->404, DocModifiedError->409, DocVersionDecrementedError
->409, else->500. updateDoc body validation -> 400/413.
"""

from __future__ import annotations

import re

from bson import ObjectId
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fleetex_service_kit import Settings, create_app

from .archive import DocArchiveManager, FSArchiveStore, InMemoryArchiveStore
from .config import DocstoreConfig
from .constants import MAX_DOC_LENGTH
from .docmanager import DocManager
from .errors import (
    DocModifiedError,
    DocVersionDecrementedError,
    NotFoundError,
)
from .mongo import MongoManager
from .serialize import build_doc_view, encode

_HEX24 = re.compile(r"^[0-9a-f]{24}$")


def _ids(project_id: str, doc_id: str | None = None):
    if not _HEX24.match(project_id):
        raise _Invalid("invalid project id")
    if doc_id is not None and not _HEX24.match(doc_id):
        raise _Invalid("invalid doc id")


class _Invalid(Exception):
    pass


def build_app(config: DocstoreConfig | None = None, *, store=None) -> FastAPI:
    config = config or DocstoreConfig.from_env()
    settings = Settings.from_env("docstore", default_port=config.port, env={})
    app = create_app(settings, connect_redis=False, status_text="docstore is alive")

    if store is None and config.backend:
        store = FSArchiveStore(config.archive_path) if config.backend == "fs" else InMemoryArchiveStore()
    app.state.config = config
    app.state.archive_store = store

    def _dm(request: Request) -> DocManager:
        mongo = MongoManager(request.app.state.db)
        archive = DocArchiveManager(mongo, request.app.state.archive_store, config.bucket, config.backend)
        return DocManager(mongo, archive)

    # ---- error mapping ---------------------------------------------------- #
    @app.exception_handler(_Invalid)
    async def _invalid(request, exc):
        return PlainTextResponse("Oops, something went wrong", status_code=500)

    @app.exception_handler(NotFoundError)
    async def _nf(request, exc):
        return Response(status_code=404)

    @app.exception_handler(DocModifiedError)
    async def _dm_mod(request, exc):
        return PlainTextResponse(str(exc), status_code=409)

    @app.exception_handler(DocVersionDecrementedError)
    async def _dvd(request, exc):
        return PlainTextResponse(str(exc), status_code=409)

    # ---- single-doc reads ------------------------------------------------- #
    @app.get("/project/{project_id}/doc/{doc_id}")
    async def get_doc(project_id: str, doc_id: str, request: Request):
        _ids(project_id, doc_id)
        include_deleted = request.query_params.get("include_deleted") == "true"
        doc = await _dm(request).get_full_doc(project_id, doc_id)
        if doc.get("deleted") and not include_deleted:
            return Response(status_code=404)
        return JSONResponse(build_doc_view(doc))

    @app.get("/project/{project_id}/doc/{doc_id}/peek")
    async def peek_doc(project_id: str, doc_id: str, request: Request):
        _ids(project_id, doc_id)
        doc, status = await _dm(request).peek_doc(project_id, doc_id)
        return JSONResponse(build_doc_view(doc), headers={"x-doc-status": status})

    @app.get("/project/{project_id}/doc/{doc_id}/raw")
    async def get_raw_doc(project_id: str, doc_id: str, request: Request):
        _ids(project_id, doc_id)
        text = await _dm(request).get_doc_lines(project_id, doc_id)
        return PlainTextResponse(text)

    @app.get("/project/{project_id}/doc/{doc_id}/deleted")
    async def is_doc_deleted(project_id: str, doc_id: str, request: Request):
        _ids(project_id, doc_id)
        return JSONResponse({"deleted": await _dm(request).is_doc_deleted(project_id, doc_id)})

    # ---- project-level reads --------------------------------------------- #
    @app.get("/project/{project_id}/doc")
    async def get_all_docs(project_id: str, request: Request):
        _ids(project_id)
        docs = await _dm(request).get_all_non_deleted_docs(project_id, {"lines": 1, "rev": 1})
        return JSONResponse([build_doc_view(d) for d in docs])

    @app.get("/project/{project_id}/doc-with-ranges")
    async def get_all_docs_with_ranges(project_id: str, request: Request):
        _ids(project_id)
        docs = await _dm(request).get_all_non_deleted_docs(project_id, {"lines": 1, "rev": 1, "ranges": 1})
        return JSONResponse([build_doc_view(d) for d in docs])

    @app.get("/project/{project_id}/ranges")
    async def get_all_ranges(project_id: str, request: Request):
        _ids(project_id)
        docs = await _dm(request).get_all_ranges(project_id)
        return JSONResponse([build_doc_view(d) for d in docs])

    @app.get("/project/{project_id}/doc-versions")
    async def get_all_doc_versions(project_id: str, request: Request):
        _ids(project_id)
        docs = await MongoManager(request.app.state.db).get_all_doc_versions(project_id)
        return JSONResponse(encode(docs))

    @app.get("/project/{project_id}/doc-deleted")
    async def get_all_deleted_docs(project_id: str, request: Request):
        _ids(project_id)
        docs = await MongoManager(request.app.state.db).get_projects_deleted_docs(
            project_id, {"name": 1, "deletedAt": 1}
        )
        return JSONResponse(
            [{"_id": str(d["_id"]), "name": d.get("name"), "deletedAt": encode(d.get("deletedAt"))} for d in docs]
        )

    @app.get("/project/{project_id}/comment-thread-ids")
    async def get_comment_thread_ids(project_id: str, request: Request):
        _ids(project_id)
        return JSONResponse(await _dm(request).get_comment_thread_ids(project_id))

    @app.get("/project/{project_id}/tracked-changes-user-ids")
    async def get_tracked_changes_user_ids(project_id: str, request: Request):
        _ids(project_id)
        return JSONResponse(await _dm(request).get_tracked_changes_user_ids(project_id))

    @app.get("/project/{project_id}/has-ranges")
    async def project_has_ranges(project_id: str, request: Request):
        _ids(project_id)
        return JSONResponse({"projectHasRanges": await _dm(request).project_has_ranges(project_id)})

    # ---- writes ----------------------------------------------------------- #
    @app.post("/project/{project_id}/doc/{doc_id}")
    async def update_doc(project_id: str, doc_id: str, request: Request):
        _ids(project_id, doc_id)
        body = await request.json()
        lines, version, ranges = body.get("lines"), body.get("version"), body.get("ranges")
        if lines is None or not isinstance(lines, list):
            return Response(status_code=400)
        if version is None or not isinstance(version, (int, float)) or isinstance(version, bool):
            return Response(status_code=400)
        if ranges is None:
            return Response(status_code=400)
        if sum(len(line) for line in lines) > MAX_DOC_LENGTH:
            return PlainTextResponse("document body too large", status_code=413)
        modified, rev = await _dm(request).update_doc(project_id, doc_id, lines, version, ranges)
        return JSONResponse({"modified": modified, "rev": rev})

    @app.patch("/project/{project_id}/doc/{doc_id}")
    async def patch_doc(project_id: str, doc_id: str, request: Request):
        _ids(project_id, doc_id)
        body = await request.json()
        # strict schema: deleted==true, deletedAt (date), name (str); extras rejected
        allowed = {"deleted", "deletedAt", "name"}
        if body.get("deleted") is not True or not set(body).issubset(allowed):
            return Response(status_code=400)
        meta = {"deleted": True}
        if "deletedAt" in body:
            meta["deletedAt"] = body["deletedAt"]
        if "name" in body:
            meta["name"] = body["name"]
        await _dm(request).patch_doc(project_id, doc_id, meta, config.archive_on_soft_delete)
        return Response(status_code=204)

    @app.delete("/project/{project_id}/doc/{doc_id}")
    async def delete_doc_deprecated(project_id: str, doc_id: str):
        return PlainTextResponse(
            "DELETE-ing a doc is DEPRECATED. PATCH the doc instead.", status_code=500
        )

    # ---- archive / destroy ------------------------------------------------ #
    @app.post("/project/{project_id}/archive")
    async def archive_all(project_id: str, request: Request):
        _ids(project_id)
        await _dm(request).archive.archive_all_docs(project_id)
        return Response(status_code=204)

    @app.post("/project/{project_id}/doc/{doc_id}/archive")
    async def archive_one(project_id: str, doc_id: str, request: Request):
        _ids(project_id, doc_id)
        await _dm(request).archive.archive_doc(project_id, doc_id)
        return Response(status_code=204)

    @app.post("/project/{project_id}/unarchive")
    async def unarchive_all(project_id: str, request: Request):
        _ids(project_id)
        await _dm(request).archive.unarchive_all_docs(project_id, config.keep_soft_deleted_docs_archived)
        return Response(status_code=200)  # note: 200, not 204

    @app.post("/project/{project_id}/destroy")
    async def destroy_project(project_id: str, request: Request):
        _ids(project_id)
        dm = _dm(request)
        await dm.mongo.destroy_project(project_id)
        await dm.archive.destroy_project(project_id)
        return Response(status_code=204)

    @app.get("/health_check")
    async def health_check():
        return Response(status_code=200)

    return app


app = build_app()
