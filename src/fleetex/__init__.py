"""Fleetex: a pip-installable launcher for self-hosting a private LaTeX editor.

Fleetex is a fork/packaging of Overleaf Community Edition. It does *not*
reimplement Overleaf. Overleaf CE is a set of Node.js services distributed as the
``sharelatex/sharelatex`` Docker image. Fleetex is a thin, zero-dependency
Python wrapper around Docker Compose that makes the upstream stack installable
and operable with ``pip install fleetex`` and a friendly CLI
(``fleetex up``, ``down``, ``status``, ``logs`` ...).

Upstream project: https://github.com/overleaf/overleaf
"""

__version__ = "0.1.0"

# The upstream image tags this launcher targets by default.
SHARELATEX_IMAGE = "sharelatex/sharelatex:latest"
MONGO_IMAGE = "mongo:8.0"
REDIS_IMAGE = "redis:6.2"

__all__ = ["__version__", "SHARELATEX_IMAGE", "MONGO_IMAGE", "REDIS_IMAGE"]
