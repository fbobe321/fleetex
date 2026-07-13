"""RequestParser — port of RequestParser.js.

Parses/validates the ``{compile: {options, rootResourcePath, resources}}`` body
into a ``ParsedRequest``. Defaults and validation match the Node original.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .errors import InvalidRequestError

COMPILERS = ("pdflatex", "latex", "xelatex", "lualatex")
SYNC_TYPES = ("full", "incremental", "history-full", "history-incremental")
MAX_TIMEOUT = 600  # seconds


@dataclass
class Resource:
    path: str
    content: str | None = None
    url: str | None = None
    fallback_url: str | None = None
    modified: datetime | None = None


@dataclass
class ParsedRequest:
    compiler: str = "pdflatex"
    timeout_ms: int = MAX_TIMEOUT * 1000
    image_name: str | None = None
    draft: bool = False
    check: str | None = None
    stop_on_first_error: bool = False
    flags: list = field(default_factory=list)
    sync_type: str | None = None
    sync_state: str | None = None
    compile_group: str | None = None
    root_resource_path: str = "main.tex"
    resources: list = field(default_factory=list)


def _check_path(path: str) -> str:
    if any(seg == ".." for seg in path.replace("\\", "/").split("/")):
        raise InvalidRequestError(f"resource path has a '..' segment: {path!r}")
    return path


# Substrings that, if present in a compiler flag, could re-enable arbitrary code
# execution (\write18) or redirect reads/writes outside the sandbox. Fleetex may
# run the compiler without container isolation, so these are rejected outright.
_FORBIDDEN_FLAG_TOKENS = (
    "shell-escape", "shellescape", "shell_escape",
    "write18", "enable-pipes", "enable-installer",
    "output-directory", "aux-directory", "outdir", "auxdir",
    "cnf-line", "jobname",
)


def _validate_flag(flag) -> str:
    if not isinstance(flag, str):
        raise InvalidRequestError("each flag must be a string")
    if not flag.startswith("-"):
        # a non-option token would be treated as an input file / command
        raise InvalidRequestError(f"flag {flag!r} must start with '-'")
    normalized = flag.lower().replace("_", "-")
    if any(tok in normalized for tok in _FORBIDDEN_FLAG_TOKENS):
        raise InvalidRequestError(f"flag {flag!r} is not allowed")
    return flag


def _parse_resource(raw: dict) -> Resource:
    path = raw.get("path")
    if not isinstance(path, str):
        raise InvalidRequestError("resource is missing a string path")
    _check_path(path)
    content, url = raw.get("content"), raw.get("url")
    if content is None and url is None:
        raise InvalidRequestError(f"resource {path!r} has neither content nor url")
    if content is not None and not isinstance(content, str):
        raise InvalidRequestError(f"resource {path!r} content must be a string")
    modified = None
    if raw.get("modified") is not None:
        try:
            modified = datetime.fromisoformat(str(raw["modified"]).replace("Z", "+00:00"))
        except ValueError:
            raise InvalidRequestError(f"resource {path!r} has an invalid modified date")
    return Resource(path=path, content=content, url=url, fallback_url=raw.get("fallbackURL"), modified=modified)


def parse(body: dict) -> ParsedRequest:
    if not isinstance(body, dict) or "compile" not in body:
        raise InvalidRequestError("missing 'compile' in request body")
    compile_ = body["compile"]
    options = compile_.get("options", {}) or {}

    compiler = options.get("compiler", "pdflatex")
    if compiler not in COMPILERS:
        raise InvalidRequestError(f"invalid compiler {compiler!r}")

    timeout = options.get("timeout", MAX_TIMEOUT)
    if not isinstance(timeout, (int, float)):
        raise InvalidRequestError("timeout must be a number")
    timeout = min(int(timeout), MAX_TIMEOUT)

    sync_type = options.get("syncType")
    if sync_type is not None and sync_type not in SYNC_TYPES:
        raise InvalidRequestError(f"invalid syncType {sync_type!r}")

    flags = options.get("flags", [])
    if not isinstance(flags, list):
        raise InvalidRequestError("flags must be a list")
    flags = [_validate_flag(f) for f in flags]

    root = compile_.get("rootResourcePath", "main.tex")
    _check_path(root)

    return ParsedRequest(
        compiler=compiler,
        timeout_ms=timeout * 1000,
        image_name=options.get("imageName"),
        draft=bool(options.get("draft", False)),
        check=options.get("check"),
        stop_on_first_error=bool(options.get("stopOnFirstError", False)),
        flags=list(flags),
        sync_type=sync_type,
        sync_state=options.get("syncState"),
        compile_group=options.get("compileGroup"),
        root_resource_path=root,
        resources=[_parse_resource(r) for r in compile_.get("resources", [])],
    )
