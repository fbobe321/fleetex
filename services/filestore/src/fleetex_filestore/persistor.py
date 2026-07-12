"""Local-filesystem persistor — port of object-persistor's FSPersistor.

Path mapping (``_fs_path``): strip one trailing slash; if NOT using
subdirectories, replace every ``/`` in the key with ``_`` (flattened layout);
then ``join(location, key)``. History blobs use real subdirectories.

Writes are atomic (temp dir inside the bucket root + ``os.replace``). Missing
objects raise ``NotFoundError``; deleting a missing object is a no-op (mirrors S3).
"""

from __future__ import annotations

import glob as globmod
import hashlib
import os
import shutil
import tempfile
from typing import AsyncIterator, Iterator

from .errors import NotFoundError, NotImplementedFsError, WriteError

_CHUNK = 64 * 1024


class FSPersistor:
    def __init__(self, use_subdirectories: bool = False) -> None:
        self.use_subdirectories = use_subdirectories

    def _fs_path(self, location: str, key: str, use_subdirectories: bool) -> str:
        if key.endswith("/"):
            key = key[:-1]
        if not (self.use_subdirectories or use_subdirectories):
            key = key.replace("/", "_")
        return os.path.join(location, key)

    async def send_stream(
        self,
        location: str,
        key: str,
        chunks: AsyncIterator[bytes],
        use_subdirectories: bool = False,
        source_md5: str | None = None,
        if_none_match: str | None = None,
    ) -> None:
        if if_none_match == "*":
            raise NotImplementedFsError("ifNoneMatch is not supported by the fs backend")
        dest = self._fs_path(location, key, use_subdirectories)
        os.makedirs(location, exist_ok=True)
        tmp_dir = tempfile.mkdtemp(prefix="tmp-", dir=location)
        tmp_file = os.path.join(tmp_dir, "uploaded-file")
        md5 = hashlib.md5()
        try:
            with open(tmp_file, "wb") as fh:
                async for chunk in chunks:
                    fh.write(chunk)
                    md5.update(chunk)
            if source_md5 is not None and md5.hexdigest() != source_md5:
                raise WriteError("md5 hash mismatch")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            os.replace(tmp_file, dest)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def get_object_size(self, location: str, key: str, use_subdirectories: bool = False) -> int:
        path = self._fs_path(location, key, use_subdirectories)
        try:
            return os.stat(path).st_size
        except FileNotFoundError:
            raise NotFoundError(f"{path} not found")

    def get_object_stream(
        self,
        location: str,
        key: str,
        start: int | None = None,
        end: int | None = None,
        use_subdirectories: bool = False,
    ) -> Iterator[bytes]:
        path = self._fs_path(location, key, use_subdirectories)
        if not os.path.isfile(path):
            raise NotFoundError(f"{path} not found")

        def generator() -> Iterator[bytes]:
            with open(path, "rb") as fh:
                offset = start or 0
                if offset:
                    fh.seek(offset)
                # end is inclusive; None means read to EOF.
                remaining = (end - offset + 1) if end is not None else None
                while True:
                    to_read = _CHUNK if remaining is None else min(_CHUNK, remaining)
                    if to_read <= 0:
                        break
                    data = fh.read(to_read)
                    if not data:
                        break
                    if remaining is not None:
                        remaining -= len(data)
                    yield data

        return generator()

    def read_object(self, location: str, key: str, use_subdirectories: bool = False) -> bytes:
        return b"".join(self.get_object_stream(location, key, use_subdirectories=use_subdirectories))

    def get_object_md5(self, location: str, key: str, use_subdirectories: bool = False) -> str:
        md5 = hashlib.md5()
        for chunk in self.get_object_stream(location, key, use_subdirectories=use_subdirectories):
            md5.update(chunk)
        return md5.hexdigest()

    def check_if_object_exists(self, location: str, key: str, use_subdirectories: bool = False) -> bool:
        return os.path.isfile(self._fs_path(location, key, use_subdirectories))

    def copy_object(self, location, source_key, dest_key, use_subdirectories: bool = False) -> None:
        src = self._fs_path(location, source_key, use_subdirectories)
        dst = self._fs_path(location, dest_key, use_subdirectories)
        if not os.path.isfile(src):
            raise NotFoundError(f"{src} not found")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)

    def delete_object(self, location, key, use_subdirectories: bool = False) -> None:
        path = self._fs_path(location, key, use_subdirectories)
        # force=True semantics: no error if missing.
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    def delete_directory(self, location, key, use_subdirectories: bool = False) -> None:
        if self.use_subdirectories or use_subdirectories:
            shutil.rmtree(os.path.join(location, key), ignore_errors=True)
        else:
            for match in globmod.glob(self._fs_path(location, key, False) + "_*"):
                try:
                    os.remove(match)
                except (FileNotFoundError, IsADirectoryError):
                    shutil.rmtree(match, ignore_errors=True)

    def get_redirect_url(self, location, key) -> None:
        # The fs backend never redirects.
        return None


def create_persistor(config) -> FSPersistor:
    if config.backend == "fs":
        return FSPersistor()
    raise NotImplementedError(
        f"backend {config.backend!r} not yet ported (Phase 3 implements fs; s3/gcs later)"
    )
