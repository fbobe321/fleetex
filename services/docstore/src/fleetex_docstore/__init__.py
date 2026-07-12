"""fleetex-docstore: Python port of Overleaf's docstore microservice."""

from .app import app, build_app

__version__ = "0.1.0"
__all__ = ["app", "build_app", "__version__"]
