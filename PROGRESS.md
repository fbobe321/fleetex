# Fleetex Reimplementation — Progress Log

> Update this at the end of every session. Keep it short. The next session reads
> **only this file + ROADMAP.md** to get oriented — cheap context, no source re-reads.

## Current status
- **Launcher (v0.1.1):** shipped — runs the real Node Overleaf via Docker. ✅
- **Phase 0 (foundations):** DONE ✅ — `services/_kit` (`fleetex-service-kit`):
  `Settings`, `create_app` (FastAPI + Mongo/Redis lifespan + /health, /status,
  optional `status_text`), JSON logging, lazy db factories, contract harness. 12 tests.
- **Phase 1 (`notifications`):** DONE ✅ — `services/notifications`
  (`fleetex-notifications`). 8 routes + /status + /health_check + 404 catch-all,
  dedup/forceCreate, soft-read via `$unset templateKey`, bulk delete,
  Express-compatible JSON. 19 tests (+1 skipped = live-Node diff), port 3042.
- **Phase 2 (`chat`):** DONE ✅ — `services/chat` (`fleetex-chat`). Two
  collections (rooms+messages). Global + thread messages, threads
  (getThreads/getThread/resolve/reopen/resolved-thread-ids), destroyProject,
  duplicate/generate/clone. Matches Node quirks: send re-adds room_id=projectId,
  lists newest-first & strip room_id, grouped threads ascending, empty-thread
  404, `{"message":"Validation errors"}` vs plain-text ObjectId 400s,
  `{"message":"Not found"}` 404. 28 tests pass, boots under uvicorn, port 3010.
  - **Same caveat as Phase 1:** verified vs spec + mongomock, not yet diffed vs
    a live Node instance (`FLEETEX_NODE_BASE=... pytest -k contract_vs_node`).

## Testing note
Each service is its own package with its own pytest config. Run per-service
(`cd services/<name> && pytest`) or all at once via `bash services/test-all.sh`.
Do NOT `pytest services/...` from the repo root — the launcher's root config
shadows the per-service `asyncio_mode` and async tests misfire.

## Next session should do
**Phase 3 — `filestore` (★★).** New territory: binary file storage, not just
Mongo JSON. Steps:
1. Subagent-map `/data3/overleaf/services/filestore` — routes (upload/download/
   copy/delete, streaming), the storage backends (local FS + S3), bucket/key
   layout, and whether it uses Mongo/Redis at all.
2. Create `services/filestore/`; implement **local-FS backend first**, S3 second.
3. Focus tests on streaming upload/download parity and the key/path layout.
4. Update this file; commit.
Read ONLY this file, ROADMAP.md, and the filestore source. chat/notifications
are the implementation template for structure (manager/serialize/app + kit).

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
