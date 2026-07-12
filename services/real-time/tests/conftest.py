from __future__ import annotations

import httpx
import pytest
from fakeredis import FakeAsyncRedis


@pytest.fixture
def redis():
    return FakeAsyncRedis(decode_responses=True)


def mock_http(handler) -> httpx.AsyncClient:
    """An httpx.AsyncClient whose requests are answered by ``handler(request)``."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class EmitRecorder:
    """Records server->client emits and disconnects for RealtimeServer tests."""

    def __init__(self) -> None:
        self.emits: list = []
        self.disconnected: list = []

    async def emit(self, event, data, sid):
        self.emits.append((sid, event, data))

    async def disconnect(self, sid):
        self.disconnected.append(sid)

    def events(self, name):
        return [(sid, data) for sid, event, data in self.emits if event == name]
