"""HTTP layer — port of app.js routes + FileController.js.

Key fidelity points:
* Range requests return **200** with the sliced bytes and NO range headers
  (Overleaf does not implement HTTP 206 here).
* GET sets no Content-Type/ETag/Accept-Ranges; HEAD sets only Content-Length.
* Missing -> 404 (empty); any other error -> 500 with the message as plain text.
* Literal bodies: /status -> "filestore is up", /health_check & POST & cacheWarm -> "OK".
"""

from __future__ import annotations

import os
import re
from typing import Iterator

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse, RedirectResponse, StreamingResponse
from fleetex_service_kit import Settings, create_app

from .config import FilestoreConfig
from .errors import NotFoundError, PersistorError
from .filehandler import FileHandler
from .keybuilder import (
    KeySpec,
    bucket_file_key,
    global_blob_key,
    project_blob_key,
    template_file_key,
)
from .persistor import create_persistor

_RANGE_MAX = 1024 * 1024 * 1024  # 1 GiB ceiling, matching FileController._getRange
_RANGE_RE = re.compile(r"^(\d*)-(\d*)$")


def _parse_range(header: str | None) -> tuple[int, int] | None:
    """Parse the first `bytes=` range; return (start, end) inclusive or None."""
    if not header or not header.startswith("bytes="):
        return None
    spec = header[len("bytes="):].split(",")[0].strip()
    m = _RANGE_RE.match(spec)
    if not m:
        return None
    s, e = m.group(1), m.group(2)
    if s == "" and e == "":
        return None
    if s == "":  # suffix
        length = int(e)
        if length <= 0:
            return None
        start, end = _RANGE_MAX - length, _RANGE_MAX - 1
    elif e == "":
        start, end = int(s), _RANGE_MAX - 1
    else:
        start, end = int(s), int(e)
    if start < 0 or start > end:
        return None
    return start, end


def _file_iter(path: str, cleanup: bool = True) -> Iterator[bytes]:
    try:
        with open(path, "rb") as fh:
            while True:
                data = fh.read(64 * 1024)
                if not data:
                    break
                yield data
    finally:
        if cleanup:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass


def build_app(config: FilestoreConfig | None = None) -> FastAPI:
    config = config or FilestoreConfig.from_env()
    settings = Settings.from_env("filestore", default_port=config.port, env={})
    app = create_app(
        settings, connect_mongo=False, connect_redis=False, status_text="filestore is up"
    )
    persistor = create_persistor(config)
    handler = FileHandler(persistor, config)
    app.state.config = config
    app.state.persistor = persistor
    app.state.handler = handler

    # ---- error mapping (404 for NotFound, else 500 plain-text message) ---- #
    @app.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError) -> Response:
        return Response(status_code=404)

    @app.exception_handler(PersistorError)
    async def _persistor_error(request: Request, exc: PersistorError) -> PlainTextResponse:
        return PlainTextResponse(str(exc), status_code=500)

    # ---- shared handlers -------------------------------------------------- #
    async def _get(request: Request, spec: KeySpec) -> Response:
        q = request.query_params
        fmt, style, cache_warm = q.get("format"), q.get("style"), q.get("cacheWarm")
        rng = _parse_range(request.headers.get("range"))
        url = handler.get_redirect_url(
            spec.bucket,
            spec.key,
            {"start": rng[0] if rng else None, "end": rng[1] if rng else None, "format": fmt, "style": style},
        )
        if url:
            return RedirectResponse(url, status_code=302)

        if fmt or style:
            png = await handler.get_converted_file_path(spec.bucket, spec.key, fmt, style)
            if cache_warm:
                os.remove(png)
                return PlainTextResponse("OK")
            return StreamingResponse(_file_iter(png), status_code=200, media_type=None)

        if cache_warm:
            persistor.get_object_size(spec.bucket, spec.key, spec.use_subdirectories)  # 404 if missing
            return PlainTextResponse("OK")

        start, end = rng if rng else (None, None)
        gen = persistor.get_object_stream(spec.bucket, spec.key, start, end, spec.use_subdirectories)
        return StreamingResponse(gen, status_code=200, media_type=None)

    def _head(spec: KeySpec) -> Response:
        size = persistor.get_object_size(spec.bucket, spec.key, spec.use_subdirectories)
        return Response(status_code=200, headers={"Content-Length": str(size)})

    async def _insert(request: Request, spec: KeySpec) -> Response:
        await handler.insert_file(spec.bucket, spec.key, request.stream())
        return PlainTextResponse("OK", status_code=200)

    # ---- template routes (registered when template_files store is set) ---- #
    if config.stores.get("template_files"):

        @app.head("/template/{template_id}/v/{version}/{fmt}")
        async def template_head(template_id: str, version: str, fmt: str):
            return _head(template_file_key(config.stores, template_id, version, fmt))

        @app.get("/template/{template_id}/v/{version}/{fmt}")
        async def template_get(template_id: str, version: str, fmt: str, request: Request):
            return await _get(request, template_file_key(config.stores, template_id, version, fmt))

        @app.get("/template/{template_id}/v/{version}/{fmt}/{sub_type}")
        async def template_get_sub(template_id: str, version: str, fmt: str, sub_type: str, request: Request):
            return await _get(request, template_file_key(config.stores, template_id, version, fmt, sub_type))

        @app.post("/template/{template_id}/v/{version}/{fmt}")
        async def template_post(template_id: str, version: str, fmt: str, request: Request):
            return await _insert(request, template_file_key(config.stores, template_id, version, fmt))

    # ---- generic bucket passthrough --------------------------------------- #
    @app.get("/bucket/{bucket}/key/{key:path}")
    async def bucket_get(bucket: str, key: str, request: Request):
        return await _get(request, bucket_file_key(bucket, key))

    # ---- history blobs ---------------------------------------------------- #
    @app.get("/history/global/hash/{hash}")
    async def global_blob_get(hash: str, request: Request):
        return await _get(request, global_blob_key(config.stores, hash))

    @app.get("/history/project/{history_id}/hash/{hash}")
    async def project_blob_get(history_id: str, hash: str, request: Request):
        return await _get(request, project_blob_key(config.stores, history_id, hash))

    # ---- operational ------------------------------------------------------ #
    @app.get("/health_check")
    async def health_check():
        return PlainTextResponse("OK")

    return app


app = build_app()
