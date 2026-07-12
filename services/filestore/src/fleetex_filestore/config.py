"""Filestore configuration — the storage-specific settings (backend, buckets,
paths), separate from the kit's generic Mongo/Redis Settings.

For the fs backend, a "bucket"/store value IS a directory path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class FilestoreConfig:
    backend: str = "fs"
    base_path: str = "./filestore_data"
    stores: dict = field(default_factory=dict)
    upload_folder: str = ""
    allow_redirects: bool = False
    enable_conversions: bool = False
    converter: str = "imagemagick"
    port: int = 3009

    @classmethod
    def from_env(cls, env: dict | None = None, base_path: str | None = None) -> "FilestoreConfig":
        env = os.environ if env is None else env
        base = base_path or env.get("FILESTORE_PATH", "./filestore_data")
        backend = env.get("BACKEND") or (
            "s3" if (env.get("AWS_ACCESS_KEY_ID") or env.get("S3_BUCKET_CREDENTIALS")) else "fs"
        )
        stores = {
            "template_files": env.get("TEMPLATE_FILES_BUCKET_NAME") or os.path.join(base, "template_files"),
            "global_blobs": env.get("OVERLEAF_EDITOR_BLOBS_BUCKET") or os.path.join(base, "global_blobs"),
            "project_blobs": env.get("OVERLEAF_EDITOR_PROJECT_BLOBS_BUCKET") or os.path.join(base, "project_blobs"),
        }
        return cls(
            backend=backend,
            base_path=base,
            stores=stores,
            upload_folder=env.get("UPLOAD_FOLDER") or os.path.join(base, "uploads"),
            allow_redirects=_truthy(env.get("ALLOW_REDIRECTS")),
            enable_conversions=_truthy(env.get("ENABLE_CONVERSIONS")),
            converter=env.get("CONVERTER", "imagemagick"),
            port=int(env.get("PORT", 3009)),
        )


def _truthy(value) -> bool:
    return str(value).lower() in ("1", "true", "yes") if value is not None else False
