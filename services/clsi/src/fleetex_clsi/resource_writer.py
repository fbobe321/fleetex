"""ResourceWriter — port of ResourceWriter.js (content resources; URL fetch deferred).

Writes resources into the compile dir, removes extraneous files between compiles,
and records ``.project-sync-state``. URL-backed resources are a documented gap
(they require the filestore UrlCache, which lands with the persistor port).
"""

from __future__ import annotations

import os

from .errors import InvalidRequestError
from .request_parser import ParsedRequest

SYNC_STATE_FILE = ".project-sync-state"

# Files always removed before a compile (subset of ResourceWriter's force-delete list).
FORCE_DELETE = {
    "output.pdf", "output.log", "output.tar.gz", "output.synctex.gz",
    "output.dvi", "output.xdv", "output.stdout", "output.stderr", "output.tex",
    "output.pdfxref",
}


def _safe_join(base: str, rel: str) -> str:
    dest = os.path.normpath(os.path.join(base, rel))
    if dest != base and not dest.startswith(base + os.sep):
        raise InvalidRequestError("resource path is outside root directory")
    return dest


class ResourceWriter:
    def __init__(self, compile_dir: str) -> None:
        self.base = os.path.normpath(compile_dir)

    def sync_resources_to_disk(self, parsed: ParsedRequest) -> list:
        self._remove_extraneous(parsed.resources)
        for resource in parsed.resources:
            self._write(resource)
        self._save_project_state(parsed)
        return parsed.resources

    def _write(self, resource) -> None:
        dest = _safe_join(self.base, resource.path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if resource.content is not None:
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write(resource.content)
        elif resource.url:
            # download URL-backed resources (e.g. binary files from filestore).
            # Failures are swallowed so a missing asset doesn't abort the compile.
            try:
                import httpx

                resp = httpx.get(resource.url, timeout=30, follow_redirects=True)
                if resp.status_code == 200:
                    with open(dest, "wb") as fh:
                        fh.write(resp.content)
            except Exception:  # noqa: BLE001
                pass

    def _remove_extraneous(self, resources: list) -> None:
        keep = {os.path.normpath(r.path) for r in resources}
        keep.add(SYNC_STATE_FILE)
        for root, _dirs, files in os.walk(self.base):
            for name in files:
                abspath = os.path.join(root, name)
                rel = os.path.relpath(abspath, self.base)
                if name in FORCE_DELETE or (rel not in keep and not _is_preserved(rel)):
                    os.remove(abspath)

    def _save_project_state(self, parsed: ParsedRequest) -> None:
        lines = [r.path for r in parsed.resources]
        lines.append(f"stateHash:{parsed.sync_state}")
        with open(os.path.join(self.base, SYNC_STATE_FILE), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))


def _is_preserved(rel: str) -> bool:
    # Keep caches/aux artifacts across compiles (approximation of isExtraneousFile).
    if rel.startswith("cache" + os.sep) or rel.startswith("output-"):
        return True
    return rel.endswith((".aux", ".dpth", ".md5"))
