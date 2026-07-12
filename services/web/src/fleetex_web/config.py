"""web (auth slice) configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class WebConfig:
    port: int = 3000
    session_secrets: list = field(default_factory=lambda: ["secret"])
    cookie_name: str = "overleaf.sid"
    cookie_max_age_ms: int = 5 * 24 * 60 * 60 * 1000  # 5 days
    secure_cookie: bool = False
    same_site: str = "lax"
    bcrypt_rounds: int = 12
    web_api_user: str = "overleaf"
    web_api_password: str = "password"
    mongo_url: str = "mongodb://mongo/sharelatex"
    redis_url: str = "redis://redis:6379"
    docstore_url: str = "http://docstore:3016"
    # editor bootstrap config
    ws_url: str = "/socket.io"
    ws_retry_handshake: int = 5
    max_doc_length: int = 2 * 1024 * 1024
    default_compiler: str = "pdflatex"
    languages: list = field(default_factory=lambda: ["en", "fr", "de", "es"])
    # Fleetex convenience: open self-registration (CE = all-trusted-users model).
    open_registration: bool = True

    @property
    def cookie_max_age_s(self) -> int:
        return self.cookie_max_age_ms // 1000

    @classmethod
    def from_env(cls, env: dict | None = None) -> "WebConfig":
        env = os.environ if env is None else env
        secrets = [
            s for s in (env.get("SESSION_SECRET"), env.get("SESSION_SECRET_UPCOMING"), env.get("SESSION_SECRET_FALLBACK"))
            if s
        ] or ["secret"]
        host = env.get("REDIS_HOST", "redis")
        return cls(
            port=int(env.get("WEB_PORT", env.get("PORT", 3000))),
            session_secrets=secrets,
            cookie_name=env.get("COOKIE_NAME", "overleaf.sid"),
            bcrypt_rounds=int(env.get("BCRYPT_ROUNDS", 12)),
            web_api_user=env.get("WEB_API_USER", "overleaf"),
            web_api_password=env.get("WEB_API_PASSWORD", "password"),
            mongo_url=env.get("MONGO_URL") or env.get("OVERLEAF_MONGO_URL") or "mongodb://mongo/sharelatex",
            redis_url=env.get("REDIS_URL", f"redis://{host}:{env.get('REDIS_PORT', '6379')}"),
            docstore_url=env.get("DOCSTORE_URL", "http://docstore:3016"),
            ws_url=env.get("WEBSOCKET_URL", "/socket.io"),
            ws_retry_handshake=int(env.get("WEBSOCKET_RETRY_HANDSHAKE", 5)),
            open_registration=env.get("OPEN_REGISTRATION", "true").lower() in ("1", "true", "yes"),
        )
