"""document-updater configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class DocUpdaterConfig:
    port: int = 3003
    redis_url: str = "redis://redis:6379"
    docstore_url: str = "http://docstore:3016"
    dispatcher_count: int = 10  # also the pending-updates-list shard count
    max_doc_length: int = 2 * 1024 * 1024
    max_age_of_op: int = 80
    project_history_url: str | None = None  # if set, snapshot to project-history on flush

    @classmethod
    def from_env(cls, env: dict | None = None) -> "DocUpdaterConfig":
        env = os.environ if env is None else env
        host = env.get("REDIS_HOST", "redis")
        return cls(
            port=int(env.get("PORT", 3003)),
            redis_url=env.get("REDIS_URL", f"redis://{host}:{env.get('REDIS_PORT', '6379')}"),
            docstore_url=env.get("DOCSTORE_URL", "http://docstore:3016"),
            dispatcher_count=int(env.get("DISPATCHER_COUNT", 10)),
            project_history_url=env.get("PROJECT_HISTORY_URL") or None,
        )
