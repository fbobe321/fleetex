"""Best-effort snapshotting to the project-history service.

On flush, document-updater posts the doc's current content to project-history so
a version is checkpointed. This is fire-and-forget: a history outage must never
break editing or flushing, so every failure is swallowed.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("document-updater")


class HistoryClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = http

    async def snapshot(self, project_id: str, doc_id: str, lines: list, pathname: str = "", source: str = "flush") -> None:
        url = f"{self.base_url}/project/{project_id}/doc/{doc_id}/version"
        payload = {"content": "\n".join(lines), "pathname": pathname, "source": source}
        client = self._http or httpx.AsyncClient()
        try:
            await client.post(url, json=payload, timeout=10)
        except Exception as exc:  # noqa: BLE001 - history is non-critical
            logger.warning("history snapshot failed for %s/%s: %s", project_id, doc_id, exc)
        finally:
            if self._http is None:
                await client.aclose()
