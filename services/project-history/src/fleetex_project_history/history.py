"""HistoryManager — version snapshots in Mongo.

Each stored version is a full-content snapshot of one doc, taken at a save point
(document-updater flush, an explicit save, a restore, or a manual checkpoint).
Versions carry a per-project monotonic ``v`` so the whole project has a single
ordered timeline. Identical consecutive snapshots of a doc are de-duplicated so
repeated flushes of an unchanged doc do not spam the history.

Granularity note: this is snapshot-at-save-point history, not op-level history —
enough for "see past versions / restore", coarser than Overleaf's per-keystroke
track-changes. The op-level upgrade can layer on later via the applied-ops feed.
"""

from __future__ import annotations

COLLECTION = "history_versions"


class HistoryManager:
    def __init__(self, db) -> None:
        self.col = db[COLLECTION]

    async def _next_version(self, project_id: str) -> int:
        latest = await self.col.find_one({"project_id": project_id}, sort=[("v", -1)], projection={"v": 1})
        return (latest["v"] + 1) if latest else 1

    async def latest_doc_version(self, project_id: str, doc_id: str) -> dict | None:
        return await self.col.find_one({"project_id": project_id, "doc_id": doc_id}, sort=[("v", -1)])

    async def record_version(
        self, project_id: str, doc_id: str, content: str, *,
        pathname: str = "", user_id: str | None = None, source: str = "flush", ts: int = 0,
    ) -> dict:
        """Store a new version unless it is identical to the doc's latest one.

        Returns ``{"created": bool, "version": <the version doc, sans _id>}``.
        """
        latest = await self.latest_doc_version(project_id, doc_id)
        if latest is not None and latest.get("content") == content:
            return {"created": False, "version": _public(latest)}
        v = await self._next_version(project_id)
        doc = {
            "project_id": project_id,
            "doc_id": doc_id,
            "pathname": pathname or (latest or {}).get("pathname", ""),
            "v": v,
            "content": content,
            "user_id": user_id,
            "source": source,
            "ts": ts,
        }
        await self.col.insert_one(doc)
        return {"created": True, "version": _public(doc)}

    async def list_project_versions(self, project_id: str, *, limit: int = 50, before: int | None = None) -> list[dict]:
        query: dict = {"project_id": project_id}
        if before is not None:
            query["v"] = {"$lt": before}
        cursor = self.col.find(query, projection={"content": 0}).sort("v", -1).limit(limit)
        return [_public(d) for d in await cursor.to_list(length=limit)]

    async def list_doc_versions(self, project_id: str, doc_id: str, *, limit: int = 100) -> list[dict]:
        cursor = self.col.find({"project_id": project_id, "doc_id": doc_id}, projection={"content": 0}).sort("v", -1).limit(limit)
        return [_public(d) for d in await cursor.to_list(length=limit)]

    async def get_version(self, project_id: str, v: int) -> dict | None:
        doc = await self.col.find_one({"project_id": project_id, "v": v})
        return _public(doc, with_content=True) if doc else None

    async def get_doc_version(self, project_id: str, doc_id: str, v: int) -> dict | None:
        doc = await self.col.find_one({"project_id": project_id, "doc_id": doc_id, "v": v})
        return _public(doc, with_content=True) if doc else None

    async def version_before(self, project_id: str, doc_id: str, v: int) -> dict | None:
        doc = await self.col.find_one(
            {"project_id": project_id, "doc_id": doc_id, "v": {"$lt": v}}, sort=[("v", -1)]
        )
        return _public(doc, with_content=True) if doc else None

    async def delete_project(self, project_id: str) -> int:
        result = await self.col.delete_many({"project_id": project_id})
        return result.deleted_count


def _public(doc: dict, *, with_content: bool = False) -> dict:
    out = {
        "project_id": doc["project_id"],
        "doc_id": doc["doc_id"],
        "pathname": doc.get("pathname", ""),
        "version": doc["v"],
        "user_id": doc.get("user_id"),
        "source": doc.get("source", ""),
        "ts": doc.get("ts", 0),
    }
    if with_content:
        out["content"] = doc.get("content", "")
    return out
