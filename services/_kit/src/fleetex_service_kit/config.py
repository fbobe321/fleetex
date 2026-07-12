"""Environment-driven settings, compatible with Overleaf's env var names.

Overleaf services are configured through env vars (``OVERLEAF_MONGO_URL``,
``REDIS_HOST`` ...). We read the same ones so a Python service can be dropped
into the existing compose stack with no new configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _redis_url_from_parts(env: dict) -> str | None:
    """Build a redis URL from Overleaf's REDIS_HOST/REDIS_PORT if present."""
    host = env.get("REDIS_HOST") or env.get("OVERLEAF_REDIS_HOST")
    if not host:
        return None
    port = env.get("REDIS_PORT", "6379")
    return f"redis://{host}:{port}"


@dataclass(frozen=True)
class Settings:
    """Runtime settings for a Fleetex Python service."""

    service_name: str
    mongo_url: str = "mongodb://mongo/sharelatex"
    redis_url: str = "redis://redis:6379"
    host: str = "0.0.0.0"
    port: int = 3000
    log_level: str = "info"

    @classmethod
    def from_env(
        cls,
        service_name: str,
        *,
        default_port: int = 3000,
        env: dict | None = None,
    ) -> "Settings":
        env = os.environ if env is None else env
        return cls(
            service_name=service_name,
            mongo_url=(
                env.get("MONGO_URL")
                or env.get("OVERLEAF_MONGO_URL")
                or cls.mongo_url
            ),
            redis_url=(
                env.get("REDIS_URL")
                or _redis_url_from_parts(env)
                or cls.redis_url
            ),
            host=env.get("LISTEN_ADDRESS", cls.host),
            port=int(env.get("PORT", default_port)),
            log_level=env.get("LOG_LEVEL", cls.log_level),
        )
