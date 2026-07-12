"""CLSI configuration (paths, download host, limits), atop the kit Settings."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ClsiConfig:
    port: int = 3013
    compiles_dir: str = "./clsi_data/compiles"
    output_dir: str = "./clsi_data/output"
    cache_dir: str = "./clsi_data/cache"
    download_host: str = "http://localhost:8080"
    output_url_prefix: str = ""
    instance_type: str | None = None
    zone: str | None = None
    is_spot_instance: bool = False
    compile_concurrency_limit: int = 64
    max_timeout: int = 600  # seconds

    @classmethod
    def from_env(cls, env: dict | None = None) -> "ClsiConfig":
        env = os.environ if env is None else env
        zone = env.get("ZONE")
        return cls(
            port=int(env.get("PORT", 3013)),
            compiles_dir=env.get("CLSI_COMPILES_PATH", "./clsi_data/compiles"),
            output_dir=env.get("CLSI_OUTPUT_PATH", "./clsi_data/output"),
            cache_dir=env.get("CLSI_CACHE_PATH", "./clsi_data/cache"),
            download_host=env.get("DOWNLOAD_HOST", "http://localhost:8080"),
            output_url_prefix=f"/zone/{zone}" if zone else "",
            instance_type=env.get("INSTANCE_TYPE"),
            zone=zone,
            is_spot_instance=env.get("PREEMPTIBLE") == "TRUE",
            compile_concurrency_limit=int(env.get("COMPILE_CONCURRENCY_LIMIT", 64)),
        )
