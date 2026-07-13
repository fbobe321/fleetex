from __future__ import annotations

import pytest
from mongomock_motor import AsyncMongoMockClient

from fleetex_project_history.app import build_app
from fleetex_service_kit import Settings


class FakeDocUpdater:
    """Records restore pushes instead of hitting a real document-updater."""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list = []

    async def set_doc(self, project_id, doc_id, content, user_id=None):
        self.calls.append({"project_id": project_id, "doc_id": doc_id, "content": content, "user_id": user_id})
        return self.ok


@pytest.fixture
def db():
    return AsyncMongoMockClient()["sharelatex"]


@pytest.fixture
def doc_updater():
    return FakeDocUpdater()


@pytest.fixture
def app(db, doc_updater):
    application = build_app(Settings.from_env("project-history", env={}), doc_updater=doc_updater)
    application.state.db = db  # lifespan doesn't run under ASGITransport
    return application
