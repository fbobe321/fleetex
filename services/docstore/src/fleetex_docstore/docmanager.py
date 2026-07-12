"""Orchestration — port of DocManager.js.

``get`` unarchives archived docs back into Mongo; ``peek`` reads archived content
without writing Mongo and verifies rev. ``update_doc`` implements the rev/version
semantics + one optimistic-lock retry.
"""

from __future__ import annotations

from .archive import DocArchiveManager
from .errors import (
    DocModifiedError,
    DocRevValueError,
    DocVersionDecrementedError,
    DocWithoutLinesError,
    NotFoundError,
)
from .mongo import MongoManager
from .ranges import json_ranges_to_mongo, should_update_ranges

_FULL_PROJECTION = {"lines": 1, "rev": 1, "deleted": 1, "version": 1, "ranges": 1, "inS3": 1}


class DocManager:
    def __init__(self, mongo: MongoManager, archive: DocArchiveManager) -> None:
        self.mongo = mongo
        self.archive = archive

    async def _get_doc(self, project_id, doc_id, projection: dict) -> dict:
        if "inS3" not in projection:
            raise ValueError("must include inS3 in projection")
        doc = await self.mongo.find_doc(project_id, doc_id, projection)
        if doc is None:
            raise NotFoundError(f"doc {doc_id} not found")
        if doc.get("inS3"):
            await self.archive.unarchive_doc(project_id, doc_id)
            return await self._get_doc(project_id, doc_id, projection)
        return doc

    async def get_full_doc(self, project_id, doc_id) -> dict:
        return await self._get_doc(project_id, doc_id, dict(_FULL_PROJECTION))

    async def get_doc_lines(self, project_id, doc_id) -> str:
        doc = await self.get_full_doc(project_id, doc_id)
        if doc.get("lines") is None:
            raise DocWithoutLinesError(f"doc {doc_id} has no lines")
        return "\n".join(doc["lines"])

    async def peek_doc(self, project_id, doc_id) -> tuple[dict, str]:
        doc = await self.mongo.find_doc(
            project_id, doc_id, {"deleted": 1, "inS3": 1, "lines": 1, "ranges": 1, "rev": 1, "version": 1}
        )
        if doc is None:
            raise NotFoundError(f"doc {doc_id} not found")
        status = "active"
        if doc.get("inS3"):
            status = "archived"
            key = self.archive._key(project_id, doc_id)
            data = self.archive.store.get(self.archive.bucket, key)
            archived = self.archive._deserialize(data)
            current = await self.mongo.find_doc(project_id, doc_id, {"rev": 1})
            if current is None:
                raise NotFoundError(f"doc {doc_id} not found")
            if archived.get("rev", current["rev"]) != current["rev"]:
                raise DocModifiedError("archived rev differs from mongo")
            doc = {**doc, "lines": archived.get("lines"), "ranges": archived.get("ranges") or {}}
        return doc, status

    async def is_doc_deleted(self, project_id, doc_id) -> bool:
        doc = await self.mongo.find_doc(project_id, doc_id, {"deleted": 1})
        if doc is None:
            raise NotFoundError(f"doc {doc_id} not found")
        return bool(doc.get("deleted"))

    async def get_all_non_deleted_docs(self, project_id, projection: dict) -> list[dict]:
        await self.archive.unarchive_all_docs(project_id)
        docs = await self.mongo.get_projects_docs(project_id, False, projection)
        if not docs:
            raise NotFoundError(f"no docs for project {project_id}")
        for doc in docs:
            if doc.get("lines") is None and "lines" in projection:
                doc["lines"] = []
        return docs

    async def get_all_ranges(self, project_id) -> list[dict]:
        await self.archive.unarchive_all_docs(project_id)
        return await self.mongo.get_projects_docs(project_id, False, {"ranges": 1})

    async def update_doc(self, project_id, doc_id, lines, version, ranges) -> tuple[bool, int]:
        for attempt in range(2):
            try:
                return await self._update_doc(project_id, doc_id, lines, version, ranges)
            except DocRevValueError:
                if attempt == 1:
                    raise
        raise DocRevValueError("unreachable")

    async def _update_doc(self, project_id, doc_id, lines, version, ranges) -> tuple[bool, int]:
        try:
            doc = await self._get_doc(
                project_id, doc_id, {"version": 1, "rev": 1, "lines": 1, "ranges": 1, "inS3": 1}
            )
        except NotFoundError:
            doc = None

        if doc is None:  # brand new doc
            new_rev = await self.mongo.upsert_into_doc_collection(
                project_id, doc_id, {"lines": lines, "ranges": json_ranges_to_mongo(ranges), "version": version}, None
            )
            return True, new_rev

        if doc.get("version", 0) > version:
            raise DocVersionDecrementedError("incoming version is older")

        update_lines = doc.get("lines") != lines
        update_version = doc.get("version", 0) != version
        update_ranges = should_update_ranges(doc.get("ranges"), ranges)
        if not (update_lines or update_version or update_ranges):
            return False, doc["rev"]

        updates: dict = {}
        if update_lines:
            updates["lines"] = lines
        if update_ranges:
            updates["ranges"] = json_ranges_to_mongo(ranges)
        if update_version:
            updates["version"] = version
        new_rev = await self.mongo.upsert_into_doc_collection(project_id, doc_id, updates, doc["rev"])
        return True, new_rev

    async def patch_doc(self, project_id, doc_id, meta: dict, archive_on_soft_delete: bool = False) -> None:
        matched = await self.mongo.patch_doc(project_id, doc_id, meta)
        if matched != 1:
            raise NotFoundError(f"doc {doc_id} not found")
        if meta.get("deleted") and archive_on_soft_delete:
            try:
                await self.archive.archive_doc(project_id, doc_id)
            except Exception:
                pass  # background best-effort, matching the Node original

    async def get_comment_thread_ids(self, project_id) -> dict:
        await self.archive.unarchive_all_docs(project_id)
        docs = await self.mongo.get_projects_docs(project_id, False, {"ranges": 1})
        out: dict = {}
        for doc in docs:
            threads = []
            for comment in (doc.get("ranges") or {}).get("comments", []):
                t = comment.get("op", {}).get("t")
                if t is not None:
                    threads.append(str(t))
            if threads:
                out[str(doc["_id"])] = threads
        return out

    async def get_tracked_changes_user_ids(self, project_id) -> list[str]:
        await self.archive.unarchive_all_docs(project_id)
        docs = await self.mongo.get_projects_docs(project_id, False, {"ranges": 1})
        users: dict = {}
        for doc in docs:
            for change in (doc.get("ranges") or {}).get("changes", []):
                uid = change.get("metadata", {}).get("user_id")
                if uid is not None and uid != "anonymous-user":
                    users[str(uid)] = True
        return list(users.keys())

    async def project_has_ranges(self, project_id) -> bool:
        docs = await self.mongo.get_projects_docs(project_id, False, {"ranges": 1})
        for doc in docs:
            ranges = doc.get("ranges") or {}
            if ranges.get("comments") or ranges.get("changes"):
                return True
        return False
