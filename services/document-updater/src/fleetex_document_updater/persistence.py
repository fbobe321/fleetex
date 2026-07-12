"""Persistence bridge — loads a doc from the docstore service on a Redis miss."""

from __future__ import annotations

import httpx


class PersistenceManager:
    def __init__(self, docstore_url: str, http: httpx.AsyncClient | None = None) -> None:
        self.base_url = docstore_url.rstrip("/")
        self.http = http or httpx.AsyncClient()

    async def get_doc(self, project_id: str, doc_id: str) -> dict | None:
        resp = await self.http.get(f"{self.base_url}/project/{project_id}/doc/{doc_id}")
        if resp.status_code != 200:
            return None
        doc = resp.json()
        return {
            "lines": doc.get("lines", []),
            "version": doc.get("version", 0),
            "ranges": doc.get("ranges") or {},
            "pathname": doc.get("pathname", ""),
        }

    async def set_doc(self, project_id: str, doc_id: str, lines: list, version: int, ranges: dict) -> None:
        await self.http.post(
            f"{self.base_url}/project/{project_id}/doc/{doc_id}",
            json={"lines": lines, "version": version, "ranges": ranges or {}},
        )
