"""Fleetex: a pip-installable launcher for self-hosting a private LaTeX editor.

Fleetex is a fork/packaging of Overleaf Community Edition. It does *not*
reimplement Overleaf. Overleaf CE is a set of Node.js services distributed as the
``sharelatex/sharelatex`` Docker image. Fleetex is a thin, zero-dependency
Python wrapper around Docker Compose that makes the upstream stack installable
and operable with ``pip install fleetex`` and a friendly CLI
(``fleetex up``, ``down``, ``status``, ``logs`` ...).

Upstream project: https://github.com/overleaf/overleaf
"""

__version__ = "0.2.1"

# The upstream image tags the "ce" edition targets by default.
SHARELATEX_IMAGE = "sharelatex/sharelatex:latest"
MONGO_IMAGE = "mongo:8.0"
REDIS_IMAGE = "redis:6.2"

# The "python" edition runs Fleetex's own from-scratch reimplementation (the
# services/ tree in this repo) via its docker-compose.yml. When no local source
# checkout is configured, the launcher clones it from here.
REPO_URL = "https://github.com/fbobe321/fleetex.git"
PYTHON_PROJECT_NAME = "fleetex-app"

__all__ = [
    "__version__",
    "SHARELATEX_IMAGE",
    "MONGO_IMAGE",
    "REDIS_IMAGE",
    "REPO_URL",
    "PYTHON_PROJECT_NAME",
]
