"""Thin client to push a restored snapshot back into the live document.

Restore takes a past version's content and writes it to document-updater's
setDoc (``POST /project/:id/doc/:doc_id``), which replaces the in-memory doc so
connected editors converge on the restored text.
"""

from __future__ import annotations

import httpx


class DocUpdaterClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = http

    async def set_doc(self, project_id: str, doc_id: str, content: str, user_id: str | None = None) -> bool:
        url = f"{self.base_url}/project/{project_id}/doc/{doc_id}"
        payload = {"lines": content.split("\n"), "source": "restore", "user_id": user_id}
        client = self._http or httpx.AsyncClient()
        try:
            resp = await client.post(url, json=payload, timeout=30)
            return resp.status_code < 400
        finally:
            if self._http is None:
                await client.aclose()
