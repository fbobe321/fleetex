"""fleetex-service-kit: shared foundations for Fleetex's Python services.

Import surface used by each ported service::

    from fleetex_service_kit import Settings, create_app
    from fleetex_service_kit.contract import call_asgi, call_http, assert_match
"""

from .app import create_app
from .config import Settings
from .db import create_mongo_client, create_redis, database_name_from_url, get_database
from .logging import configure_logging

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Settings",
    "create_app",
    "configure_logging",
    "create_mongo_client",
    "create_redis",
    "get_database",
    "database_name_from_url",
]
