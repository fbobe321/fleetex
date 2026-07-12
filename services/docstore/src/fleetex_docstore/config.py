"""Docstore-specific config (archive backend/bucket/flags), atop the kit Settings."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class DocstoreConfig:
    backend: str = ""  # "", "fs", "s3", "gcs"; "" disables archiving
    bucket: str = "bucket"
    archive_path: str = "./docstore_archive"
    archive_on_soft_delete: bool = True
    keep_soft_deleted_docs_archived: bool = True
    port: int = 3016

    @classmethod
    def from_env(cls, env: dict | None = None) -> "DocstoreConfig":
        env = os.environ if env is None else env
        return cls(
            backend=env.get("BACKEND", ""),
            bucket=env.get("BUCKET_NAME") or env.get("AWS_BUCKET") or "bucket",
            archive_path=env.get("DOCSTORE_ARCHIVE_PATH", "./docstore_archive"),
            archive_on_soft_delete=_truthy(env.get("ARCHIVE_ON_SOFT_DELETE"), True),
            keep_soft_deleted_docs_archived=_truthy(env.get("KEEP_SOFT_DELETED_DOCS_ARCHIVED"), True),
            port=int(env.get("PORT", 3016)),
        )


def _truthy(value, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).lower() in ("1", "true", "yes")
