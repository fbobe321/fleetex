"""Archiving to object storage — port of DocArchiveManager.js.

Payload is plain JSON ``{"lines","ranges","rev","schema_v":1}`` (NOT gzipped in
this service). Key = ``"<projectId>/<docId>"``. For non-s3 backends the md5 of the
exact JSON string is verified on read (Md5MismatchError on mismatch).

The persistor is abstracted as an ``ArchiveStore``; an in-memory store (default,
for tests) and a filesystem store are provided. S3/GCS come with the persistor
port later.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil

from bson import ObjectId

from .errors import Md5MismatchError, NotFoundError, WriteError
from .ranges import fix_comment_ids, json_ranges_to_mongo
from .serialize import encode


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


class ArchiveStore:
    def put(self, bucket, key, data: bytes, source_md5: str | None = None) -> None:
        raise NotImplementedError

    def get(self, bucket, key) -> bytes:
        raise NotImplementedError

    def get_md5(self, bucket, key) -> str:
        return _md5(self.get(bucket, key))

    def delete_directory(self, bucket, prefix) -> None:
        raise NotImplementedError


class InMemoryArchiveStore(ArchiveStore):
    def __init__(self) -> None:
        self._data: dict[tuple, bytes] = {}

    def put(self, bucket, key, data, source_md5=None):
        if source_md5 is not None and _md5(data) != source_md5:
            raise WriteError("md5 hash mismatch")
        self._data[(bucket, key)] = data

    def get(self, bucket, key):
        try:
            return self._data[(bucket, key)]
        except KeyError:
            raise NotFoundError(f"{bucket}/{key} not found")

    def delete_directory(self, bucket, prefix):
        for k in [k for k in self._data if k[0] == bucket and k[1].startswith(prefix)]:
            del self._data[k]


class FSArchiveStore(ArchiveStore):
    def __init__(self, root: str) -> None:
        self.root = root

    def _path(self, bucket, key):
        return os.path.join(self.root, bucket, key)

    def put(self, bucket, key, data, source_md5=None):
        if source_md5 is not None and _md5(data) != source_md5:
            raise WriteError("md5 hash mismatch")
        path = self._path(bucket, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)

    def get(self, bucket, key):
        try:
            with open(self._path(bucket, key), "rb") as fh:
                return fh.read()
        except FileNotFoundError:
            raise NotFoundError(f"{bucket}/{key} not found")

    def delete_directory(self, bucket, prefix):
        shutil.rmtree(os.path.join(self.root, bucket, prefix), ignore_errors=True)


class DocArchiveManager:
    def __init__(self, mongo, store: ArchiveStore | None, bucket: str, backend: str) -> None:
        self.mongo = mongo
        self.store = store
        self.bucket = bucket
        self.backend = backend

    @property
    def enabled(self) -> bool:
        return bool(self.backend) and self.store is not None

    @staticmethod
    def _key(project_id, doc_id) -> str:
        return f"{project_id}/{doc_id}"

    async def archive_doc(self, project_id, doc_id) -> None:
        if not self.enabled:
            return
        doc = await self.mongo.get_doc_for_archiving(project_id, doc_id)
        if doc is None:  # not found / already archived / lock held
            return
        fix_comment_ids(doc)
        payload = json.dumps(
            {
                "lines": doc.get("lines"),
                "ranges": encode(doc.get("ranges") or {}),
                "rev": doc["rev"],
                "schema_v": 1,
            }
        )
        if "\x00" in payload:
            raise WriteError("null bytes in archived doc")
        data = payload.encode("utf-8")
        source_md5 = None if self.backend == "s3" else _md5(data)
        self.store.put(self.bucket, self._key(project_id, doc_id), data, source_md5=source_md5)
        await self.mongo.mark_doc_as_archived(doc_id, doc["rev"])

    async def unarchive_doc(self, project_id, doc_id) -> None:
        mongo_doc = await self.mongo.find_doc(project_id, doc_id, {"inS3": 1, "rev": 1})
        if not mongo_doc or not mongo_doc.get("inS3"):
            return
        if not self.enabled:
            raise WriteError("archiving is not enabled")
        key = self._key(project_id, doc_id)
        data = self.store.get(self.bucket, key)
        if self.backend != "s3" and self.store.get_md5(self.bucket, key) != _md5(data):
            raise Md5MismatchError("md5 mismatch reading archived doc")
        archived = self._deserialize(data)
        archived.setdefault("rev", mongo_doc["rev"])
        await self.mongo.restore_archived_doc(project_id, doc_id, archived)

    @staticmethod
    def _deserialize(data: bytes) -> dict:
        parsed = json.loads(data.decode("utf-8"))
        if isinstance(parsed, dict) and parsed.get("schema_v") == 1 and parsed.get("lines") is not None:
            out = {"lines": parsed["lines"], "ranges": json_ranges_to_mongo(parsed.get("ranges"))}
            if parsed.get("rev") is not None:
                out["rev"] = parsed["rev"]
            return out
        if isinstance(parsed, list):  # legacy: bare lines array
            return {"lines": parsed}
        raise WriteError("unrecognized archived doc format")

    async def archive_all_docs(self, project_id) -> None:
        if not self.enabled:
            return
        for doc_id in await self.mongo.get_non_archived_project_doc_ids(project_id):
            await self.archive_doc(project_id, doc_id)

    async def unarchive_all_docs(self, project_id, keep_soft_deleted_archived: bool = False) -> None:
        if not self.enabled:
            return
        doc_ids = await self.mongo.get_archived_project_docs(
            project_id, include_deleted=not keep_soft_deleted_archived
        )
        for doc_id in doc_ids:
            await self.unarchive_doc(project_id, doc_id)

    async def destroy_project(self, project_id) -> None:
        if self.enabled:
            self.store.delete_directory(self.bucket, str(ObjectId(project_id)) if not isinstance(project_id, ObjectId) else str(project_id))
