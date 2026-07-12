"""fleetex-realtime: Python port of Overleaf's real-time (websocket) microservice."""

from .app import build_app, build_asgi

__version__ = "0.1.0"
__all__ = ["build_app", "build_asgi", "__version__"]
