"""WebApiManager — port of WebApiManager.js. Authorizes a join against `web`.

`web` stays Node at this phase; we POST to its ``/project/:id/join`` endpoint.
"""

from __future__ import annotations

import httpx

from .errors import CodedError, NotAuthorizedError


class WebApiManager:
    def __init__(self, base_url: str, user: str, password: str, http: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = (user, password)
        self.http = http or httpx.AsyncClient()

    async def join_project(self, project_id: str, user_id: str, anonymous_access_token: str | None = None) -> dict:
        url = f"{self.base_url}/project/{project_id}/join"
        resp = await self.http.post(
            url,
            auth=self.auth,
            json={"userId": user_id, "anonymousAccessToken": anonymous_access_token},
        )
        if resp.status_code == 429:
            raise CodedError("rate-limit hit when joining project", "TooManyRequests")
        if resp.status_code == 403:
            raise NotAuthorizedError()
        if resp.status_code == 404:
            raise CodedError("project not found", "ProjectNotFound")
        if resp.status_code != 200:
            raise CodedError(f"web join failed ({resp.status_code})")
        data = resp.json()
        if not data.get("project"):
            raise CodedError("web returned corrupt join response")
        return data
