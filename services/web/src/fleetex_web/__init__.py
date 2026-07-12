"""fleetex-web: Python port of Overleaf's web service (auth slice, Phase 7)."""

from .app import app, build_app

__version__ = "0.1.0"
__all__ = ["app", "build_app", "__version__"]
