# fleetex-notifications

Python port of Overleaf's `notifications` microservice (Phase 1). Mongo-only
(no Redis). Faithful to the Node original's routes, status codes, dedup/read
semantics, and JSON shapes.

## Routes

| Method & path | Behavior |
|---|---|
| `POST /user/:user_id` | Upsert a notification (dedup on `(user_id, key)` unless `forceCreate`). `200` empty. |
| `GET /user/:user_id` | List a user's unread notifications (array of docs). |
| `DELETE /user/:user_id/notification/:id` | Mark one read (`$unset templateKey, messageOpts`). |
| `DELETE /user/:user_id` | Mark read by `key` (body `{"key": ...}`, required → `400`). |
| `DELETE /key/:key` | Mark read by key across all users. |
| `GET /key/:key/count` | `{"count": n}` of unread for a key. |
| `DELETE /key/:key/bulk` | Hard-delete unread for a key → `{"count": deleted}`. |
| `GET /status` | `notifications is up`. |
| `GET /health_check` | Mongo round-trip; `200`/`500`. |

Bad path ObjectId → `404`; missing required body field → `400`; handler error → `500`.

## Run

```bash
pip install -e services/_kit -e "services/notifications[dev]"
pytest services/notifications           # full HTTP + unit tests, no DB needed
python -m fleetex_notifications         # serve on :3042 (needs Mongo)
```

## Verify against the Node original

```bash
FLEETEX_NODE_BASE=http://localhost:3042 pytest services/notifications -k contract_vs_node
```

## Flip into the stack

See [`../README.md`](../README.md). Point the Overleaf container's
`NOTIFICATIONS_URL` at this service and run it as a sidecar container
(`services/notifications/Dockerfile`), keeping Node available for rollback.
