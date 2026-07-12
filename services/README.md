# Fleetex Python services

This directory holds the **Python reimplementations** of Overleaf's backend
services (see [`../ROADMAP.md`](../ROADMAP.md)). Each is added one at a time and
replaces its Node counterpart via the strangler-fig approach.

## Layout

```
services/
├── _kit/            # fleetex-service-kit: shared foundations (Phase 0 ✅)
├── notifications/   # Phase 1  (added when started)
├── chat/            # Phase 2
└── ...
```

Each service is its own installable package (`services/<name>/pyproject.toml`)
that depends on `fleetex-service-kit`. Reference the Node original in the sibling
Overleaf checkout at `/data3/overleaf/services/<name>/`.

## The Node ↔ Python flip mechanism

Fleetex runs the real Overleaf as a single `sharelatex/sharelatex` container. To
replace one internal service with a Python version without a big-bang cutover:

1. **Build** the Python service into an image (each service ships a `Dockerfile`).
2. **Run it alongside** the stack and point the Overleaf container's env var for
   that service's URL at the Python container (e.g. `NOTIFICATIONS_URL`,
   `DOCSTORE_URL`, `CLSI_URL` — Overleaf already externalizes these). This is what
   makes the swap non-invasive: the monolith just calls a different host.
3. **Verify** with the contract-test harness (Python vs Node ground truth) and a
   smoke test in the running app.
4. **Flip** by committing the compose override; keep the Node service available
   for instant rollback.

A concrete override looks like this (illustrative — real values land in Phase 1):

```yaml
# docker-compose.fleetex-python.yml  (a compose override)
services:
  notifications:                     # new Python service container
    build: ./services/notifications
    environment:
      OVERLEAF_MONGO_URL: mongodb://mongo/sharelatex
      REDIS_HOST: redis
  sharelatex:                        # tell the monolith to use it
    environment:
      NOTIFICATIONS_URL: http://notifications:3042
```

Run with: `docker compose -f docker-compose.yml -f docker-compose.fleetex-python.yml up`.

The `fleetex` launcher will grow a `--python <service>` flag to manage these
overrides automatically as services come online.
