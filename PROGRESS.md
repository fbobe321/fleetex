# Fleetex Reimplementation — Progress Log

> Update this at the end of every session. Keep it short. The next session reads
> **only this file + ROADMAP.md** to get oriented — cheap context, no source re-reads.

## Current status
- **Launcher (v0.1.1):** shipped — runs the real Node Overleaf via Docker. ✅
- **Phase 0 (foundations):** DONE ✅ — `services/_kit` (`fleetex-service-kit`)
  provides `Settings`, `create_app` (FastAPI + Mongo/Redis lifespan + /health,
  /status), JSON logging, lazy db factories, and the contract-test harness
  (`call_asgi`/`call_http`/`assert_match`). 12 tests pass. `services/README.md`
  documents the Node↔Python flip mechanism.

## Next session should do
**Phase 1 — `notifications` (the ★ warm-up service).** Steps:
1. Read the Node original at `/data3/overleaf/services/notifications` — map its
   HTTP routes and the Mongo `notifications` collection shape. (Delegate this
   read to a subagent to keep main context cheap.)
2. Create `services/notifications/` (pyproject depending on `fleetex-service-kit`)
   and implement the routes with `create_app`.
3. Write contract tests (vs Node ground truth via `FLEETEX_NODE_BASE`, plus
   fixtures so CI passes without Node).
4. Add the compose override + smoke test; update this file; commit.
Do ONLY Phase 1. Read only this file, ROADMAP.md, and the notifications source.

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
