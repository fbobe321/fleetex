from __future__ import annotations

import pytest
from mongomock_motor import AsyncMongoMockClient

from fleetex_chat.app import build_app
from fleetex_service_kit import Settings


@pytest.fixture
def db():
    return AsyncMongoMockClient()["sharelatex"]


@pytest.fixture
def app(db):
    application = build_app(Settings.from_env("chat", env={}))
    application.state.db = db  # lifespan doesn't run under ASGITransport
    return application
