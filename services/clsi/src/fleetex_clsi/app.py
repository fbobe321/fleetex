"""HTTP layer — port of app.js routes + CompileController response assembly.

Param validation: project_id ~ /^[a-zA-Z0-9_-]+$/, user_id ~ /^[0-9a-f]{24}$/
(invalid -> 500, matching Node's generic handler). Compile always returns a
``{compile: {...}}`` envelope; lock/conflict errors set the status + HTTP code.
"""

from __future__ import annotations

import re

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fleetex_service_kit import Settings, create_app

from . import request_parser
from .compile_manager import CompileManager, CompileResult
from .config import ClsiConfig
from .errors import (
    AlreadyCompilingError,
    ClsiError,
    FilesOutOfSyncError,
    InvalidRequestError,
    NotFoundError,
    TooManyCompileRequestsError,
)

_PROJECT_ID = re.compile(r"^[a-zA-Z0-9_-]+$")
_USER_ID = re.compile(r"^[0-9a-f]{24}$")


class _Invalid(Exception):
    pass


def _validate(project_id: str, user_id: str | None = None) -> None:
    if not _PROJECT_ID.match(project_id):
        raise _Invalid("invalid project id")
    if user_id is not None and not _USER_ID.match(user_id):
        raise _Invalid("invalid user id")


def build_compile_response(config: ClsiConfig, project_id: str, user_id: str | None, result: CompileResult) -> dict:
    user_seg = f"/user/{user_id}" if user_id else ""
    output_files = []
    for f in result.output_files:
        entry = {
            "path": f["path"],
            "url": f"{config.download_host}/project/{project_id}{user_seg}/build/{f['build']}/output/{f['path']}",
            "type": f.get("type"),
            "build": f["build"],
        }
        if "size" in f:
            entry["size"] = f["size"]
        output_files.append(entry)
    return {
        "compile": {
            "status": result.status,
            "error": None,
            "stats": result.stats,
            "timings": result.timings,
            "buildId": result.build_id,
            "outputUrlPrefix": config.output_url_prefix,
            "instanceType": config.instance_type,
            "zone": config.zone,
            "isSpotInstance": config.is_spot_instance,
            "outputFiles": output_files,
        }
    }


def build_app(config: ClsiConfig | None = None, *, runner=None) -> FastAPI:
    config = config or ClsiConfig.from_env()
    settings = Settings.from_env("clsi", default_port=config.port, env={})
    app = create_app(settings, connect_mongo=False, connect_redis=False, status_text="CLSI is alive\n")
    manager = CompileManager(config, runner=runner)
    app.state.config = config
    app.state.manager = manager

    @app.exception_handler(_Invalid)
    async def _invalid(request, exc):
        return PlainTextResponse("Oops, something went wrong", status_code=500)

    @app.exception_handler(NotFoundError)
    async def _not_found(request, exc):
        return PlainTextResponse("Not Found", status_code=404)

    async def _compile(project_id: str, user_id: str | None, request: Request):
        _validate(project_id, user_id)
        body = await request.json()
        try:
            parsed = request_parser.parse(body)
            result = manager.run_compile(project_id, user_id, parsed)
        except (AlreadyCompilingError, TooManyCompileRequestsError, FilesOutOfSyncError) as exc:
            return JSONResponse(
                {"compile": {"status": exc.compile_status, "error": str(exc), "outputFiles": []}},
                status_code=exc.http_status,
            )
        except InvalidRequestError:
            return PlainTextResponse("Oops, something went wrong", status_code=500)
        return JSONResponse(build_compile_response(config, project_id, user_id, result))

    @app.post("/project/{project_id}/compile")
    async def compile_project(project_id: str, request: Request):
        return await _compile(project_id, None, request)

    @app.post("/project/{project_id}/user/{user_id}/compile")
    async def compile_project_user(project_id: str, user_id: str, request: Request):
        return await _compile(project_id, user_id, request)

    @app.post("/project/{project_id}/compile/stop")
    async def stop_project(project_id: str):
        _validate(project_id)
        manager.stop_compile(project_id, None)
        return Response(status_code=204)

    @app.post("/project/{project_id}/user/{user_id}/compile/stop")
    async def stop_project_user(project_id: str, user_id: str):
        _validate(project_id, user_id)
        manager.stop_compile(project_id, user_id)
        return Response(status_code=204)

    @app.delete("/project/{project_id}")
    async def clear_project(project_id: str):
        _validate(project_id)
        manager.clear_project(project_id, None)
        return Response(status_code=204)

    @app.delete("/project/{project_id}/user/{user_id}")
    async def clear_project_user(project_id: str, user_id: str):
        _validate(project_id, user_id)
        manager.clear_project(project_id, user_id)
        return Response(status_code=204)

    # -- synctex / wordcount (shell out; needs TeX) ----------------------- #
    def _sync_code(project_id, user_id, request):
        _validate(project_id, user_id)
        q = request.query_params
        hits = manager.synctex_from_code(project_id, user_id, q["file"], int(q["line"]), int(q["column"]))
        return JSONResponse({"pdf": hits, "downloadedFromCache": False})

    def _sync_pdf(project_id, user_id, request):
        _validate(project_id, user_id)
        q = request.query_params
        hits = manager.synctex_from_pdf(project_id, user_id, int(q["page"]), float(q["h"]), float(q["v"]))
        return JSONResponse({"code": hits, "downloadedFromCache": False})

    def _wordcount(project_id, user_id, request):
        _validate(project_id, user_id)
        filename = request.query_params.get("file", "main.tex")
        return JSONResponse({"texcount": manager.wordcount(project_id, user_id, filename)})

    @app.get("/project/{project_id}/sync/code")
    async def sync_code(project_id: str, request: Request):
        return _sync_code(project_id, None, request)

    @app.get("/project/{project_id}/user/{user_id}/sync/code")
    async def sync_code_user(project_id: str, user_id: str, request: Request):
        return _sync_code(project_id, user_id, request)

    @app.get("/project/{project_id}/sync/pdf")
    async def sync_pdf(project_id: str, request: Request):
        return _sync_pdf(project_id, None, request)

    @app.get("/project/{project_id}/user/{user_id}/sync/pdf")
    async def sync_pdf_user(project_id: str, user_id: str, request: Request):
        return _sync_pdf(project_id, user_id, request)

    @app.get("/project/{project_id}/wordcount")
    async def wordcount(project_id: str, request: Request):
        return _wordcount(project_id, None, request)

    @app.get("/project/{project_id}/user/{user_id}/wordcount")
    async def wordcount_user(project_id: str, user_id: str, request: Request):
        return _wordcount(project_id, user_id, request)

    # -- status ----------------------------------------------------------- #
    @app.get("/project/{project_id}/status")
    @app.post("/project/{project_id}/status")
    async def project_status(project_id: str):
        return PlainTextResponse("OK")

    @app.get("/health_check")
    async def health_check():
        return Response(status_code=200)

    return app


app = build_app()
