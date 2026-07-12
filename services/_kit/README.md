# fleetex-service-kit

Shared foundations for Fleetex's Python reimplementation of Overleaf backend
services. Every ported service depends on this package.

## What it provides

- `Settings.from_env(name)` — reads Overleaf-compatible env vars (`OVERLEAF_MONGO_URL`, `REDIS_HOST`, `PORT`, ...).
- `create_app(settings)` — a FastAPI app with a Mongo/Redis lifespan and `/health` + `/status` endpoints.
- `fleetex_service_kit.db` — lazy Motor (Mongo) and redis-py (Redis) client factories.
- `fleetex_service_kit.logging` — bunyan-style JSON logging matching Overleaf's format.
- `fleetex_service_kit.contract` — the **contract-test harness**: call the Python
  service in-process (`call_asgi`) and the Node original (`call_http`), normalize
  away volatile fields, and `assert_match`.

## Building a service on top of it

```python
from fleetex_service_kit import Settings, create_app

settings = Settings.from_env("notifications", default_port=3042)
app = create_app(settings)

@app.get("/user/{user_id}/notifications")
async def list_notifications(user_id: str):
    docs = await app.state.db.notifications.find({"user_id": user_id}).to_list(None)
    return [serialize(d) for d in docs]
```

## Contract testing against Node

```python
import os
from fleetex_service_kit.contract import call_asgi, call_http, assert_match

async def test_list_matches_node():
    py = await call_asgi(app, "GET", "/user/abc/notifications")
    if base := os.environ.get("FLEETEX_NODE_BASE"):
        node = await call_http(base, "GET", "/user/abc/notifications")
        assert_match(py, node, ignore={"[*]._id"})
```

Run tests with: `pip install -e ".[dev]" && pytest`.
