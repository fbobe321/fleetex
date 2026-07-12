"""real-time configuration (Redis, web/document-updater APIs, session cookie)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class RealtimeConfig:
    port: int = 3026
    redis_url: str = "redis://127.0.0.1:6379"
    web_url: str = "http://127.0.0.1:3000"
    web_api_user: str = "overleaf"
    web_api_password: str = "password"
    document_updater_url: str = "http://127.0.0.1:3003"
    cookie_name: str = "overleaf.sid"
    session_secret: str = "secret"
    pending_update_list_shard_count: int = 10

    @classmethod
    def from_env(cls, env: dict | None = None) -> "RealtimeConfig":
        env = os.environ if env is None else env
        host = env.get("REDIS_HOST", "127.0.0.1")
        port = env.get("REDIS_PORT", "6379")
        return cls(
            port=int(env.get("PORT", 3026)),
            redis_url=env.get("REDIS_URL", f"redis://{host}:{port}"),
            web_url=f"http://{env.get('WEB_API_HOST', env.get('WEB_HOST', '127.0.0.1'))}:{env.get('WEB_API_PORT', env.get('WEB_PORT', '3000'))}",
            web_api_user=env.get("WEB_API_USER", "overleaf"),
            web_api_password=env.get("WEB_API_PASSWORD", "password"),
            document_updater_url=f"http://{env.get('DOCUMENT_UPDATER_HOST', env.get('DOCUPDATER_HOST', '127.0.0.1'))}:3003",
            cookie_name=env.get("COOKIE_NAME", "overleaf.sid"),
            session_secret=env.get("SESSION_SECRET", "secret"),
            pending_update_list_shard_count=int(env.get("PENDING_UPDATE_LIST_SHARD_COUNT", 10)),
        )
