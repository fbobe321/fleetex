"""Shared fixtures: an in-memory Mongo (mongomock-motor) wired into the app.

These let the full HTTP surface be contract-tested with zero external services.
Set ``FLEETEX_NODE_BASE`` to additionally diff against a live Node original.
"""

from __future__ import annotations

import pytest
from mongomock_motor import AsyncMongoMockClient

from fleetex_notifications.app import build_app
from fleetex_service_kit import Settings


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["sharelatex"]


@pytest.fixture
def app(db):
    application = build_app(Settings.from_env("notifications", env={}))
    # Lifespan doesn't run under ASGITransport, so inject the db directly.
    application.state.db = db
    return application
