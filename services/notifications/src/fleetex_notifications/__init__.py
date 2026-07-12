"""fleetex-notifications: Python port of Overleaf's notifications microservice."""

from .app import app, build_app

__version__ = "0.1.0"
__all__ = ["app", "build_app", "__version__"]
