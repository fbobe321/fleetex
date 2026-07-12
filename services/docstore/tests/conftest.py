from __future__ import annotations

import pytest
from mongomock_motor import AsyncMongoMockClient

from fleetex_docstore.app import build_app
from fleetex_docstore.archive import InMemoryArchiveStore
from fleetex_docstore.config import DocstoreConfig


@pytest.fixture
def db():
    return AsyncMongoMockClient()["sharelatex"]


@pytest.fixture
def store():
    return InMemoryArchiveStore()


@pytest.fixture
def app(db, store):
    # backend="fs" enables archiving; the in-memory store keeps tests hermetic.
    application = build_app(DocstoreConfig(backend="fs", bucket="bucket"), store=store)
    application.state.db = db
    return application
