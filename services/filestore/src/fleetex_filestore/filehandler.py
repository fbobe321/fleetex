"""Orchestration — port of FileHandler.js (insert, get-with-conversion, redirect).

Delegates storage to the persistor and conversion to ``converter``. The redirect
gate matches getRedirectUrl: only for the named store buckets, only when
allow_redirects is set, and only when no range/format/style is requested (the fs
backend always returns None anyway).
"""

from __future__ import annotations

import os
import tempfile
from typing import AsyncIterator

from . import converter
from .config import FilestoreConfig
from .errors import InvalidParametersError
from .keybuilder import add_caching_to_key, validate_insert_key


class FileHandler:
    def __init__(self, persistor, config: FilestoreConfig) -> None:
        self.persistor = persistor
        self.config = config

    async def insert_file(self, bucket: str, key: str, chunks: AsyncIterator[bytes]) -> None:
        if not validate_insert_key(key):
            raise InvalidParametersError(f"invalid file key {key!r}")
        await self.persistor.send_stream(bucket, key, chunks)

    def get_redirect_url(self, bucket, key, opts) -> str | None:
        if not self.config.allow_redirects:
            return None
        if opts.get("start") is not None or opts.get("end") is not None:
            return None
        if opts.get("format") or opts.get("style"):
            return None
        if bucket not in self.config.stores.values():
            return None
        return self.persistor.get_redirect_url(bucket, key)

    async def get_converted_file_path(self, bucket: str, key: str, fmt: str | None, style: str | None) -> str:
        """Return a local PNG path for the requested conversion, caching into storage.

        Mirrors _getConvertedFile: serve the cached object if present, else
        convert the source, cache the PNG back under the derived key, and return
        the local file to stream (dodging read-after-write).
        """
        cache_key = add_caching_to_key(key, fmt, style)
        if self.persistor.check_if_object_exists(bucket, cache_key):
            return self._download_to_temp(bucket, cache_key, suffix=".png")

        source = self._download_to_temp(bucket, key, suffix="")
        png_path = converter.convert_to_png(source, fmt, style, self.config.converter)
        os.remove(source)

        # Cache the PNG back into storage under the derived key.
        async def _iter():
            with open(png_path, "rb") as fh:
                while True:
                    data = fh.read(64 * 1024)
                    if not data:
                        break
                    yield data

        await self.persistor.send_stream(bucket, cache_key, _iter())
        return png_path

    def _download_to_temp(self, bucket: str, key: str, suffix: str) -> str:
        path = tempfile.mkstemp(suffix=suffix)[1]
        with open(path, "wb") as fh:
            for chunk in self.persistor.get_object_stream(bucket, key):
                fh.write(chunk)
        return path
