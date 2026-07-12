"""Contract-testing harness: prove a Python service matches the Node original.

The workflow for every ported service:

1. Fire the same request at the Node service (ground truth) and the Python one.
2. Normalize away volatile fields (ids, timestamps).
3. Assert the normalized responses are identical.

Node ground truth can come from a live server (set ``FLEETEX_NODE_BASE``) or
from recorded fixtures, so tests still run in CI without Node.

Example::

    py = await call_asgi(app, "GET", "/user/abc/notifications")
    node = await call_http(os.environ["FLEETEX_NODE_BASE"], "GET", "/user/abc/notifications")
    assert_match(py, node, ignore={"[*].id", "[*]._id"})
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class Response:
    status: int
    json: Any = None
    text: str = ""
    headers: dict = field(default_factory=dict)

    @classmethod
    def from_httpx(cls, r: httpx.Response) -> "Response":
        body_json = None
        ctype = r.headers.get("content-type", "")
        if "application/json" in ctype:
            try:
                body_json = r.json()
            except (json.JSONDecodeError, ValueError):
                body_json = None
        return cls(status=r.status_code, json=body_json, text=r.text, headers=dict(r.headers))


async def call_asgi(app, method: str, path: str, **kwargs) -> Response:
    """Call a FastAPI/ASGI app in-process (no network, no port)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://svc") as client:
        r = await client.request(method, path, **kwargs)
    return Response.from_httpx(r)


async def call_http(base_url: str, method: str, path: str, **kwargs) -> Response:
    """Call a live HTTP service (e.g. the Node original)."""
    async with httpx.AsyncClient(base_url=base_url) as client:
        r = await client.request(method, path, **kwargs)
    return Response.from_httpx(r)


# --- normalization ------------------------------------------------------- #
def _matches(path: str, pattern: str) -> bool:
    """Very small glob: '*' matches one path segment, '**' matches any depth."""
    p, q = path.split("."), pattern.split(".")
    i = j = 0
    while i < len(p) and j < len(q):
        if q[j] == "**":
            return True  # greedy tail match is enough for our use
        if q[j] in ("*", "[*]") or q[j] == p[i]:
            i += 1
            j += 1
        else:
            return False
    return i == len(p) and j == len(q)


def normalize(value: Any, ignore: set[str] | None = None, _path: str = "") -> Any:
    """Recursively drop keys/paths whose dotted path matches an ``ignore`` glob.

    Paths use '.' between object keys and '[*]' for list elements, e.g.
    ``ignore={"[*].id", "createdAt", "items.[*]._id"}``.
    """
    ignore = ignore or set()
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            child = f"{_path}.{k}".lstrip(".")
            if any(_matches(child, pat) for pat in ignore):
                continue
            out[k] = normalize(v, ignore, child)
        return out
    if isinstance(value, list):
        child = f"{_path}.[*]".lstrip(".")
        return [normalize(v, ignore, child) for v in value]
    return value


# --- comparison ---------------------------------------------------------- #
def diff(python: Response, node: Response, *, ignore: set[str] | None = None) -> list[str]:
    """Return a list of human-readable differences (empty == match)."""
    problems: list[str] = []
    if python.status != node.status:
        problems.append(f"status: python={python.status} node={node.status}")
    a = normalize(python.json, ignore)
    b = normalize(node.json, ignore)
    if a != b:
        problems.append(
            "body differs:\n  python="
            + json.dumps(a, sort_keys=True, default=str)
            + "\n  node=  "
            + json.dumps(b, sort_keys=True, default=str)
        )
    return problems


def assert_match(python: Response, node: Response, *, ignore: set[str] | None = None) -> None:
    problems = diff(python, node, ignore=ignore)
    if problems:
        raise AssertionError("contract mismatch:\n" + "\n".join(problems))
