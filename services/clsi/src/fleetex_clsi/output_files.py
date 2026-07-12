"""OutputFileFinder + OutputCacheManager — discovery and build-dir caching.

Generated files are those in the compile dir that were not written as input
resources. They are copied into ``<outputDir>/generated-files/<build_id>/`` and
tagged with ``build``; ``output.pdf`` also gets a ``size``.
"""

from __future__ import annotations

import os
import shutil
import time

CACHE_SUBDIR = "generated-files"


def generate_build_id() -> str:
    # OutputCacheManager: `${Date.now().toString(16)}-${randomBytes(8).hex}`
    return f"{int(time.time() * 1000):x}-{os.urandom(8).hex()}"


def find_output_files(compile_dir: str, resource_paths: set[str]) -> list[dict]:
    resource_paths = {os.path.normpath(p) for p in resource_paths}
    files: list[dict] = []
    for root, _dirs, names in os.walk(compile_dir):
        for name in names:
            rel = os.path.relpath(os.path.join(root, name), compile_dir)
            if name.startswith(".") or name.startswith("strace"):
                continue
            if rel in resource_paths or rel == ".project-sync-state":
                continue  # an input resource, not generated output
            files.append({"path": rel, "type": _ext(rel)})
    return files


def save_output_files(output_dir: str, files: list[dict], compile_dir: str, build_id: str) -> list[dict]:
    build_dir = os.path.join(output_dir, CACHE_SUBDIR, build_id)
    saved: list[dict] = []
    for f in files:
        src = os.path.join(compile_dir, f["path"])
        dst = os.path.join(build_dir, f["path"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        entry = dict(f)
        entry["build"] = build_id
        if f["path"] == "output.pdf":
            entry["size"] = os.path.getsize(dst)
        saved.append(entry)
    return saved


def _ext(path: str) -> str | None:
    _, ext = os.path.splitext(path)
    return ext[1:] if ext else None
