"""overleaf-ce: a pip-installable launcher for self-hosting Overleaf Community Edition.

This package does *not* reimplement Overleaf. Overleaf CE is a set of Node.js
services distributed as the ``sharelatex/sharelatex`` Docker image. This package
is a thin, zero-dependency Python wrapper around Docker Compose that makes the
upstream stack installable and operable with ``pip install overleaf-ce`` and a
friendly CLI (``overleaf-ce up``, ``down``, ``status``, ``logs`` ...).

Upstream project: https://github.com/overleaf/overleaf
"""

__version__ = "0.1.0"

# The upstream image tags this launcher targets by default.
SHARELATEX_IMAGE = "sharelatex/sharelatex:latest"
MONGO_IMAGE = "mongo:8.0"
REDIS_IMAGE = "redis:6.2"

__all__ = ["__version__", "SHARELATEX_IMAGE", "MONGO_IMAGE", "REDIS_IMAGE"]
