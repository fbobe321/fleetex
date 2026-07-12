"""Bucket/key derivation — port of KeyBuilder.js and ProjectKey.js.

A ``KeySpec`` bundles what the persistor needs: which bucket (a directory path
for the fs backend) and object key, plus whether the key uses real
subdirectories (history blobs) vs the flattened ``/`` -> ``_`` layout.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass
class KeySpec:
    bucket: str
    key: str
    use_subdirectories: bool = False


def project_key_format(history_id) -> str:
    """ProjectKey.format: zero-pad to 9, reverse, split path.join(0:3, 3:6, 6:)."""
    reversed_id = str(history_id).zfill(9)[::-1]
    return os.path.join(reversed_id[0:3], reversed_id[3:6], reversed_id[6:])


def template_file_key(stores: dict, template_id: str, version: str, fmt: str, sub_type: str | None = None) -> KeySpec:
    key = f"{template_id}/v/{version}/{fmt}"
    if sub_type:
        key = f"{key}/{sub_type}"
    return KeySpec(bucket=stores["template_files"], key=key)


def bucket_file_key(bucket: str, wildcard_key: str) -> KeySpec:
    return KeySpec(bucket=bucket, key=wildcard_key)


def global_blob_key(stores: dict, hash_: str) -> KeySpec:
    key = f"{hash_[0:2]}/{hash_[2:4]}/{hash_[4:]}"
    return KeySpec(bucket=stores["global_blobs"], key=key, use_subdirectories=True)


def project_blob_key(stores: dict, history_id: str, hash_: str) -> KeySpec:
    key = f"{project_key_format(history_id)}/{hash_[0:2]}/{hash_[2:]}"
    return KeySpec(bucket=stores["project_blobs"], key=key, use_subdirectories=True)


def add_caching_to_key(key: str, fmt: str | None, style: str | None) -> str:
    """KeyBuilder.addCachingToKey — the derived cache key for a converted file."""
    base = f"{key}-converted-cache/"
    if fmt and style:
        return base + f"format-{fmt}-style-{style}"
    if fmt:
        return base + f"format-{fmt}"
    if style:
        return base + f"style-{style}"
    return base


# Insert key validation (FileHandler.insertFile): convertedKey must match this.
_INSERT_KEY_RE = re.compile(r"^[0-9a-f]{24}/([0-9a-f]{24}|v/[0-9]+/[a-z0-9]+)", re.IGNORECASE)


def validate_insert_key(key: str) -> bool:
    return bool(_INSERT_KEY_RE.match(f"{key}-converted-cache/"))
