"""HTTP-surface tests via call_asgi (FastAPI part of the app)."""

from __future__ import annotations

import pytest
from fakeredis import FakeAsyncRedis

from fleetex_realtime.app import build_app
from fleetex_realtime.config import RealtimeConfig
from fleetex_service_kit.contract import call_asgi


@pytest.fixture
def app():
    redis = FakeAsyncRedis(decode_responses=True)
    return build_app(RealtimeConfig(), redis=redis)


async def test_root_and_status(app):
    root = await call_asgi(app, "GET", "/")
    assert root.status == 200 and root.text == "real-time is open"
    status = await call_asgi(app, "GET", "/status")
    assert status.status == 200 and status.text == "real-time is alive"


async def test_health_check(app):
    assert (await call_asgi(app, "GET", "/health_check")).status == 200


async def test_clients_empty(app):
    r = await call_asgi(app, "GET", "/clients")
    assert r.status == 200 and r.json == []


async def test_count_connected_clients(app):
    # seed the connected-users set directly via the manager
    await app.state.connected.update_user_position("projX", "P.1", {"user_id": "u1"})
    r = await call_asgi(app, "GET", "/project/projX/count-connected-clients")
    assert r.json == {"nConnectedClients": 1}


async def test_send_message_publishes_204(app):
    r = await call_asgi(app, "POST", "/project/projX/message/reciveNewDoc", json={"doc": {"_id": "d1"}})
    assert r.status == 204


async def test_drain_204(app):
    assert (await call_asgi(app, "POST", "/drain")).status == 204


async def test_disconnect_unknown_client_404(app):
    assert (await call_asgi(app, "POST", "/client/nope/disconnect")).status == 404
