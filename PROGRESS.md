# Fleetex Reimplementation — Progress Log

> Update this at the end of every session. Keep it short. The next session reads
> **only this file + ROADMAP.md** to get oriented — cheap context, no source re-reads.

## Current status
- **Launcher (v0.1.1):** shipped — runs the real Node Overleaf via Docker. ✅
- **Phase 0 (foundations):** DONE ✅ — `services/_kit` (`fleetex-service-kit`):
  `Settings`, `create_app` (FastAPI + Mongo/Redis lifespan + /health, /status,
  optional `status_text`), JSON logging, lazy db factories, contract harness. 12 tests.
- **Phase 1 (`notifications`):** DONE ✅ — `services/notifications`
  (`fleetex-notifications`). Full port: 8 routes + /status + /health_check + 404
  catch-all, dedup/forceCreate, soft-read via `$unset templateKey`, by-key ops,
  bulk delete, Express-compatible JSON (ObjectId→hex, Date→`...Z`). 19 tests pass
  (+1 skipped = live-Node diff), boots under uvicorn, /status matches Node.
  - **Caveat:** parity verified vs spec + in-memory mongomock, NOT yet diffed
    against a running Node instance. To do so: run Node notifications + Mongo,
    then `FLEETEX_NODE_BASE=... pytest services/notifications -k contract_vs_node`.

## Next session should do
**Phase 2 — `chat` (★).** Same recipe as Phase 1:
1. Subagent-map the Node original at `/data3/overleaf/services/chat` (routes,
   Mongo collections/shape — chat has messages + threads/rooms, slightly richer
   than notifications).
2. Create `services/chat/` on the kit; implement routes.
3. Unit + HTTP tests via mongomock + call_asgi; optional Node diff.
4. Update this file; commit.
Read ONLY this file, ROADMAP.md, and the chat source. Reuse the notifications
service as the implementation template.

## Services ported (Node → Python)
_(none yet)_

| Service | Status | Version flipped | Notes |
|---------|--------|-----------------|-------|
| notifications | not started | – | |
| chat | not started | – | |
| filestore | not started | – | |
| docstore | not started | – | |
| clsi | not started | – | |
| real-time | not started | – | |
| web (backend) | not started | – | |
| document-updater | not started | – | hard core — do last |
| project-history | not started | – | hard core — do last |
| history-v1 | not started | – | hard core — do last |

## Gotchas / decisions log
- Frontend stays JS/TS (React); we reuse Overleaf's. Only backends go to Python.
- Reference the Node source in the sibling repo at `/data3/overleaf/services/<name>`.
